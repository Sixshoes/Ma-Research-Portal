# Ma-Research-Portal

馬遠榮副校長（Prof. Yuan-Ron Ma）學術研究資料中繼站與靜態預覽窗。

本專案透過 GitHub Actions 每日定時從 Notion 論文資料庫抓取最新資料，清洗並輸出為 `papers.json` 與 `meta.json`，發布至 GitHub Pages，供正式個人官網（[ma-portfolio](https://github.com/Sixshoes/ma-portfolio)）跨站讀取。

## 架構說明

- **`sync_notion.py`**：Notion 同步與清洗腳本（支援自動翻頁、429/5xx 指數退避重試、空資料與筆數驟降安全閘門、原子寫入與確定性排序）。
- **`papers.json`**：清洗後的完整論文清單。
- **`meta.json`**：統計摘要（`total_papers`、`total_citations`、`h_index`、`starred_count`、`with_cover_count`、`updated_at`）。
- **`index.html`**：獨立靜態預覽頁面（支援搜尋、近五年／全部切換、圖片備援）。
- **`.github/workflows/sync.yml`**：每日 UTC 01:00（台北時間 09:00）自動執行同步與推送。

## Notion 資料庫欄位對應

| Notion 欄位名稱 | 類型 | 輸出鍵名 | 說明 |
| :--- | :--- | :--- | :--- |
| `Title` | Title | `title` | 論文標題（自動串接所有格式化分段） |
| `Year` | Rich text / Number / Date | `year` | 發表西元年 |
| `Journal` | Rich text | `journal` | 發表期刊名稱 |
| `DOI` | URL | `doi` | 文獻 DOI 或連結 |
| `Citations` | Number | `citations` | 引用次數 |
| `打星號論文` | Select | `is_star` | `是`（通訊／第一作者）或 `否` |
| `研究亮點` | Formula (string) | `highlight` | 亮點分級標記 |
| `內文圖1網址` | URL | `cover_url`（優先） | 圖文摘要永久圖片連結 |
| `期刊圖網址` | URL | `file_img` / `cover_url` 備援 | 期刊封面永久圖片連結 |
| `Authors` / `作者`（選填） | Rich text | `authors` | 作者名單（提供官網高亮呈現） |
| `Takeaway` / `核心亮點`（選填） | Rich text | `takeaway` | 以 `\|` 分隔之研究亮點 |
| `Abstract` / `摘要`（選填） | Rich text | `abstract_excerpt` | 可展開閱讀之摘要文字 |

## 本機開發與測試

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

手動執行同步（需先設定環境變數）：

```bash
export NOTION_TOKEN="secret_xxx"
export DATABASE_ID="xxxxxxxx"
python sync_notion.py
```

若確實大量刪除 Notion 舊資料而觸發驟降保護，可臨時加上 `ALLOW_LARGE_DROP=true` 執行。
