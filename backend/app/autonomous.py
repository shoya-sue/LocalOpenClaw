"""
自律ループモジュール
エージェントが自分たちで会話・判断・創作を行う

フロー:
  ループ開始 → Leaderがテーマ選択 → オーケストレーション →
  出力からトリガーワード検出 → 次アクション自動実行 → 成果物ファイル生成
"""

import asyncio
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.agents.react import ReActAgent
from app.goals.checker import check_goal
from app.goals.manager import GoalManager, GoalStatus
from app.llm.ollama import chat_complete

# REACT_MODE=true の場合、自律ループでReActエンジンを使用する
REACT_MODE = os.getenv("REACT_MODE", "false").lower() == "true"

logger = logging.getLogger("uvicorn.error")

# ==============================
# 自律ループ設定
# ==============================

# 1サイクルのインターバル（秒）。環境変数で上書き可能
DEFAULT_INTERVAL = 180  # 3分

# エージェントが使う厳選トリガーワード → (担当エージェント, 追加指示)
TRIGGER_ACTIONS: dict[str, tuple[str, str]] = {
    "調査開始":   ("detective",  "詳しく現地調査・情報収集を行いレポートを作成してください"),
    "分析依頼":   ("researcher", "収集データを分析し、知見・仮説をまとめてください"),
    "実装開始":   ("engineer",   "設計書またはコードのスケッチを作成してください"),
    "提案作成":   ("sales",      "具体的な提案・アクションプランを作成してください"),
    "要約依頼":   ("secretary",  "議論の内容を箇条書きで整理・要約してください"),
    "問題発見":   ("detective",  "問題の根本原因を深掘りして調査してください"),
    "成果物作成": ("engineer",   "議論の内容を元に具体的な成果物を作成してください"),
    "次フェーズ": ("leader",     "現在の成果を踏まえて次のフェーズのテーマを決めてください"),
}

# ReActモード用のゴールリスト（具体的な調査・成果物作成ゴール）
REACT_GOALS = [
    "data/ ディレクトリの内容を調査して、現在のLocalOpenClawシステムの状態をまとめたレポートをoutput/system_report.md に作成してください。",
    "data/ 配下のファイルを調査して、AIエージェントの改善点を特定し、output/improvement_report.md に提案レポートを作成してください。",
    "data/ 配下の情報を元に、AI同士の協働で生み出せる新しい成果物のアイデアをoutput/ideas.md に書き出してください。",
    "data/ 配下のファイルを調査して、有益な知識・情報をoutput/knowledge_report.md にまとめてください。",
    "data/ 配下の情報を元に、短期プロジェクトの提案書をoutput/project_proposal.md に作成してください。",
]

# Leaderが自律的に選ぶ議題リスト（ランダムローテーション）
AUTONOMOUS_THEMES = [
    (
        "チームで今日取り組む最優先テーマを議論してください。"
        "結論として『調査開始』『実装開始』『提案作成』のいずれかのキーワードで次のアクションを指示してください。"
    ),
    (
        "LocalOpenClawシステムとして、AI同士が自律的に協働する仕組みの改善案を議論してください。"
        "課題があれば『問題発見』、改善案は『提案作成』、実装するなら『実装開始』で指示してください。"
    ),
    (
        "AI同士の協働で何か新しい成果物を作りましょう。テーマは自由に決めてください。"
        "『調査開始』→『分析依頼』→『成果物作成』の順で役割を分担してください。"
    ),
    (
        "チームの知識を結集して有益なレポートを自律作成してください。"
        "まず『調査開始』で情報収集し、次に『分析依頼』で分析、最後に『要約依頼』でまとめてください。"
    ),
    (
        "AI同士で短期プロジェクトを立ち上げてください。"
        "プロジェクト名・目標・担当を決め、それぞれが『実装開始』『調査開始』などのキーワードで着手してください。"
    ),
]


# ==============================
# 自律ループクラス
# ==============================

class AutonomousLoop:
    def __init__(
        self,
        orchestrator,
        ws_manager,
        output_dir: Path,
        interval: int = DEFAULT_INTERVAL,
        goal_manager: Optional[GoalManager] = None,
    ):
        self._orch = orchestrator
        self._ws = ws_manager
        self._output_dir = output_dir
        self._interval = interval
        self._goal_manager = goal_manager
        self._task: Optional[asyncio.Task] = None
        self._cycle = 0
        self._running = False

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("autonomous: 自律ループ開始（インターバル %d秒）", self._interval)

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("autonomous: 自律ループ停止")

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "cycle": self._cycle,
            "interval_sec": self._interval,
        }

    # ==============================
    # メインループ
    # ==============================

    async def _loop(self):
        # 最初のサイクルは少し待ってから開始（起動直後の安定化）
        await asyncio.sleep(10)
        while self._running:
            self._cycle += 1

            # REACT_MODE時はReActエンジンで自律調査・成果物作成を実行
            if REACT_MODE:
                try:
                    await self._react_cycle()
                except Exception as exc:
                    logger.warning("autonomous[react]: サイクル %d 失敗: %s", self._cycle, exc)
            else:
                theme = AUTONOMOUS_THEMES[(self._cycle - 1) % len(AUTONOMOUS_THEMES)]
                logger.info("autonomous: サイクル %d 開始 — テーマ: %s", self._cycle, theme[:40])

                await self._ws.broadcast({
                    "type": "autonomous_cycle_start",
                    "cycle": self._cycle,
                    "theme": theme,
                })

                try:
                    result = await self._orch.handle(theme)
                    await self._process_result(result, theme)
                except Exception as exc:
                    logger.warning("autonomous: サイクル %d 失敗: %s", self._cycle, exc)

            await asyncio.sleep(self._interval)

    # ==============================
    # ReActモード: エージェントが自律的にゴールを達成
    # ==============================

    async def _react_cycle(self):
        """ReActモードの1サイクル: エージェントがゴール達成まで自律的に調査・実行"""
        # goal_manager にpendingゴールがあればそちらを優先
        managed_goal = None
        if self._goal_manager:
            pending = self._goal_manager.pending_goals()
            if pending:
                managed_goal = pending[0]
                self._goal_manager.update_status(managed_goal.id, GoalStatus.IN_PROGRESS)

        goal = managed_goal.description if managed_goal else REACT_GOALS[(self._cycle - 1) % len(REACT_GOALS)]

        # detective → researcher → engineer の順でローテーション（役割に応じた調査）
        react_agents = ["detective", "researcher", "engineer"]
        agent_code = react_agents[(self._cycle - 1) % len(react_agents)]
        agent_data = self._orch.agents.get(agent_code)
        if not agent_data:
            # 指定エージェントが未定義の場合はleaderを使用
            agent_code = "leader"
            agent_data = self._orch.agents.get(agent_code) or {}

        personality = agent_data.get("personality", f"あなたは{agent_code}です。")
        logger.info("autonomous[react]: サイクル %d — agent=%s goal=%s", self._cycle, agent_code, goal[:40])

        await self._ws.broadcast({
            "type": "autonomous_cycle_start",
            "cycle": self._cycle,
            "mode": "react",
            "agent": agent_code,
            "goal": goal,
        })

        react_agent = ReActAgent(
            codename=agent_code,
            personality=personality,
            ws_manager=self._ws,
        )
        result = await react_agent.run(goal)
        await self._save_react_artifact(goal, result)

        # managed_goal がある場合は達成判定を実行してステータスを更新
        if managed_goal and self._goal_manager:
            try:
                check_result = await check_goal(managed_goal, self._output_dir)
                new_status = GoalStatus.COMPLETED if check_result.achieved else GoalStatus.PENDING
                self._goal_manager.update_status(managed_goal.id, new_status)
                await self._ws.broadcast({
                    "type": "goal_checked",
                    "goal_id": managed_goal.id,
                    "achieved": check_result.achieved,
                    "static_passed": check_result.static_passed,
                    "llm_answer": check_result.details.get("llm_answer", "SKIP"),
                    "report_path": check_result.report_path,
                })
                logger.info(
                    "autonomous[react]: ゴール '%s' 判定 — achieved=%s",
                    managed_goal.id, check_result.achieved,
                )
            except Exception as exc:
                logger.warning("autonomous[react]: ゴール判定失敗 id=%s error=%s", managed_goal.id, exc)
                if self._goal_manager:
                    self._goal_manager.update_status(managed_goal.id, GoalStatus.PENDING)

        await self._ws.broadcast({
            "type": "autonomous_cycle_done",
            "cycle": self._cycle,
            "mode": "react",
            "success": result.success,
            "steps_taken": len(result.steps),
        })

    async def _save_react_artifact(self, goal: str, result) -> None:
        """ReActの実行結果をMarkdownファイルとして保存"""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = self._output_dir / f"react_{self._cycle:03d}_{timestamp}.md"

        lines = [
            f"# ReActサイクル {self._cycle} — {timestamp}",
            "",
            "## ゴール",
            goal,
            "",
            f"## 結果（{len(result.steps)}ステップ）",
            f"**成功**: {'✓' if result.success else '✗'}",
            "",
            result.final_result,
            "",
            "## ステップ詳細",
            "",
        ]

        for step in result.steps:
            lines += [
                f"### ステップ {step.step}",
                f"**Thought**: {step.thought}",
                f"**Action**: `{step.action}`",
                f"**Observation**: {step.observation[:500]}",
                "",
            ]

        if result.error:
            lines += ["## エラー", result.error, ""]

        filepath.write_text("\n".join(lines), encoding="utf-8")
        logger.info("autonomous[react]: 成果物を保存 → %s", filepath)
        await self._ws.broadcast({
            "type": "autonomous_artifact",
            "cycle": self._cycle,
            "mode": "react",
            "path": str(filepath),
        })

    # ==============================
    # 結果処理: トリガーワード検出 → チェーン実行 → 成果物保存
    # ==============================

    async def _process_result(self, result: dict, theme: str):
        # メイン応答テキスト（leaderの統合回答）
        main_text = result.get("response", "")
        agent_results: dict[str, str] = result.get("agent_results", {})

        # 全テキストを結合してトリガーワードを検索
        all_text = main_text + "\n".join(agent_results.values())
        triggered = self._detect_triggers(all_text)

        chain_results: dict[str, str] = {}
        for word, (agent_code, instruction) in triggered.items():
            logger.info("autonomous: トリガー検出「%s」→ %s へ指示", word, agent_code)
            await self._ws.broadcast({
                "type": "autonomous_trigger",
                "keyword": word,
                "agent": agent_code,
            })
            chain_result = await self._run_agent_task(agent_code, instruction, context=main_text)
            chain_results[f"{word}({agent_code})"] = chain_result

        # 成果物ファイルを自動生成
        await self._save_artifact(theme, result, chain_results)

        await self._ws.broadcast({
            "type": "autonomous_cycle_done",
            "cycle": self._cycle,
            "triggers_fired": list(triggered.keys()),
        })

    def _detect_triggers(self, text: str) -> dict[str, tuple[str, str]]:
        """テキストからトリガーワードを検出。最初に見つかった2件まで"""
        found: dict[str, tuple[str, str]] = {}
        for word, action in TRIGGER_ACTIONS.items():
            if word in text and word not in found:
                found[word] = action
            if len(found) >= 2:
                break
        return found

    async def _run_agent_task(self, agent_code: str, instruction: str, context: str) -> str:
        """特定エージェントに単独でタスクを実行させる"""
        from app.agents.manager import AgentStatus
        agent_data = self._orch.agents.get(agent_code)
        if not agent_data:
            return f"[エージェント '{agent_code}' が見つかりません]"

        self._orch.agents.set_status(agent_code, AgentStatus.THINKING)
        await self._ws.broadcast({
            "type": "agent_status",
            "agent": agent_code,
            "status": AgentStatus.THINKING,
            "detail": f"自律タスク: {instruction[:30]}",
        })

        system = agent_data.get("personality", f"あなたは{agent_code}です。")
        prompt = f"【背景】\n{context[:500]}\n\n【指示】\n{instruction}"
        result = await chat_complete(system, prompt)

        self._orch.agents.set_status(agent_code, AgentStatus.IDLE)
        await self._ws.broadcast({
            "type": "agent_status",
            "agent": agent_code,
            "status": AgentStatus.IDLE,
            "detail": "自律タスク完了",
        })
        return result

    async def _save_artifact(self, theme: str, result: dict, chain_results: dict):
        """議論の成果物をMarkdownファイルとして保存"""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = self._output_dir / f"cycle_{self._cycle:03d}_{timestamp}.md"

        lines = [
            f"# 自律サイクル {self._cycle} — {timestamp}",
            "",
            "## テーマ",
            theme,
            "",
            "## Leaderの統合回答",
            result.get("response", "（なし）"),
            "",
        ]

        if result.get("agent_results"):
            lines += ["## 各エージェントの報告", ""]
            for agent, text in result["agent_results"].items():
                lines += [f"### {agent}", text, ""]

        if chain_results:
            lines += ["## トリガーによる追加アクション", ""]
            for key, text in chain_results.items():
                lines += [f"### {key}", text, ""]

        filepath.write_text("\n".join(lines), encoding="utf-8")
        logger.info("autonomous: 成果物を保存 → %s", filepath)
        await self._ws.broadcast({
            "type": "autonomous_artifact",
            "cycle": self._cycle,
            "path": str(filepath),
        })
