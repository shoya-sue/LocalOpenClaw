"""memory.py 単体テスト（stdlib のみ）"""
import sys
import os
import tempfile
import unittest

# backend/app を Python パスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))

# AGENT_MEMORY_PATH を一時ディレクトリに差し替えてからインポート
_tmp_dir = tempfile.mkdtemp()
os.environ["AGENT_MEMORY_PATH"] = _tmp_dir

# モジュール再ロード防止のため、importlib で確実に最新パスを使用
import importlib
import app.agents.memory as mem_mod
importlib.reload(mem_mod)

from app.agents.memory import (
    read_memory,
    write_memory,
    append_memory,
    list_memory_files,
)


class TestMemory(unittest.TestCase):
    AGENT = "test_agent"

    def test_read_nonexistent_returns_empty(self):
        content = read_memory(self.AGENT, "no_such_file.md")
        self.assertEqual(content, "")

    def test_write_and_read_roundtrip(self):
        write_memory(self.AGENT, "test.md", "hello world")
        self.assertEqual(read_memory(self.AGENT, "test.md"), "hello world")

    def test_write_overwrites_existing(self):
        write_memory(self.AGENT, "over.md", "first")
        write_memory(self.AGENT, "over.md", "second")
        self.assertEqual(read_memory(self.AGENT, "over.md"), "second")

    def test_append_adds_content(self):
        # append_memory は既存内容と追記内容を "\n" で連結する
        write_memory(self.AGENT, "append.md", "line1\n")
        append_memory(self.AGENT, "append.md", "line2\n")
        self.assertEqual(read_memory(self.AGENT, "append.md"), "line1\n\nline2\n")

    def test_list_files_returns_created_files(self):
        write_memory(self.AGENT, "a.md", "a")
        write_memory(self.AGENT, "b.md", "b")
        files = list_memory_files(self.AGENT)
        self.assertIn("a.md", files)
        self.assertIn("b.md", files)

    def test_list_files_empty_agent_returns_empty_list(self):
        files = list_memory_files("brand_new_agent_xyz")
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
