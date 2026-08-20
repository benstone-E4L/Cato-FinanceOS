"""Safe exact-HEAD live acceptance for the Cato operator workstation.

Secret values are consumed only in memory and are never printed or persisted.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import aiohttp
import websockets
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_EXE = REPO / "desktop" / "src-tauri" / "target" / "release" / "cato-desktop.exe"
SECRET_NAME = re.compile(r"(?:api[_-]?key|token|password|secret|credential)", re.IGNORECASE)
NON_SECRET_TOKEN_METADATA = {"token_budget", "context_budget_tokens", "max_output_tokens"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=REPO, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


def add(checks: list[dict[str, Any]], name: str, **evidence: Any) -> None:
    checks.append({"check": name, "result": "PASS", **evidence})


def process_exists(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        return False
    ctypes.windll.kernel32.CloseHandle(process)
    return True


def resolve_runtime(data_dir: Path) -> tuple[int, int, str]:
    port_text = (data_dir / "cato.port").read_text(encoding="utf-8").strip()
    pid_text = (data_dir / "cato.pid").read_text(encoding="utf-8").strip()
    token = (data_dir / "daemon.token").read_text(encoding="utf-8").strip()
    port, pid = int(port_text), int(pid_text)
    if not (1 <= port <= 65535):
        raise AssertionError("Cato lifecycle port marker is invalid")
    if pid <= 0:
        raise AssertionError("Cato lifecycle PID marker is invalid")
    if len(token) != 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise AssertionError("Daemon token does not match the private runtime contract")
    if not process_exists(pid):
        raise AssertionError("Cato lifecycle PID does not identify a running process")
    return port, pid, token


def validate_credential_storage(data_dir: Path) -> dict[str, Any]:
    vault = data_dir / "vault.enc"
    config = data_dir / "config.yaml"
    if not vault.is_file() or vault.stat().st_size < 64:
        raise AssertionError("Encrypted vault is missing or implausibly small")
    ciphertext = vault.read_bytes()
    for marker in (b"ANTHROPIC_API_KEY", b"TELEGRAM_BOT_TOKEN", b"FINANCEOS_CAPABILITY_TOKEN"):
        if marker in ciphertext:
            raise AssertionError("A credential label is visible in vault ciphertext")

    config_data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    violations: list[str] = []

    def inspect_config(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                inspect_config(nested, (*path, str(key)))
            return
        if not path:
            return
        normalized = path[-1].lower()
        if (
            SECRET_NAME.search(normalized)
            and not normalized.endswith("_env")
            and normalized not in NON_SECRET_TOKEN_METADATA
            and value not in (None, "", False, [], {})
        ):
            violations.append(".".join(path))

    inspect_config(config_data)
    if violations:
        raise AssertionError(f"Plaintext config contains credential-shaped values: {sorted(violations)}")
    return {
        "vault_sha256": hashlib.sha256(ciphertext).hexdigest(),
        "vault_bytes": len(ciphertext),
        "plaintext_secret_config_fields": 0,
    }


async def http_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    token: str | None = None,
) -> tuple[int, Any]:
    headers = {"X-Cato-Token": token} if token else {}
    async with session.request(method, url, headers=headers) as response:
        try:
            body = await response.json()
        except Exception:
            body = None
        return response.status, body


async def websocket_auth_checks(port: int, token: str) -> dict[str, Any]:
    uri = f"ws://127.0.0.1:{port}/ws"
    invalid_refused = False
    try:
        async with websockets.connect(
            uri, subprotocols=["cato-auth.invalid"], open_timeout=5, close_timeout=2
        ):
            pass
    except Exception:
        invalid_refused = True
    if not invalid_refused:
        raise AssertionError("Invalid WebSocket token was accepted")

    async with websockets.connect(
        uri,
        subprotocols=[f"cato-auth.{token}"],
        open_timeout=5,
        close_timeout=2,
    ) as websocket:
        await websocket.send(json.dumps({"type": "health"}))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=8))
            if message.get("type") == "health":
                if message.get("status") != "ok":
                    raise AssertionError("Authenticated WebSocket health was not OK")
                return {"valid_opened": True, "invalid_refused": True}
    raise AssertionError("Authenticated WebSocket returned no health response")


async def exercise_model(port: int, token: str) -> dict[str, Any]:
    session_id = f"live-acceptance-{uuid.uuid4().hex[:12]}"
    uri = f"ws://127.0.0.1:{port}/ws"
    prompt = "Live acceptance check. Reply with exactly CATO_LIVE_OK and nothing else."
    async with websockets.connect(
        uri,
        subprotocols=[f"cato-auth.{token}"],
        open_timeout=5,
        close_timeout=2,
        max_size=2**22,
    ) as websocket:
        await websocket.send(json.dumps({
            "type": "message",
            "text": prompt,
            "session_id": session_id,
            "channel": "web",
        }))
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            remaining = max(1, deadline - time.monotonic())
            message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=remaining))
            if message.get("type") == "error" and message.get("session_id") in (None, session_id):
                raise AssertionError("Live model route returned an error frame")
            if message.get("type") == "response" and message.get("session_id") == session_id:
                response = str(message.get("text", ""))
                if "CATO_LIVE_OK" not in response:
                    raise AssertionError("Live model response omitted the acceptance marker")
                return {
                    "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                    "response_bytes": len(response.encode("utf-8")),
                    "model": str(message.get("model") or "not-reported"),
                }
    raise AssertionError("Live model route timed out")


def launch_desktop_probe(executable: Path, port: int) -> dict[str, Any]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(executable)],
        cwd=executable.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    try:
        time.sleep(8)
        if process.poll() is not None:
            raise AssertionError(f"Native desktop exited during live probe with {process.returncode}")
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            if response.status != 200:
                raise AssertionError("Operator daemon health changed during native desktop probe")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    return {"desktop_process_alive": True, "operator_daemon_port_preserved": port}


async def live_checks(
    data_dir: Path,
    executable: Path,
    checks: list[dict[str, Any]],
    *,
    do_model: bool,
    launch_desktop: bool,
) -> None:
    port, pid, token = resolve_runtime(data_dir)
    add(checks, "operator_lifecycle_markers", port=port, pid=pid, token_length=len(token))

    storage = validate_credential_storage(data_dir)
    add(checks, "encrypted_credential_storage", **storage)

    origin = f"http://127.0.0.1:{port}"
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        status, health = await http_json(session, "GET", f"{origin}/health")
        if status != 200 or not isinstance(health, dict) or health.get("status") != "ok":
            raise AssertionError("Live daemon health contract failed")
        if health.get("ledger_recovery", {}).get("clean") is not True:
            raise AssertionError("Live daemon ledger recovery is not clean")
        add(checks, "live_daemon_health", http_status=status, version=health.get("version"))

        status, _ = await http_json(session, "GET", f"{origin}/api/inbox", token="invalid")
        assert status == 401, status
        add(checks, "invalid_http_token_refused", http_status=status)

        status, inbox = await http_json(session, "GET", f"{origin}/api/inbox", token=token)
        if status != 200 or not isinstance(inbox, dict) or not isinstance(inbox.get("email_drafts"), list):
            raise AssertionError("Authenticated live inbox contract failed")
        add(checks, "valid_http_token_and_inbox", http_status=status, draft_count=len(inbox["email_drafts"]))

        status, finance = await http_json(
            session, "GET", f"{origin}/api/finance-os/control-room", token=token
        )
        if status != 200 or not isinstance(finance, dict):
            raise AssertionError("Live FinanceOS control-room contract failed")
        if not isinstance(finance.get("connected"), bool) or not isinstance(finance.get("stale"), bool):
            raise AssertionError("Live FinanceOS state flags are invalid")
        if not finance["connected"]:
            if finance["stale"] is not True:
                raise AssertionError("Disconnected FinanceOS state was not marked stale")
        add(
            checks,
            "live_financeos_read_or_safe_fallback",
            http_status=status,
            connected=finance["connected"],
            stale=finance["stale"],
            cached_data_present=finance.get("data") is not None,
        )

        status, activity = await http_json(session, "GET", f"{origin}/api/activity")
        if status != 200 or not isinstance(activity, dict) or not isinstance(activity.get("busy"), bool):
            raise AssertionError("Live activity contract failed")
        add(checks, "live_activity_contract", http_status=status)

    ws_evidence = await websocket_auth_checks(port, token)
    add(checks, "live_websocket_auth_boundaries", **ws_evidence)

    if launch_desktop:
        desktop_evidence = await asyncio.to_thread(launch_desktop_probe, executable, port)
        add(checks, "live_native_desktop_process", **desktop_evidence)

    if do_model:
        model_evidence = await exercise_model(port, token)
        add(checks, "live_direct_anthropic_round_trip", **model_evidence)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPO / "output" / "live-cato")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ["APPDATA"]) / "cato")
    parser.add_argument("--desktop-exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--exercise-model", action="store_true")
    parser.add_argument("--skip-work-inbox", action="store_true")
    parser.add_argument("--skip-desktop-launch", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true", help="development only; result is not exact-HEAD proof")
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = args.desktop_exe.resolve()
    checks: list[dict[str, Any]] = []
    payload: dict[str, Any]
    try:
        branch = git("branch", "--show-current")
        head = git("rev-parse", "HEAD")
        dirty = git("status", "--porcelain")
        if dirty and not args.allow_dirty:
            raise AssertionError("Exact-HEAD live acceptance requires a clean worktree")
        add(checks, "git_revision_binding", branch=branch, head=head, clean=not bool(dirty))

        if not executable.is_file() or executable.stat().st_size < 1024 * 1024:
            raise AssertionError(f"Native desktop executable is missing: {executable}")
        add(
            checks,
            "native_artifact_custody",
            executable=str(executable),
            sha256=sha256_file(executable),
            bytes=executable.stat().st_size,
        )

        if not args.skip_work_inbox:
            work_output = output / "work-inbox"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "desktop" / "scripts" / "work_inbox_acceptance.py"),
                    "--skip-build",
                    "--output",
                    str(work_output),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                timeout=180,
            )
            if completed.returncode != 0:
                raise AssertionError("Rendered Work Inbox acceptance failed; inspect its result.json")
            work_result = json.loads((work_output / "result.json").read_text(encoding="utf-8"))
            assert work_result.get("result") == "PASS", work_result
            add(checks, "complete_work_inbox_acceptance", checks=len(work_result.get("checks", [])))

        asyncio.run(
            live_checks(
                args.data_dir.resolve(),
                executable,
                checks,
                do_model=args.exercise_model,
                launch_desktop=not args.skip_desktop_launch,
            )
        )
        post_head = git("rev-parse", "HEAD")
        post_dirty = git("status", "--porcelain")
        if post_head != head or (post_dirty and not args.allow_dirty):
            raise AssertionError("Repository revision or cleanliness changed during live acceptance")
        add(checks, "post_run_revision_binding", head=post_head, clean=not bool(post_dirty))
        payload = {
            "result": "PASS",
            "scope": "operator-workstation-live",
            "branch": branch,
            "head": head,
            "model_exercised": args.exercise_model,
            "checks": checks,
            "secret_values_recorded": False,
            "finance_writes_performed": False,
        }
        exit_code = 0
    except Exception as exc:
        payload = {"result": "FAIL", "error": str(exc), "checks": checks, "secret_values_recorded": False}
        exit_code = 1

    (output / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
