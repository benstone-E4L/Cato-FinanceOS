from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

# Executing this file by path otherwise prefers any globally installed Cato.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from cato.ui import server


class HarnessGateway:
    """Deterministic agent behind Cato's production HTTP and WebSocket routes."""

    _cfg = None
    _lanes: dict = {}
    sessions: dict = {}

    def __init__(self) -> None:
        self.clients: set[web.WebSocketResponse] = set()
        self._budget = SimpleNamespace(get_status=lambda: {
            "monthly_spend": 0,
            "monthly_cap": 20.0,
            "monthly_pct_remaining": 100,
            "monthly_calls": 0,
        })

    def register_websocket(self, ws: web.WebSocketResponse) -> None:
        self.clients.add(ws)

    def unregister_websocket(self, ws: web.WebSocketResponse) -> None:
        self.clients.discard(ws)

    def get_message_history(self, since_ts: int = 0) -> list:
        return []

    async def handle_ws_message(self, ws: web.WebSocketResponse, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await ws.send_json({"type": "error", "code": "invalid_json", "text": "Invalid JSON frame"})
            return
        if not isinstance(payload, dict):
            await ws.send_json({"type": "error", "code": "invalid_envelope", "text": "Expected an object"})
            return
        if payload.get("type") == "health":
            await ws.send_json({"type": "health", "status": "ok", "sessions": 0, "uptime": 1})
            return
        if payload.get("type") != "message":
            await ws.send_json({"type": "error", "code": "unsupported_type", "text": "Unsupported harness message"})
            return
        await ws.send_json({
            "type": "response",
            "text": "Authenticated Cato harness response received.",
            "session_id": payload.get("session_id"),
            "channel": "web",
            "model": "authenticated-harness",
        })


async def make_app(token: str | None = None) -> web.Application:
    runtime_token = token or os.environ.get("CATO_E2E_DAEMON_TOKEN", "")
    if not runtime_token:
        raise RuntimeError("CATO_E2E_DAEMON_TOKEN is required")
    server._DAEMON_TOKEN = runtime_token
    return await server.create_ui_app(HarnessGateway())


if __name__ == "__main__":
    runtime_port = int(os.environ.get("CATO_E2E_DAEMON_PORT", "0"))
    web.run_app(make_app(), host="127.0.0.1", port=runtime_port, print=None)
