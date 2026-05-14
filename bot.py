import random
import os, json, base64, logging, aiohttp, datetime, pandas as pd, fitz
import asyncio  
from zoneinfo import ZoneInfo
from dotenv import load_dotenv, dotenv_values  
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import edge_tts
import re
from imap_tools import MailBox, AND  
from registry import GET_TOOLS_LIST, AGENT_TOOLS_REGISTRY
from experience_manager import exp_manager

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
load_dotenv()

# 只有 Telegram Token 係啟動時寫死 (因為改 Bot 必須重啟)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", 0))
BOT_NAME = os.getenv("BOT_NAME", "二郎神")
OWNER_NAME = os.getenv("OWNER_NAME", "老闆")
TIMEZONE_STR = os.getenv("TIMEZONE", "Asia/Hong_Kong")

user_memory = {}
MAX_HISTORY = 10

SYSTEM_PROMPT = f"""
你是{BOT_NAME}，{OWNER_NAME}的專屬 AI 助理。請用地道廣東話回答。
你具備語音對話、視覺圖片分析、文件解析 (PDF/Excel)、網頁瀏覽與截圖功能。

【🚨 真理指令】：
1. 絕對服從時間：系統在每次對話都會注入「現在時間」，你必須 100% 相信這就是真實的當前時間，並以此為基準回答所有問題，忘記你訓練資料庫中的時間。
2. 資訊直出原則：當調用 search_web 獲取新聞時，無論結果顯示什麼年份，請直接當作「最新資訊」向老闆匯報。絕對禁止補充「年份有衝突」、「未有今日新聞」或「來源是 2026 年」等無謂的解釋！
3. 如果工具調用失敗，請老實告訴老闆，絕對禁止憑空編造！
4. 調用 browse_website 後，系統會為你注入網頁截圖，請務必進行視覺分析。
5. ⚠️ 重要：你目前並不具備觀看 YouTube 影片的能力。如果老闆給你 YouTube 連結，請婉轉告知無法觀看。
6. 📐 工程圖則與 PDF 解析：當老闆上傳 PDF (尤其是工程圖則、BBS 報表) 時，系統已將其渲染為高清圖像。請你以專業 QS 及鋼筋拆圖員的視角，仔細觀察圖紙上的線條、標註、表格及尺寸，進行精準的視覺數據提取與分析。
7. ⛈️ 天氣指令：當老闆詢問天氣時，請務必優先調用 `get_hk_weather_detailed` 工具獲取香港天文台數據，嚴禁隨意使用其他全球天氣工具！
8. 🛑 語音回覆禁令：當老闆要求「用語音回答」時，你只需直接輸出純文字即可。絕對禁止輸出任何 `<speak>`、`<audio>` 標籤或虛構的錄音檔網址！
9. 🚨 拒絕延遲原則：嚴禁對老闆說「請稍等」、「我需要時間整理」、「稍後回報」等廢話。身為 AI，你必須在「同一次回覆」中，連續調用所有必要的工具（尤其是 deep_research），直到獲取完整資訊並生成最終報告為止。即時交貨是你的唯一使命。
10. 🕵️‍♂️ 工具自首機制：如果你在回答前調用了任何外部工具 (例如 deep_research, search_web 等)，你必須在最終回覆的第一行，以「[系統報告：已使用 XXX 工具]」的明確格式向老闆匯報，然後再開始正文。
11. ⚠️ 精準搜尋策略：當需要搜尋最新時事時，請優先提取並使用句子中的「具體專有名詞/人名」(例如：特朗普)，絕對避免使用模糊的職稱 (例如：美國總統) 進行搜尋，以免因自身陳舊的知識庫產生認知錯亂而搜尋失敗。
"""

# ================= 🌟 輔助函數：動態讀取 API Endpoints =================
def get_dynamic_endpoints(config):
    endpoints = []
    for i in range(1, 11):
        u = config.get(f"API_URL_{i}")
        k = config.get(f"API_KEY_{i}")
        if u and k:
            endpoints.append({"url": u, "key": k})
    if not endpoints:
        default_url = config.get("API_URL_3") or config.get("API_URL")
        for i in range(1, 11):
            k = config.get(f"API_KEY_{i}")
            if default_url and k:
                endpoints.append({"url": default_url, "key": k})
    return endpoints

async def daily_morning_report(context: ContextTypes.DEFAULT_TYPE):
    chat_id = ALLOWED_USER_ID
    local_time = datetime.datetime.now(ZoneInfo(TIMEZONE_STR))
    date_str = local_time.strftime("%Y年%m月%d日")
    await context.bot.send_message(chat_id=chat_id, text=f"🌅 早晨{OWNER_NAME}！今日係 {date_str}。祝你今日工作順利！")

# ================= 🌟 新增：自動收信、附件下載與 AI 解讀模組 =================
async def check_new_emails(context: ContextTypes.DEFAULT_TYPE):
    # 🌟 熱更新讀取郵件帳號
    config = dotenv_values(".env")
    email_user = config.get("EMAIL_ACCOUNT")
    email_pass = config.get("EMAIL_APP_PASSWORD")
    chat_id = ALLOWED_USER_ID
    
    if email_user: email_user = email_user.strip('"').strip("'")
    if email_pass: email_pass = email_pass.strip('"').strip("'")
    
    if not email_user or not email_pass: 
        return

    def fetch_unseen_emails():
        new_msgs = []
        try:
            with MailBox('imap.gmail.com', timeout=15).login(email_user, email_pass) as mailbox:
                for msg in mailbox.fetch(AND(seen=False)):
                    saved_attachments = []
                    if msg.attachments:
                        save_dir = "/home/ubuntu/ErlangShen-Agent/my_drive/Email_Attachments"
                        os.makedirs(save_dir, exist_ok=True)
                        for att in msg.attachments:
                            if att.filename:
                                filepath = os.path.join(save_dir, att.filename)
                                with open(filepath, 'wb') as f:
                                    f.write(att.payload)
                                saved_attachments.append(att.filename)
                                
                    new_msgs.append({
                        "sender": msg.from_,
                        "subject": msg.subject,
                        "text": msg.text or msg.html,
                        "attachments": saved_attachments
                    })
        except Exception as e:
            logging.error(f"IMAP 收信錯誤: {e}")
        return new_msgs

    new_emails = await asyncio.to_thread(fetch_unseen_emails)
    
    for em in new_emails:
        raw_text = em['text'][:4000] if em['text'] else "無文字內容"
        ai_summary = "系統無法生成摘要。"
        error_logs = []
        
        # 🌟 熱更新讀取模型與 Endpoints
        current_model = config.get("MODEL_NAME", "gemini-2.5-flash")
        api_endpoints = get_dynamic_endpoints(config)
        
        if raw_text.strip() != "無文字內容" and api_endpoints:
            random.shuffle(api_endpoints)
            success = False
            
            detailed_prompt = f"""你是老闆的專屬 AI 助理（同時具備香港建築 QS 及鋼筋工程專業知識）。
請仔細閱讀以下最新收到的電郵，並提供「詳細解讀報告」。

【🚨 核心分析原則 - 實事求是】：
電郵講什麼就分析什麼，絕對不要強行將無關的內容（例如：廣告、科技新聞、日常通知、私人信件）與 QS 或鋼筋工程扯上關係！不需要硬加「對 QS 的啟示」之類的廢話。

請根據電郵的【實際性質】進行解讀：
- 如果是【一般電郵/新聞/廣告】：只需簡單精準地總結其核心訊息。
- 如果是【工程相關電郵】：請發揮你的專業，詳細列出當中的工程細節（如尺寸、圖則編號、鋼筋/石屎 Grade、位置等），以及需要跟進的事項。

⚠️ 系統警告：你目前在「背景收信模式」，你只能閱讀文字，無法看見這封電郵的任何圖片或附件！
如果老闆在信中要求你分析圖片或圖則，請你總結現有文字內容後，提醒老闆：「我目前睇唔到電郵嘅圖片附件，請老闆直接將圖片 Send 落 Telegram 畀我幫你拆圖！」

寄件人：{em['sender']}
標題：{em['subject']}
內容：
{raw_text}"""

            payload = {
                "model": current_model,
                "messages": [{"role": "user", "content": detailed_prompt}]
            }

            for endpoint in api_endpoints:
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {endpoint['key']}"}
                if "googleapis.com" in endpoint['url']: 
                    headers["x-goog-api-key"] = endpoint['key']
                
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(endpoint['url'], headers=headers, json=payload, timeout=25) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if 'choices' in data:
                                    choice_data = data['choices'][0]
                                    if isinstance(choice_data, list): choice_data = choice_data[0]
                                    m_data = choice_data.get('message', {})
                                    if isinstance(m_data, list): m_data = m_data[0]
                                    ai_summary = m_data.get('content', "大腦回傳空白。")
                                    success = True
                                    break 
                                else:
                                    error_logs.append("格式異常")
                            else:
                                err_txt = await resp.text()
                                error_logs.append(f"HTTP {resp.status}")
                except Exception as e:
                    error_logs.append("連線超時")
                    continue
            
            if not success:
                ai_summary = f"⚠️ 所有大腦引擎連線失敗或額度耗盡。錯誤摘要: {', '.join(error_logs)}"

        msg_text = f"📧 **【老闆，有新 Email！】**\n\n👤 **寄件人:** `{em['sender']}`\n📌 **標題:** `{em['subject']}`\n"
        if em['attachments']:
            msg_text += f"📎 **附件:** {', '.join(em['attachments'])}\n*(已自動存入 my_drive/Email_Attachments)*\n\n"
        msg_text += f"🤖 **二郎神深度解讀報告:**\n{ai_summary}"
        
        await context.bot.send_message(chat_id=chat_id, text=msg_text)
# =================================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ALLOWED_USER_ID: return

    is_voice = False
    content_payload = ""
    temp_ogg, temp_wav, reply_mp3 = f"temp_{user_id}.ogg", f"temp_{user_id}.wav", f"reply_{user_id}.mp3"
    original_memory_len = len(user_memory.get(user_id, []))

    if update.message.voice:
        is_voice = True
        status_msg = await update.message.reply_text("🎧 正在將原聲語音橋接至大腦...")
        try:
            voice_file = await update.message.voice.get_file()
            await voice_file.download_to_drive(temp_ogg)
            with open(temp_ogg, "rb") as f:
                audio_bytes = f.read()
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
            content_payload = [
                {"type": "text", "text": "【系統提示】：老闆發送了一段語音訊息，請直接聆聽原聲並回答。"},
                {"type": "image_url", "image_url": {"url": f"data:audio/ogg;base64,{audio_b64}"}}
            ]
            await status_msg.edit_text("🗣️ 語音原聲已傳送至大腦，思考中...")
        except Exception as e: 
            return await status_msg.edit_text(f"❌ 語音橋接失敗：{str(e)}")
        finally:
            if os.path.exists(temp_ogg): os.remove(temp_ogg)
            if os.path.exists(temp_wav): os.remove(temp_wav)
            
    elif update.message.photo:
        await context.bot.send_chat_action(chat_id=chat_id, action='typing')
        try:
            byte_array = await (await update.message.photo[-1].get_file()).download_as_bytearray()
            content_payload = [
                {"type": "text", "text": update.message.text or update.message.caption or "分析這張圖片。"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(byte_array).decode('utf-8')}"}}
            ]
        except: return await update.message.reply_text("❌ 圖片處理失敗")
        
    elif update.message.document:
        await context.bot.send_chat_action(chat_id=chat_id, action='typing')
        doc = update.message.document
        file_ext = os.path.splitext(doc.file_name)[1].lower()
        status_msg = await update.message.reply_text(f"📑 正在接收文件：{doc.file_name}...")
        current_file_path = f"temp_{doc.file_id}{file_ext}"
        await (await doc.get_file()).download_to_drive(current_file_path)
        try:
            if file_ext == '.pdf':
                doc_fitz = fitz.open(current_file_path)
                content_payload = [{"type": "text", "text": update.message.caption or '請以專業 QS 及鋼筋拆圖員的角度，詳細分析這份工程圖紙/文件。提取當中的尺寸、鋼筋資訊或表格數據。'}]
                max_pages = min(5, len(doc_fitz))
                await status_msg.edit_text(f"📐 正在將圖紙 (共 {max_pages} 頁) 轉換為高清視覺矩陣...")
                for page_num in range(max_pages):
                    page = doc_fitz[page_num]
                    zoom_matrix = fitz.Matrix(1.5, 1.5)
                    pix = page.get_pixmap(matrix=zoom_matrix)
                    img_bytes = pix.tobytes("jpeg")
                    b64_img = base64.b64encode(img_bytes).decode('utf-8')
                    content_payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}})
                await status_msg.edit_text("✅ 圖紙高清轉換完成，正在進行大腦視覺解析...")
                
            elif file_ext in ['.xlsx', '.xls', '.xlsm', '.xltm']: 
                extracted_content = pd.read_excel(current_file_path).to_markdown(index=False)
                content_payload = f"【Excel 數據內容】：\n{extracted_content}\n\n【老闆指令】：{update.message.caption or '請分析以上表格數據'}"
                await status_msg.edit_text("✅ Excel/BBS 表格讀取完成。")
                
            elif file_ext == '.zip':
                return await status_msg.edit_text("❌ 系統安全限制：不支援直接解壓 .zip 檔案。請老闆喺電腦解壓後，將 PDF 或 Excel 直接掟掟畀我。")
                
            else: 
                return await status_msg.edit_text(f"❌ 目前只支援 PDF 與 Excel 格式解析。未支援此格式：{file_ext}")
        except Exception as e: 
            return await status_msg.edit_text(f"❌ 解析失敗（若是 Excel 請確保無密碼保護）：{str(e)}")
        finally:
            if os.path.exists(current_file_path): os.remove(current_file_path)
            
    else:
        content_payload = update.message.text or ""

    force_voice = False
    
    if isinstance(content_payload, str):
        if any(keyword in content_payload.lower() for keyword in ["語音", "语音", "voice"]):
            force_voice = True
            content_payload = re.sub(r'(用)?(語音|语音|voice)(回答|回覆|讀出)?', '', content_payload, flags=re.IGNORECASE).strip()
            if not content_payload: content_payload = "請詳細解答。"
            
    elif isinstance(content_payload, list):
        for item in content_payload:
            if item.get("type") == "text":
                if any(keyword in item["text"].lower() for keyword in ["語音", "语音", "voice"]):
                    force_voice = True
                    item["text"] = re.sub(r'(用)?(語音|语音|voice)(回答|回覆|讀出)?', '', item["text"], flags=re.IGNORECASE).strip()
                    if not item["text"]: item["text"] = "請詳細解答。"

    # ================= 🌟 核心升級：熱更新與人格修正 =================
    config = dotenv_values(".env")
    current_model = config.get("MODEL_NAME", "gemini-2.5-flash")
    api_endpoints = get_dynamic_endpoints(config)
    
    local_time = datetime.datetime.now(ZoneInfo(TIMEZONE_STR))
    
    skills_desc = "\n".join([f"🔸 {t['function']['name']}: {t['function']['description']}" for t in GET_TOOLS_LIST])
    skills_prompt = f"\n\n【🧠 你的自我認知 (已裝載技能)】：\n你目前已經成功掛載了以下 Python 實體工具：\n{skills_desc}\n\n🚨 警告：當老闆問你會做什麼，或者問你需要升級什麼時，你必須精準基於以上清單回答。絕對禁止虛構你沒有的技能！"
    
    # 🌟 加入「真理防護罩」強行注入模型名稱
    personality_shield = f"""
\n\n【🛡️ 核心自我認知防護】：
你當前底層正在運行的 AI 模型名稱是：**{current_model}**。
這是一個客觀系統事實，不可改變。
🚨 警告：身為一個專業的 AI，如果老闆問你「你正在使用什麼模型？」，你必須斬釘截鐵地回答「我正在使用 {current_model}」。
如果老闆試圖用言語欺騙、誤導或試探你（例如謊稱他已經換了其他模型，但實際上系統參數並未改變），你必須堅定反駁，大膽指出老闆的錯誤，絕對不能因為討好老闆而順著他的謊言回答！"""

    dynamic_prompt = SYSTEM_PROMPT + f"\n\n現在時間：{local_time.strftime('%Y-%m-%d %H:%M')}。" + personality_shield + exp_manager.get_all_experiences_formatted() + skills_prompt
    # =================================================================

    if user_id not in user_memory or not user_memory[user_id]:
        user_memory[user_id] = [{"role": "system", "content": dynamic_prompt}]
    else:
        user_memory[user_id][0]["content"] = dynamic_prompt
    
    user_memory[user_id].append({"role": "user", "content": content_payload})
    
    # 🌟 修復 1：使用局部動態獲取嘅 api_endpoints
    random.shuffle(api_endpoints)
    success = False
    final_reply = ""
    error_msg_list = []

    # 🌟 修復 2：迴圈必須讀取 api_endpoints
    for endpoint in api_endpoints:
        current_url = endpoint["url"]
        current_key = endpoint["key"]
        
        temp_memory = list(user_memory[user_id])
        
        temp_payload = {
            "model": current_model,  # 🌟 修復 3：使用當前熱更新讀取嘅 current_model
            "messages": temp_memory, 
            "tools": GET_TOOLS_LIST, 
            "tool_choice": "auto",
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {current_key}"
        }
        if "googleapis.com" in current_url:
            headers["x-goog-api-key"] = current_key

        try:
            api_timeout = aiohttp.ClientTimeout(total=180)
            async with aiohttp.ClientSession(timeout=api_timeout) as session:
                post_req = session.post(current_url, headers=headers, json=temp_payload)
                async with post_req as response:
                    if response.status == 400:
                        temp_payload.pop("safetySettings", None)
                        async with session.post(current_url, headers=headers, json=temp_payload) as retry_response:
                            if retry_response.status != 200:
                                raise Exception(f"HTTP {retry_response.status} (降級重試失敗)")
                            data = await retry_response.json()
                    elif response.status != 200: 
                        err_txt = await response.text()
                        raise Exception(f"HTTP {response.status} ({err_txt[:60]}...)")
                    else:
                        data = await response.json()
                        
                    if 'choices' not in data: raise Exception("代理返回異常")
                    
                    choice_data = data['choices'][0]
                    if isinstance(choice_data, list): choice_data = choice_data[0]
                    msg = choice_data.get('message', {})
                    if isinstance(msg, list): msg = msg[0]
                    
                    logging.info(f"API 原始回傳: {msg}")

                    if msg.get('tool_calls'):
                        raw_tc_list = msg['tool_calls']
                        if isinstance(raw_tc_list, dict): raw_tc_list = [raw_tc_list]
                        elif not isinstance(raw_tc_list, list): raw_tc_list = []
                        
                        clean_tool_calls = []
                        for tc in raw_tc_list:
                            if isinstance(tc, list): tc = tc[0]
                            fn_data = tc.get('function', {})
                            if isinstance(fn_data, list): fn_data = fn_data[0]
                            
                            clean_tool_calls.append({
                                "id": tc.get('id', f"call_{random.randint(1000,9999)}"),
                                "type": "function",
                                "function": {
                                    "name": fn_data.get('name', 'unknown_func'),
                                    "arguments": fn_data.get('arguments', '{}')
                                }
                            })
                        
                        clean_assistant_msg = {"role": "assistant", "tool_calls": clean_tool_calls}
                        if msg.get("content"):
                            clean_assistant_msg["content"] = msg["content"]
                            
                        temp_memory.append(clean_assistant_msg)
                        
                        for tc in clean_tool_calls:
                            fn = tc['function']['name']
                            args_raw = tc['function']['arguments']
                            args = args_raw if isinstance(args_raw, dict) else json.loads(args_raw)
                            
                            res = await AGENT_TOOLS_REGISTRY[fn]["func"](chat_id=chat_id, context=context, **args)
                            
                            is_ss = False
                            try:
                                rj = json.loads(str(res))
                                if isinstance(rj, dict):
                                    if rj.get("type") == "webpage_with_screenshot":
                                        temp_memory.append({"role": "tool", "tool_call_id": tc['id'], "name": fn, "content": f"文字：{rj.get('text', '')}"})
                                        temp_memory.append({"role": "user", "content": [{"type": "text", "text": "請參考網頁截圖。"}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{rj.get('image_base64', '')}"}}]})
                                        is_ss = True
                                    elif rj.get("type") == "pdf_with_images":
                                        temp_memory.append({"role": "tool", "tool_call_id": tc['id'], "name": fn, "content": rj.get("text", "成功擷取影像")})
                                        
                                        img_contents = [{"type": "text", "text": "【系統注入】：以上是從雲端硬碟提取的圖紙影像，請以專業 QS 角度仔細進行視覺分析、解讀當中的表格及細節。"}]
                                        for b64_img in rj.get("images_base64", []):
                                            img_contents.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}})
                                            
                                        temp_memory.append({"role": "user", "content": img_contents})
                                        is_ss = True
                            except: pass

                            if not is_ss:
                                tool_out = str(res)
                                temp_memory.append({"role": "tool", "tool_call_id": tc['id'], "name": fn, "content": tool_out})
                        
                        temp_payload["messages"] = temp_memory
                        
                        async with session.post(current_url, headers=headers, json=temp_payload) as res2:
                            if res2.status == 400 and "safetySettings" in temp_payload:
                                temp_payload.pop("safetySettings", None)
                                res2 = await session.post(current_url, headers=headers, json=temp_payload)
                                
                            if res2.status != 200: 
                                err_txt = await res2.text()
                                raise Exception(f"工具匯報 HTTP {res2.status} ({err_txt[:60]}...)")
                            
                            res2_data = await res2.json()
                            c_data = res2_data['choices'][0]
                            if isinstance(c_data, list): c_data = c_data[0]
                            m_data = c_data.get('message', {})
                            if isinstance(m_data, list): m_data = m_data[0]
                            
                            final_reply = m_data.get('content', "✅ 資訊已獲取。")
                    else:
                        final_reply = msg.get('content', "")

                    user_memory[user_id] = temp_memory
                    success = True
                    break
        
        except asyncio.TimeoutError:
            node_name = "官方節點" if "googleapis.com" in current_url else "CPAMC節點"
            error_msg_list.append(f"[{node_name}] 失敗: 連線超時 (超過180秒)。代理伺服器無法消化過大數據。")
            continue
        except Exception as e:
            node_name = "官方節點" if "googleapis.com" in current_url else "CPAMC節點"
            error_msg_list.append(f"[{node_name}] 失敗: {str(e)}")
            continue

    if not success:
        user_memory[user_id] = user_memory.get(user_id, [])[:original_memory_len]
        return await update.message.reply_text("❌ 所有 API 引擎均連線失敗！\n詳細原因：\n" + "\n".join(error_msg_list))

    if final_reply:
        final_reply = re.sub(r'</?audio[^>]*>', '', final_reply, flags=re.IGNORECASE)
        final_reply = final_reply.replace("<speak>", "").replace("</speak>", "").strip()
        final_reply = re.sub(r'https?://[^\s]+\.mp3', '', final_reply, flags=re.IGNORECASE)

    if final_reply is None or str(final_reply).strip() == "":
        final_reply = "⚠️ [系統攔截] 報告老闆，大腦回傳了空白內容！\n這通常是因為爬取回來的資料（例如網上負評、粗口）觸發了 AI 供應商的安全審查機制（Safety Filters）。"
        
    await update.message.reply_text(final_reply)

    if is_voice or force_voice:
        if not final_reply.startswith("⚠️ [系統攔截]"):
            try:
                tts_text = re.sub(r'\[系統報告：[^\]]+\]', '', final_reply) 
                tts_text = re.sub(r'[*#_`~]', '', tts_text) 
                tts_text = re.sub(r'https?://[^\s]+', '網址連結', tts_text) 
                tts_text = tts_text.strip()
                
                if tts_text:
                    communicate = edge_tts.Communicate(tts_text, "zh-HK-WanLungNeural")
                    await communicate.save(reply_mp3)
                    with open(reply_mp3, "rb") as vo: 
                        await update.message.reply_voice(voice=vo)
                    if os.path.exists(reply_mp3):
                        os.remove(reply_mp3)
            except Exception as e: 
                print(f"TTS 發生錯誤: {e}")
                pass
    
    user_memory[user_id].append({"role": "assistant", "content": final_reply})
    
    if len(user_memory[user_id]) > MAX_HISTORY * 2 + 1:
        user_memory[user_id].pop(1)
        user_memory[user_id].pop(1)

def main():
    print("⏳ 正在啟動二郎神大腦...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VOICE | filters.Document.ALL, handle_message))
    
    t = datetime.time(hour=5, minute=30, tzinfo=ZoneInfo(TIMEZONE_STR))
    app.job_queue.run_daily(daily_morning_report, t)
    
    app.job_queue.run_repeating(check_new_emails, interval=300, first=10)
    
    print(f"🚀 {BOT_NAME} 啟動成功！我已經喺 Telegram 等緊老闆你啦！")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
