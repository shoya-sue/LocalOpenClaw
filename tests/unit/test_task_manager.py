"""TaskManager 単体テスト（stdlib のみ）"""
import sys
import os
import unittest

# backend/app を Python パスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))

from app.tasks.manager import Task, TaskManager, TaskStatus


class TestTask(unittest.TestCase):
    def test_task_id_is_8chars(self):
        t = Task("title", "desc", "leader")
        self.assertEqual(len(t.id), 8)

    def test_task_default_status_is_pending(self):
        t = Task("title", "desc", "leader")
        self.assertEqual(t.status, TaskStatus.PENDING)

    def test_to_dict_has_required_keys(self):
        t = Task("title", "desc", "leader", "user")
        d = t.to_dict()
        for key in ("id", "title", "description", "assigned_to", "created_by",
                    "status", "result", "created_at", "updated_at"):
            self.assertIn(key, d)


class TestTaskManager(unittest.TestCase):
    def setUp(self):
        self.mgr = TaskManager()

    def test_create_returns_task(self):
        t = self.mgr.create("t1", "d1", "detective")
        self.assertIsInstance(t, Task)

    def test_get_returns_created_task(self):
        t = self.mgr.create("t2", "d2", "researcher")
        self.assertEqual(self.mgr.get(t.id), t)

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.mgr.get("nonexistent"))

    def test_list_all_grows_with_creates(self):
        self.mgr.create("t3", "d3", "sales")
        self.mgr.create("t4", "d4", "secretary")
        self.assertEqual(len(self.mgr.list_all()), 2)

    def test_list_by_agent_filters(self):
        self.mgr.create("t5", "d5", "detective")
        self.mgr.create("t6", "d6", "researcher")
        self.assertEqual(len(self.mgr.list_by_agent("detective")), 1)

    def test_update_status_changes_status(self):
        t = self.mgr.create("t7", "d7", "engineer")
        self.mgr.update_status(t.id, TaskStatus.DONE, "result text")
        updated = self.mgr.get(t.id)
        self.assertEqual(updated.status, TaskStatus.DONE)
        self.assertEqual(updated.result, "result text")

    def test_update_status_unknown_task_noop(self):
        # 存在しないタスクの更新は例外を出さない
        self.mgr.update_status("ghost", TaskStatus.DONE)


if __name__ == "__main__":
    unittest.main()
