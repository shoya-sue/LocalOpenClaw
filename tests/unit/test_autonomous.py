"""AutonomousLoop 単体テスト（外部依存なし）"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

# chromadb・fastapi はテスト環境に未インストールのため、モジュールレベルでモックを登録する
# autonomous.py → react.py → rag.py / manager.py の連鎖インポートによる ImportError を回避する
import types

_chromadb_mock = types.ModuleType("chromadb")
_chromadb_mock.HttpClient = MagicMock
sys.modules.setdefault("chromadb", _chromadb_mock)

_fastapi_mock = types.ModuleType("fastapi")
_fastapi_mock.WebSocket = MagicMock
sys.modules.setdefault("fastapi", _fastapi_mock)


class TestAutonomousLoopStatus(unittest.TestCase):
    """status プロパティとstart/stopの単体テスト"""

    def _make_loop(self, interval: int = 60):
        from app.autonomous import AutonomousLoop
        return AutonomousLoop(
            orchestrator=MagicMock(),
            ws_manager=MagicMock(),
            output_dir=Path("/tmp/test_output"),
            interval=interval,
        )

    def test_initial_status_is_not_running(self):
        loop = self._make_loop()
        status = loop.status
        self.assertFalse(status["running"])
        self.assertEqual(status["cycle"], 0)
        self.assertEqual(status["interval_sec"], 60)

    def test_interval_reflected_in_status(self):
        loop = self._make_loop(interval=300)
        self.assertEqual(loop.status["interval_sec"], 300)

    def test_stop_sets_running_false(self):
        loop = self._make_loop()
        loop._running = True
        loop._task = MagicMock()
        loop.stop()
        self.assertFalse(loop._running)

    def test_stop_cancels_task(self):
        loop = self._make_loop()
        mock_task = MagicMock()
        loop._task = mock_task
        loop._running = True
        loop.stop()
        mock_task.cancel.assert_called_once()


class TestDetectTriggers(unittest.TestCase):
    """_detect_triggers のトリガーワード検出テスト"""

    def _make_loop(self):
        from app.autonomous import AutonomousLoop
        return AutonomousLoop(
            orchestrator=MagicMock(),
            ws_manager=MagicMock(),
            output_dir=Path("/tmp/test_output"),
        )

    def test_detect_single_trigger(self):
        loop = self._make_loop()
        found = loop._detect_triggers("調査を開始します。調査開始というキーワードが含まれています。")
        self.assertIn("調査開始", found)
        self.assertEqual(found["調査開始"][0], "detective")

    def test_detect_max_two_triggers(self):
        loop = self._make_loop()
        # 複数のトリガーがあっても最大2件
        text = "調査開始 分析依頼 実装開始 提案作成"
        found = loop._detect_triggers(text)
        self.assertLessEqual(len(found), 2)

    def test_no_trigger_returns_empty(self):
        loop = self._make_loop()
        found = loop._detect_triggers("トリガーワードがない普通のテキスト")
        self.assertEqual(len(found), 0)

    def test_detect_researcher_trigger(self):
        loop = self._make_loop()
        found = loop._detect_triggers("分析依頼をお願いします。")
        self.assertIn("分析依頼", found)
        self.assertEqual(found["分析依頼"][0], "researcher")


class TestSaveArtifact(unittest.IsolatedAsyncioTestCase):
    """_save_artifact のファイル生成テスト"""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._output_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    async def test_save_artifact_creates_file(self):
        from app.autonomous import AutonomousLoop

        ws = MagicMock()
        ws.broadcast = AsyncMock()
        loop = AutonomousLoop(
            orchestrator=MagicMock(),
            ws_manager=ws,
            output_dir=self._output_dir,
        )
        loop._cycle = 1

        await loop._save_artifact(
            theme="テストテーマ",
            result={"response": "Leaderの回答", "agent_results": {"detective": "調査結果"}},
            chain_results={},
        )

        files = list(self._output_dir.glob("cycle_001_*.md"))
        self.assertEqual(len(files), 1)
        content = files[0].read_text(encoding="utf-8")
        self.assertIn("テストテーマ", content)
        self.assertIn("Leaderの回答", content)
        self.assertIn("detective", content)

    async def test_save_artifact_broadcasts_event(self):
        from app.autonomous import AutonomousLoop

        ws = MagicMock()
        ws.broadcast = AsyncMock()
        loop = AutonomousLoop(
            orchestrator=MagicMock(),
            ws_manager=ws,
            output_dir=self._output_dir,
        )
        loop._cycle = 1

        await loop._save_artifact("テーマ", {"response": "回答"}, {})

        ws.broadcast.assert_called()
        call_args = ws.broadcast.call_args[0][0]
        self.assertEqual(call_args["type"], "autonomous_artifact")
        self.assertEqual(call_args["cycle"], 1)


if __name__ == "__main__":
    unittest.main()
