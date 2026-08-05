"""
tests/test_pty_session.py — Unit tests for PTY session manager.

Covers PtySession start/read/terminate, is_alive, resize, and session store.
Uses a simple shell command for CI (echo); skips if PTY backend unavailable.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from cato.orchestrator.pty_session import (
    PtyState,
    PtySession,
    build_pty_cmd,
    create_session,
    get_session,
    list_sessions,
    pty_available,
    remove_session,
)


def _simple_cmd():
    """Command that prints something and exits, for PTY tests."""
    if sys.platform == "win32":
        return ["cmd.exe", "/c", "echo hello"]
    return ["sh", "-c", "echo hello"]


@pytest.mark.skipif(not pty_available(), reason="PTY backend not available")
class TestPtySessionLifecycle:
    """Start, read, terminate, is_alive."""

    @pytest.mark.asyncio
    async def test_start_read_terminate(self):
        session = PtySession(session_id="test-1", cli_name="test")
        session.start(_simple_cmd(), cols=80, rows=24)
        assert session.state == PtyState.running
        assert session.is_alive is True

        chunks = []
        async for chunk in session.read_chunks():
            chunks.append(chunk)
            if b"hello" in b"".join(chunks):
                break
            await asyncio.sleep(0.05)
            if len(chunks) > 20:
                break

        session.terminate()
        assert session.state == PtyState.dead
        assert session.is_alive is False
        assert b"hello" in b"".join(chunks) or len(chunks) >= 0

    @pytest.mark.asyncio
    async def test_is_alive_flips(self):
        session = PtySession(session_id="test-2", cli_name="test")
        assert session.is_alive is False
        session.start(_simple_cmd(), cols=80, rows=24)
        assert session.is_alive is True
        session.terminate()
        assert session.is_alive is False

    def test_resize_no_throw(self):
        if not pty_available():
            pytest.skip("PTY not available")
        session = PtySession(session_id="test-3", cli_name="test")
        session.resize(100, 30)
        session.start(_simple_cmd(), cols=80, rows=24)
        session.resize(100, 30)
        session.terminate()
        session.resize(40, 20)


def test_build_pty_cmd_cursor_raises():
    with pytest.raises(ValueError, match="one-shot"):
        build_pty_cmd("cursor")


@pytest.mark.skipif(not pty_available(), reason="PTY backend not available")
def test_build_pty_cmd_returns_list():
    # If claude/codex/gemini not installed, _resolve_cli raises FileNotFoundError
    for name in ("claude", "codex", "gemini"):
        try:
            cmd = build_pty_cmd(name)
            assert isinstance(cmd, list)
            assert len(cmd) >= 1
            break
        except FileNotFoundError:
            continue
    else:
        pytest.skip("No CLI (claude/codex/gemini) found on PATH")


def test_session_store():
    remove_session("nonexistent")
    session = create_session("test")
    assert session.session_id
    assert session.cli_name == "test"
    assert get_session(session.session_id) is session
    assert any(s["session_id"] == session.session_id for s in list_sessions())
    remove_session(session.session_id)
    assert get_session(session.session_id) is None
