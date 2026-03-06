"""Ollama LLM連携（ストリーミング / 一括取得）"""

import json
import os
import re
from typing import AsyncGenerator

import httpx

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
# タスク実行が長くなる場合に備えてタイムアウトを大きめに設定
_TIMEOUT = 180

# qwen3系など思考モード（CoT）対応モデルではthinkingを無効化してレスポンスを高速化
_DISABLE_THINKING = os.getenv("DISABLE_THINKING", "true").lower() != "false"

# コンテキストウィンドウサイズ（トークン数）。メモリ消費に直結する
_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))

# LLMに渡すテキストの最大文字数（超えたら末尾を切り捨て）
_CONTEXT_MAX_CHARS = int(os.getenv("CONTEXT_MAX_CHARS", "3000"))


def _strip_thinking(text: str) -> str:
    """<think>...</think> ブロックを除去（思考モードの出力クリーニング）"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _trim_content(text: str, max_chars: int = _CONTEXT_MAX_CHARS) -> str:
    """テキストを最大文字数に切り詰める。超えた場合は末尾を省略記号で置換"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n…（内容が長いため省略）"


async def stream_chat(
    system_prompt: str,
    user_message: str,
    model: str = OLLAMA_MODEL,
) -> AsyncGenerator[str, None]:
    """Ollamaにチャットリクエストを送り、トークンをストリーミングで返す"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _trim_content(system_prompt)},
            {"role": "user", "content": _trim_content(user_message)},
        ],
        "stream": True,
        # 思考モード（CoT）を無効化：qwen3系モデルの高速化
        "think": not _DISABLE_THINKING,
        "options": {
            # コンテキストウィンドウ上限。小さいほどVRAM/RAMを節約できる
            "num_ctx": _NUM_CTX,
        },
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue


async def chat_complete(
    system_prompt: str,
    user_message: str,
    model: str = OLLAMA_MODEL,
) -> str:
    """チャット結果をまとめて返す（非ストリーミング）"""
    tokens: list[str] = []
    async for token in stream_chat(system_prompt, user_message, model):
        tokens.append(token)
    # 思考モードが有効な場合でも <think> ブロックを除去してクリーンな回答のみ返す
    return _strip_thinking("".join(tokens))
