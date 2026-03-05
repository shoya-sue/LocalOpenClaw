#!/usr/bin/env python3
"""
エージェント人格ランダム生成スクリプト
テンプレートYAMLからランダムに人格を組み合わせてエージェント定義を生成する。
生成履歴は logs/agent_history.md に記録される。
"""

import random
import yaml
import os
from datetime import datetime
from pathlib import Path

# パス定義
BASE_DIR = Path(__file__).parent.parent
TEMPLATE_DIR = BASE_DIR / "config" / "templates"
AGENT_DIR = BASE_DIR / "config" / "agents"
LOG_FILE = BASE_DIR / "logs" / "agent_history.md"

# 生成対象エージェントのコードネームリスト（固定）
AGENT_CODENAMES = ["leader", "detective", "researcher", "sales", "secretary", "engineer"]


def load_template(codename: str) -> dict:
    """テンプレートYAMLを読み込む"""
    template_path = TEMPLATE_DIR / f"{codename}.yaml"
    with open(template_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def pick_name(names_pool: dict) -> str:
    """名前プールからランダムに1つ選ぶ（カテゴリもランダム）"""
    categories = list(names_pool.values())
    chosen_category = random.choice(categories)
    return random.choice(chosen_category)


def generate_personality(template: dict) -> dict:
    """テンプレートからランダムに人格を生成する"""
    # サブロールをランダム選択
    sub_role = random.choice(template["sub_roles"])

    # 名前をランダム選択
    name = pick_name(template["names"])

    # personality_fragments から2〜3個ランダムに選択
    fragments = sub_role["personality_fragments"]
    selected_fragments = random.sample(fragments, k=min(3, len(fragments)))

    # speech_style から1〜2個ランダムに選択
    speech = sub_role["speech_style"]
    selected_speech = random.sample(speech, k=min(2, len(speech)))

    # common_traits からランダムに2個（positive）+ 1個（quirks）選択
    traits = template["common_traits"]
    positive = random.sample(traits["positive"], k=min(2, len(traits["positive"])))
    quirks = random.sample(traits["quirks"], k=min(1, len(traits["quirks"])))

    return {
        "name": name,
        "sub_role_id": sub_role["id"],
        "sub_role_label": sub_role["label"],
        "description": sub_role["description"],
        "personality_fragments": selected_fragments,
        "speech_style": selected_speech,
        "traits": {
            "positive": positive,
            "quirks": quirks,
        },
    }


def build_agent_yaml(codename: str, personality: dict, existing: dict) -> dict:
    """既存のエージェントYAMLに生成した人格を上書き合成する"""
    # 既存データをベースに人格部分だけ更新
    agent = dict(existing)

    agent["name"] = personality["name"]
    agent["role_category"] = existing.get("role", codename)
    agent["sub_role"] = {
        "id": personality["sub_role_id"],
        "label": personality["sub_role_label"],
        "description": personality["description"],
    }

    # personality フィールドを再生成
    fragments_text = "\n".join(f"  - {f}" for f in personality["personality_fragments"])
    speech_text = "\n".join(f"  - {s}" for s in personality["speech_style"])
    traits_positive = "\n".join(f"  - {t}" for t in personality["traits"]["positive"])
    traits_quirks = "\n".join(f"  - {t}" for t in personality["traits"]["quirks"])

    agent["personality"] = (
        f"あなたは「{personality['name']}」という名前の{personality['sub_role_label']}です。\n\n"
        f"【役割】\n{personality['description']}\n\n"
        f"【性格・信念】\n{fragments_text}\n\n"
        f"【口調・話し方】\n{speech_text}\n\n"
        f"【特性】\n{traits_positive}\n\n"
        f"【癖・習慣】\n{traits_quirks}\n"
    )

    return agent


def write_agent_yaml(codename: str, agent_data: dict) -> None:
    """エージェントYAMLを書き出す（コメントヘッダー付き）"""
    output_path = AGENT_DIR / f"{codename}.yaml"

    # YAMLシリアライズ（allow_unicode=Trueで日本語を文字化けさせない）
    yaml_content = yaml.dump(
        agent_data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        indent=2,
    )

    header = (
        f"# ========================================\n"
        f"# エージェント定義: {agent_data.get('name', codename)}\n"
        f"# codename: {codename}（固定）\n"
        f"# 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# ========================================\n\n"
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + yaml_content)


def load_existing_agent(codename: str) -> dict:
    """既存のエージェントYAMLを読み込む（存在しなければ最小構成を返す）"""
    agent_path = AGENT_DIR / f"{codename}.yaml"
    if agent_path.exists():
        with open(agent_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"codename": codename, "version": "1.0.0"}


def append_history(generation_id: str, results: list[dict]) -> None:
    """生成履歴を logs/agent_history.md に追記する"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"\n## Generation `{generation_id}` — {timestamp}\n",
        "| エージェント | 名前 | サブロール | 特性（抜粋） |",
        "|------------|------|----------|------------|",
    ]

    for r in results:
        trait_preview = r["traits"]["positive"][0] if r["traits"]["positive"] else "-"
        quirk_preview = r["traits"]["quirks"][0] if r["traits"]["quirks"] else "-"
        lines.append(
            f"| {r['codename']} ({r['role_category']}) "
            f"| {r['name']} "
            f"| {r['sub_role_label']} "
            f"| {trait_preview} / {quirk_preview} |"
        )

    lines.append("")  # 末尾に空行

    # ファイルが存在しない場合はヘッダーを付与
    if not LOG_FILE.exists():
        header_lines = [
            "# エージェント生成履歴\n",
            "このファイルは `pipeline/generate_agents.py` によって自動生成されます。\n",
        ]
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(line + "\n" for line in header_lines)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.writelines(line + "\n" for line in lines)


def generate_all(dry_run: bool = False) -> None:
    """全エージェントの人格を一括生成する"""
    # 生成IDは日時ベース
    generation_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*50}")
    print(f"  エージェント人格生成  [{generation_id}]")
    print(f"{'='*50}")

    history_records = []

    for codename in AGENT_CODENAMES:
        template = load_template(codename)
        personality = generate_personality(template)
        existing = load_existing_agent(codename)
        agent_data = build_agent_yaml(codename, personality, existing)

        # 表示
        print(f"\n[{codename.upper()}]")
        print(f"  名前     : {personality['name']}")
        print(f"  サブロール: {personality['sub_role_label']}")
        print(f"  説明     : {personality['description']}")
        print(f"  特性     : {', '.join(personality['traits']['positive'])}")
        print(f"  癖       : {personality['traits']['quirks'][0]}")

        if not dry_run:
            write_agent_yaml(codename, agent_data)

        history_records.append({
            "codename": codename,
            "role_category": template["role_category"],
            "name": personality["name"],
            "sub_role_label": personality["sub_role_label"],
            "traits": personality["traits"],
        })

    if not dry_run:
        append_history(generation_id, history_records)
        print(f"\n✓ config/agents/ 以下の6ファイルを更新しました")
        print(f"✓ logs/agent_history.md に履歴を記録しました")
    else:
        print(f"\n[DRY RUN] ファイルは変更されていません")

    print(f"{'='*50}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="エージェント人格ランダム生成スクリプト")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際にファイルを書き換えずにプレビューだけ表示する",
    )
    parser.add_argument(
        "--agent",
        type=str,
        choices=AGENT_CODENAMES,
        help="特定のエージェントだけ生成する（省略時は全員）",
    )
    args = parser.parse_args()

    if args.agent:
        # 単体生成
        AGENT_CODENAMES_backup = AGENT_CODENAMES[:]
        AGENT_CODENAMES.clear()
        AGENT_CODENAMES.append(args.agent)
        generate_all(dry_run=args.dry_run)
        AGENT_CODENAMES.clear()
        AGENT_CODENAMES.extend(AGENT_CODENAMES_backup)
    else:
        generate_all(dry_run=args.dry_run)
