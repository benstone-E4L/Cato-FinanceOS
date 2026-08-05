"""
cato/tools/outreach_bridge.py — Invoke external cold-outreach engines from Cato (dry-run default).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

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


def _resolve_engine_root(engine: str, policy_paths: dict[str, str]) -> Optional[Path]:
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

    # Prefer explicit runner scripts if present
    runners = [
        root / "run_batch.py",
        root / "run.py",
        root / "cli.py",
        root / "main.py",
    ]
    runner = next((p for p in runners if p.is_file()), None)

    if runner is not None:
        cmd = [
            sys.executable,
            str(runner),
            "--contact-id",
            contact_id,
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "conduit_outreach_pipeline",
            "run-one-json",
            "--contact-id",
            contact_id,
        ]

    if artifact:
        cmd.extend(["--artifact", artifact])
    if dry_run:
        cmd.append("--dry-run")

    if dry_run and runner is None and not (root / "src").is_dir():
        return json.dumps({
            "ok": True,
            "mode": "dry_run",
            "engine_root": str(root),
            "contact_id": contact_id,
            "artifact_path": artifact,
            "runner": None,
            "message": "Dry-run only — outreach package layout not found.",
        })

    from ..core.outreach_credentials import build_outreach_env

    env = build_outreach_env(engine_root=root, base=os.environ)
    env["CATO_OUTREACH_DRY_RUN"] = "1" if dry_run else "0"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        return json.dumps({
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (stdout_b or b"").decode("utf-8", errors="replace")[:2000],
            "stderr": (stderr_b or b"").decode("utf-8", errors="replace")[:1000],
            "cmd": cmd,
        })
    except asyncio.TimeoutError:
        return json.dumps({"ok": False, "error": "timeout", "cmd": cmd})
    except Exception as exc:
        return json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc), "cmd": cmd})
