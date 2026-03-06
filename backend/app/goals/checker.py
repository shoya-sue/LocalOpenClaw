"""
ゴール完了判定モジュール

静的チェック（ファイル存在・サイズ・キーワード）とLLM判定（YES/NO）の2段階で
ゴールの達成を判定し、検証レポートを自動生成する。
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.goals.manager import Goal, GoalStatus
from app.llm.ollama import chat_complete

logger = logging.getLogger("uvicorn.error")

_OUTPUT_DIR = Path(os.getenv("DATA_DIR", "/data")) / "output"

# LLM判定プロンプト（シンプルな二択に絞る）
_LLM_JUDGE_SYSTEM = """\
あなたはゴール達成判定の審査員です。
与えられたゴールと観察結果を元に、ゴールが達成されたかどうかを判定してください。
必ず「YES」または「NO」の一単語のみで回答してください。
"""

_LLM_JUDGE_PROMPT = """\
【ゴール】
{goal_description}

【達成基準】
{success_criteria}

【観察結果（成果物の内容）】
{observation}

このゴールは達成されましたか？ YES または NO で答えてください:"""


@dataclass
class CheckResult:
    """判定結果"""
    goal_id: str
    static_passed: bool
    llm_passed: bool
    achieved: bool  # static_passed AND llm_passed
    details: dict = field(default_factory=dict)
    report_path: str = ""


async def check_goal(goal: Goal, output_dir: Path = _OUTPUT_DIR) -> CheckResult:
    """
    ゴールの達成判定を行う。

    1. 静的チェック: ファイル存在・文字数・キーワード
    2. LLM判定: 静的チェックを通過した場合のみ実施
    3. レポート生成
    """
    details: dict = {}

    # ① 静的チェック
    static_passed, static_details = _static_check(goal, output_dir)
    details.update(static_details)

    # ② LLM判定（静的チェック通過時のみ）
    llm_passed = False
    llm_answer = "SKIP"
    if static_passed and static_details.get("file_content"):
        observation = static_details["file_content"][:800]
        llm_passed, llm_answer = await _llm_check(goal, observation)
    details["llm_answer"] = llm_answer

    achieved = static_passed and llm_passed

    # ③ 検証レポート生成
    result = CheckResult(
        goal_id=goal.id,
        static_passed=static_passed,
        llm_passed=llm_passed,
        achieved=achieved,
        details=details,
    )
    report_path = await _generate_report(goal, result, output_dir)
    result.report_path = str(report_path)

    logger.info(
        "goals[%s]: 判定完了 static=%s llm=%s achieved=%s",
        goal.id, static_passed, llm_passed, achieved,
    )
    return result


def _static_check(goal: Goal, output_dir: Path) -> tuple[bool, dict]:
    """静的チェック: ファイル存在・文字数・キーワード"""
    details: dict = {
        "file_exists": False,
        "char_count": 0,
        "keywords_found": [],
        "keywords_missing": [],
        "file_content": "",
    }

    if not goal.check_file:
        # check_fileが未設定の場合は静的チェックをスキップ（常に通過）
        return True, details

    target = output_dir / goal.check_file
    details["check_file_path"] = str(target)

    if not target.exists():
        logger.debug("goals[%s]: ファイル未存在: %s", goal.id, target)
        return False, details

    details["file_exists"] = True

    try:
        content = target.read_text(encoding="utf-8")
        details["file_content"] = content
        details["char_count"] = len(content)
    except Exception as e:
        details["read_error"] = str(e)
        return False, details

    # 文字数チェック
    if goal.min_chars > 0 and len(content) < goal.min_chars:
        logger.debug(
            "goals[%s]: 文字数不足 %d < %d", goal.id, len(content), goal.min_chars
        )
        return False, details

    # キーワードチェック
    for kw in goal.check_keywords:
        if kw in content:
            details["keywords_found"].append(kw)
        else:
            details["keywords_missing"].append(kw)

    if details["keywords_missing"]:
        logger.debug("goals[%s]: キーワード不足: %s", goal.id, details["keywords_missing"])
        return False, details

    return True, details


async def _llm_check(goal: Goal, observation: str) -> tuple[bool, str]:
    """LLM判定: シンプルなYES/NOで判定"""
    prompt = _LLM_JUDGE_PROMPT.format(
        goal_description=goal.description,
        success_criteria=goal.success_criteria,
        observation=observation,
    )
    try:
        answer = await chat_complete(_LLM_JUDGE_SYSTEM, prompt)
        # YES/NO を抽出（大文字小文字・余分な文字を除去）
        normalized = answer.strip().upper()
        if "YES" in normalized:
            return True, "YES"
        return False, "NO"
    except Exception as e:
        logger.warning("goals[%s]: LLM判定失敗: %s", goal.id, e)
        return False, f"ERROR: {e}"


async def _generate_report(goal: Goal, result: CheckResult, output_dir: Path) -> Path:
    """検証レポートを data/output/report_{goal_id}.md として生成"""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"report_{goal.id}.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    status_icon = "✓" if result.achieved else "✗"
    lines = [
        f"# ゴール検証レポート: {goal.id}",
        f"**生成日時**: {timestamp}",
        f"**達成状況**: {status_icon} {'達成' if result.achieved else '未達成'}",
        "",
        "## ゴール定義",
        f"**説明**: {goal.description}",
        f"**達成基準**: {goal.success_criteria}",
        f"**最大サイクル数**: {goal.max_cycles}",
        f"**実行済みサイクル**: {goal.cycles_done}",
        "",
        "## 判定結果",
        f"| 判定種別 | 結果 |",
        f"|---------|------|",
        f"| 静的チェック | {'✓ PASS' if result.static_passed else '✗ FAIL'} |",
        f"| LLM判定 | {result.details.get('llm_answer', 'SKIP')} |",
        f"| **総合判定** | {'✓ **達成**' if result.achieved else '✗ **未達成**'} |",
        "",
        "## 静的チェック詳細",
        f"- ファイル存在: {'✓' if result.details.get('file_exists') else '✗'} `{result.details.get('check_file_path', '-')}`",
        f"- 文字数: {result.details.get('char_count', 0)} 文字（最低: {goal.min_chars}文字）",
        f"- 必須キーワード見つかった: {result.details.get('keywords_found', [])}",
        f"- 必須キーワード不足: {result.details.get('keywords_missing', [])}",
    ]

    if result.details.get("read_error"):
        lines += ["", f"**読み込みエラー**: {result.details['read_error']}"]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("goals[%s]: レポート生成 → %s", goal.id, report_path)
    return report_path
