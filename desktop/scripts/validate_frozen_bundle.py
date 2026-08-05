#!/usr/bin/env python
"""
Validate the real frozen Cato daemon sidecar in an isolated profile.

This simulates a clean-machine launch by:
1. building the real PyInstaller sidecar,
2. copying it into a temporary install directory,
3. launching it with isolated APPDATA/HOME paths, and
4. verifying that the frozen daemon serves /health and can shut down cleanly.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import stage_sidecar


def fail(message: str) -> "NoReturn":
    print(f"[validate_frozen_bundle] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        timeout=timeout,
        text=True,
        capture_output=True,
        check=True,
    )


def staged_sidecar_path(desktop_dir: Path) -> Path:
    triple = stage_sidecar.target_triple()
    return desktop_dir / "src-tauri" / "binaries" / stage_sidecar.output_name(triple)


def build_sidecar(desktop_dir: Path, build_timeout: int) -> Path:
    sidecar_path = staged_sidecar_path(desktop_dir)
    print(f"[validate_frozen_bundle] staging real frozen sidecar: {sidecar_path.name}")
    run(
        [sys.executable, str(desktop_dir / "scripts" / "stage_sidecar.py")],
        cwd=desktop_dir.parent,
        timeout=build_timeout,
    )
    if not sidecar_path.exists():
        fail(f"staged sidecar missing after build: {sidecar_path}")
    return sidecar_path


def build_validation_env(profile_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("VIRTUAL_ENV", None)
    env.pop("CATO_SIDECAR_SOURCE", None)

    home_dir = profile_root / "home"
    appdata_dir = profile_root / "appdata" / "Roaming"
    local_appdata_dir = profile_root / "appdata" / "Local"
    home_dir.mkdir(parents=True, exist_ok=True)
    appdata_dir.mkdir(parents=True, exist_ok=True)
    local_appdata_dir.mkdir(parents=True, exist_ok=True)

    env["HOME"] = str(home_dir)
    env["USERPROFILE"] = str(home_dir)
    env["APPDATA"] = str(appdata_dir)
    env["LOCALAPPDATA"] = str(local_appdata_dir)
    return env


def best_effort_cli_probe(binary_path: Path, install_dir: Path, env: dict[str, str]) -> None:
    """Probe the frozen CLI if it responds quickly; do not fail validation on banner quirks."""
    try:
        result = subprocess.run(
            [str(binary_path), "--version"],
            cwd=str(install_dir),
            env=env,
            timeout=20,
            text=True,
            capture_output=True,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("[validate_frozen_bundle] version probe timed out; continuing with daemon launch validation")
        return

    output = (result.stdout or result.stderr or "").strip()
    if output:
        print(f"[validate_frozen_bundle] version probe: {output}")
    else:
        print(
            "[validate_frozen_bundle] version probe returned no banner output; "
            "continuing with daemon launch validation"
        )


def wait_for_port_file(port_file: Path, proc: subprocess.Popen[str], timeout: int, log_file: Path) -> int:
    deadline = time.time() + timeout
    launcher_exit_code: int | None = None
    while time.time() < deadline:
        if launcher_exit_code is None:
            launcher_exit_code = proc.poll()
        if port_file.exists():
            try:
                return int(port_file.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pass
        time.sleep(0.5)

    fail(
        f"timed out waiting for port file at {port_file}. "
        f"Launcher exit code: {launcher_exit_code!r}\n"
        f"Log tail:\n{tail_log(log_file)}"
    )


def wait_for_health(port: int, proc: subprocess.Popen[str], timeout: int, log_file: Path) -> dict:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/health"
    launcher_exit_code: int | None = None
    while time.time() < deadline:
        if launcher_exit_code is None:
            launcher_exit_code = proc.poll()
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                payload = json.loads(response.read())
            if payload.get("status") == "ok":
                return payload
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.5)

    fail(
        f"timed out waiting for {url}. "
        f"Launcher exit code: {launcher_exit_code!r}\n"
        f"Log tail:\n{tail_log(log_file)}"
    )


def stop_daemon(binary_path: Path, install_dir: Path, env: dict[str, str], proc: subprocess.Popen[str]) -> None:
    try:
        subprocess.run(
            [str(binary_path), "stop"],
            cwd=str(install_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pass

    try:
        proc.wait(timeout=30)
        return
    except subprocess.TimeoutExpired:
        pass

    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=15)


def pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def force_stop_pid(pid: int) -> None:
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def wait_for_shutdown(data_dir: Path, timeout: int = 60) -> None:
    port_file = data_dir / "cato.port"
    pid_file = data_dir / "cato.pid"
    deadline = time.time() + timeout

    while time.time() < deadline:
        if not port_file.exists():
            return
        time.sleep(1.0)

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None
        if pid and pid_is_running(pid):
            force_stop_pid(pid)

    deadline = time.time() + 15
    while time.time() < deadline:
        if not port_file.exists():
            return
        time.sleep(1.0)

    fail(f"frozen daemon stopped but {port_file} still exists")


def tail_log(log_file: Path, max_lines: int = 40) -> str:
    if not log_file.exists():
        return "(log file not created)"
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"(could not read log file: {exc})"
    return "\n".join(lines[-max_lines:]) or "(log file empty)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Reuse the already-staged sidecar instead of rebuilding it first.",
    )
    parser.add_argument(
        "--build-timeout",
        type=int,
        default=1800,
        help="Maximum seconds to allow for the PyInstaller build step.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=int,
        default=180,
        help="Maximum seconds to wait for the frozen daemon to become healthy.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    desktop_dir = Path(__file__).resolve().parents[1]
    sidecar_path = staged_sidecar_path(desktop_dir)
    if not args.skip_build:
        sidecar_path = build_sidecar(desktop_dir, args.build_timeout)
    elif not sidecar_path.exists():
        fail(f"--skip-build was set but the staged sidecar does not exist: {sidecar_path}")

    with tempfile.TemporaryDirectory(prefix="cato-frozen-validate-", ignore_cleanup_errors=True) as tmp_dir_raw:
        tmp_dir = Path(tmp_dir_raw)
        install_dir = tmp_dir / "install"
        profile_root = tmp_dir / "profile"
        log_file = tmp_dir / "frozen-daemon.log"
        install_dir.mkdir(parents=True, exist_ok=True)

        install_binary = install_dir / ("cato.exe" if sys.platform.startswith("win") else "cato")
        shutil.copy2(sidecar_path, install_binary)
        if not sys.platform.startswith("win"):
            install_binary.chmod(0o755)

        env = build_validation_env(profile_root)

        best_effort_cli_probe(install_binary, install_dir, env)

        with log_file.open("w", encoding="utf-8") as handle:
            proc = subprocess.Popen(
                [str(install_binary), "start", "--channel", "webchat"],
                cwd=str(install_dir),
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

            port_file = Path(env["APPDATA"]) / "cato" / "cato.port"
            port = wait_for_port_file(port_file, proc, args.startup_timeout, log_file)
            health = wait_for_health(port, proc, args.startup_timeout, log_file)
            print(
                "[validate_frozen_bundle] frozen daemon healthy "
                f"on http://127.0.0.1:{port} with version {health.get('version')}"
            )

            stop_daemon(install_binary, install_dir, env, proc)
            wait_for_shutdown(Path(env["APPDATA"]) / "cato")

    print("[validate_frozen_bundle] clean-profile frozen sidecar validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
