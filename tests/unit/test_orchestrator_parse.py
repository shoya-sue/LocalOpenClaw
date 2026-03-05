"""Orchestrator._parse_json 単体テスト（stdlib のみ）"""
import sys
import os
import json
import unittest

# fastapi をモック（importだけ通ればよい）
import types

# fastapi モックを sys.modules に注入
_mock_fastapi = types.ModuleType("fastapi")
_mock_fastapi.FastAPI = object
_mock_fastapi.WebSocket = object
_mock_fastapi.WebSocketDisconnect = Exception
sys.modules.setdefault("fastapi", _mock_fastapi)
sys.modules.setdefault("fastapi.middleware", types.ModuleType("fastapi.middleware"))
sys.modules.setdefault("fastapi.middleware.cors", types.ModuleType("fastapi.middleware.cors"))
_mock_cors = types.ModuleType("fastapi.middleware.cors")
_mock_cors.CORSMiddleware = object
sys.modules["fastapi.middleware.cors"] = _mock_cors

# httpx モック
_mock_httpx = types.ModuleType("httpx")
_mock_httpx.AsyncClient = object
sys.modules.setdefault("httpx", _mock_httpx)

# yaml モック
_mock_yaml = types.ModuleType("yaml")
_mock_yaml.safe_load = lambda s: {}
sys.modules.setdefault("yaml", _mock_yaml)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))

from app.orchestrator import Orchestrator


class TestParseJson(unittest.TestCase):
    def test_valid_json(self):
        text = '{"reasoning": "ok", "tasks": []}'
        result = Orchestrator._parse_json(text)
        self.assertEqual(result["reasoning"], "ok")

    def test_json_in_code_block(self):
        text = '```json\n{"tasks": [{"agent": "detective", "task": "調査"}]}\n```'
        result = Orchestrator._parse_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["tasks"]), 1)

    def test_json_embedded_in_text(self):
        text = 'はい、{"tasks": [], "direct_response": "こんにちは"} です。'
        result = Orchestrator._parse_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["direct_response"], "こんにちは")

    def test_invalid_json_returns_none(self):
        result = Orchestrator._parse_json("全く JSON ではないテキストです。")
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        result = Orchestrator._parse_json("")
        self.assertIsNone(result)

    def test_nested_json(self):
        data = {
            "reasoning": "複雑な依頼",
            "tasks": [
                {"agent": "detective", "task": "情報を調べる"},
                {"agent": "researcher", "task": "分析する"},
            ],
            "summary_needed": True,
        }
        result = Orchestrator._parse_json(json.dumps(data))
        self.assertEqual(len(result["tasks"]), 2)
        self.assertTrue(result["summary_needed"])


if __name__ == "__main__":
    unittest.main()
