"""
Unit tests for cli_process_pool module.

All tests use mocked subprocesses — no real CLIs are invoked.

Coverage targets:
- Protocol parsing: edge cases (malformed JSON, empty lines, empty prompt, huge prompt)
- PersistentProcess: start with init handshake (Codex), stop kill path, restart,
  send EOF break, send timeout, start idempotency
- CLIProcessPool: send_to double-failure, is_warm after start, concurrent sends
- Server lifecycle hooks: on_startup / on_cleanup call pool correctly
- cli_invoker pool-first path: warm pool branch for claude and codex
- cli_invoker missing error paths: SubprocessError for codex/gemini, generic
  Exception for claude, gemini timeout
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from cato.orchestrator.cli_process_pool import (
    CLIProcessPool,
    ClaudeStreamProtocol,
    CodexMCPProtocol,
    PersistentProcess,
    get_pool,
)


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _make_mock_proc(stdout_lines: list[bytes], returncode=None):
    """Create a mock asyncio subprocess with a finite readline queue."""
    proc = AsyncMock()
    proc.returncode = returncode  # None = still running
    proc.pid = 12345

    stdin = MagicMock()
    stdin.write = MagicMock()
    stdin.drain = AsyncMock()
    stdin.close = MagicMock()
    stdin.is_closing = MagicMock(return_value=False)
    proc.stdin = stdin

    line_iter = iter(stdout_lines)

    async def fake_readline():
        try:
            return next(line_iter)
        except StopIteration:
            return b""

    proc.stdout = MagicMock()
    proc.stdout.readline = fake_readline

    proc.stderr = MagicMock()
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()

    return proc


# ------------------------------------------------------------------ #
# ClaudeStreamProtocol tests                                          #
# ------------------------------------------------------------------ #

class TestClaudeStreamProtocol:

    def test_format_request_produces_valid_json(self):
        proto = ClaudeStreamProtocol()
        raw = proto.format_request("Hello world")
        obj = json.loads(raw.strip())
        assert obj["type"] == "user"
        assert obj["message"]["role"] == "user"
        assert obj["message"]["content"] == "Hello world"

    def test_format_request_newline_terminated(self):
        proto = ClaudeStreamProtocol()
        raw = proto.format_request("ping")
        assert raw.endswith("\n"), "Wire format must be newline-terminated"

    def test_format_request_empty_prompt(self):
        """Empty prompt is valid — protocol should not crash."""
        proto = ClaudeStreamProtocol()
        raw = proto.format_request("")
        obj = json.loads(raw.strip())
        assert obj["message"]["content"] == ""

    def test_format_request_large_prompt(self):
        """Large prompts must not be truncated."""
        proto = ClaudeStreamProtocol()
        big = "x" * 100_000
        raw = proto.format_request(big)
        obj = json.loads(raw.strip())
        assert len(obj["message"]["content"]) == 100_000

    def test_is_response_complete_with_result(self):
        proto = ClaudeStreamProtocol()
        data = json.dumps({"type": "assistant", "message": {"content": "hi"}}) + "\n"
        data += json.dumps({"type": "result", "result": "done"}) + "\n"
        assert proto.is_response_complete(data)

    def test_is_response_complete_without_result(self):
        proto = ClaudeStreamProtocol()
        data = json.dumps({"type": "assistant", "message": {"content": "hi"}}) + "\n"
        assert not proto.is_response_complete(data)

    def test_is_response_complete_empty_string(self):
        proto = ClaudeStreamProtocol()
        assert not proto.is_response_complete("")

    def test_is_response_complete_skips_malformed_json(self):
        """Malformed lines must not raise — they are silently skipped."""
        proto = ClaudeStreamProtocol()
        data = "not json at all\n"
        data += json.dumps({"type": "result", "result": "ok"}) + "\n"
        assert proto.is_response_complete(data)

    def test_is_response_complete_only_malformed_json(self):
        proto = ClaudeStreamProtocol()
        assert not proto.is_response_complete("{{bad}}\n{also bad}\n")

    def test_extract_text_from_result(self):
        proto = ClaudeStreamProtocol()
        data = json.dumps({"type": "result", "result": "Final answer"}) + "\n"
        assert "Final answer" in proto.extract_text(data)

    def test_extract_text_from_assistant_string_content(self):
        """Assistant message with string content (not list of blocks)."""
        proto = ClaudeStreamProtocol()
        data = json.dumps({
            "type": "assistant",
            "message": {"content": "plain string content"},
        }) + "\n"
        data += json.dumps({"type": "result", "result": ""}) + "\n"
        assert "plain string content" in proto.extract_text(data)

    def test_extract_text_from_assistant_blocks(self):
        proto = ClaudeStreamProtocol()
        data = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "block1"}]},
        }) + "\n"
        data += json.dumps({"type": "result", "result": ""}) + "\n"
        assert "block1" in proto.extract_text(data)

    def test_extract_text_fallback_when_no_known_fields(self):
        """When nothing recognizable is found, returns raw accumulated text."""
        proto = ClaudeStreamProtocol()
        raw = "some raw output\n"
        result = proto.extract_text(raw)
        assert result == raw

    def test_extract_text_skips_malformed_json(self):
        """Malformed lines are silently skipped; valid lines are still extracted."""
        proto = ClaudeStreamProtocol()
        data = "not json\n"
        data += json.dumps({"type": "result", "result": "good"}) + "\n"
        assert "good" in proto.extract_text(data)

    def test_no_initialization_message(self):
        proto = ClaudeStreamProtocol()
        assert proto.initialization_message() is None

    def test_initialization_complete_always_true(self):
        """Claude has no handshake, so initialization_complete is always True."""
        proto = ClaudeStreamProtocol()
        assert proto.initialization_complete("anything")
        assert proto.initialization_complete("")

    def test_spawn_args_contains_stream_json_flags(self):
        """spawn_args must include the stream-json mode flags."""
        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]):
            proto = ClaudeStreamProtocol()
            args = proto.spawn_args()
        assert "--input-format" in args
        assert "stream-json" in args
        assert "--output-format" in args
        assert "--no-session-persistence" in args


# ------------------------------------------------------------------ #
# CodexMCPProtocol tests                                              #
# ------------------------------------------------------------------ #

class TestCodexMCPProtocol:

    def test_format_request_is_jsonrpc(self):
        proto = CodexMCPProtocol()
        raw = proto.format_request("Fix bug")
        obj = json.loads(raw.strip())
        assert obj["jsonrpc"] == "2.0"
        assert obj["method"] == "tools/call"
        assert obj["params"]["name"] == "codex"
        assert obj["params"]["arguments"]["prompt"] == "Fix bug"

    def test_format_request_newline_terminated(self):
        proto = CodexMCPProtocol()
        assert proto.format_request("hi").endswith("\n")

    def test_format_request_increments_id(self):
        """Each call must produce a unique monotonically increasing id."""
        proto = CodexMCPProtocol()
        id1 = json.loads(proto.format_request("a").strip())["id"]
        id2 = json.loads(proto.format_request("b").strip())["id"]
        assert id2 > id1

    def test_format_request_empty_prompt(self):
        proto = CodexMCPProtocol()
        raw = proto.format_request("")
        obj = json.loads(raw.strip())
        assert obj["params"]["arguments"]["prompt"] == ""

    def test_initialization_message_is_initialize(self):
        proto = CodexMCPProtocol()
        raw = proto.initialization_message()
        assert raw is not None
        obj = json.loads(raw.strip())
        assert obj["method"] == "initialize"
        assert obj["jsonrpc"] == "2.0"

    def test_initialization_message_contains_client_info(self):
        proto = CodexMCPProtocol()
        obj = json.loads(proto.initialization_message().strip())
        assert obj["params"]["clientInfo"]["name"] == "cato"

    def test_initialization_complete_with_result(self):
        proto = CodexMCPProtocol()
        data = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}) + "\n"
        assert proto.initialization_complete(data)

    def test_initialization_complete_without_result(self):
        proto = CodexMCPProtocol()
        assert not proto.initialization_complete("")

    def test_initialization_complete_skips_malformed_json(self):
        proto = CodexMCPProtocol()
        data = "bad json\n"
        data += json.dumps({"result": {}}) + "\n"
        assert proto.initialization_complete(data)

    def test_initialization_complete_only_malformed_returns_false(self):
        proto = CodexMCPProtocol()
        assert not proto.initialization_complete("{{{garbage}}}\n")

    def test_is_response_complete_with_result(self):
        proto = CodexMCPProtocol()
        data = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": []}}) + "\n"
        assert proto.is_response_complete(data)

    def test_is_response_complete_with_error(self):
        proto = CodexMCPProtocol()
        data = json.dumps({"jsonrpc": "2.0", "id": 2, "error": {"message": "fail"}}) + "\n"
        assert proto.is_response_complete(data)

    def test_is_response_complete_empty(self):
        proto = CodexMCPProtocol()
        assert not proto.is_response_complete("")

    def test_is_response_complete_skips_malformed_json(self):
        proto = CodexMCPProtocol()
        data = "bad line\n"
        data += json.dumps({"result": {}}) + "\n"
        assert proto.is_response_complete(data)

    def test_is_response_complete_only_malformed_returns_false(self):
        proto = CodexMCPProtocol()
        assert not proto.is_response_complete("{bad json}\n")

    def test_extract_text_from_content(self):
        proto = CodexMCPProtocol()
        data = json.dumps({
            "jsonrpc": "2.0", "id": 2,
            "result": {"content": [{"type": "text", "text": "Fixed it"}]},
        }) + "\n"
        assert "Fixed it" in proto.extract_text(data)

    def test_extract_text_multiple_content_blocks(self):
        proto = CodexMCPProtocol()
        data = json.dumps({
            "jsonrpc": "2.0", "id": 2,
            "result": {"content": [
                {"type": "text", "text": "part A"},
                {"type": "text", "text": "part B"},
            ]},
        }) + "\n"
        result = proto.extract_text(data)
        assert "part A" in result
        assert "part B" in result

    def test_extract_text_from_error(self):
        proto = CodexMCPProtocol()
        data = json.dumps({
            "jsonrpc": "2.0", "id": 2,
            "error": {"message": "something broke"},
        }) + "\n"
        assert "something broke" in proto.extract_text(data)

    def test_extract_text_fallback_when_nothing_recognized(self):
        """Falls back to returning the raw accumulated string."""
        proto = CodexMCPProtocol()
        raw = "unexpected output\n"
        assert proto.extract_text(raw) == raw

    def test_extract_text_skips_malformed_json(self):
        proto = CodexMCPProtocol()
        data = "garbage line\n"
        data += json.dumps({
            "result": {"content": [{"type": "text", "text": "ok"}]}
        }) + "\n"
        assert "ok" in proto.extract_text(data)

    def test_spawn_args_contains_mcp_server(self):
        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["codex"]):
            proto = CodexMCPProtocol()
            args = proto.spawn_args()
        assert "mcp-server" in args


# ------------------------------------------------------------------ #
# PersistentProcess tests                                             #
# ------------------------------------------------------------------ #

class TestPersistentProcess:

    @pytest.mark.asyncio
    async def test_start_spawns_process(self):
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)
        mock_proc = _make_mock_proc([])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        assert pp.is_alive

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """Calling start() twice should not spawn a second process."""
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)
        mock_proc = _make_mock_proc([])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await pp.start()
            await pp.start()  # second call — should be no-op

        assert mock_exec.call_count == 1

    @pytest.mark.asyncio
    async def test_start_with_init_handshake(self):
        """Codex requires an initialization handshake — verify it completes."""
        proto = CodexMCPProtocol()
        pp = PersistentProcess("codex", proto)

        # The init handshake reads until initialization_complete() returns True.
        # Provide a valid "result" line that satisfies initialization_complete.
        init_response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode() + b"\n"
        mock_proc = _make_mock_proc([init_response])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["codex"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        assert pp.is_alive
        # Verify the init message AND the initialized notification were written
        assert mock_proc.stdin.write.call_count == 2
        # First call: initialize request
        init_written = mock_proc.stdin.write.call_args_list[0][0][0]
        init_obj = json.loads(init_written.decode())
        assert init_obj["method"] == "initialize"
        # Second call: initialized notification (MCP spec requirement)
        notif_written = mock_proc.stdin.write.call_args_list[1][0][0]
        notif_obj = json.loads(notif_written.decode())
        assert notif_obj["method"] == "notifications/initialized"
        assert "id" not in notif_obj  # notifications have no id

    @pytest.mark.asyncio
    async def test_start_init_handshake_timeout(self):
        """Initialization timeout is logged and process is still considered started.

        We simulate the timeout by making asyncio.wait_for (used inside start())
        raise TimeoutError.  We patch it only within the cli_process_pool module
        namespace so we don't affect the test runner itself.
        """
        proto = CodexMCPProtocol()
        pp = PersistentProcess("codex", proto)

        mock_proc = _make_mock_proc([])

        async def raising_wait_for(coro, timeout):
            # Cancel the coroutine to avoid "coroutine was never awaited" warnings
            coro.close()
            raise asyncio.TimeoutError

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["codex"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("cato.orchestrator.cli_process_pool.asyncio.wait_for",
                   side_effect=raising_wait_for):
            # Should not raise despite the timeout
            await pp.start()

        assert pp.is_alive

    @pytest.mark.asyncio
    async def test_stop_terminates_process(self):
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)
        mock_proc = _make_mock_proc([])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        await pp.stop()

        assert not pp.is_alive
        mock_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_kills_if_terminate_times_out(self):
        """If graceful terminate times out, kill() must be called."""
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)
        mock_proc = _make_mock_proc([])

        # Make wait() time out on the first call (after terminate), succeed on second
        wait_call_count = 0

        async def flaky_wait():
            nonlocal wait_call_count
            wait_call_count += 1
            if wait_call_count == 1:
                raise asyncio.TimeoutError
            return 0

        mock_proc.wait = flaky_wait

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        await pp.stop()

        assert not pp.is_alive
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_noop_when_not_started(self):
        """stop() on a process that was never started should not raise."""
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)
        await pp.stop()  # must not raise

    @pytest.mark.asyncio
    async def test_restart_stops_then_starts(self):
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)

        stop_called = []
        start_called = []

        async def fake_stop():
            stop_called.append(True)

        async def fake_start():
            start_called.append(True)

        with patch.object(pp, "stop", side_effect=fake_stop), \
             patch.object(pp, "start", side_effect=fake_start):
            await pp.restart()

        assert len(stop_called) == 1
        assert len(start_called) == 1

    @pytest.mark.asyncio
    async def test_send_returns_response(self):
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)

        result_line = json.dumps({"type": "result", "result": "Hello back"}).encode() + b"\n"
        mock_proc = _make_mock_proc([result_line])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        text = await pp.send("Hello")
        assert "Hello back" in text

    @pytest.mark.asyncio
    async def test_send_raises_when_not_running(self):
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)

        with pytest.raises(RuntimeError, match="not running"):
            await pp.send("Hello")

    @pytest.mark.asyncio
    async def test_send_breaks_on_eof(self):
        """When readline returns b'' (EOF), send() exits the loop and returns."""
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)

        # Only provide an EOF (empty bytes) — no result line
        mock_proc = _make_mock_proc([b""])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        # Should return without hanging (fallback to accumulated which is "")
        result = await pp.send("any prompt")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_send_raises_on_timeout(self):
        """asyncio.TimeoutError from readline propagates out of send()."""
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)

        async def timeout_readline():
            raise asyncio.TimeoutError

        mock_proc = _make_mock_proc([])
        mock_proc.stdout.readline = timeout_readline

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        with pytest.raises(asyncio.TimeoutError):
            await pp.send("prompt", timeout=0.1)

    @pytest.mark.asyncio
    async def test_send_writes_encoded_request_to_stdin(self):
        """Verify that the formatted request is actually written to stdin."""
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)

        result_line = json.dumps({"type": "result", "result": "ok"}).encode() + b"\n"
        mock_proc = _make_mock_proc([result_line])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        await pp.send("my prompt")

        mock_proc.stdin.write.assert_called_once()
        written_bytes = mock_proc.stdin.write.call_args[0][0]
        obj = json.loads(written_bytes.decode())
        assert obj["message"]["content"] == "my prompt"

    @pytest.mark.asyncio
    async def test_is_alive_false_when_process_exited(self):
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)
        mock_proc = _make_mock_proc([])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        # Simulate process exiting
        mock_proc.returncode = 1
        assert not pp.is_alive

    @pytest.mark.asyncio
    async def test_concurrent_sends_are_serialized(self):
        """Two concurrent send() calls must not interleave stdin/stdout."""
        proto = ClaudeStreamProtocol()
        pp = PersistentProcess("claude", proto)

        # Each send gets one result line
        line_a = json.dumps({"type": "result", "result": "A"}).encode() + b"\n"
        line_b = json.dumps({"type": "result", "result": "B"}).encode() + b"\n"
        mock_proc = _make_mock_proc([line_a, line_b])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await pp.start()

        # Fire two sends concurrently; both must succeed
        results = await asyncio.gather(
            pp.send("prompt A"),
            pp.send("prompt B"),
        )
        assert set(results) == {"A", "B"}


# ------------------------------------------------------------------ #
# CLIProcessPool tests                                                #
# ------------------------------------------------------------------ #

class TestCLIProcessPool:

    @pytest.mark.asyncio
    async def test_start_all_and_stop_all(self):
        pool = CLIProcessPool()

        with patch.object(PersistentProcess, "start", new_callable=AsyncMock) as mock_start, \
             patch.object(PersistentProcess, "stop", new_callable=AsyncMock) as mock_stop:
            await pool.start_all()
            assert mock_start.call_count == 2  # claude + codex

            await pool.stop_all()
            assert mock_stop.call_count == 2

    @pytest.mark.asyncio
    async def test_is_warm_false_by_default(self):
        pool = CLIProcessPool()
        assert not pool.is_warm("claude")
        assert not pool.is_warm("codex")
        assert not pool.is_warm("gemini")  # not configured

    @pytest.mark.asyncio
    async def test_is_warm_true_after_start(self):
        """is_warm returns True once the process has been started."""
        pool = CLIProcessPool()

        claude_proc = pool._processes["claude"]
        mock_proc = _make_mock_proc([])

        with patch("cato.orchestrator.cli_process_pool._resolve_cli", return_value=["claude"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await claude_proc.start()

        assert pool.is_warm("claude")

    @pytest.mark.asyncio
    async def test_send_to_succeeds_normally(self):
        """send_to returns the response when the underlying send succeeds."""
        pool = CLIProcessPool()

        async def fake_send(prompt, timeout=60.0):
            return "normal response"

        with patch.object(PersistentProcess, "send", side_effect=fake_send):
            result = await pool.send_to("claude", "hello")

        assert result == "normal response"

    @pytest.mark.asyncio
    async def test_send_to_auto_restarts_on_failure(self):
        pool = CLIProcessPool()

        call_count = 0

        async def fake_send(prompt, timeout=60.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("process died")
            return "recovered response"

        with patch.object(PersistentProcess, "send", side_effect=fake_send), \
             patch.object(PersistentProcess, "restart", new_callable=AsyncMock):
            result = await pool.send_to("claude", "test")

        assert result == "recovered response"

    @pytest.mark.asyncio
    async def test_send_to_raises_when_restart_also_fails(self):
        """When both the initial send AND the post-restart send fail, the
        exception must propagate to the caller."""
        pool = CLIProcessPool()

        async def always_fail(prompt, timeout=60.0):
            raise RuntimeError("permanently dead")

        with patch.object(PersistentProcess, "send", side_effect=always_fail), \
             patch.object(PersistentProcess, "restart", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="permanently dead"):
                await pool.send_to("claude", "test")

    @pytest.mark.asyncio
    async def test_send_to_unknown_cli_raises(self):
        pool = CLIProcessPool()
        with pytest.raises(ValueError, match="gemini"):
            await pool.send_to("gemini", "test")

    @pytest.mark.asyncio
    async def test_start_all_logs_failure_but_continues(self):
        pool = CLIProcessPool()

        start_calls = []

        async def failing_start(self_proc):
            start_calls.append(self_proc.name)
            if self_proc.name == "claude":
                raise FileNotFoundError("claude not on PATH")

        with patch.object(PersistentProcess, "start", failing_start):
            await pool.start_all()  # should not raise

        assert len(start_calls) == 2  # both attempted

    @pytest.mark.asyncio
    async def test_send_to_passes_custom_timeout(self):
        """Timeout parameter is forwarded to PersistentProcess.send()."""
        pool = CLIProcessPool()

        received_timeout = None

        async def capture_timeout(prompt, timeout=60.0):
            nonlocal received_timeout
            received_timeout = timeout
            return "ok"

        with patch.object(PersistentProcess, "send", side_effect=capture_timeout):
            await pool.send_to("claude", "hi", timeout=120.0)

        assert received_timeout == 120.0


# ------------------------------------------------------------------ #
# Singleton test                                                      #
# ------------------------------------------------------------------ #

def test_get_pool_returns_singleton():
    import cato.orchestrator.cli_process_pool as mod
    mod._pool = None  # reset
    p1 = get_pool()
    p2 = get_pool()
    assert p1 is p2
    mod._pool = None  # cleanup


def test_get_pool_creates_new_after_reset():
    import cato.orchestrator.cli_process_pool as mod
    mod._pool = None
    p1 = get_pool()
    mod._pool = None
    p2 = get_pool()
    assert p1 is not p2
    mod._pool = None  # cleanup


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
