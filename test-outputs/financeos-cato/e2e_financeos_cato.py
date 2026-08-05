from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
DESKTOP = REPO / "desktop"
SHOTS = ROOT / "screenshots"
PROOF = REPO / "proof-artifacts" / "harness-parity"
SHOTS.mkdir(parents=True, exist_ok=True)
PROOF.mkdir(parents=True, exist_ok=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_http(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.15)
    raise TimeoutError(f"server did not become ready: {url}")


def install_desktop_bridge(page: Page, daemon_port: int, token: str) -> None:
    status = json.dumps({
        "running": True,
        "http_port": daemon_port,
        "ws_port": daemon_port,
        "daemon_token": token,
    })
    page.add_init_script(
        f"""
        window.__TAURI_INTERNALS__ = {{
          invoke: async (cmd) => cmd === 'get_daemon_status' ? {status} : null,
          transformCallback: () => 1
        }};
        """
    )


def run_scenario(browser, target: str, daemon_port: int, token: str, name, test_fn):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    install_desktop_bridge(page, daemon_port, token)
    errors: list[str] = []
    page.on(
        "console",
        lambda m: errors.append(f"console:{m.text}")
        if m.type == "error" and name != "websocket_auth_boundaries" else None,
    )
    page.on("pageerror", lambda e: errors.append(f"pageerror:{e}"))
    page.on("response", lambda r: errors.append(f"http{r.status}:{r.url}") if r.status >= 500 else None)
    try:
        test_fn(page, target, daemon_port, token)
        if errors:
            raise AssertionError("; ".join(errors))
        shot = SHOTS / f"{name}_final.png"
        page.screenshot(path=str(shot), full_page=True)
        return {"name": name, "result": "PASS", "evidence": str(shot)}
    except Exception as exc:
        shot = SHOTS / f"{name}_failure.png"
        page.screenshot(path=str(shot), full_page=True)
        return {"name": name, "result": "FAIL", "evidence": f"{exc}; screenshot={shot}"}
    finally:
        context.tracing.stop(path=str(PROOF / f"{name}.trace.zip"))
        context.close()


def dashboard(page: Page, target: str, *_args) -> None:
    page.goto(target)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="Good morning, Ben.").wait_for()
    # FinanceOS is deliberately not faked: unavailable is the truthful harness state.
    assert page.get_by_text("Not connected", exact=True).is_visible()
    assert page.get_by_text("Unknown", exact=True).is_visible()


def real_http_contracts(page: Page, target: str, daemon_port: int, _token: str) -> None:
    page.goto(target)
    page.wait_for_load_state("networkidle")
    result = page.evaluate(
        """async (base) => {
          const paths = ['/health', '/api/sessions', '/api/inbox', '/api/finance-os/health'];
          const out = {};
          for (const path of paths) {
            const response = await fetch(base + path);
            out[path] = {status: response.status, body: await response.json()};
          }
          return out;
        }""",
        f"http://127.0.0.1:{daemon_port}",
    )
    assert all(value["status"] == 200 for value in result.values()), result
    assert isinstance(result["/api/sessions"]["body"], list), result
    assert "counts" in result["/api/inbox"]["body"], result
    assert "connected" in result["/api/finance-os/health"]["body"], result


def workflow_to_chat(page: Page, target: str, *_args) -> None:
    page.goto(target)
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Morning finance brief", exact=False).click()
    box = page.get_by_role("textbox")
    box.wait_for()
    if not box.input_value():
        box.fill("Prepare an E4Life morning finance brief using verified facts only.")
    page.get_by_role("button", name="Send", exact=True).click()
    page.get_by_text("Authenticated Cato harness response received.", exact=True).wait_for()


def websocket_boundaries(page: Page, target: str, daemon_port: int, token: str) -> None:
    page.goto(target)
    result = page.evaluate(
        """async ({port, token}) => {
          const attempt = (url, protocols) => new Promise(resolve => {
            let opened = false;
            const ws = new WebSocket(url, protocols);
            const timer = setTimeout(() => { ws.close(); resolve({opened, timeout: true}); }, 3000);
            ws.onopen = () => { opened = true; ws.close(); };
            ws.onclose = event => { clearTimeout(timer); resolve({opened, code: event.code}); };
            ws.onerror = () => {};
          });
          const valid = await attempt(`ws://127.0.0.1:${port}/ws`, [`cato-auth.${token}`]);
          const invalid = await attempt(`ws://127.0.0.1:${port}/ws`, ['cato-auth.invalid']);
          const queryOnly = await attempt(`ws://127.0.0.1:${port}/ws?token=${encodeURIComponent(token)}`);
          return {valid, invalid, queryOnly};
        }""",
        {"port": daemon_port, "token": token},
    )
    assert result["valid"]["opened"] is True, result
    assert result["invalid"]["opened"] is False, result
    assert result["queryOnly"]["opened"] is False, result


def malformed_frame_resilience(page: Page, target: str, daemon_port: int, token: str) -> None:
    page.goto(target)
    result = page.evaluate(
        """async ({port, token}) => new Promise((resolve, reject) => {
          const ws = new WebSocket(`ws://127.0.0.1:${port}/ws`, [`cato-auth.${token}`]);
          const messages = [];
          const timer = setTimeout(() => reject(new Error('websocket timeout')), 4000);
          ws.onopen = () => ws.send('{malformed');
          ws.onmessage = event => {
            const message = JSON.parse(event.data);
            messages.push(message);
            if (message.code === 'invalid_json') {
              ws.send(JSON.stringify({type: 'health'}));
            } else if (message.type === 'health') {
              clearTimeout(timer); ws.close(); resolve(messages);
            }
          };
          ws.onerror = () => reject(new Error('authenticated websocket failed'));
        })""",
        {"port": daemon_port, "token": token},
    )
    assert [item.get("code") or item.get("type") for item in result] == ["invalid_json", "health"], result


def main() -> int:
    daemon_port, ui_port = free_port(), free_port()
    while ui_port == daemon_port:
        ui_port = free_port()
    token = secrets.token_urlsafe(32)
    target = f"http://127.0.0.1:{ui_port}"
    env = os.environ.copy()
    env.update({
        "CATO_E2E_DAEMON_TOKEN": token,
        "CATO_E2E_DAEMON_PORT": str(daemon_port),
        "CATO_ALLOWED_BROWSER_ORIGINS": target,
    })
    daemon_log = (PROOF / "daemon.log").open("w", encoding="utf-8")
    vite_log = (PROOF / "vite.log").open("w", encoding="utf-8")
    daemon = subprocess.Popen(
        [sys.executable, str(ROOT / "authenticated_ws_harness.py")],
        cwd=REPO, env=env, stdout=daemon_log, stderr=subprocess.STDOUT,
    )
    vite = subprocess.Popen(
        ["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"],
        cwd=DESKTOP, env=env, stdout=vite_log, stderr=subprocess.STDOUT,
    )
    results = []
    try:
        wait_http(f"http://127.0.0.1:{daemon_port}/health")
        wait_http(target)
        scenarios = [
            ("dashboard", dashboard),
            ("real_http_contracts", real_http_contracts),
            ("workflow_to_chat", workflow_to_chat),
            ("websocket_auth_boundaries", websocket_boundaries),
            ("malformed_frame_resilience", malformed_frame_resilience),
        ]
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for name, fn in scenarios:
                results.append(run_scenario(browser, target, daemon_port, token, name, fn))
            browser.close()
    finally:
        for process in (vite, daemon):
            process.terminate()
        for process in (vite, daemon):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        daemon_log.close()
        vite_log.close()

    payload = {"ports_dynamic": True, "credential_random_per_run": True, "results": results}
    (ROOT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (PROOF / "test_output.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (PROOF / "changed_file_list.txt").write_text(
        "test-outputs/financeos-cato/authenticated_ws_harness.py\n"
        "test-outputs/financeos-cato/e2e_financeos_cato.py\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2))
    return 1 if any(item["result"] == "FAIL" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
