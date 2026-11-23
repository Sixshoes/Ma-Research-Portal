"""Notion 論文資料庫清洗同步腳本。

從 Notion Database 抓取所有分頁資料，清洗並輸出為：
- papers.json：提供 Ma-Research-Portal 預覽頁與 ma-portfolio 官網讀取
- meta.json：提供統計摘要（總篇數、總引用數、H-index、更新時間）
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
REQUEST_TIMEOUT_SECONDS = 30
MAX_DROP_RATIO = 0.30
SCHEMA_VERSION = 2

YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")

BASE_DIR = Path(__file__).resolve().parent
PAPERS_PATH = BASE_DIR / "papers.json"
META_PATH = BASE_DIR / "meta.json"


def build_session() -> requests.Session:
    """建立具備 429/5xx 自動重試與指數退避的 HTTP Session。"""
    retry = Retry(
        total=4,
        connect=3,
        read=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["POST"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    return session


def join_plain_text(rich_items: list[dict[str, Any]] | None) -> str:
    """串接 Notion title / rich_text 所有分段，避免格式化文字遭截斷。"""
    if not rich_items:
        return ""
    return "".join((seg.get("plain_text") or "") for seg in rich_items).strip()


def extract_property_text(props: dict[str, Any], *candidate_names: str) -> str:
    """嘗試從多個候選欄位名稱安全讀取文字內容（支援 title/rich_text/formula/select/url）。"""
    for name in candidate_names:
        prop = props.get(name)
        if not isinstance(prop, dict):
            continue
        if "title" in prop:
            text = join_plain_text(prop.get("title"))
            if text:
                return text
        if "rich_text" in prop:
            text = join_plain_text(prop.get("rich_text"))
            if text:
                return text
        if "formula" in prop and isinstance(prop.get("formula"), dict):
            val = prop["formula"].get("string")
            if isinstance(val, str) and val.strip():
                return val.strip()
        if "select" in prop and isinstance(prop.get("select"), dict):
            val = prop["select"].get("name")
            if isinstance(val, str) and val.strip():
                return val.strip()
        if "url" in prop and isinstance(prop.get("url"), str):
            val = prop["url"].strip()
            if val:
                return val
    return ""


def sanitize_url(raw: Any) -> str:
    """僅保留合法的 http/https URL，其餘回傳空字串。"""
    if not isinstance(raw, str):
        return ""
    url = raw.strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url
    return ""


def clean_year(year_prop: dict[str, Any] | None) -> str:
    """清洗年份欄位（支援 rich_text、number、date），抽出四位西元年。"""
    if not isinstance(year_prop, dict):
        return ""
    raw = ""
    if year_prop.get("rich_text"):
        raw = join_plain_text(year_prop.get("rich_text"))
    elif year_prop.get("number") is not None:
        raw = str(int(year_prop["number"]))
    elif isinstance(year_prop.get("date"), dict) and year_prop["date"].get("start"):
        raw = str(year_prop["date"]["start"])

    raw = raw.strip()
    if not raw:
        return ""
    match = YEAR_PATTERN.search(raw)
    if match:
        return match.group(1)
    return raw.split("-")[0].strip()


def clean_citations(cit_prop: dict[str, Any] | None) -> int:
    """安全轉換引用次數為非負整數。"""
    if not isinstance(cit_prop, dict):
        return 0
    val = cit_prop.get("number")
    if val is None:
        return 0
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return 0


def transform_page(page: dict[str, Any]) -> dict[str, Any]:
    """將單筆 Notion Page 轉換為標準化的論文物件。"""
    props = page.get("properties") or {}

    content_url = sanitize_url((props.get("內文圖1網址") or {}).get("url"))
    journal_url = sanitize_url((props.get("期刊圖網址") or {}).get("url"))
    cover_url = content_url or journal_url

    title_text = join_plain_text((props.get("Title") or {}).get("title")) or "無標題"
    journal_text = join_plain_text((props.get("Journal") or {}).get("rich_text")) or "Unknown"
    year_text = clean_year(props.get("Year"))
    doi_url = sanitize_url((props.get("DOI") or {}).get("url"))
    citations = clean_citations(props.get("Citations"))

    star_select = (props.get("打星號論文") or {}).get("select") or {}
    is_star = (star_select.get("name") or "否").strip()

    highlight_formula = (props.get("研究亮點") or {}).get("formula") or {}
    highlight = (highlight_formula.get("string") or "").strip()

    item: dict[str, Any] = {
        "id": str(page.get("id") or "").strip(),
        "title": title_text,
        "year": year_text,
        "journal": journal_text,
        "doi": doi_url,
        "citations": citations,
        "is_star": is_star,
        "highlight": highlight,
        "cover_url": cover_url,
        "file_img": journal_url,
    }

    # 選擇性擴充欄位：若 Notion 未來新增對應欄位即自動輸出給 A 站使用
    authors = extract_property_text(props, "Authors", "作者")
    takeaway = extract_property_text(props, "Takeaway", "核心亮點", "關鍵亮點")
    abstract_excerpt = extract_property_text(props, "Abstract", "Abstract Excerpt", "摘要")
    if authors:
        item["authors"] = authors
    if takeaway:
        item["takeaway"] = takeaway
    if abstract_excerpt:
        item["abstract_excerpt"] = abstract_excerpt

    return item


def sort_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """固定排序確保 git diff 乾淨穩定：年份新到舊 → 引用高到低 → 標題 → DOI。"""

    def sort_key(p: dict[str, Any]) -> tuple[int, int, str, str, str]:
        try:
            year_num = int(str(p.get("year") or "0"))
        except ValueError:
            year_num = 0
        return (
            -year_num,
            -int(p.get("citations") or 0),
            str(p.get("title") or "").lower(),
            str(p.get("doi") or "").lower(),
            str(p.get("id") or ""),
        )

    return sorted(papers, key=sort_key)


def compute_h_index(citations_list: list[int]) -> int:
    """根據引用數列表計算 H-index。"""
    ordered = sorted((max(0, int(c)) for c in citations_list), reverse=True)
    h = 0
    for idx, cit in enumerate(ordered, start=1):
        if cit >= idx:
            h = idx
        else:
            break
    return h


def build_metadata(papers: list[dict[str, Any]], updated_at: str | None = None) -> dict[str, Any]:
    """從論文列表產出統計摘要 metadata。"""
    citations_list = [int(p.get("citations") or 0) for p in papers]
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": updated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_papers": len(papers),
        "total_citations": sum(citations_list),
        "h_index": compute_h_index(citations_list),
        "starred_count": sum(1 for p in papers if p.get("is_star") == "是"),
        "with_cover_count": sum(1 for p in papers if p.get("cover_url")),
    }


def fetch_all_notion_pages(
    token: str,
    database_id: str,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """完整翻頁抓取 Notion Database；任一分頁失敗即拋出例外中止。"""
    url = f"{NOTION_API_BASE}/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    http = session or build_session()
    all_raw_data: list[dict[str, Any]] = []
    has_more = True
    next_cursor: str | None = None

    print("🚀 [中繼站] 開始從 Notion 搬運所有資料...")

    while has_more:
        payload: dict[str, Any] = {"page_size": 100}
        if next_cursor:
            payload["start_cursor"] = next_cursor

        res = http.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        res.raise_for_status()
        data = res.json()

        results = data.get("results")
        if not isinstance(results, list):
            raise RuntimeError("Notion API 回傳格式異常：缺少 results 陣列。")

        all_raw_data.extend(results)
        has_more = bool(data.get("has_more", False))
        next_cursor = data.get("next_cursor")
        print(f"📥 已成功下載: {len(all_raw_data)} 筆...")

        if has_more and not next_cursor:
            raise RuntimeError("Notion API 回傳 has_more=True 但缺少 next_cursor，已中止以防資料不完整。")

    return all_raw_data


def validate_against_existing(
    new_papers: list[dict[str, Any]],
    papers_path: Path,
    allow_large_drop: bool = False,
) -> None:
    """防呆閘門：禁止空資料或異常驟降覆蓋既有正式檔案。"""
    if len(new_papers) == 0:
        raise RuntimeError("抓取結果為 0 筆，已中止寫入以避免清空 papers.json。")

    if not papers_path.exists() or allow_large_drop:
        return

    try:
        existing = json.loads(papers_path.read_text(encoding="utf-8"))
    except Exception:
        return

    if isinstance(existing, list) and len(existing) >= 10:
        min_allowed = int(len(existing) * (1 - MAX_DROP_RATIO))
        if len(new_papers) < min_allowed:
            raise RuntimeError(
                f"安全閘門觸發：新資料僅 {len(new_papers)} 筆，相較既有 {len(existing)} 筆"
                f"驟降超過 {int(MAX_DROP_RATIO * 100)}%。若確定屬正常刪減，請設定環境變數 ALLOW_LARGE_DROP=true。"
            )


def atomic_write_json(path: Path, payload: Any) -> None:
    """以暫存檔 + os.replace 原子寫入 JSON，避免寫到一半毀損檔案。"""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def load_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def sync_notion_to_json(
    papers_path: Path = PAPERS_PATH,
    meta_path: Path = META_PATH,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """主同步流程：驗證環境變數 → 抓取 → 清洗排序 → 安全校驗 → 原子寫入。"""
    token = (os.getenv("NOTION_TOKEN") or "").strip()
    database_id = (os.getenv("DATABASE_ID") or "").strip()
    if not token or not database_id:
        raise RuntimeError("找不到 NOTION_TOKEN 或 DATABASE_ID，請檢查環境變數或 GitHub Secrets 設定。")

    allow_large_drop = (os.getenv("ALLOW_LARGE_DROP") or "").strip().lower() == "true"

    raw_pages = fetch_all_notion_pages(token, database_id, session=session)
    print("🧹 開始數據清洗與確定性排序...")
    refined_papers = sort_papers([transform_page(page) for page in raw_pages])

    validate_against_existing(refined_papers, papers_path, allow_large_drop=allow_large_drop)

    existing_papers = load_json_if_exists(papers_path)
    papers_changed = existing_papers != refined_papers

    if papers_changed:
        atomic_write_json(papers_path, refined_papers)

    existing_meta = load_json_if_exists(meta_path)
    candidate_meta = build_metadata(refined_papers)

    meta_stats_keys = (
        "schema_version",
        "total_papers",
        "total_citations",
        "h_index",
        "starred_count",
        "with_cover_count",
    )
    meta_needs_write = (
        papers_changed
        or not isinstance(existing_meta, dict)
        or any(existing_meta.get(k) != candidate_meta.get(k) for k in meta_stats_keys)
    )

    if meta_needs_write:
        atomic_write_json(meta_path, candidate_meta)

    print("-" * 50)
    print(
        f"✅ 同步完成：共 {candidate_meta['total_papers']} 筆、"
        f"總引用 {candidate_meta['total_citations']} 次、H-index {candidate_meta['h_index']}"
        f"（{'資料已更新' if papers_changed else '資料無變動'}）"
    )
    return candidate_meta


def main() -> int:
    try:
        sync_notion_to_json()
        return 0
    except Exception as exc:
        print(f"❌ 同步失敗：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
