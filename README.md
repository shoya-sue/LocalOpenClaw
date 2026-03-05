# LocalOpenClaw

ローカル環境で完結するマルチエージェントAIシステム。
Ollama（ローカルLLM）＋ ChromaDB（RAG）＋ FastAPI バックエンド ＋ Phaser.js ピクセルアートUIで構成される。

---

## 現在の動作状況

| コンポーネント | 状態 | URL |
|---|---|---|
| フロントエンド (Vite + React + Phaser.js) | 稼働中 | http://localhost:5173 |
| バックエンド API (FastAPI) | 稼働中 | http://localhost:8080 |
| Ollama (ローカルLLM) | 稼働中 | http://localhost:11434 |
| ChromaDB (ベクトルDB) | 稼働中 | http://localhost:8000 |

### 使用モデル

| モデル | 状態 | 備考 |
|---|---|---|
| `qwen3:1.7b` | **デフォルト（稼働中）** | メモリ効率重視。約1GB |
| `qwen3:8b` | ダウンロード済み・要メモリ確保 | 6.1GB必要。RAM不足時はロード不可 |
| `qwen2.5:14b` | ダウンロード済み | 9GB必要 |
| `qwen2.5:0.5b` | ダウンロード済み | テスト用軽量版 |

> **モデル切替**: `OLLAMA_MODEL=qwen3:8b docker compose --profile phase3 up -d backend`

---

## Tech Stack

- **フロントエンド**: React 18 + Vite + Phaser.js 3（ピクセルアートオフィスUI）
- **バックエンド**: FastAPI + Python 3.11 + WebSocket
- **LLMランタイム**: Ollama（Apple Silicon Metal GPU加速）
- **ベクトルDB**: ChromaDB（RAG用）
- **コンテナ**: Docker Compose（プロファイル段階起動）

---

## プロジェクト構成

```
LocalOpenClaw/
├── backend/              # FastAPI バックエンド
│   ├── app/              # エージェント基盤・WSエンドポイント
│   ├── config/           # エージェント設定ミラー
│   ├── Dockerfile
│   └── requirements.txt
├── config/               # エージェント定義・システム設定
│   ├── agents/           # 各エージェントのYAML定義
│   ├── templates/        # プロンプトテンプレート
│   └── openclaw.json     # システム設定
├── frontend/             # React + Phaser.js フロントエンド
│   └── src/
│       ├── App.jsx               # ルート。WS管理・状態統合
│       ├── components/
│       │   └── ControlPanel.jsx  # チャットUI・タスクキュー
│       └── game/
│           ├── PhaserGame.jsx    # Phaserラッパー（React統合）
│           └── scenes/
│               └── OfficeScene.js  # ピクセルアートオフィス
├── pipeline/             # データ取り込み（RAG用）
├── tests/                # テスト
├── docs/                 # ドキュメント
├── data/                 # データ（.gitignore対象）
├── logs/                 # ログ（.gitignore対象）
└── docker-compose.yml
```

---

## エージェント構成

| コードネーム | 名前 | 役割 |
|---|---|---|
| `leader` | ゼネラル | オーケストレーター。タスク割り振り・統合 |
| `detective` | シャーロック | 情報収集・フィールド調査 |
| `researcher` | 究 | 検証・分析 |
| `engineer` | 匠 | AI実装（LLM・RAG・エージェント） |
| `sales` | — | セールス |
| `secretary` | — | 秘書 |

---

## 起動手順

### Phase 1: インフラのみ（Ollama + ChromaDB）

```bash
docker compose up -d
```

### Phase 2: バックエンド追加

```bash
docker compose --profile phase2 up -d
```

### Phase 3: フロントエンド含む全起動

```bash
docker compose --profile phase3 up -d
```

### モデルのダウンロード（初回）

```bash
docker exec local-openclaw-ollama ollama pull qwen3:1.7b
```

---

## WebSocket イベント仕様

バックエンド `/ws` エンドポイントは以下のイベントを送受信する。

### クライアント → サーバー

```jsonc
// オーケストレーションモード（Leader がチームに割り振る）
{ "type": "orchestrate", "message": "指示内容" }

// 直接チャットモード（特定エージェントと会話）
{ "type": "chat", "agent": "leader", "message": "メッセージ" }
```

### サーバー → クライアント

| イベント | 説明 |
|---|---|
| `token` | LLMストリーミングトークン |
| `done` | 応答完了 |
| `agent_status` | エージェント状態変化（idle / thinking / busy） |
| `task_created` | タスク生成 |
| `agent_thinking` | タスク実行開始 |
| `task_done` | タスク完了 |
| `orchestration_result` | オーケストレーション結果（全エージェント統合） |

---

## ヘルスチェック

```bash
# バックエンド・モデル確認
curl http://localhost:8080/health

# Ollamaモデル一覧
curl http://localhost:8080/health/ollama

# エージェント一覧
curl http://localhost:8080/agents
```

---

## 注意事項

- `agent_memory` ボリュームはエージェントの記憶が格納される重要データ。削除禁止。
- `qwen3:8b` は約6.1GBのRAMが必要。メモリ不足の場合は `qwen3:1.7b` を使用。
- `.env.production` は設定でアクセス禁止（secrets管理）。
