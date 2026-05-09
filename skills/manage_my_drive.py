import os
import pandas as pd
import fitz

async def manage_my_drive(chat_id, context, path: str = "") -> str:
    """
    瀏覽或讀取 my_drive 中的文件。
    """
    base_path = "/home/ubuntu/ErlangShen-Agent/my_drive"
    # 過濾並確保路徑安全
    safe_path = path.replace("my_drive/", "").lstrip("/")
    full_path = os.path.join(base_path, safe_path)

    if not os.path.exists(full_path):
        return f"❌ 找不到路徑：{safe_path}。請確認文件或資料夾名稱。"

    # 如果是資料夾，返回目錄清單
    if os.path.isdir(full_path):
        try:
            items = os.listdir(full_path)
            if not items:
                return f"📂 資料夾 '{safe_path}' 是空的。"
            res = f"📂 資料夾 '{safe_path}' 內容清單：\n" + "\n".join([f"- {item}" for item in items])
            return res
        except Exception as e:
            return f"❌ 無法讀取資料夾：{str(e)}"
            
    # 如果是文件，讀取內容
    else:
        ext = os.path.splitext(full_path)[1].lower()
        try:
            if ext == '.pdf':
                doc = fitz.open(full_path)
                text = f"【PDF 文件：{safe_path} (共 {len(doc)} 頁)】\n"
                # 為防止塞爆，最多提取前 10 頁的純文字
                for i in range(min(10, len(doc))):  
                    text += f"\n--- 第 {i+1} 頁 ---\n"
                    text += doc[i].get_text("text")
                return text[:20000]
                
            elif ext in ['.xlsx', '.xls', '.csv']:
                if ext == '.csv':
                    df = pd.read_csv(full_path)
                else:
                    df = pd.read_excel(full_path)
                return f"【表格文件：{safe_path}】\n" + df.to_markdown(index=False)[:20000]
                
            elif ext in ['.txt', '.md', '.log']:
                with open(full_path, 'r', encoding='utf-8') as f:
                    return f"【文字文件：{safe_path}】\n" + f.read()[:20000]
            else:
                return f"❌ 暫時不支援解析 {ext} 格式的內容，但已確認文件存在於雲端。"
                
        except Exception as e:
            return f"❌ 讀取文件失敗：{str(e)}"
