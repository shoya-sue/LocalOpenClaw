"""ReActAgent 単体テスト（LLM・WebSocketはモック）"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

# chromadb・fastapi はテスト環境に未インストールのため、モジュールレベルでモックを登録する
# これにより rag.py の `import chromadb` および manager.py の `from fastapi import WebSocket`
# による ImportError を回避する
import types

_chromadb_mock = types.ModuleType("chromadb")
_chromadb_mock.HttpClient = MagicMock
sys.modules.setdefault("chromadb", _chromadb_mock)

_fastapi_mock = types.ModuleType("fastapi")
_fastapi_mock.WebSocket = MagicMock
sys.modules.setdefault("fastapi", _fastapi_mock)


class TestParseAction(unittest.TestCase):
    """_parse_action の単体テスト"""

    def _parse(self, text: str):
        from app.agents.react import ReActAgent
        return ReActAgent._parse_action(text)

    def test_valid_json(self):
        text = '{"thought": "考え中", "action": "finish", "result": "完了"}'
        result = self._parse(text)
        self.assertEqual(result["action"], "finish")

    def test_json_in_code_block(self):
        text = '```json\n{"thought": "考え中", "action": "read_file", "path": "a.txt"}\n```'
        result = self._parse(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "read_file")

    def test_json_embedded_in_text(self):
        text = '以下が回答です: {"thought": "T", "action": "finish", "result": "R"} 以上。'
        result = self._parse(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "finish")

    def test_think_block_removed(self):
        text = '<think>内部思考</think>\n{"thought": "T", "action": "finish", "result": "R"}'
        result = self._parse(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "finish")

    def test_invalid_json_returns_none(self):
        result = self._parse("これはJSONではない")
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        result = self._parse("")
        self.assertIsNone(result)


class TestSafePath(unittest.TestCase):
    """_safe_path のパストラバーサル対策テスト"""

    def _safe_path(self, root: Path, user_path: str):
        from app.agents.react import _safe_path
        return _safe_path(root, user_path)

    def test_valid_path_returns_path(self):
        root = Path("/data")
        result = self._safe_path(root, "output/report.md")
        self.assertIsNotNone(result)
        self.assertTrue(str(result).startswith("/data"))

    def test_traversal_returns_none(self):
        root = Path("/data")
        result = self._safe_path(root, "../../etc/passwd")
        self.assertIsNone(result)

    def test_absolute_traversal_returns_none(self):
        root = Path("/data")
        result = self._safe_path(root, "/etc/passwd")
        # /etc/passwd は /data 配下ではないので None
        self.assertIsNone(result)


class TestExecuteTool(unittest.IsolatedAsyncioTestCase):
    """_execute_tool のツール実行テスト"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data_dir = Path(self._tmpdir.name)
        self._output_dir = self._data_dir / "output"
        self._output_dir.mkdir()

    def tearDown(self):
        self._tmpdir.cleanup()

    async def _execute(self, action: dict) -> str:
        import app.agents.react as react_mod
        original_read_root = react_mod._ALLOWED_READ_ROOT
        original_write_root = react_mod._ALLOWED_WRITE_ROOT
        react_mod._ALLOWED_READ_ROOT = self._data_dir
        react_mod._ALLOWED_WRITE_ROOT = self._output_dir
        try:
            from app.agents.react import _execute_tool
            return await _execute_tool(action)
        finally:
            react_mod._ALLOWED_READ_ROOT = original_read_root
            react_mod._ALLOWED_WRITE_ROOT = original_write_root

    async def test_read_file_existing(self):
        (self._data_dir / "test.txt").write_text("テスト内容", encoding="utf-8")
        result = await self._execute({"action": "read_file", "path": "test.txt"})
        self.assertIn("テスト内容", result)

    async def test_read_file_nonexistent_shows_directory(self):
        result = await self._execute({"action": "read_file", "path": "missing.txt"})
        self.assertIn("INFO", result)

    async def test_read_file_traversal_blocked(self):
        result = await self._execute({"action": "read_file", "path": "../../etc/passwd"})
        self.assertIn("ERROR", result)

    async def test_write_file_creates_file(self):
        result = await self._execute({
            "action": "write_file",
            "path": "output/report.md",
            "content": "レポート内容",
        })
        self.assertIn("OK", result)
        self.assertTrue((self._output_dir / "report.md").exists())

    async def test_write_file_requires_output_prefix(self):
        result = await self._execute({
            "action": "write_file",
            "path": "report.md",
            "content": "内容",
        })
        self.assertIn("ERROR", result)

    async def test_unknown_tool_returns_error(self):
        result = await self._execute({"action": "nonexistent_tool"})
        self.assertIn("ERROR", result)

    async def test_search_knowledge_missing_query_returns_error(self):
        result = await self._execute({"action": "search_knowledge", "collection": "knowledge"})
        self.assertIn("ERROR", result)

    async def test_search_knowledge_calls_rag_search(self):
        mock_result = "【検索結果: 'テスト'】\n--- チャンク1 ---\n関連情報"
        with patch("app.agents.react.rag_search", new=AsyncMock(return_value=mock_result)):
            result = await self._execute({
                "action": "search_knowledge",
                "query": "テスト",
                "collection": "knowledge",
            })
        self.assertIn("検索結果", result)


class TestReActAgentRun(unittest.IsolatedAsyncioTestCase):
    """ReActAgent.run のフロー統合テスト"""

    async def test_finish_on_first_step(self):
        finish_response = '{"thought": "完了", "action": "finish", "result": "調査完了"}'

        with patch("app.agents.react.chat_complete", new=AsyncMock(return_value=finish_response)):
            from app.agents.react import ReActAgent
            agent = ReActAgent(codename="test_agent", personality="テスト用", ws_manager=None)
            result = await agent.run("テストゴール")

        self.assertTrue(result.success)
        self.assertEqual(result.final_result, "調査完了")
        self.assertEqual(len(result.steps), 1)

    async def test_max_steps_reached_without_finish(self):
        # finishせずにread_fileを繰り返す → max_steps到達
        read_response = '{"thought": "調査中", "action": "read_file", "path": "nonexistent.txt"}'

        with patch("app.agents.react.chat_complete", new=AsyncMock(return_value=read_response)):
            from app.agents.react import ReActAgent
            agent = ReActAgent(
                codename="test_agent",
                personality="テスト用",
                ws_manager=None,
                max_steps=2,
            )
            result = await agent.run("テストゴール")

        self.assertFalse(result.success)
        self.assertEqual(len(result.steps), 2)

    async def test_parse_error_terminates_loop(self):
        invalid_response = "これはJSONではない"

        with patch("app.agents.react.chat_complete", new=AsyncMock(return_value=invalid_response)):
            from app.agents.react import ReActAgent
            agent = ReActAgent(codename="test_agent", personality="テスト用", ws_manager=None)
            result = await agent.run("テストゴール")

        self.assertFalse(result.success)
        self.assertIn("PARSE ERROR", result.error)


if __name__ == "__main__":
    unittest.main()
