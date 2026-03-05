"""Ollama LLM連携（ストリーミング / 一括取得）"""

import json
import os
from typing import AsyncGenerator

import httpx

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
# タスク実行が長くなる場合に備えてタイムアウトを大きめに設定
_TIMEOUT = 180


async def stream_chat(
    system_prompt: str,
    user_message: str,
    model: str = OLLAMA_MODEL,
) -> AsyncGenerator[str, None]:
    """Ollamaにチャットリクエストを送り、トークンをストリーミングで返す"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": True,
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
    return "".join(tokens)
