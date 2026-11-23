import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sync_notion


class SyncNotionTests(unittest.TestCase):
    def test_join_plain_text_preserves_formatted_segments(self):
        page = {
            "id": "page-1",
            "properties": {
                "Title": {
                    "title": [
                        {"plain_text": "Alloy engineering of PbS"},
                        {"plain_text": "1-x"},
                        {"plain_text": "Se"},
                        {"plain_text": "x"},
                        {"plain_text": " nanostructures"},
                    ]
                },
                "Journal": {
                    "rich_text": [
                        {"plain_text": "Journal of "},
                        {"plain_text": "Alloys and Compounds"},
                    ]
                },
                "Year": {"rich_text": [{"plain_text": "2026-09-15"}]},
                "DOI": {"url": "https://doi.org/10.1016/j.jallcom.2026.191490"},
                "Citations": {"number": 12},
                "打星號論文": {"select": {"name": "是"}},
                "研究亮點": {"formula": {"string": None}},
                "內文圖1網址": {"url": "javascript:alert(1)"},
                "期刊圖網址": {"url": "https://ars.els-cdn.com/content/image/X1.jpg"},
                "Authors": {"rich_text": [{"plain_text": "Yuan-Ron Ma*, A. Researcher"}]},
            },
        }
        item = sync_notion.transform_page(page)
        self.assertEqual(item["id"], "page-1")
        self.assertEqual(item["title"], "Alloy engineering of PbS1-xSex nanostructures")
        self.assertEqual(item["journal"], "Journal of Alloys and Compounds")
        self.assertEqual(item["year"], "2026")
        self.assertEqual(item["citations"], 12)
        self.assertEqual(item["is_star"], "是")
        self.assertEqual(item["highlight"], "")
        # Invalid javascript: URL rejected, falls back to journal_url
        self.assertEqual(item["cover_url"], "https://ars.els-cdn.com/content/image/X1.jpg")
        self.assertEqual(item["file_img"], "https://ars.els-cdn.com/content/image/X1.jpg")
        self.assertEqual(item["authors"], "Yuan-Ron Ma*, A. Researcher")

    def test_missing_env_returns_nonzero_exit_code(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(sync_notion.main(), 1)

    def test_api_failure_does_not_overwrite_existing_papers(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers_path = Path(tmp) / "papers.json"
            meta_path = Path(tmp) / "meta.json"
            original = [{"title": "Existing", "year": "2025", "citations": 5}]
            papers_path.write_text(json.dumps(original), encoding="utf-8")

            mock_session = MagicMock()
            mock_session.post.side_effect = RuntimeError("Network down")

            with patch.dict(os.environ, {"NOTION_TOKEN": "tok", "DATABASE_ID": "db"}):
                with self.assertRaises(RuntimeError):
                    sync_notion.sync_notion_to_json(
                        papers_path=papers_path,
                        meta_path=meta_path,
                        session=mock_session,
                    )

            self.assertEqual(json.loads(papers_path.read_text(encoding="utf-8")), original)
            self.assertFalse(meta_path.exists())

    def test_sudden_drop_guard_blocks_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers_path = Path(tmp) / "papers.json"
            existing = [{"title": f"Paper {i}", "year": "2020", "citations": i} for i in range(20)]
            papers_path.write_text(json.dumps(existing), encoding="utf-8")

            with self.assertRaises(RuntimeError):
                sync_notion.validate_against_existing(existing[:5], papers_path, allow_large_drop=False)

            # Explicit override works
            sync_notion.validate_against_existing(existing[:5], papers_path, allow_large_drop=True)

    def test_compute_h_index_and_metadata(self):
        papers = [
            {"title": "A", "year": "2025", "citations": 100, "is_star": "是", "cover_url": "https://a.com/1.jpg"},
            {"title": "B", "year": "2024", "citations": 10, "is_star": "否", "cover_url": ""},
            {"title": "C", "year": "2023", "citations": 3, "is_star": "是", "cover_url": "https://a.com/2.jpg"},
            {"title": "D", "year": "2022", "citations": 1, "is_star": "否", "cover_url": ""},
        ]
        meta = sync_notion.build_metadata(papers, updated_at="2026-11-23T00:00:00Z")
        self.assertEqual(meta["total_papers"], 4)
        self.assertEqual(meta["total_citations"], 114)
        self.assertEqual(meta["h_index"], 3)
        self.assertEqual(meta["starred_count"], 2)
        self.assertEqual(meta["with_cover_count"], 2)


if __name__ == "__main__":
    unittest.main()
