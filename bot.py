import random
import os, json, base64, logging, aiohttp, datetime, pandas as pd, fitz
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import speech_recognition as sr
from pydub import AudioSegment
import edge_tts
import re
from registry import GET_TOOLS_LIST, AGENT_TOOLS_REGISTRY
from experience_manager import exp_manager

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

API_ENDPOINTS = []
for i in range(1, 11):
    u = os.getenv(f"API_URL_{i}")
    k = os.getenv(f"API_KEY_{i}")
    if u and k:
        API_ENDPOINTS.append({"url": u, "key": k})

if not API_ENDPOINTS:
    default_url = os.getenv("API_URL")
    for i in range(1, 11):
        k = os.getenv(f"API_KEY_{i}")
        if default_url and k:
            API_ENDPOINTS.append({"url": default_url, "key": k})

GEMINI_MODEL = os.getenv("MODEL_NAME", "gemini-2.5-flash")
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
6. ⛈️ 天氣指令：當老闆詢問天氣時，請務必優先調用 `get_hk_weather_detailed` 工具獲取香港天文台數據，嚴禁隨意使用其他全球天氣工具！
7. 🛑 語音回覆禁令：當老闆要求「用語音回答」時，你只需直接輸出純文字即可。絕對禁止輸出任何 `<speak>`、`<audio>` 標籤或虛構的錄音檔網址！🚨 嚴格禁止：絕對不可以向老闆解釋「我不能輸出語音」、「我只能用純文字回覆」、「謹遵指令」等廢話。直接開始回答正文，當作沒事發生過！
8. 🕵️‍♂️ 工具自首機制：如果你在回答前調用了任何外部工具 (例如 search_web, scrape_webpage_text, browse_website 等)，你必須在最終回覆的第一行，以「[系統報告：已使用 XXX 工具]」的明確格式向老闆匯報，然後再開始正文。
"""

async def daily_morning_report(context: ContextTypes.DEFAULT_TYPE):
    chat_id = ALLOWED_USER_ID
    local_time = datetime.datetime.now(ZoneInfo(TIMEZONE_STR))
    date_str = local_time.strftime("%Y年%m月%d日")
    await context.bot.send_message(chat_id=chat_id, text=f"🌅 早晨{OWNER_NAME}！今日係 {date_str}。祝你今日工作順利！")

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
        status_msg = await update.message.reply_text("🎧 努力聽緊...")
        try:
            voice_file = await update.message.voice.get_file()
            await voice_file.download_to_drive(temp_ogg)
            AudioSegment.from_file(temp_ogg).export(temp_wav, format="wav")
            with sr.AudioFile(temp_wav) as source:
                content_payload = sr.Recognizer().recognize_google(sr.Recognizer().record(source), language="yue-Hant-HK")
            await status_msg.edit_text(f"🗣️ 你講咗：\n「{content_payload}」")
        except: return await status_msg.edit_text("❌ 聽唔清楚。")
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
        status_msg = await update.message.reply_text(f"📑 閱讀：{doc.file_name}...")
        current_file_path = f"temp_{doc.file_id}{file_ext}"
        await (await doc.get_file()).download_to_drive(current_file_path)
        try:
            if file_ext == '.pdf': extracted_content = "".join([page.get_text() for page in fitz.open(current_file_path)])
            elif file_ext in ['.xlsx', '.xls']: extracted_content = pd.read_excel(current_file_path).to_markdown(index=False)
            else: return await status_msg.edit_text("❌ 未支援格式")
            content_payload = f"【文件內容】：\n{extracted_content}\n\n【問題】：{update.message.caption or '請分析文件'}"
            await status_msg.edit_text("✅ 讀完。")
        except: return await status_msg.edit_text("❌ 解析失敗")
        finally:
            if os.path.exists(current_file_path): os.remove(current_file_path)
    else:
        content_payload = update.message.text or ""

    force_voice = False
    text_to_check = ""
    if isinstance(content_payload, str):
        text_to_check = content_payload
    elif isinstance(content_payload, list):
        text_to_check = " ".join([str(item.get("text", "")) for item in content_payload if item.get("type") == "text"])
    
    if any(keyword in text_to_check.lower() for keyword in ["語音", "语音", "voice"]):
        force_voice = True

    local_time = datetime.datetime.now(ZoneInfo(TIMEZONE_STR))
    
    skills_desc = "\n".join([f"🔸 {t['function']['name']}: {t['function']['description']}" for t in GET_TOOLS_LIST])
    skills_prompt = f"\n\n【🧠 你的自我認知 (已裝載技能)】：\n你目前已經成功掛載了以下 Python 實體工具：\n{skills_desc}\n\n🚨 警告：當老闆問你會做什麼，或者問你需要升級什麼時，你必須精準基於以上清單回答。絕對禁止虛構你沒有的技能（例如自動點擊屏幕、操作電腦軟件等）！"
    
    dynamic_prompt = SYSTEM_PROMPT + f"\n\n現在時間：{local_time.strftime('%Y-%m-%d %H:%M')}。" + exp_manager.get_all_experiences_formatted() + skills_prompt
    
    if user_id not in user_memory or not user_memory[user_id]:
        user_memory[user_id] = [{"role": "system", "content": dynamic_prompt}]
    else:
        user_memory[user_id][0]["content"] = dynamic_prompt
    
    user_memory[user_id].append({"role": "user", "content": content_payload})
    
    random.shuffle(API_ENDPOINTS)
    success = False
    final_reply = ""
    error_msg_list = []

    for endpoint in API_ENDPOINTS:
        current_url = endpoint["url"]
        current_key = endpoint["key"]
        
        temp_memory = list(user_memory[user_id])
        temp_payload = {
            "model": GEMINI_MODEL, 
            "messages": temp_memory, 
            "tools": GET_TOOLS_LIST, 
            "tool_choice": "auto"
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {current_key}"
        }
        if "googleapis.com" in current_url:
            headers["x-goog-api-key"] = current_key

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(current_url, headers=headers, json=temp_payload) as response:
                    if response.status != 200: 
                        err_txt = await response.text()
                        raise Exception(f"HTTP {response.status} ({err_txt[:60]}...)")
                        
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
                                if isinstance(rj, dict) and rj.get("type") == "webpage_with_screenshot":
                                    temp_memory.append({"role": "tool", "tool_call_id": tc['id'], "name": fn, "content": f"文字：{rj.get('text', '')}"})
                                    temp_memory.append({"role": "user", "content": [{"type": "text", "text": "請參考網頁截圖。"}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{rj.get('image_base64', '')}"}}]})
                                    is_ss = True
                            except: pass

                            if not is_ss:
                                tool_out = str(res)
                                temp_memory.append({"role": "tool", "tool_call_id": tc['id'], "name": fn, "content": tool_out})
                        
                        temp_payload["messages"] = temp_memory
                        
                        async with session.post(current_url, headers=headers, json=temp_payload) as res2:
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
        final_reply = "⚠️ [系統攔截] 報告老闆，大腦回傳了空白內容！\n這通常是因為問題（例如「繞過反爬」）觸發了 AI 供應商的安全審查機制（Safety Filters），被判定為敏感操作而強制消音。你可以查看 agent.log 了解 API 的原始回傳。"
        
    await update.message.reply_text(final_reply)

    if is_voice or force_voice:
        if not final_reply.startswith("⚠️ [系統攔截]"):
            try:
                tts_text = final_reply.replace("*", "").replace("#", "").replace("_", "")
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
    
    print(f"🚀 {BOT_NAME} 啟動成功！我已經喺 Telegram 等緊老闆你啦！")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
