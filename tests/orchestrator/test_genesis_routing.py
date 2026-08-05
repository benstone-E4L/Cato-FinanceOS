"""
Tests for invoke_for_genesis_phase() — Genesis pipeline phase routing.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cato.orchestrator.cli_invoker import (
    _GENESIS_PHASE_ROUTING,
    _GENESIS_PHASE_TIMEOUTS,
    invoke_for_genesis_phase,
)


def _ok_result(model: str) -> dict:
    return {
        "model": model,
        "response": f"[{model}] ok",
        "confidence": 0.95,
        "latency_ms": 50.0,
        "degraded": False,
        "source": "mock",
    }


def _degraded_result(model: str) -> dict:
    return {
        "model": model,
        "response": f"[{model}] error",
        "confidence": 0.5,
        "latency_ms": 50.0,
        "degraded": True,
        "source": "mock",
    }


# ---------------------------------------------------------------------------
# Test 1: correct backend is selected for each phase
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("phase,expected_primary", [
    (1, "claude"),
    (2, "claude"),
    (3, "gemini"),
    (4, "claude"),
    (5, "claude"),
    (6, "codex"),
    (7, "claude"),
    (8, "claude"),
    (9, "claude"),
])
async def test_routing_selects_correct_primary(phase: int, expected_primary: str):
    """invoke_for_genesis_phase routes each phase to its designated primary CLI."""
    with patch(
        "cato.orchestrator.cli_invoker.invoke_subagent",
        new_callable=AsyncMock,
        return_value=_ok_result(expected_primary),
    ) as mock_sub:
        result = await invoke_for_genesis_phase(phase, "test context", "test-biz")

    assert result["degraded"] is False
    assert result["model"] == expected_primary
    # invoke_subagent called exactly once (no fallback needed)
    mock_sub.assert_called_once()
    _, kwargs = mock_sub.call_args
    assert kwargs.get("backend") == expected_primary or mock_sub.call_args.args[2] == expected_primary


# ---------------------------------------------------------------------------
# Test 2: fallback is used when primary degrades (phase 3: gemini -> claude)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_used_when_primary_degrades():
    """When primary returns degraded=True, the fallback backend is tried."""
    call_count = 0

    async def mock_subagent(prompt, task, backend="codex"):
        nonlocal call_count
        call_count += 1
        if backend == "gemini":
            return _degraded_result("gemini")
        return _ok_result("claude")

    with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=mock_subagent):
        result = await invoke_for_genesis_phase(3, "design brief", "acme")

    assert call_count == 2, "Expected two calls: primary then fallback"
    assert result["degraded"] is False
    assert result["model"] == "claude"


# ---------------------------------------------------------------------------
# Test 3: invalid phase raises ValueError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_phase_raises_value_error():
    """Phases outside 1-9 raise ValueError immediately without calling any CLI."""
    with patch("cato.orchestrator.cli_invoker.invoke_subagent", new_callable=AsyncMock) as mock_sub:
        with pytest.raises(ValueError, match="Invalid Genesis phase"):
            await invoke_for_genesis_phase(0, "ctx", "biz")
        with pytest.raises(ValueError, match="Invalid Genesis phase"):
            await invoke_for_genesis_phase(10, "ctx", "biz")

    mock_sub.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: phase with no fallback returns degraded result without second call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_fallback_returns_degraded_without_retry():
    """Phases with fallback=None do not retry when primary degrades."""
    call_count = 0

    async def mock_subagent(prompt, task, backend="codex"):
        nonlocal call_count
        call_count += 1
        return _degraded_result("claude")

    with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=mock_subagent):
        result = await invoke_for_genesis_phase(1, "research brief", "biz")

    assert call_count == 1, "No fallback for phase 1 — should only call once"
    assert result["degraded"] is True


# ---------------------------------------------------------------------------
# Sanity: routing table covers all phases 1-9
# ---------------------------------------------------------------------------

def test_routing_table_covers_all_phases():
    assert set(_GENESIS_PHASE_ROUTING.keys()) == set(range(1, 10))


def test_timeout_table_covers_all_phases():
    assert set(_GENESIS_PHASE_TIMEOUTS.keys()) == set(range(1, 10))


# ---------------------------------------------------------------------------
# Test: timeout causes degraded result, fallback is attempted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_on_primary_triggers_fallback():
    """If primary times out, fallback is tried (phase 3: gemini -> claude)."""
    import asyncio

    call_count = 0

    async def mock_subagent(prompt, task, backend="codex"):
        nonlocal call_count
        call_count += 1
        if backend == "gemini":
            raise asyncio.TimeoutError()
        return _ok_result("claude")

    with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=mock_subagent):
        result = await invoke_for_genesis_phase(3, "design brief", "acme")

    assert call_count == 2
    assert result["degraded"] is False
    assert result["model"] == "claude"
