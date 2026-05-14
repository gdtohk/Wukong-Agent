from skills.export_excel import generate_rebar_excel
import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from playwright.async_api import async_playwright
import json 
import base64
import urllib.parse
import os
import re
from experience_manager import exp_manager  # 🌟 新增：引入經驗大腦

from skills.scheduler import schedule_daily_weather
from skills.rebar import calc_rebar_weight
from skills.weather import get_hk_weather_detailed
from skills.reminder import set_reminder
from skills.system_ops import update_from_github
from skills.research import perform_deep_research # 🌟 新增：引入深度研究
from skills.manage_my_drive import manage_my_drive # 🌟 新增：引入雲端硬碟讀取技能

# ================= 全球天氣查詢 =================
async def get_global_weather(chat_id, context, location):
    print(f"🌍 [Debug] 準備查詢天氣：{location}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://wttr.in/{urllib.parse.quote(location)}?format=j1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if isinstance(data, dict) and 'current_condition' in data and len(data['current_condition']) > 0:
                        current = data['current_condition'][0]
                        return f"🌍 {location} 天氣數據：氣溫 {current.get('temp_C', '未知')}°C，狀況 {current.get('weatherDesc', [{'value': '未知'}])[0]['value']}。"
                    else:
                        return f"❌ {location} 天氣伺服器數據異常，請稍後再試。"
                return f"❌ API 拒絕連線 (HTTP {resp.status})。"
    except Exception as e: return f"❌ 查詢出錯：{str(e)}"

# ================= 全能網絡搜尋 (強化版 + 時效過濾) =================
async def search_web(chat_id, context, query, recency=None):
    """獲取即時新聞、百科知識或任何網上最新資訊"""
    print(f"🔍 [Debug] 準備全能搜尋：{query} (時間限制: {recency})")
    try:
        formatted_query = query.replace(' ', '+')
        # 🌟 核心升級：強制 Google 只搜尋特定時間範圍內嘅結果
        if recency:
            formatted_query += f"+when:{recency}"
            
        url = f"https://news.google.com/rss/search?q={formatted_query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200: return f"❌ 網絡連線失敗 (HTTP {resp.status})。"
                xml_data = await resp.text()
                root = ET.fromstring(xml_data)
                items = root.findall('.//item')
                if not items: return f"❌ 搵唔到關於「{query}」嘅任何相關資訊。"
                formatted_results = []
                for item in items[:10]:
                    title = item.findtext('title')
                    pubDate = item.findtext('pubDate')
                    formatted_results.append(f"📌 【{title}】\n🕒 發佈時間：{pubDate}")
                return "以下係我為你搵到嘅相關資訊：\n\n" + "\n\n".join(formatted_results)
    except Exception as e: return f"❌ 搜尋出錯：{str(e)}"

# ================= Playwright 網頁瀏覽 (視覺截圖) =================
async def browse_website_with_playwright(chat_id, context, url: str):
    print(f"🌐 [Debug] 準備訪問網頁：{url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            content = await page.evaluate("document.body.innerText")
            page_title = await page.title()
            screenshot_bytes = await page.screenshot(type='jpeg', quality=30, full_page=False)
            base64_encoded = base64.b64encode(screenshot_bytes).decode('utf-8')
            await browser.close()
            return json.dumps({
                "type": "webpage_with_screenshot",
                "title": page_title,
                "text": content[:1500],
                "image_base64": base64_encoded
            })
    except Exception as e: return f"❌ 訪問網頁失敗：{str(e)}"

# ================= Jina Reader 借刀殺人讀網頁 (🌟 替換 Scrapling) =================
async def read_webpage_with_jina(chat_id, context, url: str):
    """使用 Jina API 極速讀取網頁純文字內容，無視大部分防爬蟲機制"""
    print(f"🥷 [Debug] 準備使用 Jina 借刀殺人讀取網頁：{url}")
    try:
        # 在原網址前面加上 Jina 嘅 API 前綴
        jina_url = f"https://r.jina.ai/{url}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        # 🚨 設置 30 秒強制超時，防止二郎神再次無限期 Hang 機
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(jina_url, headers=headers) as resp:
                if resp.status == 200:
                    raw_text = await resp.text()
                    
                    # 截取前 3500 字，避免超長文章塞爆大腦 Token
                    final_text = raw_text[:3500]
                    return f"🥷 網頁讀取成功！以下係內容摘要：\n\n{final_text}"
                else:
                    return f"❌ Jina 伺服器無法解析此網頁 (HTTP {resp.status})，可能被極強防護攔截。"
                    
    # 捕捉超時錯誤，優雅回覆老闆
    except asyncio.TimeoutError:
        return "❌ 讀取超時 (超過30秒)。目標網站防護極嚴密，已自動放棄以免系統卡死。"
    except Exception as e: 
        return f"❌ 讀取發生錯誤：{str(e)}"

# ================= 寫入長期記憶 (🌟 新增功能) =================
async def save_agent_experience(chat_id, context, content: str):
    print(f"🧠 [Debug] 正在將經驗寫入大腦：{content}")
    return exp_manager.add_experience(content)

# ================= 工具創建助手 =================
def create_tool(func, name, desc, params, required):
    return {"func": func, "schema": {"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": params, "required": required}}}}

# ================= 技能註冊表 (無 YouTube 版) =================
AGENT_TOOLS_REGISTRY = {
    "calc_rebar_weight": create_tool(calc_rebar_weight, "calc_rebar_weight", "計算鋼筋重量。", {"d": {"type": "number"}, "length": {"type": "number"}, "qty": {"type": "number"}}, ["d", "length"]),
    "get_hk_weather_detailed": create_tool(get_hk_weather_detailed, "get_hk_weather_detailed", "獲取香港最新天氣預報。", {}, []),
    "set_reminder": create_tool(set_reminder, "set_reminder", "設定定時提醒（鬧鐘）。", {"minutes": {"type": "number"}, "message": {"type": "string"}}, ["minutes", "message"]),
    "schedule_daily_weather": create_tool(schedule_daily_weather, "schedule_daily_weather", "設定每日定時晨報。", {"hour": {"type": "integer"}, "minute": {"type": "integer"}}, ["hour", "minute"]),
    "get_global_weather": create_tool(get_global_weather, "get_global_weather", "查詢全球城市天氣。", {"location": {"type": "string"}}, ["location"]),
    
    # 🌟 更新：強制大腦使用 recency 參數！
    "search_web": create_tool(search_web, "search_web", "全能網絡搜尋。🚨【極重要】：當老闆詢問「今日新聞」、「最新消息」或「熱門新聞」時，你必須設定 recency 參數為 '1d'，強制搜尋過去 24 小時內的最新資訊，避免返回舊聞！", {
        "query": {"type": "string"},
        "recency": {"type": "string", "description": "時間限制：'1d'(過去24小時), '7d'(過去一週), '1m'(過去一個月), '1y'(過去一年)。若需要找「今天」的新聞，必須填入 '1d'！", "enum": ["1d", "7d", "1m", "1y"]}
    }, ["query"]),
    
    "update_from_github": create_tool(update_from_github, "update_from_github", "更新系統代碼。", {}, []),
    "generate_rebar_excel": create_tool(generate_rebar_excel, "generate_rebar_excel", "生成 Excel 報表。", {"report_name": {"type": "string"}, "records": {"type": "array", "items": {"type": "object", "properties": {"d": {"type": "number"}, "length": {"type": "number"}, "qty": {"type": "number"}, "weight": {"type": "number"}}, "required": ["d", "length", "qty", "weight"]}}}, ["report_name", "records"]),
    "browse_website": create_tool(browse_website_with_playwright, "browse_website", "瀏覽網頁並獲取實時截圖分析。", {"url": {"type": "string"}}, ["url"]),
    "scrape_webpage_text": create_tool(read_webpage_with_jina, "scrape_webpage_text", "使用 Jina API 極速讀取網頁純文字內容。適合用來閱讀新聞、文章、文檔等大量文字嘅網址。", {"url": {"type": "string"}}, ["url"]),
    "save_agent_experience": create_tool(save_agent_experience, "save_agent_experience", "儲存重要的工作經驗、規範或老闆的糾正指示到長期記憶庫中。當老闆要求你『記住』某事時調用。", {"content": {"type": "string"}}, ["content"]), # 🌟 新增：註冊記憶工具
    "deep_research": create_tool(perform_deep_research, "deep_research", "針對複雜問題進行深度研究與分析。當老闆要求寫報告、做詳細對比、或搜查多個網頁資料時，必須使用此工具一炮過獲取完整數據。", {"query": {"type": "string"}}, ["query"]), # 🌟 新增：深度研究工具
    "manage_my_drive": create_tool(manage_my_drive, "manage_my_drive", "瀏覽掛載的 Google Drive 資料夾，或提取當中的 PDF/Excel/CSV/Txt 文件內容。當老闆要求讀取雲端硬碟(my_drive)裡的文件時必須調用此工具。", {
        "path": {"type": "string", "description": "文件或資料夾的相對路徑。留空代表根目錄。例如：'Kwu Tung North' 或 '落标扎铁要求.pdf'"},
        "mode": {"type": "string", "description": "【核心指令】：'text' 代表純文字提取（極速，適合文字章程）；'visual' 代表將圖紙轉化為圖片供視覺分析（極致細節，適合含有工程圖則 Drawings、大樣圖、搭接長度表、表格等情況）。若老闆指示「看圖」、「視覺」或文件含有圖紙表格，必須使用 'visual'。", "enum": ["text", "visual"]}
    }, ["path"]) # 🌟 更新：雲端硬碟加入視覺模式
}
GET_TOOLS_LIST = [tool["schema"] for tool in AGENT_TOOLS_REGISTRY.values()]
