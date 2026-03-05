#!/bin/bash
# ============================================
# LocalOpenClaw セットアップスクリプト
# Phase 1: Ollama + ChromaDB MVP
# ============================================

set -e  # エラーが発生したら即停止

# --- カラー出力 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[ OK ]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERR ]${NC} $1"; exit 1; }

echo ""
echo "======================================"
echo "  LocalOpenClaw セットアップ"
echo "  Phase 1: Ollama + ChromaDB"
echo "======================================"
echo ""

# ============================================
# Step 1: 依存関係チェック
# ============================================
info "依存関係をチェック中..."

if ! command -v docker &>/dev/null; then
  error "Docker がインストールされていません。https://docs.docker.com/desktop/mac/ からインストールしてください。"
fi
success "Docker: $(docker --version | head -1)"

if ! docker compose version &>/dev/null; then
  error "Docker Compose v2 が必要です。Docker Desktop を最新版に更新してください。"
fi
success "Docker Compose: $(docker compose version | head -1)"

# Ollama チェック（ホスト側）
if command -v ollama &>/dev/null; then
  success "Ollama（ホスト）: $(ollama --version 2>/dev/null || echo '検出済み')"
  USE_HOST_OLLAMA=true
else
  warn "Ollama がホストにありません。Dockerコンテナ内のOllamaを使用します。"
  USE_HOST_OLLAMA=false
fi

# ============================================
# Step 2: モデル選択
# ============================================
echo ""
info "使用するLLMモデルを選択してください:"
echo ""
echo "  [1] qwen2.5:7b   — 軽量版 ( 約 4.7GB / RAM  8GB以上推奨 )"
echo "  [2] qwen2.5:14b  — 推奨版 ( 約 9.0GB / RAM 16GB以上推奨 ) ← デフォルト"
echo "  [3] qwen2.5:32b  — 高性能 ( 約19.0GB / RAM 32GB以上推奨 )"
echo "  [4] スキップ（後で手動ダウンロード）"
echo ""
read -rp "選択 [1-4, デフォルト: 2]: " MODEL_CHOICE

case "${MODEL_CHOICE:-2}" in
  1) OLLAMA_MODEL="qwen2.5:7b" ;;
  2) OLLAMA_MODEL="qwen2.5:14b" ;;
  3) OLLAMA_MODEL="qwen2.5:32b" ;;
  4) OLLAMA_MODEL="qwen2.5:14b"; SKIP_MODEL_PULL=true ;;
  *) OLLAMA_MODEL="qwen2.5:14b" ;;
esac

info "モデル: ${OLLAMA_MODEL}"

# docker-compose の環境変数として書き出す
echo "OLLAMA_MODEL=${OLLAMA_MODEL}" > .env
success ".env ファイルに OLLAMA_MODEL を書き込みました"

# ============================================
# Step 3: ディレクトリ確認
# ============================================
mkdir -p data/raw data/processed logs pipeline
success "ディレクトリ構成を確認しました"

# ============================================
# Step 4: Phase 1 コンテナ起動（Ollama + ChromaDB）
# ============================================
info "Phase 1 コンテナを起動中 (ollama + chromadb)..."
docker compose up -d ollama chromadb

# ============================================
# Step 5: Ollama 起動待機
# ============================================
info "Ollama の起動を待機中..."
RETRY=0
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
  RETRY=$((RETRY + 1))
  if [ $RETRY -ge 30 ]; then
    error "Ollama の起動タイムアウト。'docker compose logs ollama' で確認してください。"
  fi
  echo -n "."
  sleep 2
done
echo ""
success "Ollama が起動しました"

# ============================================
# Step 6: モデルダウンロード
# ============================================
if [ "${SKIP_MODEL_PULL}" != "true" ]; then
  if [ "${USE_HOST_OLLAMA}" = "true" ]; then
    info "ホストの Ollama でモデルをダウンロード中: ${OLLAMA_MODEL}"
    ollama pull "${OLLAMA_MODEL}"
    info "埋め込みモデルをダウンロード中: nomic-embed-text"
    ollama pull nomic-embed-text
  else
    info "コンテナ内でモデルをダウンロード中: ${OLLAMA_MODEL}"
    docker compose exec ollama ollama pull "${OLLAMA_MODEL}"
    docker compose exec ollama ollama pull nomic-embed-text
  fi
  success "モデルのダウンロードが完了しました"
else
  warn "モデルのダウンロードをスキップしました。後で以下を実行してください:"
  echo "    ollama pull ${OLLAMA_MODEL}"
  echo "    ollama pull nomic-embed-text"
fi

# ============================================
# Step 7: 接続テスト
# ============================================
info "接続テストを実行中..."

# Ollama テスト
if curl -sf http://localhost:11434/api/tags | grep -q '"models"'; then
  success "Ollama API 正常 (http://localhost:11434)"
else
  warn "Ollama API への接続に失敗しました。'docker compose logs ollama' を確認してください。"
fi

# ChromaDB テスト（起動に少し時間がかかる場合がある）
sleep 3
if curl -sf http://localhost:8000/api/v1/heartbeat > /dev/null 2>&1; then
  success "ChromaDB API 正常 (http://localhost:8000)"
else
  warn "ChromaDB がまだ起動中です。少し待ってから再確認してください。"
fi

# ============================================
# Step 8: エージェント人格の生成
# ============================================
if command -v python3 &>/dev/null && [ -f "pipeline/generate_agents.py" ]; then
  info "エージェント人格を生成中..."
  python3 pipeline/generate_agents.py
  success "エージェント人格の生成完了"
else
  warn "python3 が見つからないか generate_agents.py が存在しないため、人格生成をスキップしました。"
fi

# ============================================
# 完了
# ============================================
echo ""
echo "======================================"
echo -e "  ${GREEN}Phase 1 セットアップ完了！${NC}"
echo "======================================"
echo ""
echo "  起動中のサービス:"
echo "    Ollama   → http://localhost:11434"
echo "    ChromaDB → http://localhost:8000"
echo ""
echo "  次のフェーズ:"
echo "    Phase 2（バックエンド起動）:"
echo "      docker compose --profile phase2 up -d"
echo "      → バックエンド API: http://localhost:8080"
echo ""
echo "    Phase 3（フロントエンド起動）:"
echo "      docker compose --profile phase3 up -d"
echo "      → UI: http://localhost:5173"
echo ""
echo "  便利なコマンド:"
echo "    docker compose logs -f       # ログ確認"
echo "    docker compose ps            # 状態確認"
echo "    docker compose down          # 停止（データ保持）"
echo "    docker compose down -v       # 停止 + 全データ削除 ⚠️"
echo ""
