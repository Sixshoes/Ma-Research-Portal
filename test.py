import requests
import json
import os

# --- ⚙️ 配置區 ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")

def sync_notion_to_window():
    # 確保變數有抓到
    if not NOTION_TOKEN or not DATABASE_ID:
        print("❌ 錯誤：找不到 NOTION_TOKEN 或 DATABASE_ID，請檢查環境變數設定。")
        return

    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    all_raw_data = []
    has_more, next_cursor = True, None

    print("🚀 [中繼站] 開始從 Notion 搬運所有資料...")

    # 🔄 階段 1：自動翻頁抓取 (解決 100 筆限制)
    while has_more:
        payload = {"start_cursor": next_cursor} if next_cursor else {}
        try:
            res = requests.post(url, headers=headers, json=payload)
            res.raise_for_status() # 如果 API 報錯會直接跳到 except
            data = res.json()
            results = data.get("results", [])
            all_raw_data.extend(results)
            
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor", None)
            print(f"📥 已成功下載: {len(all_raw_data)} 筆...")
        except Exception as e:
            print(f"❌ API 請求失敗: {e}")
            break

    # 🧹 階段 2：深度清洗與防錯處理
    refined_papers = []
    print("🧹 開始數據清洗 (已啟動空值安全防護機制)...")

    for page in all_raw_data:
        props = page.get("properties", {})
        
        # 🛡️ A. 處理圖片：優先內文網址 -> 期刊網址 -> 前端遮罩
        content_url = props.get("內文圖1網址", {}).get("url") or ""
        journal_url = props.get("期刊圖網址", {}).get("url") or ""
        # 如果兩者都沒有，前端會顯示 YRM 遮罩
        cover_url = content_url if content_url else journal_url

        # 🛡️ B. 處理「期刊封面」備查圖
        # 直接拿你手動貼的「期刊圖網址」來用，保證是永久連結，徹底拋棄 Notion 檔案！
        file_img_url = journal_url 

        # 📅 C. 年份清洗 (2023-09-15 -> 2023)
        year_rich_list = props.get("Year", {}).get("rich_text") or []
        raw_year = year_rich_list[0].get("plain_text", "") if year_rich_list else ""
        clean_year = raw_year.split("-")[0] if "-" in raw_year else raw_year

        # 📦 D. 組合最終物件 (加入嚴格的空值安全防護)
        title_list = props.get("Title", {}).get("title") or []
        title_text = title_list[0].get("plain_text", "無標題") if title_list else "無標題"

        journal_rich = props.get("Journal", {}).get("rich_text") or []
        journal_text = journal_rich[0].get("plain_text", "Unknown") if journal_rich else "Unknown"

        item = {
            "title": title_text,
            "year": clean_year,
            "journal": journal_text,
            "doi": props.get("DOI", {}).get("url") or "",
            "citations": props.get("Citations", {}).get("number") or 0,
            "is_star": (props.get("打星號論文", {}).get("select") or {}).get("name", "否"),
            "highlight": (props.get("研究亮點", {}).get("formula") or {}).get("string", ""),
            "cover_url": cover_url,    # 前端主圖 (永久連結)
            "file_img": file_img_url   # 實體封面備查 (永久連結)
        }
        refined_papers.append(item)

    # 💾 階段 3：存檔
    with open("papers.json", "w", encoding="utf-8") as f:
        json.dump(refined_papers, f, ensure_ascii=False, indent=2)
    
    print("-" * 50)
    print(f"✅ 大功告成！已產出乾淨的 'papers.json' (共 {len(refined_papers)} 筆)")
    print("👉 現在你可以刷新網頁看成果了！")

if __name__ == "__main__":
    sync_notion_to_window()
