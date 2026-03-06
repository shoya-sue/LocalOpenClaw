"""
RAG（Retrieval-Augmented Generation）検索モジュール

ChromaDBに投入済みの知識ベースを検索し、関連チャンクを返す。
エージェントの search_knowledge ツールから呼び出される。

エージェント別コレクション:
  agent_{codename} コレクションにエージェントごとの知識を格納する。
  ReActAgent はデフォルトで自分自身のコレクションを検索する。
"""

import logging
import os
from urllib.parse import urlparse

import chromadb

logger = logging.getLogger("uvicorn.error")

# ChromaDB接続設定（docker-compose.yml の CHROMADB_URL に従う）
_CHROMADB_URL = os.getenv("CHROMADB_URL", "http://chromadb:8000")

# 共有知識ベースのコレクション名（pipeline/ingest.py と揃える）
DEFAULT_COLLECTION = "knowledge"
_DEFAULT_COLLECTION = DEFAULT_COLLECTION  # 後方互換

# エージェント別コレクションのプレフィックス
AGENT_COLLECTION_PREFIX = "agent_"

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


def agent_collection_name(codename: str) -> str:
    """エージェントのChromaDBコレクション名を返す（例: agent_researcher）"""
    return f"{AGENT_COLLECTION_PREFIX}{codename}"


def _build_agent_profile_text(agent: dict) -> str:
    """エージェント定義辞書からプロフィールテキストを構築する"""
    lines = [
        f"エージェント名: {agent.get('name', '')}",
        f"コードネーム: {agent.get('codename', '')}",
        f"役割カテゴリ: {agent.get('role_category', '')}",
        f"性格・ペルソナ:\n{agent.get('personality', '')}",
    ]
    sub_role = agent.get("sub_role", {})
    if sub_role:
        lines.append(
            f"サブロール: {sub_role.get('label', '')} - {sub_role.get('description', '')}"
        )
    tools = agent.get("tools", [])
    if tools:
        lines.append(f"利用可能ツール: {', '.join(tools)}")
    return "\n".join(lines)


async def ingest_agent_profiles(agents: list[dict]) -> None:
    """
    エージェント定義を各エージェント専用ChromaDBコレクションに投入する。

    コレクション名: agent_{codename}（例: agent_researcher）
    既に投入済みの場合はスキップ。

    Args:
        agents: AgentManager.get() の戻り値リスト（エージェント定義dict）
    """
    try:
        client = _get_client()
    except Exception as e:
        logger.warning("rag: ChromaDB接続失敗（スキップ）: %s", e)
        return

    for agent in agents:
        codename = agent.get("codename")
        if not codename:
            continue
        try:
            collection_name = agent_collection_name(codename)
            col = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            doc_id = f"{codename}_profile"
            existing = col.get(ids=[doc_id], include=[])
            if doc_id in existing["ids"]:
                logger.debug("rag: %s は既に投入済み（スキップ）", collection_name)
                continue
            profile_text = _build_agent_profile_text(agent)
            col.add(
                ids=[doc_id],
                documents=[profile_text],
                metadatas=[{"source": f"{codename}.yaml", "type": "agent_profile"}],
            )
            logger.info("rag: エージェントプロフィール投入完了 %s", collection_name)
        except Exception as e:
            logger.warning("rag: %s のプロフィール投入失敗: %s", codename, e)


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
