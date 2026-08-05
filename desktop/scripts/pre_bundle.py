#!/usr/bin/env python
"""
Preflight hook for `tauri build`.

This keeps the release build repeatable on Windows by:
1. stopping any running `cato-desktop` release processes,
2. verifying the target output directory is writable, and
3. staging the frozen Python sidecar.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


def fail(message: str) -> "NoReturn":
    print(f"[pre_bundle] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def stop_running_release_binary(release_exe: Path) -> None:
    if sys.platform.startswith("win"):
        result = subprocess.run(
            ["taskkill", "/F", "/IM", release_exe.name],
            capture_output=True,
            text=True,
            check=False,
        )
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if result.returncode == 0:
            print(f"[pre_bundle] stopped running {release_exe.name} processes")
            time.sleep(1.0)
            return
        if "not found" in combined or "no running instance" in combined:
            return
        fail(
            f"failed to stop running {release_exe.name} processes. "
            f"taskkill output:\n{result.stdout}{result.stderr}"
        )

    pkill = shutil.which("pkill")
    if pkill:
        subprocess.run([pkill, "-f", release_exe.stem], check=False)


def ensure_output_dir_writable(release_dir: Path, release_exe: Path) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)

    probe = release_dir / f".cato-write-test-{uuid.uuid4().hex}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        fail(f"release output directory is not writable: {release_dir} ({exc})")

    if not release_exe.exists():
        return

    temp_name = release_exe.with_name(f"{release_exe.stem}.lockcheck-{uuid.uuid4().hex}{release_exe.suffix}")
    try:
        release_exe.rename(temp_name)
        temp_name.rename(release_exe)
    except OSError as exc:
        fail(
            f"{release_exe} is still locked after preflight cleanup. "
            "Close any running Cato desktop windows and retry. "
            f"Underlying error: {exc}"
        )


def run_stage_sidecar(script_path: Path) -> None:
    subprocess.run([sys.executable, str(script_path)], check=True)


def main() -> int:
    desktop_dir = Path(__file__).resolve().parents[1]
    release_dir = desktop_dir / "src-tauri" / "target" / "release"
    release_exe = release_dir / ("cato-desktop.exe" if sys.platform.startswith("win") else "cato-desktop")

    stop_running_release_binary(release_exe)
    ensure_output_dir_writable(release_dir, release_exe)
    run_stage_sidecar(desktop_dir / "scripts" / "stage_sidecar.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
