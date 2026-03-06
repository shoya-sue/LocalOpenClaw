"""
ゴール管理モジュール

config/goals.yaml からゴール定義を読み込み、実行状態を管理する。
"""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("uvicorn.error")

# ゴール定義ファイルのデフォルトパス
_GOALS_CONFIG_PATH = Path(os.getenv("GOALS_CONFIG", "/app/config/goals.yaml"))


class GoalStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Goal:
    id: str
    description: str
    success_criteria: str
    max_cycles: int = 3
    check_file: str = ""
    check_keywords: list[str] = field(default_factory=list)
    min_chars: int = 0
    # 実行時状態
    status: GoalStatus = GoalStatus.PENDING
    cycles_done: int = 0
    completed_at: Optional[str] = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "max_cycles": self.max_cycles,
            "check_file": self.check_file,
            "check_keywords": self.check_keywords,
            "min_chars": self.min_chars,
            "status": self.status,
            "cycles_done": self.cycles_done,
            "completed_at": self.completed_at,
            "error": self.error,
        }


class GoalManager:
    """config/goals.yaml からゴールを読み込み、状態を管理する"""

    def __init__(self, config_path: Path = _GOALS_CONFIG_PATH):
        self._config_path = config_path
        self._goals: dict[str, Goal] = {}
        self.load()

    def load(self) -> None:
        """YAMLからゴール定義を読み込む（再ロード対応）"""
        if not self._config_path.exists():
            logger.warning("goals: 設定ファイルが見つかりません: %s", self._config_path)
            return

        with open(self._config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        goals_data = data.get("goals", [])
        loaded_ids = set()
        for g in goals_data:
            gid = g.get("id", "")
            if not gid:
                continue
            loaded_ids.add(gid)
            # 既存ゴールは状態を保持しつつ定義だけ更新
            if gid in self._goals:
                existing = self._goals[gid]
                existing.description = g.get("description", existing.description)
                existing.success_criteria = g.get("success_criteria", existing.success_criteria)
                existing.max_cycles = g.get("max_cycles", existing.max_cycles)
                existing.check_file = g.get("check_file", existing.check_file)
                existing.check_keywords = g.get("check_keywords", existing.check_keywords)
                existing.min_chars = g.get("min_chars", existing.min_chars)
            else:
                self._goals[gid] = Goal(
                    id=gid,
                    description=g.get("description", ""),
                    success_criteria=g.get("success_criteria", ""),
                    max_cycles=g.get("max_cycles", 3),
                    check_file=g.get("check_file", ""),
                    check_keywords=g.get("check_keywords", []),
                    min_chars=g.get("min_chars", 0),
                )

        logger.info("goals: %d件のゴールを読み込みました", len(self._goals))

    def get(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

    def list_all(self) -> list[dict]:
        return [g.to_dict() for g in self._goals.values()]

    def pending_goals(self) -> list[Goal]:
        return [g for g in self._goals.values() if g.status == GoalStatus.PENDING]

    def update_status(self, goal_id: str, status: GoalStatus, error: str = "") -> None:
        goal = self._goals.get(goal_id)
        if goal:
            goal.status = status
            goal.error = error

    def increment_cycle(self, goal_id: str) -> int:
        """サイクルカウントをインクリメントし、現在のカウントを返す"""
        goal = self._goals.get(goal_id)
        if goal:
            goal.cycles_done += 1
            return goal.cycles_done
        return 0
