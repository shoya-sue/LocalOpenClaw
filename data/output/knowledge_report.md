# LocalOpenClaw 知識レポート

## システム概要
LocalOpenClawはローカルLLMを活用したオープンソースのマルチエージェントシステムです。
インターネット接続なしに完全ローカルで動作し、プライバシーを保護しながら高度なAI処理が可能です。

## エージェント構成
- **leader**: チームを統率し、タスクを振り分けるリーダーエージェント
- **detective**: フィールド調査・情報収集を担当する探偵エージェント
- **researcher**: データ分析・考察を行う研究者エージェント
- **engineer**: 実装・技術解説を担当するエンジニアエージェント
- **sales**: 提案・説明を担当する営業エージェント
- **secretary**: 整理・要約を担当する秘書エージェント

## 主要機能
- ReActエンジンによる自律ループ（Thought → Action → Observation）
- エージェント間フィードバック（前エージェントの結果を次へ渡す）
- Watchdogによるファイル監視と自動起動

## 技術スタック
Python/FastAPI、Ollama LLM（qwen3:1.7b）、ChromaDB、WebSocket、React/Vite
