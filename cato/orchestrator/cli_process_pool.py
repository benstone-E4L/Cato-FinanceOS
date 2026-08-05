"""
Persistent CLI Process Pool for fast multi-LLM invocation.

Keeps Claude and Codex CLI processes alive as long-running daemons,
sending prompts via stdin/stdout instead of spawning new subprocesses.

- Claude: ``--input-format stream-json --output-format stream-json``
- Codex: ``codex mcp-server`` (JSON-RPC over stdio)
- Gemini: no daemon mode — uses fast subprocess with ``-e none``

Usage::

    pool = get_pool()
    await pool.start_all()
    text = await pool.send_to("claude", "Hello")
    await pool.stop_all()
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from cato.orchestrator.cli_invoker import _resolve_cli

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Protocol layer                                                      #
# ------------------------------------------------------------------ #

class CLIProtocol(abc.ABC):
    """Base class defining the wire protocol for a persistent CLI."""

    @abc.abstractmethod
    def spawn_args(self) -> List[str]:
        """Return the args list to start the long-lived process."""

    @abc.abstractmethod
    def format_request(self, prompt: str) -> str:
        """Encode *prompt* into the wire format (newline-terminated)."""

    @abc.abstractmethod
    def is_response_complete(self, accumulated: str) -> bool:
        """Return True when *accumulated* stdout contains a full response."""

    @abc.abstractmethod
    def extract_text(self, accumulated: str) -> str:
        """Pull the human-readable response text from *accumulated*."""

    def initialization_message(self) -> Optional[str]:
        """Optional handshake message to send right after spawning."""
        return None

    def initialization_complete(self, accumulated: str) -> bool:
        """Return True when the initialization handshake response is received."""
        return True

    def post_initialization_message(self) -> Optional[str]:
        """Optional message to send after handshake completes (e.g. MCP ``initialized``)."""
        return None


class ClaudeStreamProtocol(CLIProtocol):
    """Claude CLI in persistent stream-json mode."""

    def spawn_args(self) -> List[str]:
        base = _resolve_cli("claude")
        return base + [
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--no-session-persistence",
        ]

    def format_request(self, prompt: str) -> str:
        msg = {
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }
        return json.dumps(msg) + "\n"

    def is_response_complete(self, accumulated: str) -> bool:
        for line in accumulated.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "result":
                    return True
            except (json.JSONDecodeError, TypeError):
                continue
        return False

    def extract_text(self, accumulated: str) -> str:
        parts: list[str] = []
        for line in accumulated.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            # assistant text messages
            if obj.get("type") == "assistant" and "message" in obj:
                content = obj["message"].get("content", "")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
            # result message — extract final text
            if obj.get("type") == "result":
                result_text = obj.get("result", "")
                if isinstance(result_text, str) and result_text:
                    parts.append(result_text)
        return "\n".join(parts) if parts else accumulated


class CodexMCPProtocol(CLIProtocol):
    """Codex CLI in MCP server mode (JSON-RPC over stdio)."""

    _next_id: int = 0

    def _id(self) -> int:
        CodexMCPProtocol._next_id += 1
        return CodexMCPProtocol._next_id

    def spawn_args(self) -> List[str]:
        base = _resolve_cli("codex")
        return base + ["mcp-server"]

    def initialization_message(self) -> Optional[str]:
        msg = {
            "jsonrpc": "2.0",
            "id": self._id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "cato", "version": "0.1.0"},
            },
        }
        return json.dumps(msg) + "\n"

    def initialization_complete(self, accumulated: str) -> bool:
        for line in accumulated.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "result" in obj:
                    return True
            except (json.JSONDecodeError, TypeError):
                continue
        return False

    def post_initialization_message(self) -> Optional[str]:
        """MCP spec requires an ``initialized`` notification after the handshake."""
        msg = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        return json.dumps(msg) + "\n"

    def format_request(self, prompt: str) -> str:
        msg = {
            "jsonrpc": "2.0",
            "id": self._id(),
            "method": "tools/call",
            "params": {
                "name": "codex",
                "arguments": {"prompt": prompt},
            },
        }
        return json.dumps(msg) + "\n"

    def is_response_complete(self, accumulated: str) -> bool:
        for line in accumulated.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "result" in obj or "error" in obj:
                    return True
            except (json.JSONDecodeError, TypeError):
                continue
        return False

    def extract_text(self, accumulated: str) -> str:
        for line in reversed(accumulated.strip().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            # JSON-RPC result
            result = obj.get("result")
            if result and isinstance(result, dict):
                content = result.get("content", [])
                if isinstance(content, list):
                    texts = [
                        c.get("text", "")
                        for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    if texts:
                        return "\n".join(texts)
            # JSON-RPC error
            error = obj.get("error")
            if error:
                return f"[Codex MCP Error] {error.get('message', str(error))}"
        return accumulated


# ------------------------------------------------------------------ #
# Persistent process wrapper                                          #
# ------------------------------------------------------------------ #

class PersistentProcess:
    """Wraps a single long-lived CLI subprocess."""

    def __init__(self, name: str, protocol: CLIProtocol) -> None:
        self.name = name
        self.protocol = protocol
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        """Spawn the subprocess and perform the initialization handshake."""
        if self.is_alive:
            return

        args = self.protocol.spawn_args()
        logger.info("Starting persistent %s process: %s", self.name, " ".join(args))

        # Unset CLAUDECODE so claude CLI doesn't refuse with "nested session" error
        import os as _os
        env = {k: v for k, v in _os.environ.items() if k != "CLAUDECODE"}

        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Optional initialization handshake
        init_msg = self.protocol.initialization_message()
        if init_msg is not None:
            assert self._proc.stdin is not None
            self._proc.stdin.write(init_msg.encode())
            await self._proc.stdin.drain()

            accumulated = ""
            assert self._proc.stdout is not None
            try:
                while not self.protocol.initialization_complete(accumulated):
                    line = await asyncio.wait_for(
                        self._proc.stdout.readline(), timeout=30.0,
                    )
                    if not line:
                        break
                    accumulated += line.decode("utf-8", errors="replace")
            except asyncio.TimeoutError:
                logger.warning("%s initialization timed out", self.name)

            # MCP spec requires an "initialized" notification after the
            # handshake response, before any tool calls can be sent.
            post_init = self.protocol.post_initialization_message()
            if post_init is not None:
                self._proc.stdin.write(post_init.encode())
                await self._proc.stdin.drain()

        logger.info("Persistent %s process started (pid=%s)", self.name,
                     self._proc.pid if self._proc else "?")

    async def stop(self) -> None:
        """Gracefully terminate the subprocess."""
        if self._proc is None:
            return
        try:
            if self._proc.stdin and not self._proc.stdin.is_closing():
                self._proc.stdin.close()
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        except ProcessLookupError:
            pass
        finally:
            logger.info("Persistent %s process stopped", self.name)
            self._proc = None

    async def restart(self) -> None:
        """Stop then start."""
        await self.stop()
        await self.start()

    async def send(self, prompt: str, timeout: float = 60.0) -> str:
        """Send *prompt* and return the response text.

        Serializes concurrent callers via an asyncio.Lock so that
        interleaved stdin/stdout is impossible.
        """
        async with self._lock:
            if not self.is_alive:
                raise RuntimeError(f"{self.name} process is not running")

            assert self._proc is not None
            assert self._proc.stdin is not None
            assert self._proc.stdout is not None

            request = self.protocol.format_request(prompt)
            try:
                self._proc.stdin.write(request.encode())
                await self._proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise RuntimeError(f"{self.name} stdin closed unexpectedly") from exc

            accumulated = ""
            try:
                while not self.protocol.is_response_complete(accumulated):
                    line = await asyncio.wait_for(
                        self._proc.stdout.readline(), timeout=timeout,
                    )
                    if not line:
                        break  # EOF
                    accumulated += line.decode("utf-8", errors="replace")
            except asyncio.TimeoutError:
                logger.warning("%s send timed out after %.1fs", self.name, timeout)
                raise

            return self.protocol.extract_text(accumulated)


# ------------------------------------------------------------------ #
# Process pool                                                        #
# ------------------------------------------------------------------ #

class CLIProcessPool:
    """Manages persistent CLI processes for Claude and Codex."""

    def __init__(self) -> None:
        self._processes: Dict[str, PersistentProcess] = {
            "claude": PersistentProcess("claude", ClaudeStreamProtocol()),
            "codex": PersistentProcess("codex", CodexMCPProtocol()),
        }

    async def start_all(self) -> None:
        """Start all persistent processes. Failures are logged, not raised."""
        for name, proc in self._processes.items():
            try:
                await proc.start()
            except Exception as exc:
                logger.warning("Failed to start persistent %s: %s", name, exc)

    async def stop_all(self) -> None:
        """Stop all persistent processes."""
        for proc in self._processes.values():
            await proc.stop()

    async def restart(self, cli_name: str) -> None:
        """Restart a single CLI backend by name.

        Used by the /api/cli/{name}/restart endpoint and desktop UI buttons.
        """
        proc = self._processes.get(cli_name)
        if proc is None:
            raise ValueError(f"No persistent process configured for {cli_name!r}")
        await proc.restart()

    async def warm_up(self, cli_name: str) -> None:
        """Ensure a single CLI backend is started without forcing a restart."""
        proc = self._processes.get(cli_name)
        if proc is None:
            raise ValueError(f"No persistent process configured for {cli_name!r}")
        await proc.start()

    def is_warm(self, cli_name: str) -> bool:
        """Return True if *cli_name* has a running persistent process."""
        proc = self._processes.get(cli_name)
        return proc is not None and proc.is_alive

    async def send_to(self, cli_name: str, prompt: str, timeout: float = 60.0) -> str:
        """Send *prompt* to the named CLI, auto-restarting on failure."""
        proc = self._processes.get(cli_name)
        if proc is None:
            raise ValueError(f"No persistent process configured for {cli_name!r}")

        try:
            return await proc.send(prompt, timeout=timeout)
        except Exception:
            logger.warning("Persistent %s failed, attempting restart", cli_name)
            try:
                await proc.restart()
                return await proc.send(prompt, timeout=timeout)
            except Exception as exc:
                logger.error("Persistent %s restart also failed: %s", cli_name, exc)
                raise


# ------------------------------------------------------------------ #
# Module-level singleton                                              #
# ------------------------------------------------------------------ #

_pool: Optional[CLIProcessPool] = None


def get_pool() -> CLIProcessPool:
    """Return the module-level singleton CLIProcessPool."""
    global _pool
    if _pool is None:
        _pool = CLIProcessPool()
    return _pool
