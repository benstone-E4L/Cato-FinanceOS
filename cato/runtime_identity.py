"""Immutable source identity captured when the daemon process starts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _valid(value: object) -> str | None:
    candidate = str(value or "").strip().lower()
    return candidate if _SHA.fullmatch(candidate) else None


def _packaged_identity() -> str | None:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    identity = bundle_root / "cato_build_identity.json"
    try:
        return _valid(json.loads(identity.read_text(encoding="utf-8")).get("source_sha"))
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _repository_identity() -> str | None:
    repo = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _valid(completed.stdout)


# Capture exactly once. A process started at an older revision cannot become
# "current" merely because the checkout changes underneath it.
_STARTUP_SOURCE_SHA = (
    _valid(os.environ.get("CATO_BUILD_SHA"))
    or _packaged_identity()
    or _repository_identity()
    or "unknown"
)


def runtime_source_sha() -> str:
    return _STARTUP_SOURCE_SHA
