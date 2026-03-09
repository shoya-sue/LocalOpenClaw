"""
自律ループモジュール
エージェントが自分たちで会話・判断・創作を行う

フロー:
  ループ開始 → Leaderがテーマ選択 → オーケストレーション →
  出力からトリガーワード検出 → 次アクション自動実行 → 成果物ファイル生成
"""

import asyncio
import json
import logging
import os
import random
import re
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

# 台本作成指示：5区間フォーマット・映像指示・テキストオーバーレイ・BGMキュー必須
_SCRIPT_INSTRUCTION = (
    "60秒縦型動画の台本を以下の5区間・秒単位で作成してください。"
    "各区間に映像指示・ナレーション（「」でセリフ）・テキストオーバーレイ・BGMキューを必ず記載してください。\n\n"
    "0-5秒（フック）:\n  映像: \n  ナレーション: 「」\n  テキスト: \n  BGM: \n\n"
    "5-20秒（本編①）:\n  映像: \n  ナレーション: 「」\n  テキスト: \n  BGM: \n\n"
    "20-40秒（本編②）:\n  映像: \n  ナレーション: 「」\n  テキスト: \n  BGM: \n\n"
    "40-55秒（まとめ）:\n  映像: \n  ナレーション: 「」\n  テキスト: \n  BGM: \n\n"
    "55-60秒（CTA）:\n  映像: \n  ナレーション: 「」\n  テキスト: \n  BGM:"
)

# JSON出力指示：動画制作ツール用の完全スキーマ（resolution/aspect_ratio/scenes[]/bgm_cue含む）
# 【重要】プレースホルダーをそのままコピーせず、上の引き継ぎ情報から内容を埋めること
_JSON_INSTRUCTION = (
    "上の引き継ぎ情報（台本・トレンド・提案）を使って、動画コンテンツの仕様を以下のJSONスキーマで出力してください。\n"
    "【重要】各フィールドは動画テーマに合わせた具体的な内容で埋めること。プレースホルダーをそのまま出力しない。\n"
    "必ず ```json コードブロックで囲むこと。\n\n"
    '{\n'
    '  "title": "（動画テーマに合った具体的なタイトル）",\n'
    '  "platform": "YouTube Shorts",\n'
    '  "resolution": "1080x1920",\n'
    '  "aspect_ratio": "9:16",\n'
    '  "duration_sec": 60,\n'
    '  "target_audience": "（ターゲット視聴者：年代・性別・悩みを具体的に）",\n'
    '  "hook": "（冒頭0-5秒の視聴者を引き付けるセリフ。例：「まだ○○で損してるの？」）",\n'
    '  "scenes": [\n'
    '    {"time": "0-5", "visual": "（映像の具体的な内容）", "narration": "（セリフ全文）", "text_overlay": "（画面テキスト）", "bgm_cue": "（BGMの雰囲気）"},\n'
    '    {"time": "5-20", "visual": "（映像の具体的な内容）", "narration": "（セリフ全文）", "text_overlay": "（画面テキスト）", "bgm_cue": "（BGMの雰囲気）"},\n'
    '    {"time": "20-40", "visual": "（映像の具体的な内容）", "narration": "（セリフ全文）", "text_overlay": "（画面テキスト）", "bgm_cue": "（BGMの雰囲気）"},\n'
    '    {"time": "40-55", "visual": "（映像の具体的な内容）", "narration": "（セリフ全文）", "text_overlay": "（画面テキスト）", "bgm_cue": "（BGMの雰囲気）"},\n'
    '    {"time": "55-60", "visual": "（チャンネル登録ボタンを映す）", "narration": "（CTAのセリフ）", "text_overlay": "チャンネル登録お願いします！", "bgm_cue": "フェードアウト"}\n'
    '  ],\n'
    '  "cta": "（視聴者への具体的なCTA文。例：「このチャンネルでは毎週○○情報を発信中！チャンネル登録して最新動画を見逃さないで！」）",\n'
    '  "hashtags": ["#（テーマ関連タグ1）", "#（テーマ関連タグ2）", "#（テーマ関連タグ3）", "#（テーマ関連タグ4）", "#（テーマ関連タグ5）", "#（テーマ関連タグ6）", "#（テーマ関連タグ7）", "#（テーマ関連タグ8）", "#（テーマ関連タグ9）", "#（テーマ関連タグ10）"]\n'
    "}"
)

# エージェントが使う厳選トリガーワード → (担当エージェント, 追加指示)
TRIGGER_ACTIONS: dict[str, tuple[str, str]] = {
    "調査開始":   ("detective",  "SNSトレンド・ターゲット視聴者・人気ハッシュタグを具体的な数字で調査してレポートしてください"),
    "分析依頼":   ("researcher", "動画の最適構成を設計し、ターゲット視聴者・差別化ポイントを時間軸（0-5秒、5-20秒…）で分析してください"),
    "JSON出力":   ("engineer",   _JSON_INSTRUCTION),
    "提案作成":   ("sales",      "フック文3案（数字・疑問文・衝撃の事実パターン）とCTA・ハッシュタグ10個を今すぐ提案してください"),
    "台本作成":   ("secretary",  _SCRIPT_INSTRUCTION),
    "問題発見":   ("detective",  "視聴維持率が下がる原因を具体的に調査し、改善策を報告してください"),
    "成果物作成": ("engineer",   _JSON_INSTRUCTION),
    "次フェーズ": ("leader",     "現在の成果を踏まえて次のフェーズのテーマを決めてください"),
}

# ReActモード用ゴールリスト（60秒動画コンテンツ連続生成）
REACT_GOALS = [
    (
        "AIと日常生活をテーマにした60秒縦型動画のコンテンツをJSON形式で作成し、"
        "output/content_ai_daily.json に保存してください。"
        "JSONには title, platform(YouTube Shorts), target_audience, hook(冒頭3秒のセリフ), "
        "script(秒単位の配列: time/visual/narration), cta, hashtags を含めてください。"
    ),
    (
        "今すぐ使えるライフハックをテーマにした60秒縦型動画のコンテンツをJSON形式で作成し、"
        "output/content_lifehack.json に保存してください。"
        "JSONには title, platform(TikTok), target_audience, hook, script, cta, hashtags を含めてください。"
    ),
    (
        "10分で作れる簡単レシピをテーマにした60秒縦型動画のコンテンツをJSON形式で作成し、"
        "output/content_recipe.json に保存してください。"
        "JSONには title, platform(Instagram Reels), target_audience, hook, script, cta, hashtags を含めてください。"
    ),
    (
        "朝のルーティンをテーマにした60秒縦型動画のコンテンツをJSON形式で作成し、"
        "output/content_morning_routine.json に保存してください。"
        "JSONには title, platform(YouTube Shorts), target_audience, hook, script, cta, hashtags を含めてください。"
    ),
    (
        "最新テクノロジー解説をテーマにした60秒縦型動画のコンテンツをJSON形式で作成し、"
        "output/content_tech.json に保存してください。"
        "JSONには title, platform(TikTok), target_audience, hook, script, cta, hashtags を含めてください。"
    ),
    (
        "お金の節約術をテーマにした60秒縦型動画のコンテンツをJSON形式で作成し、"
        "output/content_money_saving.json に保存してください。"
        "JSONには title, platform(YouTube Shorts), target_audience, hook, script, cta, hashtags を含めてください。"
    ),
    (
        "メンタルヘルス・ストレス解消をテーマにした60秒縦型動画のコンテンツをJSON形式で作成し、"
        "output/content_mental_health.json に保存してください。"
        "JSONには title, platform(Instagram Reels), target_audience, hook, script, cta, hashtags を含めてください。"
    ),
]

# Leaderが自律的に選ぶ議題リスト（60秒動画コンテンツ連続生成）
AUTONOMOUS_THEMES = [
    (
        "「AIと日常生活」をテーマにした60秒縦型動画（YouTube Shorts向け）のコンテンツを作成してください。"
        "detectiveがトレンドと視聴者ニーズを調査し、researcherが構成を設計してください。"
        "構成が決まったら『台本作成』で秒単位の台本を作成してください。"
        "台本完成後は『JSON出力』でJSON形式にフォーマットしてください。"
    ),
    (
        "「今すぐ使えるライフハック3選」をテーマにした60秒縦型動画（TikTok向け）のコンテンツを作成してください。"
        "冒頭3秒で視聴者を引き付けるフックから始め、本編で3つのハック、最後にフォロー促進のCTAで締めてください。"
        "researcherが具体的なハックを選定したら『台本作成』で秒単位の台本を作ってください。"
        "台本完成後は『JSON出力』でJSON形式にフォーマットしてください。"
    ),
    (
        "「10分で作れる簡単レシピ」をテーマにした60秒縦型動画（Instagram Reels向け）のコンテンツを作成してください。"
        "食材・手順・完成映像の構成で視覚的に魅力的なコンテンツにしてください。"
        "detectiveがトレンドレシピを調査し、salesが視聴者を引き付けるポイントを提案してください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「生産性を上げる朝のルーティン」をテーマにした60秒縦型動画（YouTube Shorts向け）のコンテンツを作成してください。"
        "20代〜30代の社会人をターゲットに、朝5:30〜7:00の理想的なルーティンを紹介してください。"
        "researcherが科学的根拠のある習慣を選定し、secretaryが台本を整理してください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「2026年注目のテクノロジー」をテーマにした60秒縦型動画（TikTok向け）のコンテンツを作成してください。"
        "テック系コンテンツとして、AI・量子コンピューティング・空間コンピューティングから1つ選んで深掘りしてください。"
        "detectiveが最新情報を調査し、engineerが技術的な正確性を確認してください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「月3万円節約できる生活術」をテーマにした60秒縦型動画（YouTube Shorts向け）のコンテンツを作成してください。"
        "固定費削減・食費節約・サブスク見直しの3ポイントを紹介する構成にしてください。"
        "salesが説得力のある数字と事例を提案し、secretaryが分かりやすい台本にまとめてください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「1日5分でできるメンタルリセット法」をテーマにした60秒縦型動画（Instagram Reels向け）のコンテンツを作成してください。"
        "ストレスを抱えた20〜40代をターゲットに、科学的根拠のある方法を3つ紹介してください。"
        "researcherが心理学・神経科学の観点から手法を選定し、salesが共感を呼ぶ切り口を提案してください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「筋トレ初心者が3ヶ月で変わる！自宅トレーニング3選」をテーマにした60秒縦型動画（YouTube Shorts向け）のコンテンツを作成してください。"
        "道具なしでできる体幹・腕・脚のトレーニングを紹介し、before/after効果を強調してください。"
        "detectiveが人気トレーニング動画のトレンドを調査し、secretaryが分かりやすい台本にまとめてください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「英語が話せるようになる！1日10分の勉強法」をテーマにした60秒縦型動画（TikTok向け）のコンテンツを作成してください。"
        "社会人の英語学習者をターゲットに、シャドーイング・音読・アプリ活用の3ステップを紹介してください。"
        "researcherが効果的な学習法の研究を調査し、salesが「今すぐ始めたくなる」フック文を提案してください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「部屋が変わると人生が変わる！ミニマリスト収納術3選」をテーマにした60秒縦型動画（Instagram Reels向け）のコンテンツを作成してください。"
        "20〜30代の一人暮らしをターゲットに、クローゼット・キッチン・デスクの整理術を紹介してください。"
        "detectiveがトレンドの収納インテリアを調査し、secretaryがビジュアル映えする台本を作成してください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「睡眠の質を劇的に上げる！寝る前5分の習慣」をテーマにした60秒縦型動画（YouTube Shorts向け）のコンテンツを作成してください。"
        "睡眠不足に悩む30〜40代をターゲットに、ストレッチ・スマホ断ち・アロマの3つの習慣を紹介してください。"
        "researcherが睡眠科学の最新知見を調査し、salesが共感を呼ぶオープニングを提案してください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「副業で月5万円！スキルゼロから始めるフリーランス入門」をテーマにした60秒縦型動画（TikTok向け）のコンテンツを作成してください。"
        "会社員の副業初心者をターゲットに、ライティング・デザイン・動画編集の3つの始め方を紹介してください。"
        "detectiveが副業トレンドと需要を調査し、salesが「今すぐ行動したくなる」CTAを提案してください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
    ),
    (
        "「スキンケア迷子卒業！肌タイプ別の正しい洗顔方法」をテーマにした60秒縦型動画（Instagram Reels向け）のコンテンツを作成してください。"
        "スキンケア初心者の20代女性をターゲットに、乾燥肌・脂性肌・混合肌別のケア方法を紹介してください。"
        "researcherが皮膚科学の根拠を調査し、secretaryが視覚的に分かりやすい台本にまとめてください。"
        "『台本作成』で秒単位の台本を作り、『JSON出力』でフォーマットしてください。"
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
                # 出力フォーマット仕様をテーマ先頭に付加して品質を担保
                theme = "【フォーマット】9:16縦型・1080×1920・60秒動画\n【必須出力】秒単位台本＋JSON仕様書（resolution/scenes[]/bgm_cue含む）\n\n" + theme
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
                self._goal_manager.update_status(managed_goal.id, new_status, report_path=check_result.report_path)
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

        # テーマ文字列も含めてトリガーワードを検索
        # テーマに明示的に指定されたトリガーを確実に発火させる
        all_text = main_text + "\n".join(agent_results.values()) + "\n" + theme
        triggered = self._detect_triggers(all_text)

        chain_results: dict[str, str] = {}
        for word, (agent_code, instruction) in triggered.items():
            logger.info("autonomous: トリガー検出「%s」→ %s へ指示", word, agent_code)
            await self._ws.broadcast({
                "type": "autonomous_trigger",
                "keyword": word,
                "agent": agent_code,
            })
            chain_result = await self._run_agent_task(
                agent_code, instruction, context=main_text, agent_results=agent_results
            )
            chain_results[f"{word}({agent_code})"] = chain_result

        # 成果物ファイルを自動生成
        await self._save_artifact(theme, result, chain_results)

        await self._ws.broadcast({
            "type": "autonomous_cycle_done",
            "cycle": self._cycle,
            "triggers_fired": list(triggered.keys()),
        })

    def _detect_triggers(self, text: str) -> dict[str, tuple[str, str]]:
        """テキストからトリガーワードを検出。最初に見つかった5件まで"""
        found: dict[str, tuple[str, str]] = {}
        for word, action in TRIGGER_ACTIONS.items():
            if word in text and word not in found:
                found[word] = action
            if len(found) >= 5:
                break
        return found

    async def _run_agent_task(
        self,
        agent_code: str,
        instruction: str,
        context: str,
        agent_results: Optional[dict[str, str]] = None,
    ) -> str:
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

        # コンテキスト構築: Leaderの統合回答 + 各エージェントの個別報告
        # engineerには台本(secretary)を優先して多く渡す。他エージェントは600文字/件
        max_context_chars = int(os.getenv("CONTEXT_MAX_CHARS", "3000")) // 2
        per_agent_chars = 600
        context_parts = [f"【Leaderの統合回答】\n{context[:400]}"]
        if agent_results:
            # secretaryの台本をengineerに優先して渡すため先頭に配置
            priority_order = ["secretary", "sales", "researcher", "detective"]
            ordered = sorted(
                agent_results.items(),
                key=lambda kv: priority_order.index(kv[0]) if kv[0] in priority_order else 99
            )
            for agent, text in ordered:
                context_parts.append(f"【{agent}の報告】\n{text[:per_agent_chars]}")
        full_context = "\n\n".join(context_parts)
        if len(full_context) > max_context_chars:
            full_context = "…（省略）\n" + full_context[-max_context_chars:]
        logger.info(
            "autonomous: _run_agent_task %s — context %d文字", agent_code, len(full_context)
        )

        prompt = f"【背景情報】\n{full_context}\n\n【指示】\n{instruction}"
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
        """議論の成果物をMarkdownファイルとして保存。JSON検出時は .json も出力"""
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

        # JSON出力トリガーの結果からJSONを抽出して別ファイルにも保存
        json_path = await self._try_save_json(chain_results, timestamp)

        await self._ws.broadcast({
            "type": "autonomous_artifact",
            "cycle": self._cycle,
            "path": str(filepath),
            "json_path": str(json_path) if json_path else None,
        })

    async def _try_save_json(self, chain_results: dict, timestamp: str) -> Optional[Path]:
        """chain_results の中からJSONブロックを抽出・検証してファイルに保存する"""
        all_text = "\n".join(chain_results.values())

        parsed = None

        # 各 ```json ... ``` ブロックを非グリーディで探し、先頭から順に試す
        # 複数ブロック（engineer + secretary）がある場合に誤マッチしないよう非グリーディ
        for block_match in re.finditer(r"```json\s*(.*?)\s*```", all_text, re.DOTALL):
            block = block_match.group(1).strip()
            try:
                candidate = json.loads(block)
                # 動画仕様書として必要なフィールドを持つブロックを優先
                if "title" in candidate and ("hook" in candidate or "scenes" in candidate):
                    parsed = candidate
                    break
            except json.JSONDecodeError:
                # ブロック内の {...} 部分だけ抽出して再試行
                inner = re.search(r"\{.*\}", block, re.DOTALL)
                if inner:
                    try:
                        candidate = json.loads(inner.group())
                        if "title" in candidate and ("hook" in candidate or "scenes" in candidate):
                            parsed = candidate
                            break
                    except json.JSONDecodeError:
                        continue

        if parsed is None:
            return None

        try:

            # 動画制作に最低限必要なフィールドを検証
            required_fields = {"title", "hook"}
            missing = required_fields - parsed.keys()
            if missing:
                logger.warning("autonomous: JSON検証失敗 — 必須フィールド不足: %s", missing)
                return None

            # scenesフィールドが空または存在しない場合はスケルトンを補完
            if not parsed.get("scenes"):
                parsed["scenes"] = [
                    {"time": "0-5", "visual": "", "narration": "", "text_overlay": "", "bgm_cue": ""},
                    {"time": "5-20", "visual": "", "narration": "", "text_overlay": "", "bgm_cue": ""},
                    {"time": "20-40", "visual": "", "narration": "", "text_overlay": "", "bgm_cue": ""},
                    {"time": "40-55", "visual": "", "narration": "", "text_overlay": "", "bgm_cue": ""},
                    {"time": "55-60", "visual": "", "narration": "", "text_overlay": "", "bgm_cue": ""},
                ]
                logger.warning("autonomous: scenesフィールドが空のためスケルトンを補完")

            # 動画フォーマット情報を自動補完（未設定の場合）
            parsed.setdefault("resolution", "1080x1920")
            parsed.setdefault("aspect_ratio", "9:16")
            parsed.setdefault("duration_sec", 60)

            json_path = self._output_dir / f"content_{self._cycle:03d}_{timestamp}.json"
            json_path.write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("autonomous: JSONコンテンツを保存 → %s", json_path)
            return json_path
        except (json.JSONDecodeError, IndexError) as exc:
            logger.warning("autonomous: JSON解析失敗: %s", exc)
            return None
