#!/usr/bin/env python
"""Write a local custody manifest binding native, sidecar, and dist to HEAD."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1]
REPO = DESKTOP.parent
RELEASE = DESKTOP / "src-tauri" / "target" / "release"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip().lower()
    expected = os.environ.get("CATO_BUILD_SHA", "").strip().lower()
    if not SHA_PATTERN.fullmatch(head) or expected != head:
        raise SystemExit("[build-manifest] CATO_BUILD_SHA must equal the full current HEAD")

    executable = RELEASE / ("cato-desktop.exe" if os.name == "nt" else "cato-desktop")
    staged_sidecars = sorted((DESKTOP / "src-tauri" / "binaries").glob("cato-*"))
    runtime_sidecar = RELEASE / ("cato.exe" if os.name == "nt" else "cato")
    dist_files = sorted(path for path in (DESKTOP / "dist").rglob("*") if path.is_file())
    if (
        not executable.is_file()
        or not runtime_sidecar.is_file()
        or len(staged_sidecars) != 1
        or not dist_files
    ):
        raise SystemExit(
            "[build-manifest] native executable, runtime sidecar, one staged sidecar, and dist are required"
        )
    runtime_sha = sha256(runtime_sidecar)
    staged_sha = sha256(staged_sidecars[0])
    if runtime_sha != staged_sha or runtime_sidecar.stat().st_size != staged_sidecars[0].stat().st_size:
        raise SystemExit("[build-manifest] runtime sidecar differs from the staged bundle sidecar")

    payload = {
        "schema": 2,
        "source_sha": head,
        "native": {"path": executable.name, "sha256": sha256(executable), "bytes": executable.stat().st_size},
        "sidecar": {
            "path": runtime_sidecar.name,
            "sha256": runtime_sha,
            "bytes": runtime_sidecar.stat().st_size,
        },
        "staged_sidecar": {
            "path": staged_sidecars[0].name,
            "sha256": staged_sha,
            "bytes": staged_sidecars[0].stat().st_size,
        },
        "dist": {
            str(path.relative_to(DESKTOP / "dist")).replace("\\", "/"): sha256(path)
            for path in dist_files
        },
    }
    target = RELEASE / "cato-build-manifest.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[build-manifest] PASS {head} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
