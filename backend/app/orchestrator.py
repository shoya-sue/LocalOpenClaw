"""
Leaderエージェントがチームをオーケストレーションするロジック

フロー:
  ユーザーメッセージ → Leader分析 → タスク割り当て → 各エージェント実行 → Leader統合 → 最終回答
"""

import json
import re
from typing import Optional

from app.agents.manager import AgentManager, AgentStatus
from app.llm.ollama import chat_complete
from app.tasks.manager import TaskManager, TaskStatus
from app.ws.manager import ConnectionManager

# Leaderが受け取るオーケストレーション指示テンプレート
_ORCHESTRATION_SYSTEM = """\
あなたは「{name}」というリーダーエージェントです。
チームメンバー: detective（調査・情報収集）, researcher（分析・考察）, sales（提案・説明）, secretary（整理・要約）, engineer（実装・技術解説）

ユーザーの依頼を分析し、どのメンバーにどのタスクを振るか決定してください。
必ず以下のJSON形式のみで回答してください（日本語OK、追加テキスト不要）:

{{
  "reasoning": "依頼の分析と割り当て理由（1〜2文）",
  "tasks": [
    {{"agent": "detective", "task": "調査してほしい内容"}},
    {{"agent": "researcher", "task": "分析してほしい内容"}}
  ],
  "summary_needed": true
}}

あなた自身が直接答えられる場合（挨拶・簡単な質問など）はタスクを作らず以下の形式で:

{{
  "reasoning": "直接回答できる",
  "tasks": [],
  "direct_response": "ここに回答を書く"
}}
"""

# Leaderが各エージェント報告を統合するプロンプト
_SUMMARY_PROMPT = """\
あなたはチームリーダーです。
チームメンバーからの報告を基に、ユーザーへの最終回答を日本語でまとめてください。

【ユーザーの依頼】
{message}

【チームからの報告】
{reports}

ユーザーへの回答（リーダーとして自然な文体で）:"""


class Orchestrator:
    def __init__(
        self,
        agent_manager: AgentManager,
        task_manager: TaskManager,
        ws_manager: ConnectionManager,
    ):
        self.agents = agent_manager
        self.tasks = task_manager
        self.ws = ws_manager

    async def handle(self, message: str) -> dict:
        """ユーザーメッセージをオーケストレーションして結果を返す"""
        leader = self.agents.get("leader")
        if not leader:
            return {"error": "Leader agent not found"}

        # ① Leaderがタスク分析
        await self._set_status("leader", AgentStatus.THINKING)
        system = _ORCHESTRATION_SYSTEM.format(name=leader.get("name", "リーダー"))
        plan_raw = await chat_complete(system, message)
        plan = self._parse_json(plan_raw)

        if plan is None:
            # JSON抽出失敗 → Leaderの出力をそのまま直接回答として返す
            plan = {"tasks": [], "direct_response": plan_raw}

        # ② 直接回答の場合
        if not plan.get("tasks"):
            await self._set_status("leader", AgentStatus.IDLE)
            return {
                "orchestration": False,
                "agent": "leader",
                "response": plan.get("direct_response", plan_raw),
                "tasks": [],
            }

        # ③ タスク作成 & WebSocket通知
        created_tasks = []
        for spec in plan["tasks"]:
            agent_code = spec.get("agent")
            task_desc = spec.get("task")
            if not agent_code or not task_desc:
                continue
            task = self.tasks.create(
                title=f"[{agent_code}] {task_desc[:40]}",
                description=task_desc,
                assigned_to=agent_code,
                created_by="leader",
            )
            created_tasks.append(task)
            await self.ws.broadcast({
                "type": "task_created",
                "task_id": task.id,
                "agent": agent_code,
                "title": task.title,
            })

        await self._set_status("leader", AgentStatus.IDLE)

        # ④ 各エージェントがタスクを実行（直列）
        results: dict[str, str] = {}
        for task in created_tasks:
            agent_data = self.agents.get(task.assigned_to)
            if not agent_data:
                continue

            await self._set_status(task.assigned_to, AgentStatus.THINKING)
            self.tasks.update_status(task.id, TaskStatus.IN_PROGRESS)
            await self.ws.broadcast({
                "type": "agent_thinking",
                "agent": task.assigned_to,
                "task_id": task.id,
            })

            agent_system = agent_data.get("personality", f"あなたは{task.assigned_to}です。")
            result = await chat_complete(agent_system, task.description)
            results[task.assigned_to] = result

            self.tasks.update_status(task.id, TaskStatus.DONE, result)
            await self._set_status(task.assigned_to, AgentStatus.IDLE)
            await self.ws.broadcast({
                "type": "task_done",
                "task_id": task.id,
                "agent": task.assigned_to,
                # 長すぎるとWebSocketが詰まるのでプレビューのみ配信
                "preview": result[:300] + "…" if len(result) > 300 else result,
            })

        # ⑤ Leaderが結果を統合
        if plan.get("summary_needed", True) and results:
            await self._set_status("leader", AgentStatus.THINKING)
            reports = "\n\n".join(
                f"【{agent}の報告】\n{text}" for agent, text in results.items()
            )
            summary_prompt = _SUMMARY_PROMPT.format(message=message, reports=reports)
            final = await chat_complete(
                leader.get("personality", "あなたはリーダーです。"),
                summary_prompt,
            )
            await self._set_status("leader", AgentStatus.IDLE)
        else:
            final = "\n\n".join(
                f"**{agent}**: {text}" for agent, text in results.items()
            )

        return {
            "orchestration": True,
            "reasoning": plan.get("reasoning", ""),
            "tasks": [t.to_dict() for t in created_tasks],
            "response": final,
            "agent_results": results,
        }

    async def _set_status(self, codename: str, status: AgentStatus):
        self.agents.set_status(codename, status)
        await self.ws.broadcast({
            "type": "agent_status",
            "agent": codename,
            "status": status,
        })

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """LLM出力からJSONオブジェクトを抽出する"""
        # ```json ... ``` ブロックを除去
        text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
        # まず全体をJSONとして試みる
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # {...} 部分だけ抽出して試みる
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None
