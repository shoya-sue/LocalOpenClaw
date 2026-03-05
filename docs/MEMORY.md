# LocalOpenClaw プロジェクトメモ

## プロジェクト概要
ローカルPC上で完全自律動作するAIエージェントチームシステム。
詳細: `docs/requirements.md`

## 確定スタック
- LLM: Ollama (Apple Silicon) + Qwen 3.5
- エージェントFW: OpenClaw (Docker)
- ベクトルDB: ChromaDB → Qdrant
- UI: Phaser.js + React (Pixelact UI)
- データ: LlamaIndex + 前処理Pythonスクリプト

## エージェント構成（6体）
リーダー・探偵・研究者・営業・秘書・エンジニア(土方)
最小MVP: リーダー・探偵・エンジニアの3体

## 人格継続の仕組み
- config/agents/*.yaml = 人格定義（Git管理）
- Dockerボリューム = Markdownメモリ（経験蓄積）
- 再ビルドしても人格・記憶は引き継がれる

## データ方針
- スクリプトで厳選したデータのみAIへ投入
- 小さなデータセットから始め段階的に拡大
- 全データソース対応（ファイル/Git/ブックマーク/カレンダー等）
