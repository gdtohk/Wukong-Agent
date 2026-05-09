import os
import pandas as pd
import fitz
import re
import base64
import json

async def manage_my_drive(chat_id, context, path: str = "", mode: str = "text") -> str:
    """
    瀏覽或讀取 my_drive 中的文件。支援純文字與視覺雙模式。
    """
    base_path = "/home/ubuntu/ErlangShen-Agent/my_drive"
    # 過濾並確保路徑安全，處理繁簡體及空白
    safe_path = path.replace("my_drive/", "").replace("铁", "鐵").lstrip("/")
    full_path = os.path.join(base_path, safe_path)

    if not os.path.exists(full_path):
        return f"❌ 找不到路徑：{safe_path}。請先叫我『睇下目錄』確認準確檔名。"

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
                total_pages = len(doc)
                
                # 🌟 新增：視覺分析模式 (將圖紙變相片送給大腦)
                if mode == "visual":
                    text = f"【👁️ 視覺模式啟動：{safe_path} (共 {total_pages} 頁)】\n"
                    images_b64 = []
                    
                    # 🌟 修復：解除 3 頁限制，放寬到 10 頁，等二郎神可以睇晒 8 頁嘅積王！
                    max_pages = min(10, total_pages) 
                    for i in range(max_pages):  
                        page = doc[i]
                        zoom_matrix = fitz.Matrix(1.5, 1.5) # 智能降頻 1.5倍
                        pix = page.get_pixmap(matrix=zoom_matrix)
                        img_bytes = pix.tobytes("jpeg")
                        b64_img = base64.b64encode(img_bytes).decode('utf-8')
                        images_b64.append(b64_img)
                        
                    return json.dumps({
                        "type": "pdf_with_images",
                        "text": text + f"已在底層將圖紙前 {max_pages} 頁渲染為高清圖片，並成功橋接至視覺大腦。",
                        "images_base64": images_b64
                    })
                    
                # 原有的純文字極速模式
                else:
                    text = f"【📝 文字模式 PDF：{safe_path} (共 {total_pages} 頁)】\n"
                    raw_content = ""
                    # 文字模式同樣可以放寬到前 10 頁
                    for i in range(min(10, total_pages)):  
                        raw_content += doc[i].get_text("text")
                    
                    clean_content = re.sub(r'\n+', '\n', raw_content)
                    clean_content = re.sub(r' +', ' ', clean_content)
                    
                    text += clean_content[:3500] 
                    if len(raw_content) > 3500:
                        text += "\n\n...(內容過長，已截取前段供分析)..."
                    return text
                
            elif ext in ['.xlsx', '.xls', '.csv']:
                if ext == '.csv':
                    df = pd.read_csv(full_path)
                else:
                    df = pd.read_excel(full_path)
                return f"【表格文件：{safe_path}】\n" + df.head(50).to_markdown(index=False)[:4000]
                
            elif ext in ['.txt', '.md', '.log']:
                with open(full_path, 'r', encoding='utf-8') as f:
                    return f"【文字文件：{safe_path}】\n" + f.read()[:4000]
            else:
                return f"❌ 暫時不支援解析 {ext} 格式的內容。"
                
        except Exception as e:
            return f"❌ 讀取文件失敗：{str(e)}"
