"""エージェントのメモリファイル読み書き（/workspace/{codename}/memory/）"""

import os
from pathlib import Path

AGENT_MEMORY_PATH = Path(os.getenv("AGENT_MEMORY_PATH", "/workspace"))


def read_memory(codename: str, filename: str) -> str:
    """エージェントのメモリファイルを読み込む。存在しなければ空文字を返す"""
    memory_file = AGENT_MEMORY_PATH / codename / "memory" / filename
    if not memory_file.exists():
        return ""
    return memory_file.read_text(encoding="utf-8")


def write_memory(codename: str, filename: str, content: str):
    """エージェントのメモリファイルを上書きする"""
    memory_dir = AGENT_MEMORY_PATH / codename / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / filename).write_text(content, encoding="utf-8")


def append_memory(codename: str, filename: str, content: str):
    """エージェントのメモリファイルに追記する"""
    existing = read_memory(codename, filename)
    write_memory(codename, filename, existing + "\n" + content if existing else content)


def list_memory_files(codename: str) -> list[str]:
    """エージェントのメモリファイル一覧を返す"""
    memory_dir = AGENT_MEMORY_PATH / codename / "memory"
    if not memory_dir.exists():
        return []
    return [f.name for f in sorted(memory_dir.glob("*.md"))]
