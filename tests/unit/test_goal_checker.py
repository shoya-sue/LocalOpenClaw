"""GoalChecker 単体テスト（LLMはモック）"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

from app.goals.manager import Goal, GoalStatus


def _make_goal(**kwargs) -> Goal:
    defaults = dict(
        id="test_goal",
        description="テスト用ゴール",
        success_criteria="テスト基準",
        max_cycles=3,
        check_file="",
        check_keywords=[],
        min_chars=0,
    )
    defaults.update(kwargs)
    return Goal(**defaults)


class TestStaticCheck(unittest.TestCase):
    """_static_check の単体テスト（LLM不使用）"""

    def setUp(self):
        # 一時出力ディレクトリ
        self._tmpdir = tempfile.TemporaryDirectory()
        self._output_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _static_check(self, goal: Goal):
        from app.goals.checker import _static_check
        return _static_check(goal, self._output_dir)

    def test_no_check_file_passes(self):
        """check_fileが未設定なら静的チェックは常にパス"""
        goal = _make_goal(check_file="")
        passed, details = self._static_check(goal)
        self.assertTrue(passed)

    def test_missing_file_fails(self):
        """指定ファイルが存在しない場合はFAIL"""
        goal = _make_goal(check_file="missing.md")
        passed, details = self._static_check(goal)
        self.assertFalse(passed)
        self.assertFalse(details["file_exists"])

    def test_existing_file_passes(self):
        """ファイルが存在すればPASS"""
        (self._output_dir / "result.md").write_text("内容", encoding="utf-8")
        goal = _make_goal(check_file="result.md")
        passed, details = self._static_check(goal)
        self.assertTrue(passed)
        self.assertTrue(details["file_exists"])

    def test_min_chars_fail(self):
        """文字数が足りない場合はFAIL"""
        (self._output_dir / "short.md").write_text("短い", encoding="utf-8")
        goal = _make_goal(check_file="short.md", min_chars=100)
        passed, details = self._static_check(goal)
        self.assertFalse(passed)

    def test_min_chars_pass(self):
        """文字数が十分な場合はPASS"""
        content = "あ" * 200
        (self._output_dir / "long.md").write_text(content, encoding="utf-8")
        goal = _make_goal(check_file="long.md", min_chars=100)
        passed, details = self._static_check(goal)
        self.assertTrue(passed)
        self.assertEqual(details["char_count"], 200)

    def test_keyword_found_passes(self):
        """キーワードが含まれている場合はPASS"""
        (self._output_dir / "kw.md").write_text("重要なキーワードがここにある", encoding="utf-8")
        goal = _make_goal(check_file="kw.md", check_keywords=["キーワード"])
        passed, details = self._static_check(goal)
        self.assertTrue(passed)
        self.assertIn("キーワード", details["keywords_found"])

    def test_keyword_missing_fails(self):
        """キーワードが不足している場合はFAIL"""
        (self._output_dir / "nokw.md").write_text("関係ない内容", encoding="utf-8")
        goal = _make_goal(check_file="nokw.md", check_keywords=["必須ワード"])
        passed, details = self._static_check(goal)
        self.assertFalse(passed)
        self.assertIn("必須ワード", details["keywords_missing"])


class TestCheckGoal(unittest.IsolatedAsyncioTestCase):
    """check_goal の統合テスト（LLMはモック）"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._output_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    async def test_check_goal_achieved_when_static_and_llm_pass(self):
        content = "プロジェクト概要と詳細な内容がここに含まれている。" * 10
        (self._output_dir / "report.md").write_text(content, encoding="utf-8")
        goal = _make_goal(check_file="report.md", min_chars=10)

        with patch("app.goals.checker.chat_complete", new=AsyncMock(return_value="YES")):
            from app.goals.checker import check_goal
            result = await check_goal(goal, self._output_dir)

        self.assertTrue(result.static_passed)
        self.assertTrue(result.llm_passed)
        self.assertTrue(result.achieved)
        self.assertEqual(result.details["llm_answer"], "YES")

    async def test_check_goal_not_achieved_when_llm_fails(self):
        content = "内容あり"
        (self._output_dir / "result.md").write_text(content, encoding="utf-8")
        goal = _make_goal(check_file="result.md")

        with patch("app.goals.checker.chat_complete", new=AsyncMock(return_value="NO")):
            from app.goals.checker import check_goal
            result = await check_goal(goal, self._output_dir)

        self.assertTrue(result.static_passed)
        self.assertFalse(result.llm_passed)
        self.assertFalse(result.achieved)

    async def test_check_goal_skips_llm_when_static_fails(self):
        goal = _make_goal(check_file="nonexistent.md")

        with patch("app.goals.checker.chat_complete", new=AsyncMock()) as mock_llm:
            from app.goals.checker import check_goal
            result = await check_goal(goal, self._output_dir)

        # 静的チェック失敗 → LLMは呼ばれない
        mock_llm.assert_not_called()
        self.assertFalse(result.static_passed)
        self.assertFalse(result.achieved)
        self.assertEqual(result.details["llm_answer"], "SKIP")

    async def test_check_goal_generates_report(self):
        (self._output_dir / "data.md").write_text("内容", encoding="utf-8")
        goal = _make_goal(check_file="data.md")

        with patch("app.goals.checker.chat_complete", new=AsyncMock(return_value="YES")):
            from app.goals.checker import check_goal
            result = await check_goal(goal, self._output_dir)

        # レポートが生成されている
        self.assertTrue(result.report_path)
        report = Path(result.report_path)
        self.assertTrue(report.exists())
        self.assertIn("test_goal", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
