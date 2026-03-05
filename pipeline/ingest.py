#!/usr/bin/env python3
"""
ChromaDB データ投入スクリプト

data/processed/ 以下の .md / .txt ファイルを読み込み、
ChromaDB コレクション "knowledge" にベクトル化して格納する。

使い方:
  python3 pipeline/ingest.py                      # 全ファイル投入
  python3 pipeline/ingest.py --collection docs    # コレクション名を指定
  python3 pipeline/ingest.py --dry-run            # 実際には投入しない

前提:
  - ChromaDB が http://localhost:8000 で起動していること
  - data/processed/ にMarkdownまたはテキストファイルがあること
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Generator

# ChromaDB 接続設定
CHROMADB_HOST = os.getenv("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8000"))
DEFAULT_COLLECTION = "knowledge"

# データディレクトリ
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data" / "processed"

# ドキュメントの最大チャンクサイズ（文字数）
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """テキストを重複ありで分割する"""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        # 文末（。！？\n）で切れる位置を探す
        for sep in ("。", "！", "？", "\n\n"):
            last_sep = chunk.rfind(sep)
            if last_sep > chunk_size // 2:
                chunk = chunk[:last_sep + len(sep)]
                break
        chunks.append(chunk.strip())
        # 必ず前進する（len(chunk) <= overlap でも最低1文字進む）
        start += max(1, len(chunk) - overlap)

    return [c for c in chunks if c]  # 空チャンク除去


def iter_documents(data_dir: Path) -> Generator[tuple[str, str, dict], None, None]:
    """data/processed 以下のファイルをチャンクに分解してyieldする

    Returns:
        (doc_id, text, metadata) のタプル
    """
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".md", ".txt"):
            continue

        content = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not content:
            continue

        # 相対パスをIDのプレフィックスに使用
        rel_path = path.relative_to(data_dir)
        chunks = chunk_text(content)

        for i, chunk in enumerate(chunks):
            doc_id = f"{rel_path}#chunk{i}"
            metadata = {
                "source": str(rel_path),
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            yield doc_id, chunk, metadata


def ingest(collection_name: str = DEFAULT_COLLECTION, dry_run: bool = False) -> None:
    """ChromaDB にドキュメントを投入する"""
    # データディレクトリの確認
    if not DATA_DIR.exists():
        print(f"[ERROR] data/processed ディレクトリが存在しません: {DATA_DIR}")
        sys.exit(1)

    # ドキュメント収集
    docs = list(iter_documents(DATA_DIR))
    if not docs:
        print(f"[WARN] data/processed/ に投入対象ファイル (.md/.txt) がありません")
        print(f"       テキストファイルを data/processed/ に配置してから再実行してください")
        return

    print(f"\n{'='*50}")
    print(f"  ChromaDB データ投入")
    print(f"  コレクション: {collection_name}")
    print(f"  ドキュメント数: {len(docs)} チャンク")
    print(f"{'='*50}\n")

    for doc_id, text, meta in docs:
        preview = text[:60].replace("\n", " ")
        print(f"  [{meta['source']}] chunk{meta['chunk_index']}: {preview}...")

    if dry_run:
        print(f"\n[DRY RUN] ChromaDB への投入はスキップされました")
        return

    # chromadb インポート（実行時のみ）
    try:
        import chromadb
    except ImportError:
        print("[ERROR] chromadb がインストールされていません")
        print("        pip install chromadb  または Docker コンテナ内で実行してください")
        sys.exit(1)

    # ChromaDB 接続
    client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)

    # コレクション取得 or 作成
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},  # コサイン類似度
    )

    # 既存IDをチェックして重複をスキップ
    existing_ids = set(collection.get(include=[])["ids"])

    new_ids, new_docs, new_metas = [], [], []
    for doc_id, text, meta in docs:
        if doc_id in existing_ids:
            print(f"  [SKIP] {doc_id} は既に存在します")
            continue
        new_ids.append(doc_id)
        new_docs.append(text)
        new_metas.append(meta)

    if not new_ids:
        print("\n全ドキュメントが既にインデックス済みです。スキップします。")
        return

    # バッチ投入（ChromaDB の埋め込みはデフォルト: all-MiniLM-L6-v2）
    BATCH = 100
    for i in range(0, len(new_ids), BATCH):
        batch_ids = new_ids[i:i+BATCH]
        batch_docs = new_docs[i:i+BATCH]
        batch_metas = new_metas[i:i+BATCH]
        collection.add(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
        print(f"  投入完了: {i+len(batch_ids)}/{len(new_ids)} チャンク")

    total = collection.count()
    print(f"\n✓ コレクション '{collection_name}' の総ドキュメント数: {total}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChromaDB データ投入スクリプト")
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help=f"投入先コレクション名（デフォルト: {DEFAULT_COLLECTION}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイルを確認するだけで投入はしない",
    )
    args = parser.parse_args()

    ingest(collection_name=args.collection, dry_run=args.dry_run)
