"""タスク管理（インメモリ）"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class Task:
    def __init__(
        self,
        title: str,
        description: str,
        assigned_to: str,
        created_by: str = "user",
    ):
        self.id = str(uuid.uuid4())[:8]
        self.title = title
        self.description = description
        self.assigned_to = assigned_to
        self.created_by = created_by
        self.status = TaskStatus.PENDING
        self.result: Optional[str] = None
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "assigned_to": self.assigned_to,
            "created_by": self.created_by,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def create(
        self,
        title: str,
        description: str,
        assigned_to: str,
        created_by: str = "user",
    ) -> Task:
        task = Task(title, description, assigned_to, created_by)
        self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list_all(self) -> list[dict]:
        return [t.to_dict() for t in self._tasks.values()]

    def list_by_agent(self, codename: str) -> list[dict]:
        return [t.to_dict() for t in self._tasks.values() if t.assigned_to == codename]

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[str] = None,
    ):
        task = self._tasks.get(task_id)
        if task:
            task.status = status
            if result is not None:
                task.result = result
            task.updated_at = datetime.now().isoformat()
