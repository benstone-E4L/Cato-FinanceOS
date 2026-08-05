"""
tests/test_cursor_subagent.py

Tests for:
  - invoke_cursor_cli  (Cursor Agent CLI invoker — real headless implementation)
  - _resolve_cursor_agent (binary locator)
  - invoke_subagent    (backend dispatcher)
  - CatoConfig subagent fields

Live test result (2026-03-07, updated):
  The ``agent`` CLI (cursor-agent v2026.02.27) supports ``--print`` mode for
  headless non-interactive output.  invoke_cursor_cli now uses this via
  node.exe + index.js directly (bypassing the .cmd/.ps1 launcher which hangs
  without a TTY).  ``agent login`` must be run once to authenticate.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.orchestrator.cli_invoker import (
    _resolve_cursor_agent,
    invoke_cursor_cli,
    invoke_subagent,
)


# ------------------------------------------------------------------ #
# _resolve_cursor_agent — binary locator                             #
# ------------------------------------------------------------------ #

def test_resolve_cursor_agent_not_installed(tmp_path, monkeypatch):
    """Raises FileNotFoundError when LOCALAPPDATA has no cursor-agent dir."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="cursor-agent not installed"):
        _resolve_cursor_agent()


def test_resolve_cursor_agent_empty_versions(tmp_path, monkeypatch):
    """Raises FileNotFoundError when versions directory exists but is empty."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "cursor-agent" / "versions").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="versions directory is empty"):
        _resolve_cursor_agent()


def test_resolve_cursor_agent_missing_node(tmp_path, monkeypatch):
    """Raises FileNotFoundError when node.exe is absent from version dir."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ver = tmp_path / "cursor-agent" / "versions" / "2026.02.27-abc"
    ver.mkdir(parents=True)
    (ver / "index.js").write_text("// stub")
    # node.exe intentionally absent
    with pytest.raises(FileNotFoundError, match="node.exe not found"):
        _resolve_cursor_agent()


def test_resolve_cursor_agent_picks_latest_version(tmp_path, monkeypatch):
    """Returns paths from the lexicographically latest version directory."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for ver_name in ("2026.01.01-aaa", "2026.02.27-bbb", "2026.01.15-ccc"):
        ver = tmp_path / "cursor-agent" / "versions" / ver_name
        ver.mkdir(parents=True)
        (ver / "node.exe").write_text("stub")
        (ver / "index.js").write_text("stub")

    node_exe, index_js = _resolve_cursor_agent()
    assert "2026.02.27-bbb" in node_exe
    assert "2026.02.27-bbb" in index_js


# ------------------------------------------------------------------ #
# invoke_cursor_cli — happy path                                      #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_invoke_cursor_cli_success(tmp_path, monkeypatch):
    """Returns a non-degraded result when the agent subprocess succeeds."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ver = tmp_path / "cursor-agent" / "versions" / "2026.02.27-e7d2ef6"
    ver.mkdir(parents=True)
    (ver / "node.exe").write_text("stub")
    (ver / "index.js").write_text("stub")

    with patch("cato.orchestrator.cli_invoker._run_subprocess_async",
               new_callable=AsyncMock,
               return_value="The refactored function looks good.") as mock_sub:
        result = await invoke_cursor_cli("def foo(): pass", "refactor foo")

    assert result["model"] == "cursor"
    assert result["degraded"] is False
    assert result["source"] == "subprocess"
    assert "refactored" in result["response"]
    assert result["confidence"] >= 0.0
    assert result["latency_ms"] >= 0
    # Verify --print and --trust flags were passed
    call_args = mock_sub.call_args[0][0]  # first positional arg = args list
    assert "--print" in call_args
    assert "--trust" in call_args
    assert "--yolo" in call_args
    assert "--model" in call_args
    assert "auto" in call_args


@pytest.mark.asyncio
async def test_invoke_cursor_cli_returns_correct_shape(tmp_path, monkeypatch):
    """Return dict has all required keys."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ver = tmp_path / "cursor-agent" / "versions" / "2026.02.27-e7d2ef6"
    ver.mkdir(parents=True)
    (ver / "node.exe").write_text("stub")
    (ver / "index.js").write_text("stub")

    with patch("cato.orchestrator.cli_invoker._run_subprocess_async",
               new_callable=AsyncMock, return_value="ok"):
        result = await invoke_cursor_cli("prompt", "task")

    for key in ("model", "response", "confidence", "latency_ms", "degraded", "source"):
        assert key in result, f"Missing key: {key}"
    assert result["model"] == "cursor"


# ------------------------------------------------------------------ #
# invoke_cursor_cli — error paths                                     #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_invoke_cursor_cli_not_installed_returns_degraded(tmp_path, monkeypatch):
    """Returns degraded=True when cursor-agent is not installed."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # no cursor-agent directory → FileNotFoundError from _resolve_cursor_agent
    result = await invoke_cursor_cli("prompt", "task")

    assert result["model"] == "cursor"
    assert result["degraded"] is True
    assert result["source"] == "mock"
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_invoke_cursor_cli_subprocess_error_returns_degraded(tmp_path, monkeypatch):
    """Returns degraded=True when the agent subprocess fails."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ver = tmp_path / "cursor-agent" / "versions" / "2026.02.27-e7d2ef6"
    ver.mkdir(parents=True)
    (ver / "node.exe").write_text("stub")
    (ver / "index.js").write_text("stub")

    from cato.orchestrator.cli_invoker import SubprocessError
    with patch("cato.orchestrator.cli_invoker._run_subprocess_async",
               new_callable=AsyncMock,
               side_effect=SubprocessError("node.exe", 1, "usage limit exceeded")):
        result = await invoke_cursor_cli("prompt", "task")

    assert result["model"] == "cursor"
    assert result["degraded"] is True
    assert "usage limit" in result["response"]


@pytest.mark.asyncio
async def test_invoke_cursor_cli_timeout_returns_degraded(tmp_path, monkeypatch):
    """Returns degraded=True on subprocess timeout."""
    import asyncio
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ver = tmp_path / "cursor-agent" / "versions" / "2026.02.27-e7d2ef6"
    ver.mkdir(parents=True)
    (ver / "node.exe").write_text("stub")
    (ver / "index.js").write_text("stub")

    with patch("cato.orchestrator.cli_invoker._run_subprocess_async",
               new_callable=AsyncMock,
               side_effect=asyncio.TimeoutError()):
        result = await invoke_cursor_cli("prompt", "task")

    assert result["model"] == "cursor"
    assert result["degraded"] is True
    assert "timed out" in result["response"].lower()


@pytest.mark.asyncio
async def test_invoke_cursor_cli_never_raises(tmp_path, monkeypatch):
    """invoke_cursor_cli must not raise any exception — returns degraded instead."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # not installed → clean degraded return
    try:
        result = await invoke_cursor_cli("prompt", "task")
        assert isinstance(result, dict)
    except Exception as exc:
        pytest.fail(f"invoke_cursor_cli raised unexpectedly: {exc}")


# ------------------------------------------------------------------ #
# invoke_subagent — backend dispatch                                  #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_invoke_subagent_dispatches_to_codex():
    """backend='codex' calls invoke_codex_cli."""
    with patch("cato.orchestrator.cli_invoker.invoke_codex_cli",
               new_callable=AsyncMock,
               return_value={"model": "codex", "response": "ok", "confidence": 0.8,
                             "latency_ms": 10, "degraded": False, "source": "pool"}) as mock_codex:
        result = await invoke_subagent("prompt", "task", backend="codex")

    mock_codex.assert_awaited_once_with("prompt", "task")
    assert result["model"] == "codex"


@pytest.mark.asyncio
async def test_invoke_subagent_dispatches_to_claude():
    """backend='claude' calls invoke_claude_api."""
    with patch("cato.orchestrator.cli_invoker.invoke_claude_api",
               new_callable=AsyncMock,
               return_value={"model": "claude", "response": "ok", "confidence": 0.9,
                             "latency_ms": 10, "degraded": False, "source": "pool"}) as mock_claude:
        result = await invoke_subagent("prompt", "task", backend="claude")

    mock_claude.assert_awaited_once_with("prompt", "task")
    assert result["model"] == "claude"


@pytest.mark.asyncio
async def test_invoke_subagent_dispatches_to_gemini():
    """backend='gemini' calls invoke_gemini_cli."""
    with patch("cato.orchestrator.cli_invoker.invoke_gemini_cli",
               new_callable=AsyncMock,
               return_value={"model": "gemini", "response": "ok", "confidence": 0.75,
                             "latency_ms": 10, "degraded": False, "source": "subprocess"}) as mock_gemini:
        result = await invoke_subagent("prompt", "task", backend="gemini")

    mock_gemini.assert_awaited_once_with("prompt", "task")
    assert result["model"] == "gemini"


@pytest.mark.asyncio
async def test_invoke_subagent_dispatches_to_cursor():
    """backend='cursor' calls invoke_cursor_cli."""
    with patch("cato.orchestrator.cli_invoker.invoke_cursor_cli",
               new_callable=AsyncMock,
               return_value={"model": "cursor", "response": "ok", "confidence": 0.80,
                             "latency_ms": 15, "degraded": False, "source": "subprocess"}) as mock_cursor:
        result = await invoke_subagent("prompt", "task", backend="cursor")

    mock_cursor.assert_awaited_once_with("prompt", "task")
    assert result["model"] == "cursor"


@pytest.mark.asyncio
async def test_invoke_subagent_unknown_backend_falls_back_to_codex():
    """Unknown backend string falls back to codex without raising."""
    with patch("cato.orchestrator.cli_invoker.invoke_codex_cli",
               new_callable=AsyncMock,
               return_value={"model": "codex", "response": "fallback", "confidence": 0.7,
                             "latency_ms": 5, "degraded": False, "source": "subprocess"}) as mock_codex:
        result = await invoke_subagent("prompt", "task", backend="chatgpt")  # type: ignore[arg-type]

    mock_codex.assert_awaited_once()
    assert result["model"] == "codex"


# ------------------------------------------------------------------ #
# CatoConfig subagent fields                                         #
# ------------------------------------------------------------------ #

def test_config_subagent_defaults():
    """subagent_enabled=False, subagent_coding_backend='codex' by default."""
    from cato.config import CatoConfig
    cfg = CatoConfig()
    assert cfg.subagent_enabled is False
    assert cfg.subagent_coding_backend == "codex"


def test_config_subagent_fields_persist_round_trip(tmp_path):
    """Saving and reloading config preserves subagent fields."""
    from cato.config import CatoConfig
    cfg_path = tmp_path / "config.yaml"
    cfg = CatoConfig()
    cfg.subagent_enabled = True
    cfg.subagent_coding_backend = "cursor"
    cfg.save(config_path=cfg_path)

    loaded = CatoConfig.load(config_path=cfg_path)
    assert loaded.subagent_enabled is True
    assert loaded.subagent_coding_backend == "cursor"


def test_config_subagent_all_backends_accepted(tmp_path):
    """Each supported backend string round-trips correctly."""
    from cato.config import CatoConfig
    for backend in ("claude", "codex", "gemini", "cursor"):
        cfg_path = tmp_path / f"config_{backend}.yaml"
        cfg = CatoConfig()
        cfg.subagent_enabled = True
        cfg.subagent_coding_backend = backend
        cfg.save(config_path=cfg_path)
        loaded = CatoConfig.load(config_path=cfg_path)
        assert loaded.subagent_coding_backend == backend
