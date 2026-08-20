"""Rendered production-bundle acceptance for the complete Work Inbox contract."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

from playwright.sync_api import Page, sync_playwright

DESKTOP = Path(__file__).resolve().parents[1]
REPO = DESKTOP.parent
EXPECTED_NAV = [
    "Work Inbox",
    "Waiting/Follow-ups",
    "Approvals",
    "Calendar",
    "Company Tasks",
    "Finance",
    "Ask E4L",
    "Activity/Automations",
    "Settings/Diagnostics",
]
EXPECTED_GROUPS = ["needs_me", "waiting", "approvals", "due_soon", "fyi", "resolved"]
LEGACY_DESTINATIONS = {
    "dashboard": "Work Inbox",
    "inbox": "Work Inbox",
    "alerts": "Work Inbox",
    "chat": "Ask E4L",
    "memory": "Ask E4L",
    "audit": "Activity/Automations",
    "cron": "Activity/Automations",
    "sessions": "Activity/Automations",
    "replay": "Activity/Automations",
    "usage": "Activity/Automations",
    "logs": "Activity/Automations",
    "budget": "Activity/Automations",
    "settings": "Settings/Diagnostics",
    "config": "Settings/Diagnostics",
    "identity": "Settings/Diagnostics",
    "auth-keys": "Settings/Diagnostics",
    "skills": "Settings/Diagnostics",
    "system": "Settings/Diagnostics",
    "diagnostics": "Settings/Diagnostics",
    "nodes": "Settings/Diagnostics",
    "flows": "Settings/Diagnostics",
    "coding-agent": "Settings/Diagnostics",
    "interactive-cli": "Settings/Diagnostics",
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_http(url: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.15)
    raise TimeoutError(f"acceptance server did not become ready: {url}")


def stop_finance(origin: str) -> None:
    request = Request(f"{origin}/acceptance/stop-finance", method="POST")
    with urlopen(request, timeout=5) as response:
        payload = json.loads(response.read())
    assert payload == {"finance_running": False}, payload


def wait_for_finance_state(page: Page, state: str, timeout_ms: int = 35_000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        page.get_by_role("button", name="Refresh").click()
        try:
            page.get_by_text(state, exact=True).wait_for(timeout=7_000)
            return
        except Exception:
            continue
    raise AssertionError(f"FinanceOS card never reached {state!r}")


def run_acceptance(page: Page, origin: str, output: Path) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    page.goto(origin, wait_until="domcontentloaded")
    page.get_by_role("heading", name="Work Inbox", exact=True).wait_for(timeout=20_000)
    checks.append({"check": "default_landing", "result": "PASS"})

    nav = page.locator(".sidebar-nav-item")
    labels = [nav.nth(index).locator(".sidebar-nav-copy > span").inner_text() for index in range(nav.count())]
    assert labels == EXPECTED_NAV, labels
    checks.append({"check": "exact_nine_item_navigation", "result": "PASS"})

    groups = page.locator("[data-work-inbox-group]")
    group_ids = [groups.nth(index).get_attribute("data-work-inbox-group") for index in range(groups.count())]
    assert group_ids == EXPECTED_GROUPS, group_ids
    checks.append({"check": "six_groups_fixed_order", "result": "PASS"})

    wait_for_finance_state(page, "Live")
    assert page.get_by_text("Close status: acceptance-ready", exact=False).is_visible()
    page.screenshot(path=str(output / "work-inbox-live.png"), full_page=True)
    checks.append({"check": "financeos_live_card", "result": "PASS"})

    page.get_by_role("button", name="Approvals Drafts & Monday updates").click()
    page.get_by_role("heading", name="Approvals", exact=True).wait_for()
    finance_link = page.get_by_role("link", name="Open FinanceOS approvals in a separate application")
    assert finance_link.get_attribute("href") == "http://127.0.0.1:3001"
    assert finance_link.get_attribute("target") == "_blank"
    assert page.get_by_text("Finance approvals are never handled here", exact=True).is_visible()
    checks.append({"check": "approval_authority_boundary", "result": "PASS"})

    for legacy, destination in LEGACY_DESTINATIONS.items():
        page.evaluate(
            "legacy => window.dispatchEvent(new CustomEvent('cato-navigate', {detail: legacy}))",
            legacy,
        )
        page.locator(".command-breadcrumb strong").filter(has_text=destination).wait_for()
    checks.append({"check": "all_legacy_routes_resolve", "result": "PASS"})

    page.get_by_role("button", name="Cato Work Inbox").click()
    page.get_by_role("heading", name="Work Inbox", exact=True).wait_for()
    stop_finance(origin)
    wait_for_finance_state(page, "Stale")
    assert page.get_by_text("Close status: acceptance-ready", exact=False).is_visible()
    assert page.get_by_text("as of", exact=False).is_visible()
    page.screenshot(path=str(output / "work-inbox-stale.png"), full_page=True)
    checks.append({"check": "financeos_outage_cached_stale_no_crash", "result": "PASS"})

    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPO / "output" / "playwright" / "work-inbox")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not args.skip_build:
        subprocess.run(["npm.cmd", "run", "build"], cwd=DESKTOP, check=True)

    appdata = Path(tempfile.mkdtemp(prefix="cato-work-inbox-acceptance-"))
    port = free_port()
    origin = f"http://127.0.0.1:{port}"
    server_log_path = output / "acceptance-server.log"
    server_log = server_log_path.open("w", encoding="utf-8")
    server = subprocess.Popen(
        [
            sys.executable,
            str(DESKTOP / "scripts" / "work_inbox_acceptance_server.py"),
            "--dist",
            str(DESKTOP / "dist"),
            "--port",
            str(port),
            "--appdata",
            str(appdata),
        ],
        cwd=REPO,
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )
    console_failures: list[str] = []
    expected_degradations: list[str] = []
    payload: dict[str, object]
    exit_code = 1
    try:
        wait_http(f"{origin}/acceptance/status")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()

            def capture_console(message) -> None:
                if message.type != "error":
                    return
                text = message.text
                if (
                    ("WebSocket connection to" in text and "/ws" in text and "404" in text)
                    or text == "[useChatStream] WebSocket error"
                    or "503 (Service Unavailable)" in text
                ):
                    expected_degradations.append(text)
                    return
                console_failures.append(text)

            page.on("console", capture_console)
            page.on("pageerror", lambda error: console_failures.append(str(error)))
            checks = run_acceptance(page, origin, output)
            context.close()
            browser.close()
        assert console_failures == [], console_failures
        payload = {
            "result": "PASS",
            "production_bundle": str(DESKTOP / "dist"),
            "cato_route": "real",
            "finance_fixture": "loopback",
            "ports_dynamic": True,
            "checks": checks,
            "console_failures": console_failures,
            "expected_fixture_degradations": expected_degradations,
        }
        exit_code = 0
    except Exception as exc:
        payload = {"result": "FAIL", "error": str(exc), "console_failures": console_failures}
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)
        server_log.close()
        shutil.rmtree(appdata, ignore_errors=True)

    (output / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
