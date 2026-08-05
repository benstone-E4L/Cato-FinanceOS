"""
Unit tests for cli_invoker module.

The refactored invoker uses asyncio.create_subprocess_exec() instead of
subprocess.run(), so tests that previously patched 'subprocess.run' now patch
'asyncio.create_subprocess_exec' (or the internal helper '_run_subprocess_async').

New coverage targets (added in audit pass):
- Pool-first warm path for invoke_claude_api and invoke_codex_cli
- SubprocessError paths for codex and gemini
- asyncio.TimeoutError path for gemini
- Generic Exception path for claude (catch-all handler)
- _run_subprocess_async: success, non-zero exit, timeout, empty stdout warning
"""

import asyncio
import time
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from cato.orchestrator.cli_invoker import (
    invoke_claude_api,
    invoke_codex_cli,
    invoke_gemini_cli,
    invoke_all_parallel,
    invoke_with_early_termination,
    SubprocessError,
    _resolve_cli,
    _run_subprocess_async,
)


# ------------------------------------------------------------------ #
# _run_subprocess_async unit tests                                    #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_run_subprocess_async_success():
    """Happy path: process exits 0, stdout returned."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0

    # communicate() is awaited via asyncio.wait_for — make it an AsyncMock
    mock_proc.communicate = AsyncMock(return_value=(b"hello output\n", b""))
    mock_proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await _run_subprocess_async(["echo", "hello"])

    assert result == "hello output"


@pytest.mark.asyncio
async def test_run_subprocess_async_nonzero_exit_raises():
    """Non-zero returncode must raise SubprocessError."""
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"something went wrong"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(SubprocessError) as exc_info:
            await _run_subprocess_async(["bad_cmd"])

    assert exc_info.value.returncode == 1
    assert "something went wrong" in exc_info.value.stderr


@pytest.mark.asyncio
async def test_run_subprocess_async_timeout_kills_process():
    """On TimeoutError the process must be killed and the error re-raised.

    We simulate the TimeoutError by making communicate() raise it directly,
    which is what asyncio.wait_for does internally when the deadline fires.
    The second communicate() call (reap the zombie) must succeed.
    """
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()

    # First call: raises TimeoutError (simulates wait_for expiry)
    # Second call: returns normally (reap after kill)
    mock_proc.communicate = AsyncMock(
        side_effect=[asyncio.TimeoutError(), (b"", b"")]
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(asyncio.TimeoutError):
            await _run_subprocess_async(["slow_cmd"], timeout_sec=60.0)

    mock_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_run_subprocess_async_empty_stdout_logs_warning(caplog):
    """When stdout is empty but stderr has content, a warning is logged."""
    import logging
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b"progress info"))
    mock_proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         caplog.at_level(logging.WARNING, logger="cato.orchestrator.cli_invoker"):
        result = await _run_subprocess_async(["some_cmd"])

    assert result == ""
    assert any("empty stdout" in rec.message or "stderr" in rec.message
               for rec in caplog.records)


# ------------------------------------------------------------------ #
# invoke_claude_api                                                   #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_invoke_claude_api_success():
    """Test successful Claude CLI invocation via subprocess path."""
    async def fake_subprocess(args, timeout_sec=60.0):
        return "Test response [confidence: 0.85]"

    with patch(
        'cato.orchestrator.cli_invoker._run_subprocess_async',
        side_effect=fake_subprocess,
    ):
        result = await invoke_claude_api("test prompt", "test task")

    assert result["model"] == "claude"
    assert "Test response" in result["response"]
    assert 0 <= result["confidence"] <= 1
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_invoke_claude_api_uses_pool_when_warm():
    """When the pool is warm for claude, pool.send_to() is used instead of subprocess."""
    mock_pool = MagicMock()
    mock_pool.is_warm.return_value = True
    mock_pool.send_to = AsyncMock(return_value="pool response [confidence: 0.90]")

    # get_pool is imported lazily inside the function body; patch at source module
    with patch("cato.orchestrator.cli_process_pool.get_pool", return_value=mock_pool):
        result = await invoke_claude_api("test prompt", "test task")

    mock_pool.send_to.assert_awaited_once()
    assert result["model"] == "claude"
    assert "pool response" in result["response"]
    assert result["degraded"] is False
    assert result["source"] == "pool"


@pytest.mark.asyncio
async def test_invoke_claude_api_falls_back_to_subprocess_when_pool_cold():
    """When pool.is_warm() is False, the subprocess path is taken."""
    mock_pool = MagicMock()
    mock_pool.is_warm.return_value = False

    async def fake_subprocess(args, timeout_sec=60.0):
        return "subprocess response [confidence: 0.80]"

    with patch("cato.orchestrator.cli_process_pool.get_pool", return_value=mock_pool), \
         patch("cato.orchestrator.cli_invoker._run_subprocess_async",
               side_effect=fake_subprocess):
        result = await invoke_claude_api("test prompt", "test task")

    mock_pool.send_to.assert_not_called()
    assert "subprocess response" in result["response"]
    assert result["source"] == "subprocess"


@pytest.mark.asyncio
async def test_invoke_claude_cli_not_installed():
    """Test Claude CLI fallback when not installed."""
    with patch(
        'cato.orchestrator.cli_invoker._resolve_cli',
        side_effect=FileNotFoundError("claude not found"),
    ):
        result = await invoke_claude_api("test prompt", "test task")

    assert result["model"] == "claude"
    assert result["confidence"] == 0.75
    assert "[Claude Mock]" in result["response"]
    assert result["degraded"] is True
    assert result["latency_ms"] >= 0
    assert result["source"] == "mock"


@pytest.mark.asyncio
async def test_invoke_claude_cli_nonzero_exit():
    """Test Claude CLI with non-zero exit code (e.g. nested session)."""
    with patch(
        'cato.orchestrator.cli_invoker._resolve_cli',
        return_value=["claude"],
    ), patch(
        'cato.orchestrator.cli_invoker._run_subprocess_async',
        side_effect=SubprocessError("claude", 1, "Cannot launch inside another session"),
    ):
        result = await invoke_claude_api("test prompt", "test task")

    assert result["model"] == "claude"
    assert result["confidence"] == 0.5
    assert "Cannot launch" in result["response"]
    assert result["degraded"] is True


@pytest.mark.asyncio
async def test_invoke_claude_api_timeout():
    """asyncio.TimeoutError from subprocess is caught and returns degraded result."""
    mock_pool = MagicMock()
    mock_pool.is_warm.return_value = False

    with patch("cato.orchestrator.cli_process_pool.get_pool", return_value=mock_pool), \
         patch("cato.orchestrator.cli_invoker._run_subprocess_async",
               side_effect=asyncio.TimeoutError()):
        result = await invoke_claude_api("test prompt", "test task")

    assert result["model"] == "claude"
    assert result["confidence"] == 0.5
    assert "timed out" in result["response"].lower()
    assert result["degraded"] is True


@pytest.mark.asyncio
async def test_invoke_claude_api_generic_exception():
    """Catch-all Exception handler returns degraded result without raising."""
    mock_pool = MagicMock()
    mock_pool.is_warm.return_value = False

    with patch("cato.orchestrator.cli_process_pool.get_pool", return_value=mock_pool), \
         patch("cato.orchestrator.cli_invoker._run_subprocess_async",
               side_effect=RuntimeError("unexpected error")):
        result = await invoke_claude_api("test prompt", "test task")

    assert result["model"] == "claude"
    assert result["confidence"] == 0.5
    assert "unexpected error" in result["response"]
    assert result["degraded"] is True


# ------------------------------------------------------------------ #
# invoke_codex_cli                                                    #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_invoke_codex_cli_uses_pool_when_warm():
    """When the pool is warm for codex, pool.send_to() is used."""
    mock_pool = MagicMock()
    mock_pool.is_warm.return_value = True
    mock_pool.send_to = AsyncMock(return_value="codex pool answer [confidence: 0.88]")

    with patch("cato.orchestrator.cli_process_pool.get_pool", return_value=mock_pool):
        result = await invoke_codex_cli("test prompt", "test task")

    mock_pool.send_to.assert_awaited_once()
    assert result["model"] == "codex"
    assert "codex pool answer" in result["response"]
    assert result["degraded"] is False
    assert result["source"] == "pool"


@pytest.mark.asyncio
async def test_invoke_codex_cli_falls_back_to_subprocess_when_cold():
    """When pool.is_warm() is False, subprocess path is used for codex."""
    mock_pool = MagicMock()
    mock_pool.is_warm.return_value = False

    async def fake_subprocess(args, timeout_sec=60.0):
        return "codex subprocess result [confidence: 0.75]"

    with patch("cato.orchestrator.cli_process_pool.get_pool", return_value=mock_pool), \
         patch("cato.orchestrator.cli_invoker._run_subprocess_async",
               side_effect=fake_subprocess):
        result = await invoke_codex_cli("test prompt", "test task")

    mock_pool.send_to.assert_not_called()
    assert "codex subprocess result" in result["response"]
    assert result["source"] == "subprocess"


@pytest.mark.asyncio
async def test_invoke_codex_cli_not_installed():
    """Test Codex CLI fallback when not installed."""
    with patch(
        'cato.orchestrator.cli_invoker._resolve_cli',
        side_effect=FileNotFoundError("codex not found"),
    ):
        result = await invoke_codex_cli("test prompt", "test task")

    assert result["model"] == "codex"
    assert result["confidence"] == 0.72
    assert "[Codex Mock]" in result["response"]
    assert result["degraded"] is True
    assert result["latency_ms"] >= 0
    assert result["source"] == "mock"


@pytest.mark.asyncio
async def test_invoke_codex_cli_subprocess_error():
    """Test Codex CLI with a generic subprocess error."""
    with patch(
        'cato.orchestrator.cli_invoker._run_subprocess_async',
        side_effect=OSError("Subprocess error"),
    ):
        result = await invoke_codex_cli("test prompt", "test task")

    assert result["model"] == "codex"
    assert "Error" in result["response"]
    assert result["confidence"] == 0.6


@pytest.mark.asyncio
async def test_invoke_codex_cli_nonzero_exit():
    """SubprocessError from codex returns a degraded result with error text."""
    with patch(
        'cato.orchestrator.cli_invoker._resolve_cli',
        return_value=["codex"],
    ), patch(
        'cato.orchestrator.cli_invoker._run_subprocess_async',
        side_effect=SubprocessError("codex", 1, "codex crashed badly"),
    ):
        result = await invoke_codex_cli("test prompt", "test task")

    assert result["model"] == "codex"
    assert result["confidence"] == 0.6
    assert "codex crashed badly" in result["response"]
    assert result["degraded"] is True


@pytest.mark.asyncio
async def test_invoke_codex_cli_timeout():
    """Test Codex CLI timeout path."""
    with patch(
        'cato.orchestrator.cli_invoker._run_subprocess_async',
        side_effect=asyncio.TimeoutError(),
    ):
        result = await invoke_codex_cli("test prompt", "test task")

    assert result["model"] == "codex"
    assert "timed out" in result["response"].lower() or "Error" in result["response"]
    assert result["confidence"] == 0.6


# ------------------------------------------------------------------ #
# invoke_gemini_cli                                                   #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_invoke_gemini_cli_success():
    """Gemini always uses subprocess (no pool); verify happy path."""
    async def fake_subprocess(args, timeout_sec=60.0):
        return "gemini response [confidence: 0.78]"

    with patch("cato.orchestrator.cli_invoker._resolve_cli", return_value=["gemini"]), \
         patch("cato.orchestrator.cli_invoker._run_subprocess_async",
               side_effect=fake_subprocess):
        result = await invoke_gemini_cli("test prompt", "test task")

    assert result["model"] == "gemini"
    assert result["degraded"] is False
    assert result["source"] == "subprocess"


@pytest.mark.asyncio
async def test_invoke_gemini_cli_not_installed():
    """Test Gemini CLI fallback when not installed."""
    with patch(
        'cato.orchestrator.cli_invoker._resolve_cli',
        side_effect=FileNotFoundError("gemini not found"),
    ):
        result = await invoke_gemini_cli("test prompt", "test task")

    assert result["model"] == "gemini"
    assert result["confidence"] == 0.68
    assert "[Gemini Mock]" in result["response"]
    assert result["latency_ms"] >= 0
    assert result["source"] == "mock"


@pytest.mark.asyncio
async def test_invoke_gemini_cli_subprocess_error():
    """Test Gemini CLI with a generic subprocess error."""
    with patch(
        'cato.orchestrator.cli_invoker._run_subprocess_async',
        side_effect=OSError("Subprocess error"),
    ):
        result = await invoke_gemini_cli("test prompt", "test task")

    assert result["model"] == "gemini"
    assert "Error" in result["response"]
    assert result["confidence"] == 0.55


@pytest.mark.asyncio
async def test_invoke_gemini_cli_nonzero_exit():
    """SubprocessError from gemini returns a degraded result with error text."""
    with patch(
        'cato.orchestrator.cli_invoker._resolve_cli',
        return_value=["gemini"],
    ), patch(
        'cato.orchestrator.cli_invoker._run_subprocess_async',
        side_effect=SubprocessError("gemini", 2, "gemini api quota exceeded"),
    ):
        result = await invoke_gemini_cli("test prompt", "test task")

    assert result["model"] == "gemini"
    assert result["confidence"] == 0.6
    assert "gemini api quota exceeded" in result["response"]
    assert result["degraded"] is True


@pytest.mark.asyncio
async def test_invoke_gemini_cli_timeout():
    """asyncio.TimeoutError from gemini subprocess returns degraded result."""
    with patch(
        'cato.orchestrator.cli_invoker._resolve_cli',
        return_value=["gemini"],
    ), patch(
        'cato.orchestrator.cli_invoker._run_subprocess_async',
        side_effect=asyncio.TimeoutError(),
    ):
        result = await invoke_gemini_cli("test prompt", "test task")

    assert result["model"] == "gemini"
    assert result["confidence"] == 0.55
    assert "timed out" in result["response"].lower()
    assert result["degraded"] is True


# ------------------------------------------------------------------ #
# invoke_all_parallel                                                 #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_invoke_all_parallel():
    """Test parallel invocation of all 3 models."""
    async def fake_subprocess(args, timeout_sec=60.0):
        return "Mock response [confidence: 0.80]"

    with patch('cato.orchestrator.cli_invoker._run_subprocess_async', side_effect=fake_subprocess):
        claude_result, codex_result, gemini_result = await invoke_all_parallel(
            "test prompt",
            "test task",
        )

    assert claude_result["model"] == "claude"
    assert codex_result["model"] == "codex"
    assert gemini_result["model"] == "gemini"

    for result in [claude_result, codex_result, gemini_result]:
        assert "response" in result
        assert "confidence" in result
        assert "latency_ms" in result
        assert 0 <= result["confidence"] <= 1


@pytest.mark.asyncio
async def test_invoke_all_parallel_latency():
    """Parallel invocation should complete in roughly the time of the slowest
    single coroutine rather than the sum of all three."""

    call_count = 0

    async def fake_subprocess(args, timeout_sec=3.0):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)   # 50 ms simulated I/O
        return "[Mock] response [confidence: 0.72]"

    with patch('cato.orchestrator.cli_invoker._run_subprocess_async', side_effect=fake_subprocess):
        start = time.time()
        await invoke_all_parallel("test prompt", "test task")
        parallel_latency = time.time() - start

    # Two subprocess calls each take 50 ms; if truly parallel the total
    # should be well under 150 ms (3 x 50 ms sequential).
    assert parallel_latency < 0.150, (
        f"Expected parallel latency < 150 ms, got {parallel_latency * 1000:.1f} ms. "
        "This may indicate the event loop is being blocked."
    )


@pytest.mark.asyncio
async def test_invoke_all_parallel_no_waiting():
    """invoke_all_parallel returns exactly 3 non-None results."""
    async def fake_subprocess(args, timeout_sec=60.0):
        return "Mock response [confidence: 0.72]"

    with patch('cato.orchestrator.cli_invoker._run_subprocess_async', side_effect=fake_subprocess):
        result = await invoke_all_parallel("test prompt", "test task")
    assert len(result) == 3
    assert all(r is not None for r in result)


# ------------------------------------------------------------------ #
# invoke_with_early_termination                                       #
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_invoke_with_early_termination_enqueues_results():
    """invoke_with_early_termination pushes all 3 model results into the queue."""
    async def fake_subprocess(args, timeout_sec=60.0):
        return "Mock response [confidence: 0.72]"

    queue: asyncio.Queue = asyncio.Queue()

    with patch('cato.orchestrator.cli_invoker._run_subprocess_async', side_effect=fake_subprocess):
        await invoke_with_early_termination("test prompt", "test task", queue)

    assert queue.qsize() == 3
    models_seen = set()
    while not queue.empty():
        item = queue.get_nowait()
        models_seen.add(item["model"])
    assert models_seen == {"claude", "codex", "gemini"}


@pytest.mark.asyncio
async def test_invoke_with_early_termination_degraded_results_still_enqueued():
    """Even when CLIs are not installed, degraded results must be enqueued."""
    queue: asyncio.Queue = asyncio.Queue()

    with patch(
        'cato.orchestrator.cli_invoker._resolve_cli',
        side_effect=FileNotFoundError("not found"),
    ):
        await invoke_with_early_termination("test", "task", queue)

    assert queue.qsize() == 3
    while not queue.empty():
        item = queue.get_nowait()
        assert item["degraded"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
