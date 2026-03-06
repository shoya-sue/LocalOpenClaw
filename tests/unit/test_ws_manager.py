"""ConnectionManager 単体テスト"""
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

# fastapi.WebSocket はテスト環境にないためモック
import types
_fastapi_mock = types.ModuleType("fastapi")
_fastapi_mock.WebSocket = MagicMock
sys.modules.setdefault("fastapi", _fastapi_mock)

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

from app.ws.manager import ConnectionManager


class TestConnectionManager(unittest.IsolatedAsyncioTestCase):
    def _make_ws(self) -> MagicMock:
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    async def test_connect_accepts_and_adds_client(self):
        mgr = ConnectionManager()
        ws = self._make_ws()
        await mgr.connect(ws)
        ws.accept.assert_called_once()
        self.assertEqual(mgr.client_count, 1)

    async def test_disconnect_removes_client(self):
        mgr = ConnectionManager()
        ws = self._make_ws()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        self.assertEqual(mgr.client_count, 0)

    def test_disconnect_noop_for_unknown_client(self):
        mgr = ConnectionManager()
        ws = self._make_ws()
        # 接続していないクライアントを disconnect しても例外を起こさない
        mgr.disconnect(ws)
        self.assertEqual(mgr.client_count, 0)

    async def test_broadcast_sends_to_all_clients(self):
        mgr = ConnectionManager()
        ws1, ws2 = self._make_ws(), self._make_ws()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        await mgr.broadcast({"type": "test"})
        ws1.send_json.assert_called_once_with({"type": "test"})
        ws2.send_json.assert_called_once_with({"type": "test"})

    async def test_broadcast_removes_disconnected_client(self):
        mgr = ConnectionManager()
        ws = self._make_ws()
        ws.send_json = AsyncMock(side_effect=Exception("断線"))
        await mgr.connect(ws)
        self.assertEqual(mgr.client_count, 1)
        await mgr.broadcast({"type": "test"})
        # 送信失敗したクライアントは自動削除される
        self.assertEqual(mgr.client_count, 0)

    async def test_client_count_reflects_connections(self):
        mgr = ConnectionManager()
        self.assertEqual(mgr.client_count, 0)
        ws1, ws2 = self._make_ws(), self._make_ws()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        self.assertEqual(mgr.client_count, 2)
        mgr.disconnect(ws1)
        self.assertEqual(mgr.client_count, 1)


if __name__ == "__main__":
    unittest.main()
