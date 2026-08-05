from __future__ import annotations

import json

from aiohttp import web

from cato.ui import server


TOKEN = "cato-e2e-browser-harness-token"


class HarnessGateway:
    """Small deterministic agent behind Cato's real authenticated /ws route."""

    _cfg = None
    sessions: dict = {}

    def __init__(self) -> None:
        self.clients: set[web.WebSocketResponse] = set()

    def register_websocket(self, ws: web.WebSocketResponse) -> None:
        self.clients.add(ws)

    def unregister_websocket(self, ws: web.WebSocketResponse) -> None:
        self.clients.discard(ws)

    async def handle_ws_message(self, ws: web.WebSocketResponse, raw: str) -> None:
        payload = json.loads(raw)
        if payload.get("type") == "health":
            await ws.send_str(json.dumps({"type": "health", "status": "ok", "sessions": 0, "uptime": 1}))
            return
        if payload.get("type") != "message":
            await ws.send_str(json.dumps({"type": "error", "text": "Unsupported harness message"}))
            return
        await ws.send_str(json.dumps({
            "type": "response",
            "text": "Authenticated Cato harness response received.",
            "session_id": payload.get("session_id"),
            "channel": "web",
            "model": "authenticated-harness",
        }))


async def make_app() -> web.Application:
    server._DAEMON_TOKEN = TOKEN
    return await server.create_ui_app(HarnessGateway())


if __name__ == "__main__":
    web.run_app(make_app(), host="127.0.0.1", port=8080, print=None)
