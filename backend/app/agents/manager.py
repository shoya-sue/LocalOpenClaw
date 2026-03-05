"""エージェント定義の読み込みと状態管理"""

import os
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/app/config"))


class AgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    BUSY = "busy"


class AgentManager:
    def __init__(self):
        self._agents: dict[str, dict] = {}
        self._status: dict[str, AgentStatus] = {}
        self.reload()

    def reload(self):
        """config/agents/*.yaml を全て読み込む"""
        agents_dir = CONFIG_DIR / "agents"
        if not agents_dir.exists():
            return
        for yaml_file in sorted(agents_dir.glob("*.yaml")):
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            codename = data.get("codename", yaml_file.stem)
            self._agents[codename] = data
            if codename not in self._status:
                self._status[codename] = AgentStatus.IDLE

    def get(self, codename: str) -> Optional[dict]:
        return self._agents.get(codename)

    def list_all(self) -> list[dict]:
        return [
            {
                "codename": a.get("codename"),
                "name": a.get("name"),
                "role_category": a.get("role_category", ""),
                "sub_role": a.get("sub_role", {}),
                "status": self._status.get(a.get("codename"), AgentStatus.IDLE),
            }
            for a in self._agents.values()
        ]

    def set_status(self, codename: str, status: AgentStatus):
        self._status[codename] = status

    def get_status(self, codename: str) -> AgentStatus:
        return self._status.get(codename, AgentStatus.IDLE)

    def codenames(self) -> list[str]:
        return list(self._agents.keys())
