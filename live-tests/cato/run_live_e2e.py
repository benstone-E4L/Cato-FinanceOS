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
import sqlite3
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
DEFAULT_MANIFEST = REPO / "desktop" / "src-tauri" / "target" / "release" / "cato-build-manifest.json"
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


def _windows_file_is_encrypted(path: Path) -> bool:
    """Return whether *path* is protected by Windows EFS."""
    if os.name != "nt":
        return False
    file_attributes = getattr(path.stat(), "st_file_attributes", 0)
    return bool(file_attributes & 0x4000)  # FILE_ATTRIBUTE_ENCRYPTED


def validate_repo_secret_sources() -> dict[str, Any]:
    inspected = 0
    violations: list[str] = []
    encrypted_operator_fields = 0
    for dotenv in [REPO / ".env", *REPO.glob(".env.*")]:
        if not dotenv.is_file():
            continue
        inspected += 1
        encrypted_at_rest = _windows_file_is_encrypted(dotenv)
        for raw_line in dotenv.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if SECRET_NAME.search(name.strip()) and value.strip():
                if encrypted_at_rest and name.strip() == "CATO_VAULT_PASSWORD":
                    encrypted_operator_fields += 1
                else:
                    violations.append(f"{dotenv.name}:{name.strip()}")
    if violations:
        raise AssertionError(f"Repository dotenv contains nonempty secret fields: {sorted(violations)}")
    return {
        "dotenv_files_inspected": inspected,
        "plaintext_secret_fields": 0,
        "efs_encrypted_operator_password_fields": encrypted_operator_fields,
        "repository_dotenv_used_for_launch": False,
    }


def validate_windows_service_secret_source() -> dict[str, Any]:
    if os.name != "nt":
        return {"windows_service_checked": False, "persisted_vault_password_fields": 0}
    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\CatoDaemon",
            0,
            winreg.KEY_READ,
        )
    except FileNotFoundError:
        return {"windows_service_checked": True, "persisted_vault_password_fields": 0}
    try:
        try:
            environment, _ = winreg.QueryValueEx(key, "Environment")
        except FileNotFoundError:
            environment = []
    finally:
        winreg.CloseKey(key)
    entries = [environment] if isinstance(environment, str) else list(environment or [])
    count = sum(
        1 for entry in entries
        if str(entry).strip().upper().startswith("CATO_VAULT_PASSWORD=")
    )
    if count:
        raise AssertionError("CatoDaemon registry persists the vault master password")
    return {"windows_service_checked": True, "persisted_vault_password_fields": 0}


def validate_build_manifest(manifest_path: Path, executable: Path, head: str) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssertionError(f"Native custody manifest unavailable: {manifest_path}") from exc
    if manifest.get("source_sha") != head:
        raise AssertionError("Native custody manifest is not bound to current HEAD")
    native = manifest.get("native") or {}
    actual_native_sha = sha256_file(executable)
    if native.get("sha256") != actual_native_sha or native.get("bytes") != executable.stat().st_size:
        raise AssertionError("Native executable does not match the exact-HEAD custody manifest")
    sidecar = manifest.get("sidecar") or {}
    sidecar_name = sidecar.get("path")
    if not isinstance(sidecar_name, str) or Path(sidecar_name).name != sidecar_name:
        raise AssertionError("Custody manifest has no safe runtime-sidecar path")
    sidecar_path = manifest_path.parent / sidecar_name
    if not sidecar_path.is_file():
        raise AssertionError("Runtime sidecar from the custody manifest is missing")
    actual_sidecar_sha = sha256_file(sidecar_path)
    if sidecar.get("sha256") != actual_sidecar_sha or sidecar.get("bytes") != sidecar_path.stat().st_size:
        raise AssertionError("Runtime sidecar does not match the exact-HEAD custody manifest")
    staged = manifest.get("staged_sidecar") or {}
    staged_name = staged.get("path")
    if not isinstance(staged_name, str) or Path(staged_name).name != staged_name:
        raise AssertionError("Custody manifest has no safe staged-sidecar path")
    staged_path = REPO / "desktop" / "src-tauri" / "binaries" / staged_name
    if not staged_path.is_file():
        raise AssertionError("Staged sidecar from the custody manifest is missing")
    actual_staged_sha = sha256_file(staged_path)
    if (
        staged.get("sha256") != actual_staged_sha
        or staged.get("bytes") != staged_path.stat().st_size
        or actual_staged_sha != actual_sidecar_sha
    ):
        raise AssertionError("Staged and runtime sidecars do not match exact-HEAD custody")
    dist = manifest.get("dist")
    if not isinstance(dist, dict) or not dist:
        raise AssertionError("Custody manifest has no production-bundle hashes")
    for relative, expected_sha in dist.items():
        path = REPO / "desktop" / "dist" / str(relative)
        if not path.is_file() or sha256_file(path) != expected_sha:
            raise AssertionError(f"Production bundle differs from custody manifest: {relative}")
    return {
        "manifest": str(manifest_path),
        "source_sha": head,
        "native_sha256": actual_native_sha,
        "sidecar_sha256": actual_sidecar_sha,
        "runtime_sidecar": str(sidecar_path),
        "staged_sidecar_sha256": actual_staged_sha,
        "dist_file_count": len(dist),
    }


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


def process_image_path(pid: int) -> Path:
    if os.name != "nt":
        return Path(f"/proc/{pid}/exe").resolve(strict=True)
    import ctypes
    from ctypes import wintypes

    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        raise AssertionError("Unable to open the Cato daemon process for custody validation")
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
            process, 0, buffer, ctypes.byref(size)
        ):
            raise AssertionError("Unable to resolve the Cato daemon executable path")
        return Path(buffer.value).resolve(strict=True)
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


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


async def exercise_model(port: int, token: str, routing_db: Path) -> dict[str, Any]:
    session_id = f"live-acceptance-{uuid.uuid4().hex[:12]}"
    uri = f"ws://127.0.0.1:{port}/ws"
    prompt = "Live acceptance check. Reply with exactly CATO_LIVE_OK and nothing else."
    with sqlite3.connect(routing_db) as connection:
        baseline_id = int(
            connection.execute("SELECT COALESCE(MAX(id), 0) FROM routing_events").fetchone()[0]
        )
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
                if response.strip() != "CATO_LIVE_OK":
                    raise AssertionError("Live model response was not the exact acceptance marker")
                with sqlite3.connect(routing_db) as connection:
                    route_events = connection.execute(
                        """
                        SELECT provider, success, routed_model, status, actual_cost, content_chars
                        FROM routing_events
                        WHERE id > ?
                        ORDER BY id ASC
                        """,
                        (baseline_id,),
                    ).fetchall()
                matching = [
                    event for event in route_events
                    if event[0] == "anthropic" and event[1] == 1 and event[3] == "ok"
                    and int(event[5]) == len(response)
                ]
                if not matching:
                    raise AssertionError("Live model response has no new routing audit event")
                if len(route_events) != 1 or len(matching) != 1:
                    raise AssertionError("Live model routing receipt was not uniquely correlated")
                route_event = matching[0]
                provider, success, routed_model, status, actual_cost, content_chars = route_event
                if provider != "anthropic" or success != 1 or status != "ok":
                    raise AssertionError("Live model routing audit did not prove Anthropic success")
                response_model = str(message.get("model") or "")
                if response_model != routed_model:
                    raise AssertionError(
                        "Live response model metadata does not match the routing audit"
                    )
                if int(content_chars) != len(response):
                    raise AssertionError("Live response length does not match the routing audit")
                return {
                    "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                    "response_bytes": len(response.encode("utf-8")),
                    "provider": provider,
                    "model": routed_model,
                    "routing_status": status,
                    "routing_content_chars": content_chars,
                    "actual_cost_usd": actual_cost,
                    "model_metadata_matches": True,
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
    expected_head: str,
    expected_runtime_sidecar: Path,
    expected_runtime_sidecar_sha: str,
) -> None:
    port, pid, token = resolve_runtime(data_dir)
    add(checks, "operator_lifecycle_markers", port=port, pid=pid, token_length=len(token))
    daemon_image = process_image_path(pid)
    if daemon_image != expected_runtime_sidecar.resolve(strict=True):
        raise AssertionError("Running daemon is not the custody-manifest runtime sidecar")
    daemon_image_sha = sha256_file(daemon_image)
    if daemon_image_sha != expected_runtime_sidecar_sha:
        raise AssertionError("Running daemon executable differs from exact-HEAD custody")
    add(
        checks,
        "live_daemon_artifact_identity",
        executable=str(daemon_image),
        sha256=daemon_image_sha,
    )

    storage = validate_credential_storage(data_dir)
    add(checks, "encrypted_credential_storage", **storage)

    origin = f"http://127.0.0.1:{port}"
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        status, health = await http_json(session, "GET", f"{origin}/health")
        if status != 200 or not isinstance(health, dict) or health.get("status") != "ok":
            raise AssertionError("Live daemon health contract failed")
        if health.get("ledger_recovery", {}).get("clean") is not True:
            raise AssertionError("Live daemon ledger recovery is not clean")
        if health.get("source_sha") != expected_head:
            raise AssertionError(
                f"Running daemon source identity {health.get('source_sha')!r} does not match HEAD"
            )
        add(
            checks,
            "live_daemon_health",
            http_status=status,
            version=health.get("version"),
            source_sha=health.get("source_sha"),
        )

        status, _ = await http_json(session, "GET", f"{origin}/api/inbox", token="invalid")
        if status != 401:
            raise AssertionError(f"Invalid HTTP token returned {status}, expected 401")
        add(checks, "invalid_http_token_refused", http_status=status)

        status, inbox = await http_json(session, "GET", f"{origin}/api/inbox", token=token)
        if status != 200 or not isinstance(inbox, dict) or not isinstance(inbox.get("email_drafts"), list):
            raise AssertionError("Authenticated live inbox contract failed")
        add(checks, "valid_http_token_and_inbox", http_status=status, draft_count=len(inbox["email_drafts"]))

        finance_started = time.monotonic()
        status, finance = await http_json(
            session, "GET", f"{origin}/api/finance-os/control-room", token=token
        )
        finance_elapsed_ms = round((time.monotonic() - finance_started) * 1000)
        if status != 200 or not isinstance(finance, dict):
            raise AssertionError("Live FinanceOS control-room contract failed")
        if not isinstance(finance.get("connected"), bool) or not isinstance(finance.get("stale"), bool):
            raise AssertionError("Live FinanceOS state flags are invalid")
        if not finance["connected"]:
            if finance["stale"] is not True:
                raise AssertionError("Disconnected FinanceOS state was not marked stale")
        if finance_elapsed_ms > 6000:
            raise AssertionError("Live FinanceOS fallback exceeded the desktop timeout budget")
        add(
            checks,
            "live_financeos_read_or_safe_fallback",
            http_status=status,
            connected=finance["connected"],
            stale=finance["stale"],
            cached_data_present=finance.get("data") is not None,
            elapsed_ms=finance_elapsed_ms,
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
        model_evidence = await exercise_model(port, token, data_dir / "routing_log.sqlite3")
        add(checks, "live_direct_anthropic_round_trip", **model_evidence)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPO / "output" / "live-cato")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ["APPDATA"]) / "cato")
    parser.add_argument("--desktop-exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--build-manifest", type=Path, default=DEFAULT_MANIFEST)
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

        secret_source_evidence = validate_repo_secret_sources()
        add(checks, "repository_plaintext_secret_gate", **secret_source_evidence)
        service_secret_evidence = validate_windows_service_secret_source()
        add(checks, "service_plaintext_secret_gate", **service_secret_evidence)

        if not executable.is_file() or executable.stat().st_size < 1024 * 1024:
            raise AssertionError(f"Native desktop executable is missing: {executable}")
        custody = validate_build_manifest(args.build_manifest.resolve(), executable, head)
        add(checks, "native_artifact_custody", executable=str(executable), **custody)

        if not args.skip_work_inbox:
            work_output = output / "work-inbox"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "desktop" / "scripts" / "work_inbox_acceptance.py"),
                    "--skip-build",
                    "--expected-head",
                    head,
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
            if work_result.get("result") != "PASS":
                raise AssertionError(f"Work Inbox acceptance did not report PASS: {work_result}")
            add(
                checks,
                "complete_work_inbox_acceptance",
                assertions=len(work_result.get("checks", [])),
            )

        asyncio.run(
            live_checks(
                args.data_dir.resolve(),
                executable,
                checks,
                do_model=args.exercise_model,
                launch_desktop=not args.skip_desktop_launch,
                expected_head=head,
                expected_runtime_sidecar=Path(custody["runtime_sidecar"]),
                expected_runtime_sidecar_sha=str(custody["sidecar_sha256"]),
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
        payload = {
            "result": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "checks": checks,
            "secret_values_recorded": False,
        }
        exit_code = 1

    (output / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
