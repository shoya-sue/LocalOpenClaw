"""agents/memory.py 単体テスト"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))


class TestAgentMemory(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._base = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _patch(self):
        return patch("app.agents.memory.AGENT_MEMORY_PATH", self._base)

    def test_read_memory_nonexistent_returns_empty(self):
        from app.agents.memory import read_memory
        with self._patch():
            result = read_memory("leader", "memory.md")
        self.assertEqual(result, "")

    def test_write_and_read_memory(self):
        from app.agents.memory import read_memory, write_memory
        with self._patch():
            write_memory("leader", "memory.md", "テスト内容")
            result = read_memory("leader", "memory.md")
        self.assertEqual(result, "テスト内容")

    def test_write_memory_creates_directories(self):
        from app.agents.memory import write_memory
        with self._patch():
            write_memory("new_agent", "notes.md", "メモ")
            expected = self._base / "new_agent" / "memory" / "notes.md"
            self.assertTrue(expected.exists())

    def test_append_memory_to_existing(self):
        from app.agents.memory import append_memory, read_memory, write_memory
        with self._patch():
            write_memory("leader", "memory.md", "最初の行")
            append_memory("leader", "memory.md", "追記行")
            result = read_memory("leader", "memory.md")
        self.assertIn("最初の行", result)
        self.assertIn("追記行", result)

    def test_append_memory_to_nonexistent_creates_file(self):
        from app.agents.memory import append_memory, read_memory
        with self._patch():
            append_memory("leader", "new.md", "初回追記")
            result = read_memory("leader", "new.md")
        self.assertEqual(result, "初回追記")

    def test_list_memory_files_returns_md_files(self):
        from app.agents.memory import list_memory_files, write_memory
        with self._patch():
            write_memory("leader", "memory.md", "内容A")
            write_memory("leader", "notes.md", "内容B")
            files = list_memory_files("leader")
        self.assertIn("memory.md", files)
        self.assertIn("notes.md", files)
        self.assertEqual(len(files), 2)

    def test_list_memory_files_empty_for_no_agent(self):
        from app.agents.memory import list_memory_files
        with self._patch():
            result = list_memory_files("nonexistent_agent")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
