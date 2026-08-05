"""
cato/api/ws_auth.py — fail-closed authentication for the WebSocket endpoints
that reach a subprocess.

WHY THIS MODULE EXISTS
----------------------
``/ws/coding-agent/{task_id}`` and ``/ws/pty/{session_id}`` are both listed in
``cato.ui.server._TOKEN_EXEMPT_WS_PREFIXES``: the ``X-Cato-Token`` middleware
deliberately does NOT check them, because a browser ``WebSocket`` cannot set a
request header, so those two handlers authenticate themselves after the
upgrade (header, ``?token=`` query param, or a first-message ``auth`` envelope).

Both handlers used to read the expected token as::

    daemon_token = request.app.get("daemon_token", "")
    if daemon_token:
        ...check...

— i.e. an application assembled without a ``daemon_token`` key, or with an
empty one, served a completely UNAUTHENTICATED subprocess spawn: the coding
agent fans out to the claude/codex/gemini/cursor CLIs, and the PTY endpoint is
a live interactive terminal.

That is the fail-open-on-empty defect this codebase has now shipped four
times (the genesis allowlist, a telegram command allowlist, the scheduler,
and here). "No token configured" now means "no connection", never "no
checking". There is no configuration value that turns this off.

This module authenticates only; it is NOT a second gate. Authorization for
model-originated actions still belongs to
:meth:`cato.agent_loop.AgentLoop.guarded_action`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Any, Awaitable, Callable, Optional

from aiohttp import WSMsgType, web

logger = logging.getLogger(__name__)

#: WebSocket close code used for every authentication refusal here.
WS_UNAUTHORIZED = 4401


def expected_ws_token(request: web.Request) -> str:
    """Return the daemon token this app expects, or "" when it has none."""
    return str(request.app.get("daemon_token") or "").strip()


async def _token_from_first_message(
    ws: web.WebSocketResponse, timeout: float,
) -> str:
    """Read one frame and return ``token`` from an ``{"type":"auth"}`` envelope."""
    try:
        first = await asyncio.wait_for(ws.receive(), timeout=timeout)
    except asyncio.TimeoutError:
        return ""
    except Exception:  # pragma: no cover — transport teardown races
        return ""
    if first.type != WSMsgType.TEXT:
        return ""
    try:
        parsed = json.loads(first.data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ""
    if not isinstance(parsed, dict) or parsed.get("type") != "auth":
        return ""
    return str(parsed.get("token") or "")


async def authenticate_ws(
    request: web.Request,
    ws: web.WebSocketResponse,
    *,
    endpoint: str,
    envelope_timeout: float = 5.0,
    on_deny: Optional[Callable[[str], Awaitable[Any]]] = None,
) -> bool:
    """Authenticate an already-prepared WebSocket. True means proceed.

    FAIL CLOSED in both directions:

    * an app with no ``daemon_token`` refuses every connection — it never
      degrades to "unauthenticated is fine";
    * a missing, malformed or mismatched token refuses the connection.

    On refusal the socket is closed with :data:`WS_UNAUTHORIZED` and the
    caller must return immediately. ``on_deny`` lets a handler emit its own
    protocol-shaped error frame first.
    """
    expected = expected_ws_token(request)
    if not expected:
        logger.error(
            "%s refused: this application has no daemon_token configured, so "
            "the connection cannot be authenticated. An unauthenticated "
            "subprocess surface is exactly the failure this check exists to "
            "prevent — configure the daemon token.",
            endpoint,
        )
        if on_deny is not None:
            try:
                await on_deny("Unauthorized: daemon token not configured")
            except Exception:  # pragma: no cover — best effort
                pass
        await ws.close(code=WS_UNAUTHORIZED, message=b"Unauthorized")
        return False

    token = (
        request.headers.get("X-Cato-Token", "")
        or request.rel_url.query.get("token", "")
    )
    if not token:
        token = await _token_from_first_message(ws, envelope_timeout)

    if not token or not secrets.compare_digest(token, expected):
        logger.warning("%s refused: missing or invalid X-Cato-Token.", endpoint)
        if on_deny is not None:
            try:
                await on_deny("Unauthorized")
            except Exception:  # pragma: no cover — best effort
                pass
        await ws.close(code=WS_UNAUTHORIZED, message=b"Unauthorized")
        return False

    return True
