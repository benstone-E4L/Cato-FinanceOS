"""Rendered production-bundle acceptance for the complete Work Inbox contract."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
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
LEGACY_ACTIVE_TABS = {
    "chat": "chat", "memory": "memory",
    "audit": "audit", "cron": "cron", "sessions": "sessions",
    "replay": "sessions", "usage": "usage", "logs": "logs", "budget": "budget",
    "settings": "settings", "config": "config", "identity": "identity",
    "auth-keys": "auth-keys", "skills": "skills", "system": "system",
    "diagnostics": "diagnostics", "nodes": "nodes", "flows": "flows",
    "coding-agent": "coding-agent", "interactive-cli": "interactive-cli",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip().lower()


def bundle_contains_sha(dist: Path, expected_head: str) -> bool:
    for path in [dist / "index.html", *(dist / "assets").glob("*")]:
        if path.is_file() and expected_head.encode("ascii") in path.read_bytes():
            return True
    return False


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
    require(payload == {"finance_running": False}, f"unexpected Finance stop payload: {payload}")


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


def run_acceptance(page: Page, origin: str, output: Path, expected_head: str) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    page.goto(origin, wait_until="domcontentloaded")
    page.get_by_role("heading", name="Work Inbox", exact=True).wait_for(timeout=20_000)
    checks.append({"check": "default_landing", "result": "PASS"})

    nav = page.locator(".sidebar-nav-item")
    labels = [nav.nth(index).locator(".sidebar-nav-copy > span").inner_text() for index in range(nav.count())]
    require(labels == EXPECTED_NAV, f"navigation mismatch: {labels}")
    checks.append({"check": "exact_nine_item_navigation", "result": "PASS"})

    groups = page.locator("[data-work-inbox-group]")
    group_ids = [groups.nth(index).get_attribute("data-work-inbox-group") for index in range(groups.count())]
    require(group_ids == EXPECTED_GROUPS, f"Work Inbox groups mismatch: {group_ids}")
    checks.append({"check": "six_groups_fixed_order", "result": "PASS"})

    wait_for_finance_state(page, "Live")
    require(page.get_by_text("Close status: acceptance-ready", exact=False).is_visible(), "live Finance card content missing")
    page.screenshot(path=str(output / "work-inbox-live.png"), full_page=True)
    checks.append({"check": "financeos_live_card", "result": "PASS"})

    page.get_by_role("button", name="Approvals Drafts & Monday updates").click()
    page.get_by_role("heading", name="Approvals", exact=True).wait_for()
    finance_link = page.get_by_role("link", name="Open FinanceOS approvals in a separate application")
    with urlopen(f"{origin}/acceptance/status", timeout=5) as response:
        acceptance_status = json.loads(response.read())
    require(
        finance_link.get_attribute("href") == acceptance_status["approval_url"],
        "Finance approval link did not use the daemon-configured authority",
    )
    require(finance_link.get_attribute("target") == "_blank", "Finance approval link must open separately")
    require(page.get_by_text("Finance approvals are never handled here", exact=True).is_visible(), "approval boundary copy missing")
    checks.append({"check": "approval_authority_boundary", "result": "PASS"})

    for legacy, destination in LEGACY_DESTINATIONS.items():
        page.evaluate(
            "legacy => window.dispatchEvent(new CustomEvent('cato-navigate', {detail: legacy}))",
            legacy,
        )
        page.locator(".command-breadcrumb strong").filter(has_text=destination).wait_for()
        if legacy in {"dashboard", "inbox", "alerts"}:
            page.locator("[data-work-inbox-group]").first.wait_for()
            require(
                page.locator("[data-work-inbox-group]").count() == len(EXPECTED_GROUPS),
                f"legacy {legacy} did not render Work Inbox content",
            )
        else:
            active_tab = LEGACY_ACTIVE_TABS[legacy]
            surface = (
                page.locator(f'.ask-e4l-view[data-active-tab="{active_tab}"]')
                if destination == "Ask E4L"
                else page.locator(f'.tab-hub-panel[data-active-tab="{active_tab}"]')
            )
            surface.wait_for()
            require(surface.is_visible(), f"legacy {legacy} did not render intended {active_tab} content")
    checks.append({"check": "all_legacy_routes_resolve", "result": "PASS"})

    page.evaluate(
        "() => window.dispatchEvent(new CustomEvent('cato-navigate', {detail: 'diagnostics'}))"
    )
    page.get_by_label("Native build identity").filter(has_text=f"Native {expected_head[:8]}").wait_for()
    require(page.get_by_role("alert").filter(has_text="build identity mismatch").count() == 0, "native/frontend identity mismatch rendered")
    checks.append({"check": "rendered_native_frontend_identity", "result": "PASS"})

    page.get_by_role("button", name="Cato Work Inbox").click()
    page.get_by_role("heading", name="Work Inbox", exact=True).wait_for()
    stop_finance(origin)
    wait_for_finance_state(page, "Stale")
    require(page.get_by_text("Close status: acceptance-ready", exact=False).is_visible(), "cached Finance card disappeared")
    require(page.get_by_text("as of", exact=False).is_visible(), "stale Finance timestamp missing")
    page.screenshot(path=str(output / "work-inbox-stale.png"), full_page=True)
    checks.append({"check": "financeos_outage_cached_stale_no_crash", "result": "PASS"})

    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPO / "output" / "playwright" / "work-inbox")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--expected-head", default=None)
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    expected_head = (args.expected_head or git_head()).strip().lower()
    require(len(expected_head) == 40, "expected HEAD must be a full Git SHA")
    if not args.skip_build:
        build_env = os.environ.copy()
        build_env["VITE_CATO_BUILD_SHA"] = expected_head
        subprocess.run(["npm.cmd", "run", "build"], cwd=DESKTOP, check=True, env=build_env)
    require(
        bundle_contains_sha(DESKTOP / "dist", expected_head),
        f"production bundle does not contain expected build SHA {expected_head}",
    )

    appdata = Path(tempfile.mkdtemp(prefix="cato-work-inbox-acceptance-"))
    port = free_port()
    origin = f"http://127.0.0.1:{port}"
    server_log_path = output / "acceptance-server.log"
    server_log = server_log_path.open("w", encoding="utf-8")
    server_env = os.environ.copy()
    server_env["CATO_EXPECTED_BUILD_SHA"] = expected_head
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
        env=server_env,
    )
    console_failures: list[str] = []
    expected_degradations: list[str] = []
    generic_503_console: list[str] = []
    response_503s: list[str] = []
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
                if "503 (Service Unavailable)" in text:
                    generic_503_console.append(text)
                    return
                if (
                    ("WebSocket connection to" in text and "/ws" in text and "404" in text)
                    or text == "[useChatStream] WebSocket error"
                ):
                    expected_degradations.append(text)
                    return
                console_failures.append(text)

            page.on("console", capture_console)
            page.on("pageerror", lambda error: console_failures.append(str(error)))
            page.on(
                "response",
                lambda response: response_503s.append(response.url)
                if response.status == 503 else None,
            )
            checks = run_acceptance(page, origin, output, expected_head)
            context.close()
            browser.close()
        require(console_failures == [], f"browser console failures: {console_failures}")
        require(
            len(generic_503_console) == len(response_503s),
            f"unattributed 503 console errors: console={len(generic_503_console)} responses={response_503s}",
        )
        allowed_fixture_503_paths = {
            # Populated only for routes whose fixture dependency is explicitly
            # unavailable; every response is still matched by exact URL/status.
            "/api/routing/status",  # create_ui_app(None): no model gateway in browser fixture
        }
        unexpected_503s = [
            url for url in response_503s
            if urlparse(url).path not in allowed_fixture_503_paths
        ]
        require(unexpected_503s == [], f"unexpected HTTP 503 responses: {unexpected_503s}")
        payload = {
            "result": "PASS",
            "production_bundle": str(DESKTOP / "dist"),
            "cato_route": "real",
            "finance_fixture": "loopback",
            "ports_dynamic": True,
            "build_head": expected_head,
            "checks": checks,
            "console_failures": console_failures,
            "expected_fixture_degradations": expected_degradations,
            "expected_fixture_503s": response_503s,
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
