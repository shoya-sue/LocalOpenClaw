"""GoalManager 単体テスト（stdlib のみ・外部依存なし）"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

from app.goals.manager import Goal, GoalManager, GoalStatus


def _write_yaml(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


_VALID_YAML = """\
goals:
  - id: goal_a
    description: Aの説明
    success_criteria: Aの基準
    max_cycles: 2
    check_file: a.md
    check_keywords: [keyword1]
    min_chars: 100
  - id: goal_b
    description: Bの説明
    success_criteria: Bの基準
"""


class TestGoalManagerLoad(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".yaml", delete=False, mode="w", encoding="utf-8"
        )
        self._tmp.write(_VALID_YAML)
        self._tmp.close()

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _mgr(self) -> GoalManager:
        from pathlib import Path
        return GoalManager(config_path=Path(self._tmp.name))

    def test_load_correct_count(self):
        mgr = self._mgr()
        self.assertEqual(len(mgr.list_all()), 2)

    def test_get_existing_goal(self):
        mgr = self._mgr()
        g = mgr.get("goal_a")
        self.assertIsNotNone(g)
        self.assertEqual(g.id, "goal_a")
        self.assertEqual(g.max_cycles, 2)
        self.assertEqual(g.check_file, "a.md")
        self.assertEqual(g.min_chars, 100)

    def test_get_nonexistent_returns_none(self):
        mgr = self._mgr()
        self.assertIsNone(mgr.get("nonexistent"))

    def test_default_status_is_pending(self):
        mgr = self._mgr()
        g = mgr.get("goal_b")
        self.assertEqual(g.status, GoalStatus.PENDING)

    def test_pending_goals_filters_correctly(self):
        mgr = self._mgr()
        mgr.update_status("goal_a", GoalStatus.COMPLETED)
        pending = mgr.pending_goals()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, "goal_b")

    def test_update_status_changes_goal_status(self):
        mgr = self._mgr()
        mgr.update_status("goal_a", GoalStatus.IN_PROGRESS)
        g = mgr.get("goal_a")
        self.assertEqual(g.status, GoalStatus.IN_PROGRESS)

    def test_update_status_unknown_goal_is_noop(self):
        mgr = self._mgr()
        # 存在しないゴールへの更新は例外を出さない
        mgr.update_status("ghost", GoalStatus.COMPLETED)

    def test_increment_cycle_increments_count(self):
        mgr = self._mgr()
        count = mgr.increment_cycle("goal_a")
        self.assertEqual(count, 1)
        count = mgr.increment_cycle("goal_a")
        self.assertEqual(count, 2)

    def test_increment_cycle_unknown_goal_returns_zero(self):
        mgr = self._mgr()
        self.assertEqual(mgr.increment_cycle("ghost"), 0)

    def test_reload_updates_definition_preserves_status(self):
        """再ロード時: 定義は更新されるが実行時状態（status/cycles_done）は維持される"""
        mgr = self._mgr()
        mgr.update_status("goal_a", GoalStatus.IN_PROGRESS)
        mgr.increment_cycle("goal_a")

        # YAMLのmax_cyclesを変更して再ロード
        _write_yaml(self._tmp.name, """\
goals:
  - id: goal_a
    description: 更新後
    success_criteria: 基準
    max_cycles: 5
""")
        mgr.load()
        g = mgr.get("goal_a")
        self.assertEqual(g.max_cycles, 5)           # 定義が更新されている
        self.assertEqual(g.status, GoalStatus.IN_PROGRESS)  # 状態は維持
        self.assertEqual(g.cycles_done, 1)          # カウントも維持

    def test_to_dict_has_required_keys(self):
        mgr = self._mgr()
        d = mgr.get("goal_a").to_dict()
        for key in ("id", "description", "success_criteria", "max_cycles",
                    "check_file", "check_keywords", "min_chars", "status",
                    "cycles_done", "completed_at", "error"):
            self.assertIn(key, d)

    def test_missing_config_file_loads_empty(self):
        from pathlib import Path
        mgr = GoalManager(config_path=Path("/nonexistent/goals.yaml"))
        self.assertEqual(len(mgr.list_all()), 0)


if __name__ == "__main__":
    unittest.main()
