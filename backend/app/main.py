"""
LocalOpenClaw バックエンド API v0.2.0 (Phase 2)
エージェント管理・タスク管理・オーケストレーション・WebSocket配信
"""

import os

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.agents.manager import AgentManager
from app.agents.memory import append_memory, list_memory_files, read_memory, write_memory
from app.llm.ollama import OLLAMA_BASE_URL, OLLAMA_MODEL, stream_chat
from app.orchestrator import Orchestrator
from app.tasks.manager import TaskManager
from app.ws.manager import ConnectionManager

app = FastAPI(title="LocalOpenClaw API", version="0.2.0")

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


# ==============================
# ヘルスチェック
# ==============================

@app.get("/health")
async def health():
    """サービス稼働確認"""
    return {
        "status": "ok",
        "version": "0.2.0",
        "model": OLLAMA_MODEL,
        "ws_clients": ws_manager.client_count,
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
