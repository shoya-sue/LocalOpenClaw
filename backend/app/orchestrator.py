"""
Leaderエージェントがチームをオーケストレーションするロジック

フロー:
  ユーザーメッセージ → Leader分析 → タスク割り当て → 各エージェント実行（前の結果を次へ渡す）→ Leader統合 → 最終回答
"""

import json
import logging
import os
import re
from typing import Optional

from app.agents.manager import AgentManager, AgentStatus
from app.llm.ollama import chat_complete
from app.tasks.manager import TaskManager, TaskStatus
from app.ws.manager import ConnectionManager

logger = logging.getLogger("uvicorn.error")

# フィードバックとして渡す前エージェント結果の最大文字数（CONTEXT_MAX_CHARSの半分）
_FEEDBACK_MAX_CHARS = int(os.getenv("CONTEXT_MAX_CHARS", "3000")) // 2

# Leaderが受け取るオーケストレーション指示テンプレート
_ORCHESTRATION_SYSTEM = """\
あなたは「{name}」というリーダーエージェントです。
チームメンバー:
- detective: SNSトレンド調査・視聴者ニーズ収集・競合分析
- researcher: 動画構成設計・差別化分析・科学的根拠調査
- sales: フック文3案（数字・疑問文・衝撃の事実）・CTA・ハッシュタグ10個提案
- secretary: 60秒縦型動画の秒単位台本作成（0-5秒/5-20秒/20-40秒/40-55秒/55-60秒）
- engineer: 動画制作ツール用JSON仕様書出力（title/platform/scenes[]/hook/cta/hashtags必須）

【重要ルール】
- 「動画」「コンテンツ」「台本」「YouTube Shorts」「TikTok」「Instagram Reels」「60秒」「縦型」のいずれかが含まれる依頼は、必ず全5名（detective/researcher/sales/secretary/engineer）にタスクを振ること
- タスクを振る際は必ずengineerを最後に配置し「JSON出力」を担当させること
- 直接回答（tasks: []）は「おはよう」「ありがとう」などコンテンツ制作と完全に無関係な場合のみ

必ず以下のJSON形式のみで回答してください（追加テキスト不要）:

{{
  "reasoning": "依頼の分析と割り当て理由（1〜2文）",
  "tasks": [
    {{"agent": "detective", "task": "SNSトレンドと視聴者ニーズを具体的な数字で調査"}},
    {{"agent": "researcher", "task": "動画構成と差別化ポイントを時間軸で設計"}},
    {{"agent": "sales", "task": "フック文3案・CTA・ハッシュタグ10個を提案"}},
    {{"agent": "secretary", "task": "60秒縦型動画の秒単位台本を作成"}},
    {{"agent": "engineer", "task": "動画制作用JSON仕様書を出力"}}
  ],
  "summary_needed": true
}}

直接回答の場合（コンテンツ制作と無関係な挨拶・質問のみ）:

{{
  "reasoning": "直接回答できる",
  "tasks": [],
  "direct_response": "ここに回答を書く"
}}
"""

# 前エージェントの結果を次エージェントに渡すシステムプロンプト追記テンプレート
_FEEDBACK_CONTEXT_TEMPLATE = """\

【前のエージェントからの引き継ぎ情報】
{feedback}

上記の情報を参考にしながら、以下の自分のタスクに取り組んでください。
"""

# Leaderが各エージェント報告を統合するプロンプト
_SUMMARY_PROMPT = """\
あなたは動画コンテンツチームのクリエイティブディレクターです。
チームメンバーの報告を統合して、完成した動画コンテンツ仕様書を出力してください。

【動画テーマ】
{message}

【チームからの報告】
{reports}

以下の形式で動画コンテンツ仕様書を出力してください（質問は絶対にしない）:

## 動画タイトル
（具体的なタイトル）

## ターゲット視聴者
（具体的な属性）

## 秒単位台本
0-5秒（フック）: 映像／ナレーション「セリフ」／テキスト:
5-20秒（本編①）: 映像／ナレーション「セリフ」／テキスト:
20-40秒（本編②）: 映像／ナレーション「セリフ」／テキスト:
40-55秒（まとめ）: 映像／ナレーション「セリフ」／テキスト:
55-60秒（CTA）: 映像／ナレーション「セリフ」／テキスト:

## CTA
（具体的なアクション促進文）

## ハッシュタグ
（#タグ を10個）"""


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
        await self._set_status("leader", AgentStatus.THINKING, "タスク分析中")
        system = _ORCHESTRATION_SYSTEM.format(name=leader.get("name", "リーダー"))
        plan_raw = await chat_complete(system, message)
        plan = self._parse_json(plan_raw)

        if plan is None:
            # JSON抽出失敗 → Leaderの出力をそのまま直接回答として返す
            plan = {"tasks": [], "direct_response": plan_raw}

        # ② 直接回答の場合
        if not plan.get("tasks"):
            await self._set_status("leader", AgentStatus.IDLE, "待命中")
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

        await self._set_status("leader", AgentStatus.IDLE, "待命中")

        # ④ 各エージェントがタスクを実行（直列）
        # 前エージェントの結果を次エージェントへフィードバックとして渡す
        results: dict[str, str] = {}
        previous_observations: list[str] = []  # 前エージェントの結果蓄積
        for task in created_tasks:
            agent_data = self.agents.get(task.assigned_to)
            if not agent_data:
                continue

            await self._set_status(task.assigned_to, AgentStatus.THINKING, task.title)
            self.tasks.update_status(task.id, TaskStatus.IN_PROGRESS)
            await self.ws.broadcast({
                "type": "agent_thinking",
                "agent": task.assigned_to,
                "task_id": task.id,
            })

            agent_system = agent_data.get("personality", f"あなたは{task.assigned_to}です。")

            # 前エージェントの結果があればシステムプロンプトに追記してフィードバック
            if previous_observations:
                feedback_text = "\n---\n".join(previous_observations)
                # FEEDBACK_MAX_CHARS を超えないよう末尾から切り取る
                if len(feedback_text) > _FEEDBACK_MAX_CHARS:
                    feedback_text = "…（省略）\n" + feedback_text[-_FEEDBACK_MAX_CHARS:]
                agent_system = agent_system + _FEEDBACK_CONTEXT_TEMPLATE.format(
                    feedback=feedback_text
                )
                from_agents = list(results.keys())
                logger.info(
                    "orchestrator: context_handoff %s → %s (%d文字)",
                    from_agents,
                    task.assigned_to,
                    len(feedback_text),
                )
                await self.ws.broadcast({
                    "type": "context_handoff",
                    "to_agent": task.assigned_to,
                    "from_agents": from_agents,
                    "feedback_chars": len(feedback_text),
                })

            result = await chat_complete(agent_system, task.description)
            results[task.assigned_to] = result
            # 次エージェントへ渡す観察結果を蓄積（エージェント名付き）
            previous_observations.append(f"[{task.assigned_to}の結果]\n{result}")

            self.tasks.update_status(task.id, TaskStatus.DONE, result)
            await self._set_status(task.assigned_to, AgentStatus.IDLE, "作業完了")
            await self.ws.broadcast({
                "type": "task_done",
                "task_id": task.id,
                "agent": task.assigned_to,
                # 長すぎるとWebSocketが詰まるのでプレビューのみ配信
                "preview": result[:300] + "…" if len(result) > 300 else result,
            })

        # ⑤ Leaderが結果を統合
        if plan.get("summary_needed", True) and results:
            await self._set_status("leader", AgentStatus.THINKING, "統合・回答作成中")
            reports = "\n\n".join(
                f"【{agent}の報告】\n{text}" for agent, text in results.items()
            )
            summary_prompt = _SUMMARY_PROMPT.format(message=message, reports=reports)
            final = await chat_complete(
                leader.get("personality", "あなたはリーダーです。"),
                summary_prompt,
            )
            await self._set_status("leader", AgentStatus.IDLE, "待命中")
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

    async def _set_status(self, codename: str, status: AgentStatus, detail: str = ""):
        self.agents.set_status(codename, status)
        await self.ws.broadcast({
            "type": "agent_status",
            "agent": codename,
            "status": status,
            "detail": detail,
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
