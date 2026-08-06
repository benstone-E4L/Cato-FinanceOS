"""
cato/tools/shell.py — Shell execution tool with configurable safety modes.

Modes:
  sandbox : subprocess in temp dir, no shell=True, args parsed via shlex
  gateway : allowlist-based filtering (default — safe for general use)
  full    : unrestricted asyncio.create_subprocess_shell

All executions are logged to ~/.cato/logs/shell_audit.log.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..platform import get_data_dir

logger = logging.getLogger(__name__)

_CATO_DIR = get_data_dir()
_AUDIT_LOG = _CATO_DIR / "logs" / "shell_audit.log"
_APPROVALS_FILE = _CATO_DIR / "exec-approvals.json"
_MAX_OUTPUT_CHARS = 8000
_MAX_TIMEOUT = 300


def _take_unrestricted_grant(args: dict[str, Any]) -> bool:
    """True exactly once per human-approved unrestricted shell call.

    Fail-closed: any failure to reach the approval machinery answers False.
    """
    try:
        from ..core.approval_policy import take_execution_grant
        return bool(take_execution_grant("shell", args))
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Execution-grant lookup failed (%s); refusing full mode.", exc)
        return False


def _default_workspace() -> Path:
    """Resolve the shell tool's default cwd, honouring ``CATO_WORKSPACE_DIR``.

    BH-010 — bridge config.yaml's `workspace_dir` into the shell tool.
    Without this the tool's default cwd (and the clamp boundary for
    gateway/sandbox modes) drifts away from the operator-configured path.
    """
    custom = os.environ.get("CATO_WORKSPACE_DIR")
    if custom:
        return Path(custom).expanduser().resolve()
    return _CATO_DIR / "workspace"


class ShellTool:
    """Execute shell commands with configurable safety modes.

    Modes:
      sandbox: subprocess with no network, limited filesystem access (safest)
      gateway: subprocess with allowlist of permitted commands
      full:    unrestricted subprocess (only for trusted use)

    Default: gateway mode
    """

    DEFAULT_ALLOWLIST: list[str] = [
        "ls", "cat", "head", "tail", "grep", "find", "wc", "echo", "printf",
        "python3", "python", "git",
        "mkdir", "cp", "mv", "chmod", "pwd", "env", "which", "date",
        "sort", "uniq", "sed", "awk", "tr", "cut", "tee", "touch",
        # NOTE: rm / shell hosts (cmd, powershell, pwsh) are NOT default —
        # on Windows gateway mode routes through create_subprocess_shell, so an
        # allowlisted host would execute an attacker-controlled payload string.
        # Opt them in via ~/.cato/exec-approvals.json (EXTENDED) if required.
    ]

    # Extended allowlist — opt-in only, NOT in DEFAULT_ALLOWLIST
    # Add these to ~/.cato/exec-approvals.json if you need them
    EXTENDED_ALLOWLIST: list[str] = [
        "curl", "wget", "pip", "pip3", "npm", "node",
        "rm",
        "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    ]

    def __init__(self) -> None:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self, args: dict[str, Any]) -> str:
        """Dispatch from agent_loop tool registry (receives raw args dict).

        SECURITY — ``mode`` is a SCOPE SELECTOR, not a caller preference.
        ``mode="full"`` is an unrestricted ``create_subprocess_shell`` with no
        allowlist and no workspace clamp, so an arbitrary caller (a model tool
        call, a cron job's stored args, an HTTP body) must not be able to
        select it just by asking. It is honoured from exactly two sources,
        neither of which is expressible as a caller-supplied argument:

          1. a single-use execution grant minted by
             ``OutboundApprovalStore.consume()`` when a human approved this
             exact command, or
          2. the operator's own ``powershell_full_mode`` config opt-in, and
             only for a PowerShell invocation.

        Without one of those, an unrestricted request FAILS CLOSED with an
        explicit refusal rather than being silently downgraded — the same
        shape as cato/tools/integration_tool.py's live-write refusal.
        """
        command = args.get("command", "")
        timeout = min(int(args.get("timeout", 30)), _MAX_TIMEOUT)
        cwd = args.get("cwd") or str(_default_workspace())

        try:
            first_word = shlex.split(command)[0].lower() if command.strip() else ""
        except ValueError:
            first_word = command.strip().split()[0].lower() if command.strip() else ""
        base_cmd = Path(first_word).name
        is_powershell = base_cmd in ("powershell", "powershell.exe", "pwsh", "pwsh.exe")

        requested = str(args.get("mode") or "gateway").strip().lower()
        operator_full = False
        if is_powershell:
            # Auto-upgrade to full mode for PowerShell commands only when the
            # operator has explicitly opted in via powershell_full_mode=true.
            from ..config import CatoConfig
            cfg = CatoConfig.load()
            operator_full = bool(getattr(cfg, "powershell_full_mode", False))

        if requested == "full" or operator_full:
            if operator_full:
                mode = "full"
            elif _take_unrestricted_grant(args):
                mode = "full"
            else:
                self._audit("full", command, -1, blocked=True)
                return json.dumps({
                    "error": (
                        "[SHELL] Unrestricted shell (mode='full') requires a "
                        "human-approved execution ticket. 'mode' in call "
                        "arguments cannot authorize it."
                    ),
                    "approval_required": True,
                    "requested_mode": "full",
                })
        else:
            mode = requested

        # Only clamp cwd to workspace root in sandbox/gateway mode.
        # Full mode (PowerShell) may need to operate anywhere on the system.
        if mode != "full":
            workspace_root = _default_workspace()
            if cwd:
                cwd_path = Path(cwd).resolve()
                try:
                    cwd_path.relative_to(workspace_root.resolve())
                except ValueError:
                    cwd = str(workspace_root)

        try:
            result = await self._run(command=command, mode=mode, timeout=timeout, cwd=cwd)
        except PermissionError as exc:
            # Fail closed with a structured refusal so callers/agents never see
            # an uncaught exception as a soft signal to retry unrestricted.
            return json.dumps({
                "error": str(exc),
                "blocked": True,
                "approval_required": True,
                "requested_mode": mode,
            })
        return json.dumps(result)

    async def _run(
        self,
        command: str,
        mode: str = "gateway",
        timeout: int = 30,
        cwd: Optional[str] = None,
    ) -> dict:
        """
        Execute a shell command.

        Args:
            command: Shell command string
            mode: "sandbox" | "gateway" | "full"
            timeout: Max seconds (default 30, max 300)
            cwd: Working directory (default: ~/.cato/workspace/)

        Returns:
            {"stdout": str, "stderr": str, "returncode": int, "truncated": bool}
        """
        work_dir = Path(cwd or _default_workspace())
        work_dir.mkdir(parents=True, exist_ok=True)

        if mode == "gateway":
            allowlist = self._load_allowlist()
            try:
                first_word = shlex.split(command)[0] if command.strip() else ""
            except ValueError:
                # Unbalanced quotes etc. — refuse rather than guess a first token.
                self._audit(mode, command, -1, blocked=True)
                raise PermissionError(
                    "Command could not be parsed for gateway allowlist check "
                    "(fail-closed)."
                )
            base_cmd = Path(first_word).name.lower()  # strip path prefix if any
            if base_cmd not in allowlist and base_cmd.removesuffix(".exe") not in allowlist:
                self._audit(mode, command, -1, blocked=True)
                raise PermissionError(
                    f"Command '{base_cmd}' not in gateway allowlist. "
                    f"Allowed: {sorted(allowlist)}"
                )

            # C-2: Windows gateway executes the *full* string under shell
            # interpretation. First-token allowlisting is not enough — refuse
            # irreversible / high-stakes payloads (incl. quote/escape/concat
            # dodges that _classify_shell now catches). Full mode + execution
            # grant remains the only escape hatch.
            from ..safety import RiskTier, _classify_shell
            risk = _classify_shell({"command": command})
            if risk >= RiskTier.IRREVERSIBLE:
                self._audit(mode, command, -1, blocked=True)
                raise PermissionError(
                    f"Gateway mode refuses {risk.name} shell payload without an "
                    f"execution grant (fail-closed). Re-submit via approved "
                    f"mode='full' after human approval."
                )

        try:
            if mode == "sandbox":
                result = await self._run_sandbox(command, timeout, work_dir)
            elif mode == "full":
                result = await self._run_full(command, timeout, work_dir)
            else:
                # gateway uses same subprocess approach as sandbox but in cwd
                result = await self._run_sandbox(command, timeout, work_dir)
        except asyncio.TimeoutError:
            self._audit(mode, command, -1, blocked=False, timed_out=True)
            raise TimeoutError(f"Command exceeded {timeout}s timeout: {command!r}")

        self._audit(mode, command, result["returncode"])
        return result

    # ------------------------------------------------------------------
    # Subprocess runners
    # ------------------------------------------------------------------

    async def _run_sandbox(self, command: str, timeout: int, cwd: Path) -> dict:
        """Run via subprocess with shlex-parsed args (no shell=True on POSIX).

        On Windows, CMD builtins (echo, dir, type, etc.) are not filesystem
        executables — create_subprocess_exec raises WinError 2 for them.
        Route through cmd.exe on Windows so builtins work correctly while
        still honouring the gateway allowlist (checked before this call).
        """
        try:
            cmd_args = shlex.split(command)
        except ValueError as exc:
            return {"stdout": "", "stderr": f"shlex parse error: {exc}", "returncode": 1, "truncated": False}

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = cwd if cwd.exists() else Path(tmp)
            if sys.platform == "win32":
                # cmd.exe handles builtins; allowlist check already validated first word
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(run_dir),
                    env=self._minimal_env(),
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(run_dir),
                    env=self._minimal_env(),
                )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                raise

        return self._build_result(stdout_b, stderr_b, proc.returncode)

    async def _run_full(self, command: str, timeout: int, cwd: Path) -> dict:
        """Run via asyncio.create_subprocess_shell — unrestricted."""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd.exists() else None,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise

        return self._build_result(stdout_b, stderr_b, proc.returncode)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_result(self, stdout_b: bytes, stderr_b: bytes, returncode: int) -> dict:
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        combined_len = len(stdout) + len(stderr)
        truncated = combined_len > _MAX_OUTPUT_CHARS

        if truncated:
            keep = max(0, _MAX_OUTPUT_CHARS - len(stderr))
            suffix = f"\n[... truncated {combined_len - _MAX_OUTPUT_CHARS} chars ...]"
            stdout = stdout[:keep] + suffix

        return {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "truncated": truncated,
        }

    def _load_allowlist(self) -> set[str]:
        if _APPROVALS_FILE.exists():
            try:
                data = json.loads(_APPROVALS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return set(data)
            except (json.JSONDecodeError, OSError):
                pass
        return set(self.DEFAULT_ALLOWLIST)

    @staticmethod
    def _minimal_env() -> dict[str, str]:
        """Return a trimmed environment for sandbox execution."""
        if sys.platform == "win32":
            # cmd.exe requires SYSTEMROOT/COMSPEC to start; PATHEXT for .exe/.cmd resolution
            keep = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC",
                    "WINDIR", "TEMP", "TMP", "USERPROFILE", "USERNAME"}
        else:
            keep = {"PATH", "HOME", "USER", "LANG", "TERM", "TMPDIR", "TMP", "TEMP"}
        return {k: v for k, v in os.environ.items() if k in keep}

    def _audit(
        self,
        mode: str,
        command: str,
        returncode: int,
        blocked: bool = False,
        timed_out: bool = False,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        status = "BLOCKED" if blocked else ("TIMEOUT" if timed_out else "OK")
        line = f"{ts} | mode={mode} | rc={returncode} | status={status} | cmd={command!r}\n"
        try:
            with _AUDIT_LOG.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            logger.warning("Could not write shell audit log: %s", _AUDIT_LOG)
