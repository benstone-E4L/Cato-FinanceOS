"""Fail-closed one-shot stdin bridge to the external outreach engine."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_OUTREACH_TIMEOUT_SECONDS = 120.0

OUTREACH_SCHEMA = {
    "name": "outreach.run",
    "description": (
        "Run ConduitScore cold-outreach pipeline CLI for one contact. "
        "Defaults to dry_run=true (no send). Set engine path in night-shift-policy.yaml."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contact_id": {"type": "string"},
            "artifact_path": {"type": "string"},
            "engine": {
                "type": "string",
                "enum": ["conduit_outreach_pipeline", "reverse_funnel_outreach", "auto"],
            },
            "dry_run": {"type": "boolean"},
        },
        "required": ["contact_id"],
    },
}


def _resolve_engine_root(engine: str, policy_paths: dict[str, str]) -> Path | None:
    key = "outreach_engine_cli" if engine == "auto" else f"{engine}_root"
    raw = policy_paths.get(key) or policy_paths.get("outreach_engine_cli") or ""
    if raw:
        p = Path(raw).expanduser()
        if p.exists():
            return p if p.is_dir() else p.parent
    # Convention: sibling folders next to Cato repo parent
    desktop = Path(__file__).resolve().parents[2].parent
    for name in (
        "conduit_outreach_pipeline",
        "reverse_funnel_outreach",
        engine if engine != "auto" else "",
    ):
        if not name:
            continue
        cand = desktop / name
        if cand.is_dir():
            return cand
    return None


async def execute_outreach_run(args: dict[str, Any]) -> str:
    from ..core.night_shift_policy import assert_skill_allowed, load_night_shift_policy

    dry_run = args.get("dry_run", True)
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("1", "true", "yes")

    try:
        assert_skill_allowed("outreach.run", {**args, "dry_run": dry_run})
    except PermissionError as exc:
        return json.dumps({"ok": False, "error": "policy_blocked", "message": str(exc)})

    policy = load_night_shift_policy()
    engine = str(args.get("engine") or "auto")
    contact_id = str(args.get("contact_id") or "")
    artifact = str(args.get("artifact_path") or "")

    root = _resolve_engine_root(engine, policy.paths)
    if root is None:
        if dry_run:
            return json.dumps({
                "ok": True,
                "mode": "dry_run",
                "engine_root": None,
                "contact_id": contact_id,
                "message": (
                    "Dry-run only — outreach engine path not configured. "
                    "Set paths.outreach_engine_cli in night-shift-policy.yaml."
                ),
            })
        return json.dumps({
            "ok": False,
            "error": "engine_not_configured",
            "message": (
                "Set paths.outreach_engine_cli in docs/night-shift-policy.yaml "
                "to your outreach repo root."
            ),
            "hint_paths_checked": ["Desktop/conduit_outreach_pipeline", "Desktop/reverse_funnel_outreach"],
        })

    # Only this entrypoint implements the versioned stdin credential protocol.
    runner = root / "run_batch.py"
    if not runner.is_file():
        return json.dumps({
            "ok": False,
            "error": "secure_outreach_entrypoint_unavailable",
            "message": "The outreach engine does not expose the approved stdin credential channel.",
        })

    cmd = [sys.executable, str(runner), "--contact-id", contact_id]

    if artifact:
        cmd.extend(["--artifact", artifact])
    if dry_run:
        cmd.append("--dry-run")

    from ..core.outreach_credentials import (
        OutreachCredentialError,
        build_credential_envelope,
        build_outreach_env,
    )

    try:
        envelope, credential_values = build_credential_envelope()
    except OutreachCredentialError as exc:
        return json.dumps({
            "ok": False,
            "error": "outreach_credentials_unavailable",
            "message": str(exc),
        })

    child_env = build_outreach_env()
    child_env["CATO_OUTREACH_DRY_RUN"] = "1" if dry_run else "0"
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(root),
        env=child_env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=envelope), timeout=_OUTREACH_TIMEOUT_SECONDS
        )
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return json.dumps({
            "ok": False,
            "error": "outreach_timeout",
            "message": "The outreach child exceeded its bounded runtime.",
        })
    finally:
        # Drop the parent's serialized copy as soon as the child has consumed stdin.
        envelope = b""

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if any(value and (value in stdout_text or value in stderr_text) for value in credential_values):
        return json.dumps({
            "ok": False,
            "error": "outreach_child_credential_output",
            "message": "The outreach child emitted protected data; output was suppressed.",
        })

    try:
        result = json.loads(stdout_text.splitlines()[-1]) if stdout_text else None
    except (IndexError, json.JSONDecodeError):
        result = None
    if not isinstance(result, dict):
        return json.dumps({
            "ok": False,
            "error": "outreach_child_invalid_response",
            "message": "The outreach child returned no valid JSON response.",
            "returncode": proc.returncode,
        })
    if proc.returncode != 0 and result.get("ok") is not False:
        return json.dumps({
            "ok": False,
            "error": "outreach_child_failed",
            "message": "The outreach child exited unsuccessfully.",
            "returncode": proc.returncode,
        })
    return json.dumps(result)
