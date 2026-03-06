"""
Web検索モジュール

DuckDuckGo Search API（APIキー不要）を使い、エージェントがWebで
リサーチ・技術情報収集を自律的に行えるようにする。
"""

import logging
import os

logger = logging.getLogger("uvicorn.error")

# 1クエリあたりの最大取得件数
_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "3"))

# 1件あたりの最大表示文字数（num_ctx制約対応）
_SNIPPET_MAX_CHARS = int(os.getenv("WEB_SEARCH_SNIPPET_CHARS", "200"))


async def web_search(query: str, max_results: int = _MAX_RESULTS) -> str:
    """
    DuckDuckGo でWeb検索し、タイトル・URL・スニペットを返す。

    Args:
        query: 検索クエリ（英語推奨）
        max_results: 取得する検索結果件数

    Returns:
        整形済みの検索結果文字列。エラー時は [ERROR] プレフィックス付き文字列。
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "[ERROR] duckduckgo-search がインストールされていません（pip install duckduckgo-search）"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        logger.warning("web_search: 検索失敗 query=%s error=%s", query, e)
        return f"[ERROR] Web検索失敗: {e}"

    if not results:
        return f"[INFO] '{query}' の検索結果が見つかりませんでした"

    lines = [f"【Web検索結果: '{query}'】\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "タイトルなし")
        url = r.get("href", "")
        body = r.get("body", "")
        snippet = body[:_SNIPPET_MAX_CHARS]
        if len(body) > _SNIPPET_MAX_CHARS:
            snippet += "…"
        lines.append(f"--- {i}. {title} ---\nURL: {url}\n{snippet}\n")

    logger.info("web_search: query=%s results=%d件", query, len(results))
    return "\n".join(lines)
