"""AgentManager 単体テスト"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

import types
_fastapi_mock = types.ModuleType("fastapi")
from unittest.mock import MagicMock
_fastapi_mock.WebSocket = MagicMock
sys.modules.setdefault("fastapi", _fastapi_mock)


SAMPLE_YAML = """\
codename: leader
name: Leader
role_category: orchestrator
personality: あなたはleaderです。
"""

SAMPLE_YAML2 = """\
codename: detective
name: Detective
role_category: investigator
personality: あなたはdetectiveです。
"""


class TestAgentManager(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        agents_dir = Path(self._tmpdir.name) / "agents"
        agents_dir.mkdir()
        (agents_dir / "leader.yaml").write_text(SAMPLE_YAML, encoding="utf-8")
        (agents_dir / "detective.yaml").write_text(SAMPLE_YAML2, encoding="utf-8")
        self._agents_dir = agents_dir

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_manager(self):
        from app.agents.manager import AgentManager
        with patch("app.agents.manager.CONFIG_DIR", Path(self._tmpdir.name)):
            mgr = AgentManager()
        return mgr

    def test_reload_loads_all_agents(self):
        mgr = self._make_manager()
        self.assertEqual(len(mgr.codenames()), 2)
        self.assertIn("leader", mgr.codenames())
        self.assertIn("detective", mgr.codenames())

    def test_get_returns_agent_data(self):
        mgr = self._make_manager()
        agent = mgr.get("leader")
        self.assertIsNotNone(agent)
        self.assertEqual(agent["name"], "Leader")

    def test_get_returns_none_for_unknown(self):
        mgr = self._make_manager()
        self.assertIsNone(mgr.get("unknown_agent"))

    def test_list_all_contains_status(self):
        mgr = self._make_manager()
        result = mgr.list_all()
        self.assertEqual(len(result), 2)
        for item in result:
            self.assertIn("status", item)

    def test_set_and_get_status(self):
        from app.agents.manager import AgentStatus
        mgr = self._make_manager()
        mgr.set_status("leader", AgentStatus.THINKING)
        self.assertEqual(mgr.get_status("leader"), AgentStatus.THINKING)

    def test_default_status_is_idle(self):
        from app.agents.manager import AgentStatus
        mgr = self._make_manager()
        self.assertEqual(mgr.get_status("leader"), AgentStatus.IDLE)

    def test_get_status_unknown_returns_idle(self):
        from app.agents.manager import AgentStatus
        mgr = self._make_manager()
        self.assertEqual(mgr.get_status("nonexistent"), AgentStatus.IDLE)

    def test_reload_no_dir_does_not_raise(self):
        from app.agents.manager import AgentManager
        # agents ディレクトリが存在しない場合も例外を出さない
        with patch("app.agents.manager.CONFIG_DIR", Path("/nonexistent_path_xyz")):
            mgr = AgentManager()
        self.assertEqual(len(mgr.codenames()), 0)


if __name__ == "__main__":
    unittest.main()
