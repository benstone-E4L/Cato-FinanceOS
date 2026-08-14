"""Real-process proof for graceful Windows production-runner shutdown."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "cato_svc_runner.py"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _isolated_child_environment(profile: Path) -> dict[str, str]:
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "COMSPEC",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERNAME",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(
        {
            "APPDATA": str(profile / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(profile / "AppData" / "Local"),
            "USERPROFILE": str(profile),
            "HOME": str(profile),
        }
    )
    return env


def _wait_for_health(port: int, process: subprocess.Popen[bytes]) -> int:
    deadline = time.monotonic() + 60.0
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"production runner exited before health; code={process.returncode}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return response.status
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise AssertionError("production runner did not reach health before timeout")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console-control regression")
def test_production_runner_ctrl_break_exits_clean_and_removes_owned_markers(
    tmp_path: Path,
) -> None:
    isolated_profile = tmp_path / "profile"
    appdata = isolated_profile / "AppData" / "Roaming"
    localappdata = isolated_profile / "AppData" / "Local"
    data_dir = appdata / "cato"
    workspace = data_dir / "workspace"
    data_dir.mkdir(parents=True)
    localappdata.mkdir(parents=True)
    workspace.mkdir(parents=True)

    port = _free_loopback_port()
    config = {
        "webchat_port": port,
        "workspace_dir": str(workspace),
        "pipeline_root_dir": str(data_dir / "businesses"),
        "telegram_enabled": False,
        "mcp_enabled": False,
        "genesis_enabled": False,
        "swarmsync_enabled": False,
    }
    (data_dir / "config.yaml").write_text(
        "\n".join(f"{key}: {json.dumps(value)}" for key, value in config.items()) + "\n",
        encoding="utf-8",
    )

    password = uuid4().hex
    child_env = _isolated_child_environment(isolated_profile)
    init_code = (
        "from pathlib import Path; import sys; from cato.vault import Vault; "
        "vault = Vault(vault_path=Path(sys.argv[1])); "
        "vault.unlock(sys.stdin.buffer.read().decode(), allow_create=True)"
    )
    subprocess.run(
        [sys.executable, "-c", init_code, str(data_dir / "vault.enc")],
        cwd=REPO_ROOT,
        env=child_env,
        input=password.encode("utf-8"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=30.0,
    )

    child_env["CATO_VAULT_PASSWORD"] = password

    process = subprocess.Popen(
        [sys.executable, str(RUNNER)],
        cwd=REPO_ROOT,
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    forced_termination = False
    try:
        assert _wait_for_health(port, process) == 200
        pid_marker = data_dir / "cato.pid"
        port_marker = data_dir / "cato.port"
        assert pid_marker.is_file()
        assert port_marker.is_file()

        process.send_signal(signal.CTRL_BREAK_EVENT)
        exit_code = process.wait(timeout=30.0)

        assert exit_code == 0
        assert not pid_marker.exists(), "runner did not remove its PID marker"
        assert not port_marker.exists(), "daemon did not remove its port marker"
        assert forced_termination is False
    finally:
        if process.poll() is None:
            forced_termination = True
            process.kill()
            process.wait(timeout=10.0)
