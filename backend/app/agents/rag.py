"""
RAG（Retrieval-Augmented Generation）検索モジュール

ChromaDBに投入済みの知識ベースを検索し、関連チャンクを返す。
エージェントの search_knowledge ツールから呼び出される。
"""

import logging
import os
from urllib.parse import urlparse

import chromadb

logger = logging.getLogger("uvicorn.error")

# ChromaDB接続設定（docker-compose.yml の CHROMADB_URL に従う）
_CHROMADB_URL = os.getenv("CHROMADB_URL", "http://chromadb:8000")

# デフォルトコレクション名（pipeline/ingest.py と揃える）
_DEFAULT_COLLECTION = "knowledge"

# 1クエリあたりの最大取得チャンク数
_MAX_RESULTS = int(os.getenv("RAG_MAX_RESULTS", "3"))

# 1チャンクあたりの最大表示文字数（num_ctx制約対応）
_CHUNK_PREVIEW_CHARS = int(os.getenv("RAG_CHUNK_PREVIEW_CHARS", "300"))


def _get_client() -> chromadb.HttpClient:
    """CHROMADB_URLからhostとportを解析してHttpClientを生成する"""
    parsed = urlparse(_CHROMADB_URL)
    host = parsed.hostname or "chromadb"
    port = parsed.port or 8000
    return chromadb.HttpClient(host=host, port=port)


async def search_knowledge(query: str, collection: str = _DEFAULT_COLLECTION, n_results: int = _MAX_RESULTS) -> str:
    """
    ChromaDBの知識ベースをクエリで検索し、関連チャンクを文字列で返す。

    Args:
        query: 検索クエリ（自然言語）
        collection: ChromaDBコレクション名（デフォルト: "knowledge"）
        n_results: 取得するチャンク数（デフォルト: 3）

    Returns:
        検索結果を整形した文字列。エラー時は [ERROR] プレフィックス付き文字列。
    """
    try:
        client = _get_client()
        col = client.get_collection(name=collection)
        results = col.query(
            query_texts=[query],
            n_results=min(n_results, _MAX_RESULTS),
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        if not documents:
            return f"[INFO] '{query}' に関連する知識が見つかりませんでした（コレクション: {collection}）"

        lines = [f"【検索結果: '{query}'】\n"]
        for i, (doc, meta) in enumerate(zip(documents, metadatas), 1):
            source = meta.get("source", "不明") if meta else "不明"
            preview = doc[:_CHUNK_PREVIEW_CHARS]
            if len(doc) > _CHUNK_PREVIEW_CHARS:
                preview += "…（省略）"
            lines.append(f"--- チャンク{i} (出典: {source}) ---\n{preview}\n")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("rag: search_knowledge 失敗 query=%s error=%s", query, e)
        return f"[ERROR] 知識ベース検索失敗: {e}"
