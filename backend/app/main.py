"""
LocalOpenClaw バックエンド API v0.4.0
エージェント管理・タスク管理・オーケストレーション・WebSocket配信
完全自律動作: 自律ループ + トリガーワード連鎖 + 成果物自動生成
"""

import asyncio
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.agents.manager import AgentManager
from app.agents.memory import append_memory, list_memory_files, read_memory, write_memory
from app.autonomous import AutonomousLoop
from app.llm.ollama import OLLAMA_BASE_URL, OLLAMA_MODEL, stream_chat
from app.orchestrator import Orchestrator
from app.tasks.manager import TaskManager
from app.ws.manager import ConnectionManager

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="LocalOpenClaw API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================
# シングルトン初期化
# ==============================
ws_manager = ConnectionManager()
agent_manager = AgentManager()
task_manager = TaskManager()
orchestrator = Orchestrator(agent_manager, task_manager, ws_manager)

_AUTONOMOUS_INTERVAL = int(os.environ.get("AUTONOMOUS_INTERVAL", "180"))
_OUTPUT_DIR = Path(os.environ.get("DATA_DIR", "/data")) / "output"
autonomous_loop = AutonomousLoop(orchestrator, ws_manager, _OUTPUT_DIR, _AUTONOMOUS_INTERVAL)


# ==============================
# ヘルスチェック
# ==============================

@app.get("/health")
async def health():
    """サービス稼働確認"""
    return {
        "status": "ok",
        "version": "0.4.0",
        "model": OLLAMA_MODEL,
        "ws_clients": ws_manager.client_count,
        "autonomous": autonomous_loop.status,
    }


@app.get("/health/ollama")
async def health_ollama():
    """Ollama接続確認"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
            models = [m["name"] for m in resp.json().get("models", [])]
            return {"status": "ok", "models": models}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# ==============================
# エージェント
# ==============================

@app.get("/agents")
async def list_agents():
    """全エージェント一覧（状態付き）"""
    return {"agents": agent_manager.list_all()}


@app.get("/agents/{codename}")
async def get_agent(codename: str):
    """特定エージェントの詳細"""
    agent = agent_manager.get(codename)
    if not agent:
        return {"error": f"Agent '{codename}' not found"}
    return {**agent, "status": agent_manager.get_status(codename)}


@app.post("/agents/reload")
async def reload_agents():
    """エージェント定義をYAMLから再読み込みする"""
    agent_manager.reload()
    return {"reloaded": agent_manager.codenames()}


# ==============================
# エージェントメモリ
# ==============================

@app.get("/agents/{codename}/memory")
async def get_memory(codename: str, filename: str = "memory.md"):
    content = read_memory(codename, filename)
    return {"codename": codename, "filename": filename, "content": content}


@app.get("/agents/{codename}/memory/files")
async def list_memory(codename: str):
    return {"codename": codename, "files": list_memory_files(codename)}


@app.put("/agents/{codename}/memory")
async def put_memory(codename: str, filename: str, content: str):
    write_memory(codename, filename, content)
    return {"codename": codename, "filename": filename, "updated": True}


@app.post("/agents/{codename}/memory/append")
async def post_memory_append(codename: str, filename: str, content: str):
    append_memory(codename, filename, content)
    return {"codename": codename, "filename": filename, "appended": True}


# ==============================
# タスク
# ==============================

@app.get("/tasks")
async def list_tasks():
    return {"tasks": task_manager.list_all()}


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    task = task_manager.get(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}
    return task.to_dict()


@app.get("/tasks/agent/{codename}")
async def list_agent_tasks(codename: str):
    return {"tasks": task_manager.list_by_agent(codename)}


# ==============================
# チャット
# ==============================

@app.get("/chat/{agent_codename}")
async def chat_get(agent_codename: str, message: str):
    """単一エージェントとの直接チャット（REST / 非ストリーミング）"""
    agent = agent_manager.get(agent_codename)
    system_prompt = (
        agent.get("personality", f"あなたは{agent_codename}です。") if agent else ""
    )
    tokens: list[str] = []
    async for token in stream_chat(system_prompt, message):
        tokens.append(token)
    return {"agent": agent_codename, "response": "".join(tokens)}


@app.post("/orchestrate")
async def orchestrate(message: str):
    """Leaderがチームをオーケストレーションして回答（REST）"""
    result = await orchestrator.handle(message)
    return result


# ==============================
# Webhook（外部イベントからの自律起動）
# ==============================

class WebhookPayload(BaseModel):
    message: str


@app.post("/webhook")
async def webhook(payload: WebhookPayload):
    """外部トリガーからOrchestratorを起動する（CI/CD・cron・他サービス連携）"""
    result = await orchestrator.handle(payload.message)
    return result


# ==============================
# Watchdog（data/ ディレクトリ監視 → 自律動作）
# ==============================

_DEBOUNCE_SEC = 2.0  # 同一ファイルの連続イベントを無視する秒数


class _DataDirHandler(FileSystemEventHandler):
    """data/ 配下にファイルが作成・変更されたら内容をOrchestrator に投げる"""

    def __init__(self, loop: asyncio.AbstractEventLoop, orch: Orchestrator):
        self._loop = loop
        self._orch = orch
        # {path: last_trigger_time} — デバウンス用
        self._last_triggered: dict[str, float] = {}

    def on_created(self, event):
        if event.is_directory:
            return
        self._trigger(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._trigger(event.src_path)

    def _trigger(self, path: str):
        now = time.monotonic()
        # デバウンス: 同一ファイルが _DEBOUNCE_SEC 以内に再トリガーされたら無視
        if now - self._last_triggered.get(path, 0) < _DEBOUNCE_SEC:
            return
        self._last_triggered[path] = now
        try:
            content = Path(path).read_text(encoding="utf-8").strip()
            if not content:
                return
            logger.info("watchdog: %s → Orchestrator 起動", path)
            asyncio.run_coroutine_threadsafe(self._orch.handle(content), self._loop)
        except Exception as exc:
            logger.warning("watchdog trigger failed: %s", exc)


@app.on_event("startup")
async def _startup():
    """アプリ起動時に watchdog と自律ループを開始する"""
    # docker-compose で ./data:/data にマウントされているため /data を優先
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_event_loop()
    handler = _DataDirHandler(loop, orchestrator)
    observer = Observer()
    observer.schedule(handler, str(data_dir), recursive=False)
    observer.start()
    app.state.watchdog = observer
    logger.info("watchdog: data/ ディレクトリの監視を開始しました")

    autonomous_loop.start()


@app.on_event("shutdown")
async def _shutdown():
    """アプリ終了時に watchdog と自律ループを停止する"""
    autonomous_loop.stop()

    observer: Observer | None = getattr(app.state, "watchdog", None)
    if observer:
        observer.stop()
        observer.join()
        logger.info("watchdog: 停止しました")


# ==============================
# 自律ループ制御
# ==============================

@app.get("/autonomous/status")
async def autonomous_status():
    """自律ループの稼働状態を返す"""
    return autonomous_loop.status


@app.post("/autonomous/start")
async def autonomous_start():
    """自律ループを手動起動する"""
    if not autonomous_loop._running:
        autonomous_loop.start()
    return autonomous_loop.status


@app.post("/autonomous/stop")
async def autonomous_stop():
    """自律ループを手動停止する"""
    autonomous_loop.stop()
    return autonomous_loop.status


# ==============================
# WebSocket
# ==============================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """フロントエンドとのリアルタイム接続

    受け付けるイベント:
      {"type": "chat",        "agent": "leader",   "message": "..."}
      {"type": "orchestrate",                       "message": "..."}
    """
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "chat")

            if msg_type == "chat":
                agent_code = data.get("agent", "leader")
                message = data.get("message", "")
                agent = agent_manager.get(agent_code)
                system_prompt = (
                    agent.get("personality", f"あなたは{agent_code}です。") if agent else ""
                )
                async for token in stream_chat(system_prompt, message):
                    await ws.send_json({"type": "token", "agent": agent_code, "content": token})
                await ws.send_json({"type": "done", "agent": agent_code})

            elif msg_type == "orchestrate":
                message = data.get("message", "")
                result = await orchestrator.handle(message)
                await ws.send_json({"type": "orchestration_result", **result})

    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
