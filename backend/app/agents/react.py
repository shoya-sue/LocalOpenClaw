"""
ReActエンジン（Reasoning + Acting）

フロー:
  ゴール設定 → [Thought → Action → Observation] × max_steps → Finish

利用可能なツール:
  read_file       /data/ 配下のファイルを読み込む
  write_file      /data/output/ 配下にファイルを書き込む
  read_memory     エージェントのメモリを読む
  search_knowledge ChromaDBの知識ベースを検索する（RAG）
  finish          結論を出してループを終了する
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.agents.memory import read_memory as agent_read_memory
from app.agents.rag import DEFAULT_COLLECTION as _DEFAULT_COLLECTION, agent_collection_name, search_knowledge as rag_search
from app.agents.web import web_search as agent_web_search
from app.llm.ollama import chat_complete
from app.ws.manager import ConnectionManager

logger = logging.getLogger("uvicorn.error")

# ツール実行の許可ディレクトリ
_DATA_ROOT = Path(os.getenv("DATA_DIR", "/data"))
_ALLOWED_READ_ROOT = _DATA_ROOT
_ALLOWED_WRITE_ROOT = _DATA_ROOT / "output"

# デフォルト最大ステップ数（暴走防止）
DEFAULT_MAX_STEPS = int(os.getenv("REACT_MAX_STEPS", "5"))

# ステップ履歴の最大文字数（num_ctx制約対応）
_HISTORY_MAX_CHARS = int(os.getenv("REACT_HISTORY_MAX_CHARS", "1500"))

# ==============================
# システムプロンプト
# ==============================

_SYSTEM_PROMPT_TEMPLATE = """\
あなたは自律エージェントです。ゴールを達成するためにツールを使って行動してください。

利用可能なツール（JSON形式で出力）:
- read_file:        {{"thought":"...", "action":"read_file",        "path":"ファイル名またはサブパス（例: report.txt, processed/data.csv）"}}
- write_file:       {{"thought":"...", "action":"write_file",       "path":"output/ファイル名", "content":"内容"}}
- read_memory:      {{"thought":"...", "action":"read_memory",      "codename":"エージェント名", "filename":"memory.md"}}
- search_knowledge: {{"thought":"...", "action":"search_knowledge", "query":"検索クエリ", "collection":"{agent_collection}"}}
- web_search:       {{"thought":"...", "action":"web_search",       "query":"検索クエリ（英語推奨）"}}
- finish:           {{"thought":"...", "action":"finish",           "result":"最終的な結論"}}

ルール:
- 必ずJSONのみで回答してください。JSONの外にテキストを書かないでください
- read_file の path は data/ を除いたファイル名のみ指定（例: react-test.txt, output/summary.md）
- write_file の path は必ず output/ で始めてください
- search_knowledge はあなた専用の知識ベース（RAG）を検索する。自分の役割・スキルを調べる際に使用してください
- web_search はDuckDuckGoでWeb検索する。最新情報・技術情報の収集に使用してください
- 調査・検証が完了したら必ず finish を呼んでください
"""


def _build_system_prompt(codename: str) -> str:
    """エージェントのcodernameに合わせてシステムプロンプトを生成する"""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        agent_collection=agent_collection_name(codename)
    )


# ==============================
# データクラス
# ==============================

@dataclass
class ReactStep:
    """1ステップ（Thought + Action + Observation）"""
    step: int
    thought: str
    action: str
    action_params: dict
    observation: str = ""


@dataclass
class ReactResult:
    """ReActセッション全体の結果"""
    agent: str
    goal: str
    steps: list[ReactStep] = field(default_factory=list)
    final_result: str = ""
    success: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "goal": self.goal,
            "steps": [
                {
                    "step": s.step,
                    "thought": s.thought,
                    "action": s.action,
                    "params": s.action_params,
                    "observation": s.observation,
                }
                for s in self.steps
            ],
            "final_result": self.final_result,
            "success": self.success,
            "error": self.error,
        }


# ==============================
# ツール実行
# ==============================

def _safe_path(root: Path, user_path: str) -> Optional[Path]:
    """パストラバーサル対策。root の外に出ようとするパスは None を返す"""
    target = (root / user_path).resolve()
    if not str(target).startswith(str(root.resolve())):
        return None
    return target


async def _execute_tool(action: dict, default_collection: str = _DEFAULT_COLLECTION) -> str:
    """アクション dict を受け取りツールを実行して結果文字列を返す"""
    tool = action.get("action", "")

    if tool == "read_file":
        path_str = action.get("path", "")
        target = _safe_path(_ALLOWED_READ_ROOT, path_str)
        if target is None:
            return f"[ERROR] 許可されていないパスです: {path_str}"
        if not target.exists():
            # 存在しないファイルの代わりにディレクトリ一覧を返す（調査の手がかりに）
            parent = target.parent
            if parent.exists():
                files = [f.name for f in sorted(parent.iterdir())]
                return f"[INFO] {path_str} は存在しません。同ディレクトリ: {files}"
            return f"[ERROR] ファイルが存在しません: {path_str}"
        try:
            content = target.read_text(encoding="utf-8")
            if len(content) > 800:
                return content[:800] + "\n…（省略）"
            return content
        except Exception as e:
            return f"[ERROR] ファイル読み込み失敗: {e}"

    elif tool == "write_file":
        path_str = action.get("path", "")
        content = action.get("content", "")
        if not path_str.startswith("output/"):
            return f"[ERROR] write_file の path は output/ で始めてください: {path_str}"
        # "output/" プレフィックスを除いてWRITE_ROOT配下に書き込む
        relative = path_str.removeprefix("output/")
        target = _safe_path(_ALLOWED_WRITE_ROOT, relative)
        if target is None:
            return f"[ERROR] output/ 配下のパスのみ書き込み可能です: {path_str}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"[OK] {target.name} に書き込みました（{len(content)}文字）"
        except Exception as e:
            return f"[ERROR] ファイル書き込み失敗: {e}"

    elif tool == "read_memory":
        codename = action.get("codename", "")
        filename = action.get("filename", "memory.md")
        content = agent_read_memory(codename, filename)
        if not content:
            return f"[INFO] {codename}/{filename} は空またはファイルが存在しません"
        if len(content) > 600:
            return content[:600] + "\n…（省略）"
        return content

    elif tool == "search_knowledge":
        query = action.get("query", "")
        collection = action.get("collection", default_collection)
        if not query:
            return "[ERROR] search_knowledge には query が必要です"
        return await rag_search(query, collection)

    elif tool == "web_search":
        query = action.get("query", "")
        if not query:
            return "[ERROR] web_search には query が必要です"
        return await agent_web_search(query)

    elif tool == "finish":
        # finish は _run ループ内で処理するため、ここには通常来ない
        return action.get("result", "")

    else:
        return f"[ERROR] 不明なアクション: {tool}（read_file / write_file / read_memory / search_knowledge / finish を使用してください）"


# ==============================
# ReActAgent
# ==============================

class ReActAgent:
    """ReActループでゴールを自律達成するエージェント"""

    def __init__(
        self,
        codename: str,
        personality: str,
        ws_manager: Optional[ConnectionManager] = None,
        max_steps: int = DEFAULT_MAX_STEPS,
    ):
        self.codename = codename
        self.personality = personality
        self.ws = ws_manager
        self.max_steps = max_steps

    async def run(self, goal: str) -> ReactResult:
        """ReActループを実行して結果を返す"""
        result = ReactResult(agent=self.codename, goal=goal)
        steps: list[ReactStep] = []

        logger.info("react[%s]: 開始 goal=%s", self.codename, goal[:60])

        for step_num in range(1, self.max_steps + 1):
            await self._broadcast("react_step_start", {
                "agent": self.codename,
                "step": step_num,
                "max_steps": self.max_steps,
            })

            # Thought + Action を LLM に生成させる
            user_prompt = self._build_prompt(goal, steps)
            system = self.personality + "\n\n" + _build_system_prompt(self.codename)
            raw = await chat_complete(system, user_prompt)
            action = self._parse_action(raw)

            if action is None:
                # JSON解析失敗 → エラーとして終了
                obs = f"[PARSE ERROR] JSON解析失敗。LLM出力: {raw[:200]}"
                step = ReactStep(
                    step=step_num,
                    thought="（JSON解析失敗）",
                    action="finish",
                    action_params={},
                    observation=obs,
                )
                steps.append(step)
                result.steps = steps
                result.error = obs
                result.final_result = obs
                await self._broadcast_step(step)
                logger.warning("react[%s]: ステップ%d JSON解析失敗", self.codename, step_num)
                break

            thought = action.get("thought", "")
            action_name = action.get("action", "finish")
            action_params = {k: v for k, v in action.items() if k not in ("thought", "action")}

            step = ReactStep(
                step=step_num,
                thought=thought,
                action=action_name,
                action_params=action_params,
            )

            await self._broadcast("react_thought", {
                "agent": self.codename,
                "step": step_num,
                "thought": thought,
                "action": action_name,
            })
            logger.info("react[%s]: ステップ%d thought=%s action=%s", self.codename, step_num, thought[:50], action_name)

            # finish アクション → ループ終了
            if action_name == "finish":
                step.observation = action_params.get("result", "")
                result.final_result = step.observation
                result.success = True
                steps.append(step)
                result.steps = steps
                await self._broadcast_step(step)
                logger.info("react[%s]: finish到達（%dステップ）", self.codename, step_num)
                break

            # ツール実行 → Observation 取得
            # エージェント自身のコレクションをデフォルトで検索する
            observation = await _execute_tool(
                action, default_collection=agent_collection_name(self.codename)
            )
            step.observation = observation
            steps.append(step)

            await self._broadcast("react_observation", {
                "agent": self.codename,
                "step": step_num,
                "action": action_name,
                "observation": observation[:300],
            })
            await self._broadcast_step(step)

        else:
            # 最大ステップ到達（finish なしで終了）
            result.steps = steps
            result.final_result = steps[-1].observation if steps else "（結果なし）"
            result.success = False
            logger.warning("react[%s]: 最大ステップ(%d)到達", self.codename, self.max_steps)

        await self._broadcast("react_finish", {
            "agent": self.codename,
            "steps_taken": len(result.steps),
            "success": result.success,
            "result_preview": result.final_result[:200],
        })

        return result

    def _build_prompt(self, goal: str, steps: list[ReactStep]) -> str:
        """履歴をコンパクトに整形してプロンプトを構築する"""
        lines = [f"【ゴール】\n{goal}\n"]

        if steps:
            lines.append("【これまでのステップ】")
            history_text = ""
            for s in steps:
                entry = (
                    f"ステップ{s.step}:\n"
                    f"  Thought: {s.thought}\n"
                    f"  Action: {s.action}\n"
                    f"  Observation: {s.observation[:300]}\n"
                )
                history_text += entry

            # num_ctx 制約を超えないよう古い履歴を末尾優先で切り捨て
            if len(history_text) > _HISTORY_MAX_CHARS:
                history_text = "…（古い履歴省略）\n" + history_text[-_HISTORY_MAX_CHARS:]
            lines.append(history_text)

        lines.append("次のアクションをJSONのみで出力してください:")
        return "\n".join(lines)

    @staticmethod
    def _parse_action(text: str) -> Optional[dict]:
        """LLM出力からJSONオブジェクトを抽出する"""
        # ```json ... ``` ブロックを除去
        text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
        # qwen3 の <think>...</think> 思考ブロックを除去
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # まず全体を JSON として試みる
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

    async def _broadcast(self, event_type: str, payload: dict):
        if self.ws:
            await self.ws.broadcast({"type": event_type, **payload})

    async def _broadcast_step(self, step: ReactStep):
        if self.ws:
            await self.ws.broadcast({
                "type": "react_step",
                "agent": self.codename,
                "step": step.step,
                "thought": step.thought,
                "action": step.action,
                "params": step.action_params,
                "observation": step.observation[:300],
            })
