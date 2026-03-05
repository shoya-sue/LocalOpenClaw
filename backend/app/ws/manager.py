"""WebSocket接続管理"""

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self._clients:
            self._clients.remove(ws)

    async def broadcast(self, event: dict):
        """全クライアントにイベントをブロードキャスト"""
        disconnected = []
        for ws in self._clients:
            try:
                await ws.send_json(event)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self._clients.remove(ws)

    async def send_to(self, ws: WebSocket, event: dict):
        await ws.send_json(event)

    @property
    def client_count(self) -> int:
        return len(self._clients)
