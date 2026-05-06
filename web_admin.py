from flask import Flask, render_template_string, request, redirect, flash, session, jsonify
import os, json, asyncio, aiohttp, datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv, dotenv_values

# 嘗試載入 Telegram 嘅工具庫 (防錯機制)
try:
    from registry import GET_TOOLS_LIST, AGENT_TOOLS_REGISTRY
except ImportError:
    GET_TOOLS_LIST = []
    AGENT_TOOLS_REGISTRY = {}

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "erlangshen_super_secret")
ENV_PATH = ".env"
ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "Admin_Not_Set_999") 

# 網頁版專屬記憶體
WEB_MEMORY = []
MAX_HISTORY = 10

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ErlangShen Agent 控制中心</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; background-color: #f0f2f5; height: 100vh; display: flex; flex-direction: column; }
        .login-container { max-width: 400px; margin: 100px auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        h1, h3 { color: #1a73e8; text-align: center; }
        
        /* 聊天室 UI */
        .chat-container { max-width: 900px; margin: 20px auto; width: 95%; flex: 1; display: flex; flex-direction: column; background: white; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; position: relative; }
        
        /* --- 修改頂部 Header 為相對定位，方便容納左邊按鈕 --- */
        .chat-header { position: relative; background: #1a1a1a; color: white; padding: 15px; display: flex; align-items: center; justify-content: center; gap: 15px; font-weight: bold; }
        
        /* --- 新增：頂部左上角 Setting 按鈕 --- */
        .header-setting-btn { position: absolute; left: 20px; background: #333; color: #ccc; border: 1px solid #555; border-radius: 6px; padding: 6px 12px; font-size: 13px; cursor: pointer; transition: 0.3s; display: flex; align-items: center; gap: 5px; }
        .header-setting-btn:hover { background: #555; color: white; border-color: #777; }

        .chat-box { flex: 1; padding: 20px; overflow-y: auto; background: #fafafa; display: flex; flex-direction: column; gap: 15px; }
        .message { max-width: 75%; padding: 12px 18px; border-radius: 8px; line-height: 1.5; font-size: 15px; word-wrap: break-word; }
        .msg-user { background: #1a73e8; color: white; align-self: flex-end; border-bottom-right-radius: 0; }
        .msg-ai { background: #e9ecef; color: black; align-self: flex-start; border-bottom-left-radius: 0; }
        .chat-input-area { padding: 15px; background: white; border-top: 1px solid #ddd; display: flex; gap: 10px; }
        .chat-input-area input { flex: 1; padding: 12px; font-size: 15px; border: 1px solid #ccc; border-radius: 6px; outline: none; }
        .chat-input-area button { padding: 12px 24px; font-size: 15px; font-weight: bold; background: #34a853; color: white; border: none; border-radius: 6px; cursor: pointer; transition: 0.3s; }
        .chat-input-area button:hover { background: #2b8a44; }

        /* Modal 設定視窗 */
        .modal { display: {% if show_settings %}block{% else %}none{% endif %}; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5); overflow: auto; }
        .modal-content { background-color: #fff; margin: 5% auto; padding: 30px; border-radius: 12px; width: 90%; max-width: 800px; position: relative; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
        .close-btn { position: absolute; right: 20px; top: 15px; font-size: 28px; font-weight: bold; color: #aaa; cursor: pointer; }
        .close-btn:hover { color: black; }
        
        /* 模型切換標籤樣式 */
        .model-selector { margin-bottom: 15px; background: #f8f9fa; padding: 15px; border-radius: 8px; border: 1px solid #e0e0e0; }
        .model-tags { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
        .model-tag { background: white; border: 1px solid #ccc; padding: 8px 14px; border-radius: 20px; font-size: 14px; cursor: pointer; color: #333; transition: 0.2s; font-family: monospace; }
        .model-tag:hover { background: #e8f0fe; border-color: #1a73e8; color: #1a73e8; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        
        /* 表單元素 */
        textarea { width: 100%; height: 300px; font-family: 'Courier New', Courier, monospace; font-size: 14px; padding: 15px; border: 1px solid #ccc; border-radius: 8px; box-sizing: border-box; }
        input[type="password"], input[type="text"] { width: 100%; padding: 12px; font-size: 16px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; margin-bottom: 15px; }
        .btn-save { background-color: #34a853; color: white; padding: 12px; width: 100%; border: none; border-radius: 6px; font-size: 16px; font-weight: bold; cursor: pointer; margin-top: 15px; }
        .btn-restart { background-color: #ea4335; color: white; padding: 12px; width: 100%; border: none; border-radius: 6px; font-size: 16px; font-weight: bold; cursor: pointer; margin-top: 15px; }
        .btn-logout { display: block; text-align: center; background-color: #9aa0a6; color: white; padding: 10px; border-radius: 6px; text-decoration: none; margin-top: 30px; font-weight: bold; }
        .alert { padding: 15px; background-color: #e8f0fe; border-left: 5px solid #1a73e8; color: #1967d2; margin-bottom: 20px; border-radius: 4px; font-weight: bold; text-align: center; }
    </style>
</head>
<body>
    {% with messages = get_flashed_messages() %}
        {% if messages %}
            <div style="position: absolute; top: 10px; width: 100%; z-index: 2000;">
            {% for message in messages %}
                <div class="alert" style="max-width: 600px; margin: auto; box-shadow: 0 4px 12px rgba(0,0,0,0.2);">{{ message }}</div>
            {% endfor %}
            </div>
        {% endif %}
    {% endwith %}

    {% if not logged_in %}
    <div class="login-container">
        <h1>ErlangShen Control Center</h1>
        <form method="POST" action="/login">
            <h3>系統已鎖定，請登入：</h3>
            <input type="password" name="pwd" id="pwdInput" placeholder="請輸入管理員密碼..." required autofocus>
            <div style="text-align: right; margin-top: -10px; margin-bottom: 15px;">
                <label style="font-size: 14px; color: #5f6368; cursor: pointer;">
                    <input type="checkbox" onclick="document.getElementById('pwdInput').type = this.checked ? 'text' : 'password';"> 👁️ 顯示密碼
                </label>
            </div>
            <button type="submit" style="width: 100%; padding: 12px; background: #1a73e8; color: white; border: none; border-radius: 6px; font-size: 16px; font-weight: bold; cursor: pointer;">登入系統</button>
        </form>
    </div>
    {% else %}
    
    <div class="chat-container">
        <!-- 包含 Setting 按鈕、頭像與標題嘅完美 Header -->
        <div class="chat-header">
            <button class="header-setting-btn" onclick="document.getElementById('settingsModal').style.display='block'">⚙️ Setting</button>
            <img src="https://raw.githubusercontent.com/gdtohk/ErlangShen-Agent/main/ErlangShen_logo.png" alt="二郎神" style="height: 50px; width: 50px; border-radius: 50%; object-fit: cover; background: white; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.5);">
            <span style="font-size: 22px;">ErlangShen Agent - Web</span>
        </div>
        
        <div class="chat-box" id="chatBox">
            <div class="message msg-ai">老闆你好！ErlangShen 喺度。今晚有咩我可以幫到你？</div>
        </div>
        
        <div class="chat-input-area">
            <input type="text" id="userInput" placeholder="輸入文字..." onkeypress="if(event.key === 'Enter') sendMessage()">
            <button onclick="sendMessage()">發送</button>
        </div>
    </div>

    <div id="settingsModal" class="modal">
        <div class="modal-content">
            <span class="close-btn" onclick="document.getElementById('settingsModal').style.display='none'">&times;</span>
            <h1>⚙️ Configuration Panel</h1>
            <form method="POST" action="/save">
                <h3>編輯 .env 設定檔：</h3>
                
                <!-- 新增：快速模型切換視窗 -->
                <div class="model-selector">
                    <strong style="color: #444; font-size: 15px;">✨ 快速切換模型 (點擊自動替換下方文字)：</strong>
                    <div class="model-tags">
                        <span class="model-tag" onclick="replaceModel(this, 'gemini-3.1-pro-preview')">gemini-3.1-pro-preview</span>
                        <span class="model-tag" onclick="replaceModel(this, 'gemini-3.1-flash-lite-preview')">gemini-3.1-flash-lite-preview</span>
                        <span class="model-tag" onclick="replaceModel(this, 'gemini-3-pro-preview')">gemini-3-pro-preview</span>
                        <span class="model-tag" onclick="replaceModel(this, 'gemini-3-flash-preview')">gemini-3-flash-preview</span>
                        <span class="model-tag" onclick="replaceModel(this, 'gemini-2.5-pro')">gemini-2.5-pro</span>
                        <span class="model-tag" onclick="replaceModel(this, 'gemini-2.5-flash')">gemini-2.5-flash</span>
                        <span class="model-tag" onclick="replaceModel(this, 'gemini-2.5-flash-lite')">gemini-2.5-flash-lite</span>
                    </div>
                </div>

                <textarea name="env_content" id="envTextarea">{{ env_content }}</textarea>
                <button type="submit" class="btn-save">💾 儲存並覆蓋設定</button>
            </form>
            <hr style="margin: 30px 0; border: 0; border-top: 1px solid #eee;">
            <form method="POST" action="/restart" onsubmit="return confirm('確定要強行重新啟動二郎神嗎？');">
                <h3>🚀 系統操作：</h3>
                <button type="submit" class="btn-restart">🔄 重新啟動 bot.py</button>
            </form>
            <form method="POST" action="/clear_memory" onsubmit="return confirm('清除網頁版記憶體？');">
                <button type="submit" style="background-color: #fbbc04; color: black; padding: 12px; width: 100%; border: none; border-radius: 6px; font-size: 16px; font-weight: bold; cursor: pointer; margin-top: 15px;">🧠 清空網頁版記憶</button>
            </form>
            <a href="/logout" class="btn-logout">🚪 安全登出</a>
        </div>
    </div>

    <script>
        // 替換模型邏輯
        function replaceModel(buttonElem, modelName) {
            const textarea = document.getElementById('envTextarea');
            let content = textarea.value;
            // 尋找並替換 MODEL_NAME=... 這一行
            const regex = /^MODEL_NAME=.*$/m;
            if (regex.test(content)) {
                textarea.value = content.replace(regex, `MODEL_NAME=${modelName}`);
            } else {
                textarea.value = `MODEL_NAME=${modelName}\n` + content;
            }
            
            // 視覺回饋：變色加打勾
            const originalText = buttonElem.innerText;
            buttonElem.innerText = '✅ 已切換';
            buttonElem.style.background = '#e8f0fe';
            buttonElem.style.color = '#1a73e8';
            buttonElem.style.borderColor = '#1a73e8';
            
            setTimeout(() => {
                buttonElem.innerText = originalText;
                buttonElem.style.background = 'white';
                buttonElem.style.color = '#333';
                buttonElem.style.borderColor = '#ccc';
            }, 1500);
        }

        async function sendMessage() {
            const inputField = document.getElementById('userInput');
            const chatBox = document.getElementById('chatBox');
            const text = inputField.value.trim();
            if (!text) return;

            const userMsg = document.createElement('div');
            userMsg.className = 'message msg-user';
            userMsg.textContent = text;
            chatBox.appendChild(userMsg);
            inputField.value = '';
            chatBox.scrollTop = chatBox.scrollHeight;

            const aiMsg = document.createElement('div');
            aiMsg.className = 'message msg-ai';
            aiMsg.textContent = '⏳ 思考與調用工具中...';
            chatBox.appendChild(aiMsg);
            chatBox.scrollTop = chatBox.scrollHeight;

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text })
                });
                const data = await response.json();
                
                if (data.reply) {
                    aiMsg.innerHTML = data.reply.replace(/\\n/g, '<br>');
                } else {
                    aiMsg.textContent = '❌ ' + (data.error || '發生未知錯誤');
                }
            } catch (err) {
                aiMsg.textContent = '❌ 網絡錯誤或後端無回應。';
            }
            chatBox.scrollTop = chatBox.scrollHeight;
        }
        
        window.onclick = function(event) {
            var modal = document.getElementById('settingsModal');
            if (event.target == modal) {
                modal.style.display = "none";
            }
        }
    </script>
    {% endif %}
</body>
</html>
"""

@app.route('/')
def index():
    if not session.get('logged_in'):
        return render_template_string(HTML_TEMPLATE, logged_in=False)
    
    env_content = ""
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            env_content = f.read()
    
    show_settings = request.args.get('show_settings') == '1'
    return render_template_string(HTML_TEMPLATE, logged_in=True, env_content=env_content, show_settings=show_settings)

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('pwd') == ADMIN_PASSWORD:
        session['logged_in'] = True
        flash("✅ 登入成功！")
    else:
        flash("❌ 密碼錯誤！")
    return redirect('/')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/')

@app.route('/clear_memory', methods=['POST'])
def clear_memory():
    global WEB_MEMORY
    WEB_MEMORY = []
    flash("✅ 網頁版記憶體已清空！")
    return redirect('/?show_settings=1')

@app.route('/save', methods=['POST'])
def save():
    if not session.get('logged_in'): return redirect('/')
    new_content = request.form.get('env_content', '')
    new_content = new_content.replace('\r\n', '\n')
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    flash("✅ 設定已儲存！請緊記點擊「重新啟動 bot.py」令新設定生效。")
    return redirect('/?show_settings=1')

@app.route('/restart', methods=['POST'])
def restart():
    if not session.get('logged_in'): return redirect('/')
    try:
        os.system('pkill -f "python3 bot.py"')
        os.system('nohup python3 bot.py > agent.log 2>&1 &')
        flash("🚀 前線大腦 (bot.py) 已成功重新啟動！")
    except Exception as e:
        flash(f"❌ 重啟失敗：{str(e)}")
    return redirect('/?show_settings=1')

@app.route('/api/chat', methods=['POST'])
async def api_chat():
    global WEB_MEMORY
    if not session.get('logged_in'): return jsonify({"error": "未授權訪問"}), 401
    
    user_text = request.json.get('message', '')
    if not user_text: return jsonify({"error": "內容不能為空"}), 400

    config = dotenv_values(ENV_PATH)
    bot_name = config.get("BOT_NAME", "二郎神")
    owner_name = config.get("OWNER_NAME", "老闆")
    tz_str = config.get("TIMEZONE", "Asia/Hong_Kong")
    model = config.get("MODEL_NAME", "gemini-3.1-flash-lite-preview")
    
    api_url, api_key = None, None
    for i in range(1, 11):
        u = config.get(f"API_URL_{i}")
        k = config.get(f"API_KEY_{i}")
        if u and k:
            api_url, api_key = u, k
            break
            
    if not api_url:
        api_url = config.get("API_URL_3")
        api_key = config.get("API_KEY_3")

    if not api_url or not api_key:
        return jsonify({"error": "找不到有效的 API 引擎，請檢查 Setting 配置！"}), 500

    local_time = datetime.datetime.now(ZoneInfo(tz_str))
    sys_prompt = f"""你是{bot_name}，{owner_name}的專屬 AI 助理。請用地道廣東話回答。
    你現在正在 Web 控制面板與老闆對話。
    現在時間：{local_time.strftime('%Y-%m-%d %H:%M')}。"""

    if not WEB_MEMORY:
        WEB_MEMORY.append({"role": "system", "content": sys_prompt})
    else:
        WEB_MEMORY[0]["content"] = sys_prompt
        
    WEB_MEMORY.append({"role": "user", "content": user_text})
    
    if len(WEB_MEMORY) > MAX_HISTORY * 2 + 1:
        WEB_MEMORY.pop(1)
        WEB_MEMORY.pop(1)

    forbidden_tools = ['set_reminder', 'schedule_daily_weather']
    web_tools = [t for t in GET_TOOLS_LIST if t['function']['name'] not in forbidden_tools]

    payload = {
        "model": model,
        "messages": WEB_MEMORY,
        "tools": web_tools,
        "tool_choice": "auto"
    }

    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}
    if 'googleapis.com' in api_url:
        headers['x-goog-api-key'] = api_key

    try:
        async with aiohttp.ClientSession() as http_session:
            async with http_session.post(api_url, headers=headers, json=payload) as resp:
                data = await resp.json()
                msg = data['choices'][0]['message']

                if msg.get('tool_calls'):
                    temp_memory = list(WEB_MEMORY)
                    temp_memory.append(msg)
                    
                    for tc in msg['tool_calls']:
                        fn_name = tc['function']['name']
                        args_raw = tc['function']['arguments']
                        args = args_raw if isinstance(args_raw, dict) else json.loads(args_raw)
                        
                        try:
                            if fn_name in AGENT_TOOLS_REGISTRY:
                                res = await AGENT_TOOLS_REGISTRY[fn_name]["func"](chat_id=0, context=None, **args)
                                temp_memory.append({"role": "tool", "tool_call_id": tc['id'], "name": fn_name, "content": str(res)})
                        except Exception as e:
                            temp_memory.append({"role": "tool", "tool_call_id": tc['id'], "name": fn_name, "content": f"工具執行失敗: {str(e)}"})

                    payload["messages"] = temp_memory
                    async with http_session.post(api_url, headers=headers, json=payload) as resp2:
                        data2 = await resp2.json()
                        final_reply = data2['choices'][0]['message']['content']
                        WEB_MEMORY.append({"role": "assistant", "content": final_reply})
                        return jsonify({"reply": final_reply})
                else:
                    reply = msg.get('content', "✅ 已收到指令。")
                    WEB_MEMORY.append({"role": "assistant", "content": reply})
                    return jsonify({"reply": reply})
                    
    except Exception as e:
        WEB_MEMORY.pop() 
        return jsonify({"error": f"連線或執行失敗: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
