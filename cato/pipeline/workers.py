from __future__ import annotations

import abc
import asyncio
import time
from pathlib import Path
from typing import Optional

from cato.orchestrator.cli_invoker import _resolve_cli
from cato.orchestrator.confidence_extractor import extract_confidence
from cato.vault_bootstrap import safe_subprocess_environment

from .models import WorkerAssignment, WorkerResult


class WorkerAdapter(abc.ABC):
    name: str

    @abc.abstractmethod
    async def run(self, assignment: WorkerAssignment) -> WorkerResult:
        raise NotImplementedError


async def _run_cli(
    args: list[str],
    *,
    cwd: Optional[Path],
    timeout_sec: float,
) -> tuple[int, str, str, float]:
    env = safe_subprocess_environment()
    start = time.time()
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdin=None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise
    latency_ms = (time.time() - start) * 1000
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
        latency_ms,
    )


class _SimpleCLIAdapter(WorkerAdapter):
    cli_name: str
    prompt_mode: str

    def __init__(self, cli_name: str, prompt_mode: str) -> None:
        self.name = cli_name
        self.cli_name = cli_name
        self.prompt_mode = prompt_mode

    async def run(self, assignment: WorkerAssignment) -> WorkerResult:
        try:
            cli = _resolve_cli(self.cli_name)
        except FileNotFoundError as exc:
            return WorkerResult(
                worker=self.name,
                success=False,
                response="",
                source="pipeline",
                degraded=True,
                error=str(exc),
            )

        if self.prompt_mode == "print":
            args = cli + ["-p", assignment.prompt]
        else:
            args = cli + [self.prompt_mode, assignment.prompt]

        try:
            code, stdout, stderr, latency_ms = await _run_cli(
                args,
                cwd=assignment.cwd,
                timeout_sec=assignment.timeout_sec,
            )
        except asyncio.TimeoutError:
            return WorkerResult(
                worker=self.name,
                success=False,
                response="",
                source="subprocess",
                latency_ms=assignment.timeout_sec * 1000,
                error=f"{self.name} timed out after {assignment.timeout_sec:.0f}s",
            )

        text = stdout or stderr
        return WorkerResult(
            worker=self.name,
            success=(code == 0),
            response=text,
            source="subprocess",
            latency_ms=latency_ms,
            degraded=(code != 0),
            error="" if code == 0 else (stderr or stdout or f"{self.name} exited with code {code}"),
        )


class ClaudeWorkerAdapter(_SimpleCLIAdapter):
    def __init__(self) -> None:
        super().__init__("claude", "print")


class GeminiWorkerAdapter(_SimpleCLIAdapter):
    def __init__(self) -> None:
        super().__init__("gemini", "print")


class CodexWorkerAdapter(_SimpleCLIAdapter):
    def __init__(self) -> None:
        super().__init__("codex", "exec")


def get_worker_registry() -> dict[str, WorkerAdapter]:
    return {
        "claude": ClaudeWorkerAdapter(),
        "gemini": GeminiWorkerAdapter(),
        "codex": CodexWorkerAdapter(),
    }
