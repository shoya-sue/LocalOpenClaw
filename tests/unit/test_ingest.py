"""ingest.py のロジック単体テスト（stdlib のみ、ChromaDB接続不要）"""
import sys
import os
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../pipeline'))

from ingest import chunk_text, iter_documents


class TestChunkText(unittest.TestCase):
    def test_short_text_returns_single_chunk(self):
        text = "短いテキスト"
        result = chunk_text(text)
        self.assertEqual(result, [text])

    def test_long_text_is_split(self):
        # 800字を超えるテキストは分割される
        text = "あ" * 1600
        result = chunk_text(text)
        self.assertGreater(len(result), 1)

    def test_all_chunks_are_nonempty(self):
        text = "テスト。" * 300  # 約1200字
        result = chunk_text(text)
        for chunk in result:
            self.assertTrue(len(chunk) > 0)

    def test_overlap_means_total_chars_exceed_original(self):
        # チャンクの合計文字数 > 元テキスト（重複があるため）
        text = "x" * 2000
        chunks = chunk_text(text, chunk_size=500, overlap=100)
        total = sum(len(c) for c in chunks)
        self.assertGreater(total, len(text))


class TestIterDocuments(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def test_empty_dir_yields_nothing(self):
        results = list(iter_documents(self.tmpdir))
        self.assertEqual(results, [])

    def test_md_file_is_included(self):
        (self.tmpdir / "test.md").write_text("マークダウン内容", encoding="utf-8")
        results = list(iter_documents(self.tmpdir))
        self.assertEqual(len(results), 1)
        doc_id, text, meta = results[0]
        self.assertIn("マークダウン内容", text)
        self.assertEqual(meta["source"], "test.md")

    def test_txt_file_is_included(self):
        (self.tmpdir / "notes.txt").write_text("テキスト内容", encoding="utf-8")
        results = list(iter_documents(self.tmpdir))
        self.assertEqual(len(results), 1)

    def test_other_extensions_are_skipped(self):
        (self.tmpdir / "data.json").write_text('{"key": "value"}', encoding="utf-8")
        (self.tmpdir / "image.png").write_bytes(b"\x89PNG")
        results = list(iter_documents(self.tmpdir))
        self.assertEqual(results, [])

    def test_empty_file_is_skipped(self):
        (self.tmpdir / "empty.md").write_text("", encoding="utf-8")
        results = list(iter_documents(self.tmpdir))
        self.assertEqual(results, [])

    def test_chunk_index_in_metadata(self):
        # 大きなファイルが複数チャンクになった場合、メタデータに chunk_index が含まれる
        (self.tmpdir / "big.md").write_text("テスト。" * 500, encoding="utf-8")
        results = list(iter_documents(self.tmpdir))
        self.assertGreater(len(results), 1)
        for doc_id, text, meta in results:
            self.assertIn("chunk_index", meta)
            self.assertIn("total_chunks", meta)
            self.assertEqual(meta["total_chunks"], len(results))


if __name__ == "__main__":
    unittest.main()
