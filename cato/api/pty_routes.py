"""
cato/api/pty_routes.py — REST and WebSocket routes for interactive PTY sessions.

Endpoints:
- POST   /api/pty/sessions         — create session, body: { "cli": "claude"|"codex"|"gemini" }
- GET    /api/pty/sessions         — list sessions
- DELETE /api/pty/sessions/{id}    — terminate session
- POST   /api/pty/sessions/{id}/resize — body: { "cols", "rows" }
- GET    /ws/pty/{session_id}      — bidirectional terminal stream

WebSocket protocol (JSON):
- Client -> Server: { "type": "input", "data": "..." } | { "type": "resize", "cols": N, "rows": N }
- Server -> Client: { "type": "output", "data": "..." } | { "type": "session_event", "event": "started"|"died", ... }
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets

from aiohttp import web, WSMsgType

from cato.api.ws_auth import authenticate_ws
from cato.core.operator_ledger import (
    OperatorLedgerUnavailable,
    record_operator_action,
)
from cato.orchestrator.pty_session import (
    ALLOWED_PTY_CLIS,
    build_pty_cmd,
    create_session,
    get_session,
    list_sessions,
    pty_available,
    remove_idle_sessions,
    remove_session,
)
from cato.vault_bootstrap import safe_subprocess_environment

logger = logging.getLogger(__name__)

# Single source of truth, shared with the spawn helper so the route check and
# the spawn check can never drift apart. Enforced again in build_pty_cmd().
ALLOWED_CLIS = ALLOWED_PTY_CLIS


def _pty_env_for_cli(cli_name: str) -> dict[str, str]:
    """Build a non-secret PTY environment for a natively authenticated CLI."""
    env = safe_subprocess_environment()
    env["TERM"] = "xterm-256color"
    return env


async def post_sessions(request: web.Request) -> web.Response:
    """POST /api/pty/sessions — Create a new PTY session."""
    try:
        from cato.config import CatoConfig
        cfg = CatoConfig.load()
        if not getattr(cfg, "interactive_cli_enabled", True):
            return web.json_response(
                {"error": "Interactive CLI is disabled in config"},
                status=503,
            )
    except Exception:
        pass
    if not pty_available():
        return web.json_response(
            {"error": "PTY not available; install pywinpty (Windows) or ptyprocess (Unix)"},
            status=503,
        )
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    cli = (body.get("cli") or "").strip().lower()
    # FAIL CLOSED on an empty allowlist: no allowed CLIs means no PTY, never
    # "anything goes". Three earlier allowlists in this codebase read an empty
    # collection as "no restriction"; this one does not.
    if not ALLOWED_CLIS or cli not in ALLOWED_CLIS:
        return web.json_response(
            {"error": f"cli must be one of {sorted(ALLOWED_CLIS)}"},
            status=400,
        )
    try:
        from cato.config import CatoConfig
        cfg = CatoConfig.load()
        remove_idle_sessions(getattr(cfg, "pty_idle_timeout_sec", 0))
    except Exception:
        pass
    try:
        cmd = build_pty_cmd(cli)
    except (ValueError, FileNotFoundError) as e:
        return web.json_response({"error": str(e)}, status=400)
    session = create_session(cli)
    try:
        from cato.config import CatoConfig
        cfg = CatoConfig.load()
        cwd = body.get("cwd") or (getattr(cfg, "cli_session_cwd", None) or "").strip() or None
        cols = int(body.get("cols") or getattr(cfg, "pty_default_cols", 80))
        rows = int(body.get("rows") or getattr(cfg, "pty_default_rows", 24))
    except Exception:
        cwd = body.get("cwd") or None
        cols = int(body.get("cols", 80))
        rows = int(body.get("rows", 24))
    env = _pty_env_for_cli(cli)

    async def _start() -> None:
        session.start(cmd, env=env, cwd=cwd, cols=cols, rows=rows)

    # An interactive terminal cannot be approval-gated per keystroke, so it is
    # LEDGERED instead: the spawn is recorded INTENT-before-dispatch, and the
    # session dies rather than run unrecorded. See cato/core/operator_ledger.py.
    try:
        await record_operator_action(
            tool_name="pty.session.create",
            tool_input={"cli": cli, "cwd": cwd, "cols": cols, "rows": rows,
                        "session_id": session.session_id},
            session_id=session.session_id,
            run=_start,
            reversibility=0.9,
        )
    except OperatorLedgerUnavailable as e:
        remove_session(session.session_id)
        logger.error("PTY start refused for %s: %s", cli, e)
        return web.json_response({"error": str(e)}, status=503)
    except Exception as e:
        remove_session(session.session_id)
        logger.exception("PTY start failed for %s", cli)
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({
        "session_id": session.session_id,
        "cli": session.cli_name,
    })


async def get_sessions_list(request: web.Request) -> web.Response:
    """GET /api/pty/sessions — List active sessions."""
    try:
        from cato.config import CatoConfig
        cfg = CatoConfig.load()
        remove_idle_sessions(getattr(cfg, "pty_idle_timeout_sec", 0))
    except Exception:
        pass
    return web.json_response({"sessions": list_sessions()})


async def delete_session(request: web.Request) -> web.Response:
    """DELETE /api/pty/sessions/{session_id} — Terminate and remove session."""
    session_id = request.match_info.get("session_id")
    if not session_id:
        return web.json_response({"error": "session_id required"}, status=400)
    session = get_session(session_id)
    if not session:
        return web.json_response({"error": "Session not found"}, status=404)
    remove_session(session_id)
    return web.json_response({"ok": True})


async def post_resize(request: web.Request) -> web.Response:
    """POST /api/pty/sessions/{session_id}/resize — Set terminal size."""
    session_id = request.match_info.get("session_id")
    if not session_id:
        return web.json_response({"error": "session_id required"}, status=400)
    session = get_session(session_id)
    if not session:
        return web.json_response({"error": "Session not found"}, status=404)
    try:
        body = await request.json()
        cols = int(body.get("cols", 80))
        rows = int(body.get("rows", 24))
    except Exception:
        return web.json_response({"error": "Invalid JSON body with cols/rows"}, status=400)
    session.resize(cols, rows)
    return web.json_response({"ok": True})


async def pty_websocket_handler(request: web.Request) -> web.StreamResponse:
    """GET /ws/pty/{session_id} — Bidirectional terminal stream."""
    session_id = request.match_info.get("session_id")
    if not session_id:
        return web.json_response({"error": "session_id required"}, status=400)
    session = get_session(session_id)
    if not session:
        return web.json_response({"error": "Session not found"}, status=404)

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Authenticate — FAIL CLOSED. This is a live interactive terminal attached
    # to a real PTY subprocess, and it is exempt from the X-Cato-Token
    # middleware, so the check here is the only one. It used to be skipped
    # entirely when the app carried no daemon_token; see cato/api/ws_auth.py.
    if not await authenticate_ws(
        request, ws, endpoint="/ws/pty", envelope_timeout=2.0,
    ):
        return ws

    async def send_output(chunk: bytes) -> None:
        try:
            text = chunk.decode("utf-8", errors="replace")
            await ws.send_str(json.dumps({"type": "output", "data": text}))
        except Exception:
            pass

    async def send_session_event(event: str, **kwargs: object) -> None:
        try:
            await ws.send_str(json.dumps({"type": "session_event", "event": event, **kwargs}))
        except Exception:
            pass

    reader_task: asyncio.Task | None = None
    try:
        await send_session_event("started")
        reader_task = asyncio.create_task(_stream_pty_output(session, send_output))

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    obj = json.loads(msg.data)
                    if obj.get("type") == "input":
                        session.write(obj.get("data") or "")
                    elif obj.get("type") == "resize":
                        cols = int(obj.get("cols", 80))
                        rows = int(obj.get("rows", 24))
                        session.resize(cols, rows)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
    finally:
        if reader_task is not None:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
        if session and not session.is_alive:
            try:
                await send_session_event("died")
            except Exception:
                pass
        remove_session(session_id)
        try:
            await ws.close()
        except Exception:
            pass

    return ws


async def _stream_pty_output(session, send_output) -> None:
    """Forward PTY read_chunks to send_output until session dies."""
    try:
        async for chunk in session.read_chunks():
            await send_output(chunk)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


def register_routes(app: web.Application) -> None:
    """Register PTY REST and WebSocket routes."""
    app.router.add_post("/api/pty/sessions", post_sessions)
    app.router.add_get("/api/pty/sessions", get_sessions_list)
    app.router.add_delete("/api/pty/sessions/{session_id}", delete_session)
    app.router.add_post("/api/pty/sessions/{session_id}/resize", post_resize)
    app.router.add_get("/ws/pty/{session_id}", pty_websocket_handler)
    logger.info("PTY routes registered")
