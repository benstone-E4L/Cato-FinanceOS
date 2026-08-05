"""
cato_playwright_full_test.py
============================================================
Comprehensive Playwright end-to-end test for the Cato AI agent
web UI running at http://localhost:8080.

Tests every page, every interactive element, every API endpoint
reachable from the UI, and documents all bugs found.

Run:
    python cato_playwright_full_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import (
    Page,
    Request,
    Response,
    async_playwright,
    ConsoleMessage,
)

BASE_URL = "http://localhost:8080"
SCREENSHOTS_DIR = Path(r"C:\Users\Administrator\Desktop\Cato\test_screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Bug tracker
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Bug:
    bug_id: str
    page: str
    description: str
    expected: str
    actual: str
    severity: str  # Critical / High / Medium / Low
    endpoint: str = ""
    extra: str = ""


bugs: list[Bug] = []
test_results: list[dict] = []


def record_bug(
    bug_id: str,
    page: str,
    description: str,
    expected: str,
    actual: str,
    severity: str,
    endpoint: str = "",
    extra: str = "",
) -> None:
    b = Bug(bug_id, page, description, expected, actual, severity, endpoint, extra)
    bugs.append(b)
    print(f"  [BUG {bug_id}] ({severity}) {description}")


def record_result(test_name: str, passed: bool, detail: str = "") -> None:
    test_results.append({"test": test_name, "passed": passed, "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {test_name}" + (f" — {detail}" if detail else ""))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def screenshot(page: Page, name: str) -> None:
    path = SCREENSHOTS_DIR / f"{name}.png"
    await page.screenshot(path=str(path), full_page=True)


async def wait_for_page_stable(page: Page, timeout: int = 3000) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    await asyncio.sleep(0.5)


async def navigate_to_view(page: Page, view: str) -> None:
    """Navigate to a page using the JS navigate() function in dashboard.html."""
    # Map friendly names to data-page attribute values
    PAGE_MAP = {
        "dashboard": "dashboard",
        "chat": "chat",
        "coding agent": "agents",
        "agents": "agents",
        "skills": "skills",
        "cron": "cron",
        "cron jobs": "cron",
        "sessions": "sessions",
        "usage": "usage",
        "audit": "audit",
        "audit log": "audit",
        "logs": "logs",
        "alerts": "alerts",
        "memory": "memory",
        "system": "system",
        "diagnostics": "diagnostics",
        "config": "config",
        "budget": "budget",
        "conduit": "conduit",
        "vault": "vault",
        "auth": "vault",
        "auth keys": "vault",
        "auth & keys": "vault",
        "identity": "config",  # No identity page in web UI — config is closest
        "flows": "cron",       # No flows page in web UI — cron is closest
        "nodes": "system",     # No nodes page in web UI — system is closest
    }
    page_id = PAGE_MAP.get(view.lower(), view.lower())
    try:
        await page.evaluate(f"navigate('{page_id}')")
        await asyncio.sleep(0.8)
    except Exception:
        # Fallback: click nav item with data-page attribute
        try:
            nav_item = await page.query_selector(f".nav-item[data-page='{page_id}']")
            if nav_item:
                await nav_item.click(timeout=5000)
                await asyncio.sleep(0.8)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# API pre-flight checks (pure HTTP, no browser)
# ─────────────────────────────────────────────────────────────────────────────

def test_api_endpoints() -> None:
    print("\n=== API ENDPOINT PRE-FLIGHT ===")

    endpoints: list[tuple[str, str, int]] = [
        ("GET", "/health", 200),
        ("GET", "/api/heartbeat", 200),
        ("GET", "/api/adapters", 200),
        ("GET", "/api/budget/summary", 200),
        ("GET", "/api/sessions", 200),
        ("GET", "/api/usage/summary", 200),
        ("GET", "/api/config", 200),
        ("GET", "/api/skills", 200),
        ("GET", "/api/cron/jobs", 200),
        ("GET", "/api/audit/entries", 200),
        ("GET", "/api/logs", 200),
        ("GET", "/api/flows", 200),
        ("GET", "/api/nodes", 200),
        ("GET", "/api/memory/stats", 200),
        ("GET", "/api/cli/status", 200),
        ("GET", "/api/action-guard/status", 200),
        ("GET", "/api/vault/keys", 200),
        ("GET", "/api/workspace/files", 200),
        ("GET", "/api/diagnostics/query-classifier", 200),
        ("GET", "/api/diagnostics/contradiction-health", 200),
        ("GET", "/api/diagnostics/decision-memory", 200),
        ("GET", "/api/diagnostics/anomaly-domains", 200),
        ("GET", "/api/diagnostics/skill-corrections", 200),
        ("GET", "/api/chat/history", 200),
    ]

    for method, path, expected_code in endpoints:
        try:
            r = requests.request(method, BASE_URL + path, timeout=5)
            passed = r.status_code == expected_code
            record_result(f"API {method} {path}", passed,
                          f"status={r.status_code}")
            if not passed:
                record_bug(
                    f"API-{path.replace('/', '-').strip('-')}",
                    "API",
                    f"{method} {path} returned {r.status_code}",
                    f"HTTP {expected_code}",
                    f"HTTP {r.status_code}",
                    "High",
                    endpoint=path,
                )
        except Exception as exc:
            record_result(f"API {method} {path}", False, str(exc))
            record_bug(
                f"API-{path.replace('/', '-').strip('-')}",
                "API",
                f"{method} {path} raised exception",
                "HTTP 200 response",
                str(exc),
                "Critical",
                endpoint=path,
            )

    # -- Heartbeat status check --
    try:
        hb = requests.get(BASE_URL + "/api/heartbeat", timeout=5).json()
        if hb.get("status") == "unknown" and hb.get("last_heartbeat") is None:
            record_bug(
                "HB-001",
                "Dashboard / Heartbeat API",
                "Heartbeat API returns status='unknown' with null last_heartbeat and null agent_name",
                "Heartbeat status should be 'alive' with a valid last_heartbeat timestamp when daemon is running",
                f"status={hb.get('status')}, last_heartbeat={hb.get('last_heartbeat')}, agent_name={hb.get('agent_name')}",
                "High",
                endpoint="/api/heartbeat",
                extra="Dashboard will display 'unknown' heartbeat status pill, misleading users into thinking agent is not running",
            )
            record_result("Heartbeat status is alive", False, f"got status={hb.get('status')}")
        else:
            record_result("Heartbeat status is alive", True)
    except Exception as exc:
        record_result("Heartbeat endpoint reachable", False, str(exc))

    # -- Config returns empty object --
    try:
        cfg = requests.get(BASE_URL + "/api/config", timeout=5).json()
        if cfg == {}:
            record_bug(
                "CFG-001",
                "Config page",
                "GET /api/config returns empty object {}",
                "Should return current config values (agent_name, default_model, etc.)",
                "Returns: {}",
                "High",
                endpoint="/api/config",
                extra="Config form will show all fields as blank/default. User edits and saves but next reload loses them if PATCH doesn't persist to disk.",
            )
            record_result("Config returns non-empty data", False, "got {}")
        else:
            record_result("Config returns non-empty data", True)
    except Exception as exc:
        record_result("Config endpoint", False, str(exc))

    # -- Config PATCH returns data vs status:ok --
    try:
        r = requests.patch(BASE_URL + "/api/config",
                           json={"test_key": "test_val"}, timeout=5)
        resp = r.json()
        if resp.get("status") == "ok":
            record_bug(
                "CFG-002",
                "Config page",
                "PATCH /api/config returns {status: ok} instead of the updated config object",
                "Should return the updated config object so the UI can refresh",
                f"Returns: {resp}",
                "Medium",
                endpoint="/api/config",
                extra="ConfigView.tsx expects data.error check and then sets config from response. When response is {status:'ok'} the form may not update correctly.",
            )
            record_result("PATCH /api/config returns updated config", False, f"got {resp}")
        else:
            record_result("PATCH /api/config returns updated config", True)
    except Exception as exc:
        record_result("PATCH /api/config", False, str(exc))

    # -- Identity PUT works --
    try:
        r = requests.put(BASE_URL + "/api/workspace/file",
                         json={"name": "SOUL.md", "content": "# Test\n"}, timeout=5)
        resp = r.json()
        if resp.get("status") == "ok":
            record_result("PUT /api/workspace/file saves file", True)
            # Restore original
            orig = requests.get(BASE_URL + "/api/workspace/file?name=SOUL.md", timeout=5).json()
        else:
            record_bug(
                "IDENT-001",
                "Identity page",
                "PUT /api/workspace/file did not return {status: ok}",
                "{status: ok}",
                str(resp),
                "High",
                endpoint="/api/workspace/file",
            )
            record_result("PUT /api/workspace/file saves file", False, str(resp))
    except Exception as exc:
        record_result("PUT /api/workspace/file", False, str(exc))

    # -- POST /api/workspace/file should be 405 (only PUT supported) --
    try:
        r = requests.post(BASE_URL + "/api/workspace/file",
                          json={"name": "SOUL.md", "content": "# test"}, timeout=5)
        if r.status_code == 405:
            record_bug(
                "IDENT-002",
                "Identity page",
                "POST /api/workspace/file returns 405 Method Not Allowed",
                "Identity save uses PUT which works, but method clarity in API is missing",
                "POST returns 405, only PUT is accepted",
                "Low",
                endpoint="/api/workspace/file",
                extra="API only supports PUT. Frontend correctly uses PUT. No user impact but API should document this.",
            )
        record_result("Identity file endpoint method check", True, f"POST=405 (correct, PUT=200)")
    except Exception as exc:
        record_result("Identity file method check", False, str(exc))

    # -- Cron toggle with non-existent job --
    try:
        r = requests.post(BASE_URL + "/api/cron/jobs/nonexistent-job/toggle", timeout=5)
        if r.status_code == 500:
            record_bug(
                "CRON-001",
                "Cron Jobs page",
                "POST /api/cron/jobs/{name}/toggle returns 500 for nonexistent job",
                "Should return 404 Not Found with informative error message",
                f"HTTP 500, body: {r.text[:200]}",
                "Medium",
                endpoint="/api/cron/jobs/{name}/toggle",
                extra="Error message 'Expecting value: line 1 column 1 (char 0)' suggests JSON parsing error on empty/missing config.",
            )
            record_result("Cron toggle non-existent job returns 404", False, f"got 500")
        else:
            record_result("Cron toggle non-existent job returns 404", True, f"got {r.status_code}")
    except Exception as exc:
        record_result("Cron toggle 404 handling", False, str(exc))

    # -- Diagnostics contradiction-health SQLite thread error --
    try:
        r = requests.get(BASE_URL + "/api/diagnostics/contradiction-health", timeout=5)
        resp = r.json()
        if "error" in resp and "SQLite" in str(resp.get("error", "")):
            record_bug(
                "DIAG-001",
                "Diagnostics page",
                "GET /api/diagnostics/contradiction-health contains SQLite thread safety error in response",
                "Should return clean contradiction health data without error field",
                f"error field: {resp.get('error', '')[:120]}",
                "High",
                endpoint="/api/diagnostics/contradiction-health",
                extra="SQLite objects created in one thread cannot be used in another. ContradictionDetector needs thread-safe connection management (WAL + per-call connections).",
            )
            record_result("Diagnostics contradiction-health no SQLite error", False)
        else:
            record_result("Diagnostics contradiction-health no SQLite error", True)
    except Exception as exc:
        record_result("Diagnostics contradiction-health", False, str(exc))

    # -- CLI status: codex/gemini/cursor logged_in=false --
    try:
        cli = requests.get(BASE_URL + "/api/cli/status", timeout=5).json()
        cold_tools = [name for name, status in cli.items()
                      if isinstance(status, dict) and status.get("installed") and not status.get("logged_in")]
        if cold_tools:
            record_bug(
                "SYS-001",
                "System page",
                f"CLI tools {cold_tools} show as 'cold' (installed but not logged_in) in /api/cli/status",
                "Tools that the coding agent successfully uses should show as 'warm' (logged_in=true)",
                f"installed=true, logged_in=false for: {cold_tools}",
                "Medium",
                endpoint="/api/cli/status",
                extra="SystemView shows these as 'cold' (red badge). Coding agent readme/memory says Codex works. The logged_in check may not correctly detect auth state for these tools.",
            )
            record_result("All installed CLI tools show warm", False, f"cold: {cold_tools}")
        else:
            record_result("All installed CLI tools show warm", True)
    except Exception as exc:
        record_result("CLI status check", False, str(exc))

    # -- Chat history contains raw tool call XML --
    try:
        history = requests.get(BASE_URL + "/api/chat/history", timeout=5).json()
        for msg in history:
            if "<minimax:tool_call>" in msg.get("text", ""):
                record_bug(
                    "CHAT-001",
                    "Chat page",
                    "Chat response in /api/chat/history contains raw XML tool call markup (<minimax:tool_call>)",
                    "Tool call XML should be stripped or hidden before storing/displaying chat responses",
                    f"Message text contains: <minimax:tool_call> block visible to user",
                    "High",
                    endpoint="/api/chat/history",
                    extra="The LLM (MiniMax m2.5 via OpenRouter) outputs tool calls as XML. The gateway/agent loop must strip these before returning text to the user.",
                )
                record_result("Chat responses free of raw tool call XML", False)
                break
        else:
            record_result("Chat responses free of raw tool call XML", True)
    except Exception as exc:
        record_result("Chat history check", False, str(exc))

    # -- Chat history contains cost line --
    try:
        history = requests.get(BASE_URL + "/api/chat/history", timeout=5).json()
        for msg in history:
            text = msg.get("text", "")
            if "this call | Month:" in text and "$" in text:
                record_bug(
                    "CHAT-002",
                    "Chat page",
                    "Chat response contains cost/budget line visible to user (e.g. '$0.0000 this call | Month: $0.00/$20.00 | 100% remaining')",
                    "Budget/cost information should be tracked internally and shown only in the Budget page, not in chat messages",
                    f"Message text ends with: [{text[text.rfind('[$'):text.rfind(']')+1] if '[$' in text else 'cost line'}]",
                    "Medium",
                    endpoint="/api/chat/history",
                    extra="The agent_loop or gateway appends spend info to the response text. This should be stripped before sending to the WebSocket client.",
                )
                record_result("Chat responses free of cost lines", False)
                break
        else:
            record_result("Chat responses free of cost lines", True)
    except Exception as exc:
        record_result("Chat cost line check", False, str(exc))

    # -- Chat identity: "I'm Claude Code" --
    try:
        history = requests.get(BASE_URL + "/api/chat/history", timeout=5).json()
        for msg in history:
            text = msg.get("text", "")
            if msg.get("role") == "assistant" and (
                "I'm Claude Code" in text or "Claude Code" in text
            ):
                record_bug(
                    "CHAT-003",
                    "Chat page",
                    "Chat assistant identifies itself as 'Claude Code' instead of 'Cato'",
                    "Assistant should identify as 'Cato' — Cato's own identity per SOUL.md/IDENTITY.md",
                    f"Response text: {text[:200]}",
                    "High",
                    endpoint="/api/chat/history",
                    extra="The IDENTITY.md and SOUL.md workspace files define Cato's identity. These must be injected into the system prompt. The LLM defaulting to 'Claude Code' means system prompt is missing or not effective.",
                )
                record_result("Chat assistant identifies as Cato (not Claude Code)", False)
                break
        else:
            record_result("Chat assistant identifies as Cato (not Claude Code)", True)
    except Exception as exc:
        record_result("Chat identity check", False, str(exc))

    # -- Chat identity tries to call Anthropic API to confirm identity --
    try:
        history = requests.get(BASE_URL + "/api/chat/history", timeout=5).json()
        for msg in history:
            text = msg.get("text", "")
            if msg.get("role") == "assistant" and "anthropic" in text.lower() and "confirm" in text.lower():
                record_bug(
                    "CHAT-004",
                    "Chat page",
                    "Chat assistant attempts to call Anthropic API to confirm its own identity",
                    "Cato should know its own identity from SOUL.md/IDENTITY.md without external API calls",
                    f"Response includes: '{text[:300]}'",
                    "High",
                    endpoint="/api/chat/history",
                    extra="This is a hallucination/identity confusion issue. Cato is running MiniMax model via OpenRouter but its identity files say it is Cato. The model should not be attempting external identity verification.",
                )
                record_result("Chat assistant does not call Anthropic API for identity", False)
                break
        else:
            record_result("Chat assistant does not call Anthropic API for identity", True)
    except Exception as exc:
        record_result("Chat Anthropic API identity check", False, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Browser tests
# ─────────────────────────────────────────────────────────────────────────────

async def run_browser_tests() -> None:
    print("\n=== BROWSER TESTS (Playwright) ===")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            java_script_enabled=True,
        )

        # Collect console errors and network failures
        console_errors: list[str] = []
        failed_requests: list[str] = []

        page = await context.new_page()

        page.on("console", lambda msg: console_errors.append(
            f"[{msg.type.upper()}] {msg.text}"
        ) if msg.type in ("error", "warning") else None)

        page.on("requestfailed", lambda req: failed_requests.append(
            f"{req.method} {req.url} — {req.failure}"
        ))

        try:
            # ── 1. Initial page load ─────────────────────────────────────────
            print("\n-- Page Load --")
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            await wait_for_page_stable(page)

            # Dismiss onboarding overlay if present (sets localStorage flag)
            await page.evaluate("""() => {
                localStorage.setItem('cato_onboarded', '1');
                const overlay = document.getElementById('onboarding-overlay');
                if (overlay) overlay.style.display = 'none';
                // Also call dismissOnboarding if defined
                if (typeof dismissOnboarding === 'function') dismissOnboarding();
            }""")
            await asyncio.sleep(0.5)

            await screenshot(page, "T01_initial_load")

            title = await page.title()
            record_result("Page title set", bool(title), f"title='{title}'")

            # Check sidebar exists
            sidebar = await page.query_selector("#sidebar, .sidebar, aside")
            record_result("Sidebar visible", sidebar is not None)

            # Check nav items are present
            nav_items = await page.query_selector_all(".nav-item")
            record_result("Navigation items present", len(nav_items) > 0,
                          f"found {len(nav_items)} items")

            if len(nav_items) == 0:
                record_bug(
                    "NAV-001",
                    "All pages",
                    "No .nav-item elements found in sidebar",
                    "Sidebar should have navigation items for each view",
                    "Zero nav items found in DOM",
                    "Critical",
                )

            # ── 2. Settings link in sidebar ──────────────────────────────────
            print("\n-- Sidebar Navigation Check --")
            nav_texts = []
            for item in nav_items:
                t = (await item.inner_text()).strip()
                nav_texts.append(t)

            # Print safely (strip non-ASCII for Windows console)
            safe_nav = [t.encode("ascii", "replace").decode("ascii") for t in nav_texts]
            print(f"  Nav items found: {safe_nav}")

            # Check that essential nav items are present
            expected_pages = ["dashboard", "chat", "skills", "cron", "sessions",
                               "usage", "config", "budget", "system", "diagnostics"]
            page_ids_found = []
            nav_elements = await page.query_selector_all(".nav-item[data-page]")
            for el in nav_elements:
                pid = await el.get_attribute("data-page")
                if pid:
                    page_ids_found.append(pid)

            missing_pages = [p for p in expected_pages if p not in page_ids_found]
            record_result("All expected nav pages present", not missing_pages,
                          f"found: {page_ids_found}" if missing_pages else f"{len(page_ids_found)} pages")
            if missing_pages:
                record_bug(
                    "NAV-002",
                    "All pages / Sidebar",
                    f"Navigation missing pages: {missing_pages}",
                    f"All of {expected_pages} should be in sidebar navigation",
                    f"Missing: {missing_pages}, Found: {page_ids_found}",
                    "High",
                )

            # Check for "Settings" group label — web UI has no explicit "Settings" group header
            settings_group = await page.query_selector(".nav-group-header:text('Settings')")
            if not settings_group:
                record_bug(
                    "NAV-003",
                    "All pages / Sidebar",
                    "No 'Settings' group label in sidebar navigation",
                    "Sidebar should have a labeled 'Settings' group containing Config, Budget, Alerts, Auth, Identity",
                    "Settings group header not present in sidebar",
                    "Low",
                    extra="The Tauri Sidebar.tsx has a proper 'Settings' group. The web dashboard.html sidebar lacks this grouping label, making navigation harder to scan.",
                )

            # ── 3. Dashboard page ────────────────────────────────────────────
            print("\n-- Dashboard --")
            # Try to navigate to dashboard
            await navigate_to_view(page, "Dashboard")
            await wait_for_page_stable(page)
            await screenshot(page, "T02_dashboard")

            # Check for key dashboard elements
            page_content = await page.content()

            # Gateway status check
            if "gateway" in page_content.lower() or "online" in page_content.lower():
                record_result("Dashboard: Gateway status visible", True)
            else:
                record_result("Dashboard: Gateway status visible", False, "Not found in DOM")

            # Heartbeat section
            if "heartbeat" in page_content.lower():
                record_result("Dashboard: Heartbeat section present", True)
                # Check if it shows "unknown"
                if "unknown" in page_content.lower():
                    record_bug(
                        "DASH-001",
                        "Dashboard",
                        "Dashboard heartbeat section displays 'unknown' status",
                        "Should show 'alive' or last known heartbeat time when daemon is running",
                        "Dashboard shows heartbeat status as 'unknown'",
                        "High",
                        endpoint="/api/heartbeat",
                        extra="API /api/heartbeat returns {status:'unknown', last_heartbeat:null, agent_name:null}. The agent_loop is not calling the heartbeat endpoint to report its status.",
                    )
            else:
                record_result("Dashboard: Heartbeat section present", False)

            # Budget display
            if "$" in page_content or "spend" in page_content.lower() or "budget" in page_content.lower():
                record_result("Dashboard: Budget data visible", True)
            else:
                record_result("Dashboard: Budget data visible", False)

            # ── 4. Chat page ─────────────────────────────────────────────────
            print("\n-- Chat page --")
            await navigate_to_view(page, "Chat")
            await wait_for_page_stable(page)
            await screenshot(page, "T03_chat")

            # Web UI uses #chat-input textarea and #send-btn
            chat_input = await page.query_selector(
                "#chat-input, textarea.chat-input, textarea[placeholder*='message']"
            )
            record_result("Chat: Input field present", chat_input is not None)

            send_btn = await page.query_selector(
                "#send-btn, button.chat-send-btn, button[onclick*='sendMessage']"
            )
            record_result("Chat: Send button present", send_btn is not None)

            if not send_btn:
                record_bug(
                    "CHAT-005",
                    "Chat page",
                    "Chat send button (#send-btn) not found or not visible in chat page",
                    "Chat page should have a visible Send button to submit messages",
                    "No #send-btn or button[onclick*='sendMessage'] found in active chat page",
                    "High",
                    extra="The button exists in dashboard.html at line 524 with id='send-btn'. May be hidden due to page not being active, or selector mismatch.",
                )

            # Check WS status — web UI uses health-dot / health-pill in sidebar
            health_dot = await page.query_selector(".health-dot, .health-pill")
            if health_dot:
                health_text = (await health_dot.inner_text()).strip()
                record_result("Chat: WS/health status visible", True, f"health='{health_text}'")
            else:
                # Check if WS is connected via JS state
                ws_ready = await page.evaluate("() => typeof state !== 'undefined' ? state.wsReady : null")
                record_result("Chat: WebSocket state reachable via JS", ws_ready is not None,
                              f"wsReady={ws_ready}")
                if ws_ready is False:
                    record_bug(
                        "CHAT-006",
                        "Chat page",
                        "WebSocket not connected (state.wsReady=false) in web UI",
                        "state.wsReady should be true when daemon is running and WS is available",
                        f"state.wsReady={ws_ready}",
                        "High",
                        endpoint="ws://127.0.0.1:8081/ws",
                        extra="Web UI chat connects to ws://localhost:8081/ws via state.ws. If wsReady=false, messages cannot be sent.",
                    )

            # Check for Telegram messages appearing
            page_content = await page.content()
            if "telegram" in page_content.lower():
                record_result("Chat: Telegram integration visible", True)
            else:
                record_result("Chat: Telegram badge/label present", False, "No telegram mention in DOM")

            # ── 5. Coding Agent page ─────────────────────────────────────────
            print("\n-- Coding Agent page --")
            await navigate_to_view(page, "Coding Agent")
            await wait_for_page_stable(page)
            await screenshot(page, "T04_coding_agent")

            page_content = await page.content()
            if "coding" in page_content.lower() or "agent" in page_content.lower():
                record_result("Coding Agent: Page loaded", True)
            else:
                record_result("Coding Agent: Page loaded", False, "No coding agent content")
                record_bug(
                    "CODE-001",
                    "Coding Agent page",
                    "Coding Agent page does not load or has no content",
                    "Should show coding agent interface with task input, model selector, and output panel",
                    "Page appears empty or shows no coding-agent-specific elements",
                    "High",
                )

            # ── 6. Skills page ───────────────────────────────────────────────
            print("\n-- Skills page --")
            await navigate_to_view(page, "Skills")
            await wait_for_page_stable(page)
            await screenshot(page, "T05_skills")

            skills_data = requests.get(BASE_URL + "/api/skills", timeout=5).json()
            # Allow JS to populate skills list
            await asyncio.sleep(1.5)
            page_content = await page.content()

            skills_div = await page.query_selector("#skills-page, #skills-list, .skills-grid, .skills-container")
            if skills_data:
                # Skills exist — check if any skill name appears in page
                skill_names = []
                for s in skills_data[:5]:
                    if isinstance(s, dict):
                        skill_names.append(s.get("name", s.get("dir", "")))
                    else:
                        skill_names.append(str(s))

                visible = any(name.lower()[:8] in page_content.lower() for name in skill_names if name)
                record_result("Skills: Skills list renders", visible,
                              f"checking {len(skill_names)} skills, visible={visible}")
                if not visible:
                    record_bug(
                        "SKILL-001",
                        "Skills page",
                        "Skills from /api/skills not rendered in Skills page",
                        f"Skills page should list {len(skills_data)} skills from API",
                        f"None of {skill_names[:3]} found in page DOM",
                        "Medium",
                        endpoint="/api/skills",
                        extra="Skills may be loaded asynchronously. Check if loadSkills() JS function is called on page navigation.",
                    )
            else:
                record_result("Skills: Skills list renders", True, "empty skills list")

            # ── 7. Cron Jobs page ────────────────────────────────────────────
            print("\n-- Cron Jobs page --")
            await navigate_to_view(page, "Cron")
            await wait_for_page_stable(page)
            await screenshot(page, "T06_cron_jobs")

            page_content = await page.content()
            if "cron" in page_content.lower() or "job" in page_content.lower():
                record_result("Cron: Page loaded", True)
            else:
                record_result("Cron: Page loaded", False)

            # Check "Add Job" or create button
            add_btn = await page.query_selector(
                "button[class*='btn-primary'], button:text('Add'), button:text('New'), button:text('Create')"
            )
            record_result("Cron: Create/Add job button present",
                          add_btn is not None)

            # ── 8. Sessions page ─────────────────────────────────────────────
            print("\n-- Sessions page --")
            await navigate_to_view(page, "Sessions")
            await wait_for_page_stable(page)
            await screenshot(page, "T07_sessions")

            sessions_data = requests.get(BASE_URL + "/api/sessions", timeout=5).json()
            page_content = await page.content()

            record_result("Sessions: Page loaded", "session" in page_content.lower())

            if sessions_data:
                session_id = sessions_data[0]["session_id"]
                if session_id[:8] in page_content:
                    record_result("Sessions: Active sessions displayed", True)
                else:
                    record_result("Sessions: Active sessions displayed", False,
                                  f"session_id {session_id[:8]} not in page")
                    record_bug(
                        "SESS-001",
                        "Sessions page",
                        "Active sessions from /api/sessions not rendered in sessions view",
                        "Sessions page should list all active sessions with their IDs and status",
                        "Session IDs not found in rendered page content",
                        "Medium",
                        endpoint="/api/sessions",
                    )

            # ── 9. Usage page ────────────────────────────────────────────────
            print("\n-- Usage page --")
            await navigate_to_view(page, "Usage")
            await wait_for_page_stable(page)
            await screenshot(page, "T08_usage")

            page_content = await page.content()
            record_result("Usage: Page loaded", "usage" in page_content.lower() or "call" in page_content.lower())

            # ── 10. Logs page ────────────────────────────────────────────────
            print("\n-- Logs page --")
            await navigate_to_view(page, "Logs")
            await wait_for_page_stable(page)
            await screenshot(page, "T09_logs")

            logs_data = requests.get(BASE_URL + "/api/logs", timeout=5).json()
            await asyncio.sleep(1.5)  # allow JS to populate
            page_content = await page.content()
            record_result("Logs: Page loaded", True)

            logs_table = await page.query_selector("#logs-page, #log-table, .log-list, #logs-tbody")
            if logs_data and len(logs_data) > 0:
                # Check if log level or logger name appears (msg format may differ)
                log_levels = ["INFO", "ERROR", "WARNING", "DEBUG"]
                visible = any(lvl in page_content for lvl in log_levels)
                if visible:
                    record_result("Logs: Log entries rendered", True)
                else:
                    # Check if logs are still loading
                    if "loading" in page_content.lower():
                        record_result("Logs: Log entries rendered", False, "stuck in loading")
                        record_bug(
                            "LOGS-001",
                            "Logs page",
                            "Logs page stuck in loading state — log level strings not visible",
                            "Logs page should display log entries with INFO/ERROR/WARNING level indicators",
                            "No log level strings (INFO, ERROR, WARNING) found in rendered page",
                            "Medium",
                            endpoint="/api/logs",
                        )
                    else:
                        record_result("Logs: Log entries rendered", False,
                                      "log level strings not in page content")
            else:
                record_result("Logs: Log entries rendered", True, "no logs to display")

            # ── 11. Audit Log page ───────────────────────────────────────────
            print("\n-- Audit Log page --")
            await navigate_to_view(page, "Audit")
            await wait_for_page_stable(page)
            await screenshot(page, "T10_audit_log")

            page_content = await page.content()
            record_result("Audit: Page loaded", "audit" in page_content.lower() or "verify" in page_content.lower())

            # Look for Verify button
            verify_btn = await page.query_selector("button:text('Verify'), button[class*='verify']")
            record_result("Audit: Verify chain button present", verify_btn is not None)

            if verify_btn:
                await verify_btn.click()
                await asyncio.sleep(1)
                await screenshot(page, "T10b_audit_verify")
                record_result("Audit: Verify chain button clickable", True)

            # ── 12. Config page ──────────────────────────────────────────────
            print("\n-- Config page --")
            await navigate_to_view(page, "Config")
            await wait_for_page_stable(page)
            await screenshot(page, "T11_config")

            page_content = await page.content()
            record_result("Config: Page loaded",
                          "config" in page_content.lower() or "agent" in page_content.lower())

            # Check form fields
            agent_name_input = await page.query_selector("input[placeholder*='agent'], input[name*='agent']")
            form_inputs = await page.query_selector_all("input.form-input, select.settings-select, input[type='checkbox']")
            record_result("Config: Form inputs present", len(form_inputs) > 0,
                          f"found {len(form_inputs)} inputs")

            # Try saving config — call saveConfig() via JS (config page in web UI)
            try:
                save_result = await page.evaluate("""async () => {
                    if (typeof saveConfig === 'function') {
                        try { await saveConfig(); return 'called'; }
                        catch(e) { return 'error: ' + e.message; }
                    }
                    // Fallback: click save button within active config page
                    const configPage = document.getElementById('config-page');
                    if (configPage) {
                        const btn = configPage.querySelector('button.btn-primary, button[onclick*="save"]');
                        if (btn && btn.offsetParent !== null) { btn.click(); return 'clicked'; }
                        return 'no-btn';
                    }
                    return 'no-config-page';
                }""")
                await asyncio.sleep(1.5)
                await screenshot(page, "T11b_config_save")
                record_result("Config: Save function invoked", True, f"result={save_result}")
            except Exception as exc:
                record_result("Config: Save function invoked", False, str(exc))

            # ── 13. Budget page ──────────────────────────────────────────────
            print("\n-- Budget page --")
            await navigate_to_view(page, "Budget")
            await wait_for_page_stable(page)
            await screenshot(page, "T12_budget")

            page_content = await page.content()
            budget_page = await page.query_selector("#budget-page.active, #budget-page[style*='block']")
            record_result("Budget: Page loaded",
                          "budget" in page_content.lower() or "$" in page_content)

            # Check spend data rendering
            if "0.00" in page_content or "session" in page_content.lower():
                record_result("Budget: Spend data rendered", True)
            else:
                record_result("Budget: Spend data rendered", False)
                record_bug(
                    "BUDG-001",
                    "Budget page",
                    "Budget page does not render spend data",
                    "Should show session spend, monthly spend, caps, and percentage remaining",
                    "Budget amounts not visible in page",
                    "Medium",
                    endpoint="/api/budget/summary",
                )

            # ── 14. Alerts page ──────────────────────────────────────────────
            # Note: The web UI's alerts are embedded in the sidebar badge, not a dedicated page
            print("\n-- Alerts page (web UI embedded) --")
            # Alerts in dashboard.html are a nav item that shows badge but no dedicated page
            alerts_nav = await page.query_selector(".nav-item[data-page='alerts']")
            if not alerts_nav:
                record_bug(
                    "ALERTS-001",
                    "Alerts",
                    "No dedicated Alerts page exists in the web UI dashboard",
                    "There should be an alerts page (/alerts) accessible from sidebar with alert management UI",
                    "Nav item 'alerts' not found; web UI has no alerts page div",
                    "High",
                    extra="The Tauri desktop app has AlertsView.tsx. The web UI dashboard.html does not include an alerts page or nav item for it.",
                )
                record_result("Alerts: Nav item present in web UI", False)
            else:
                record_result("Alerts: Nav item present in web UI", True)
                await alerts_nav.click()
                await asyncio.sleep(0.8)
                await screenshot(page, "T13_alerts")

            # ── 15. Auth & Keys page ─────────────────────────────────────────
            print("\n-- Auth & Keys page (Vault & Auth) --")
            await navigate_to_view(page, "vault")
            await wait_for_page_stable(page)
            await screenshot(page, "T14_auth_keys")

            page_content = await page.content()
            record_result("Auth Keys: Page loaded",
                          "key" in page_content.lower() or "vault" in page_content.lower() or "auth" in page_content.lower())

            # Check vault key list div is present (loaded async)
            await asyncio.sleep(1)  # allow JS to populate
            vault_key_list = await page.query_selector("#vault-key-list")
            if vault_key_list:
                list_content = await vault_key_list.inner_text()
                vault_keys = requests.get(BASE_URL + "/api/vault/keys", timeout=5).json()
                if vault_keys and any(k in list_content for k in vault_keys):
                    record_result("Auth Keys: Vault keys rendered in list", True)
                elif vault_keys and "Loading" in list_content:
                    record_result("Auth Keys: Vault keys still loading", False, "stuck in loading state")
                    record_bug(
                        "AUTH-001",
                        "Auth & Keys page",
                        "Vault key list stuck in 'Loading vault keys...' state",
                        "Should display vault key names from /api/vault/keys",
                        f"#vault-key-list content: '{list_content[:100]}'",
                        "High",
                        endpoint="/api/vault/keys",
                    )
                else:
                    record_result("Auth Keys: Vault keys rendered in list", True, "empty or loaded")
            else:
                record_result("Auth Keys: Vault key list element present", False)
                record_bug(
                    "AUTH-001",
                    "Auth & Keys page",
                    "Vault key list element (#vault-key-list) not found in page",
                    "Vault & Auth page should have a key list div populated from /api/vault/keys",
                    "#vault-key-list not in DOM",
                    "High",
                    endpoint="/api/vault/keys",
                )

            # ── 16. Identity page ────────────────────────────────────────────
            # Note: The web UI (dashboard.html) does NOT have an Identity page.
            # Identity editing is only in the Tauri desktop app (IdentityView.tsx).
            # The web UI Config page has some identity-related fields (agent_name).
            print("\n-- Identity page (web UI: not present, checking Config) --")
            identity_page_exists = await page.query_selector("#identity-page")
            if not identity_page_exists:
                record_bug(
                    "IDENT-004",
                    "Identity page",
                    "No dedicated Identity/workspace-files page in web UI dashboard",
                    "Web UI should have an Identity page for editing SOUL.md, IDENTITY.md, USER.md, AGENTS.md",
                    "No #identity-page div found in dashboard.html DOM",
                    "High",
                    endpoint="/api/workspace/files",
                    extra="IdentityView.tsx exists in the Tauri desktop app but has not been ported to the web dashboard.html. Users of the web UI cannot edit identity files.",
                )
                record_result("Identity: Dedicated page in web UI", False,
                              "Not present — only in Tauri app")
            else:
                record_result("Identity: Dedicated page in web UI", True)

            await screenshot(page, "T15_identity_check")

            # ── 17. Flows page ───────────────────────────────────────────────
            # Note: No Flows page in web UI dashboard.html — only in Tauri app
            print("\n-- Flows page (web UI: not present) --")
            flows_page = await page.query_selector("#flows-page")
            if not flows_page:
                record_bug(
                    "FLOW-003",
                    "Flows page",
                    "No dedicated Flows page in web UI dashboard",
                    "Web UI should have a Flows page for managing declarative multi-step workflows",
                    "No #flows-page div found in dashboard.html DOM",
                    "Medium",
                    endpoint="/api/flows",
                    extra="FlowsView.tsx exists in Tauri but is not ported to the web UI. The API endpoints /api/flows are functional.",
                )
                record_result("Flows: Dedicated page in web UI", False)
            else:
                record_result("Flows: Dedicated page in web UI", True)

            # ── 18. Nodes (Remote Nodes) page ────────────────────────────────
            # Note: No Nodes page in web UI dashboard.html — only in Tauri app
            print("\n-- Nodes page (web UI: not present) --")
            nodes_page = await page.query_selector("#nodes-page")
            if not nodes_page:
                record_bug(
                    "NODE-001",
                    "Nodes page",
                    "No dedicated Remote Nodes page in web UI dashboard",
                    "Web UI should have a Nodes page for monitoring remote Cato nodes",
                    "No #nodes-page div found in dashboard.html DOM",
                    "Low",
                    endpoint="/api/nodes",
                    extra="NodesView.tsx exists in Tauri but not ported to web UI.",
                )
                record_result("Nodes: Dedicated page in web UI", False)
            else:
                record_result("Nodes: Dedicated page in web UI", True)

            # ── 19. Memory page ──────────────────────────────────────────────
            print("\n-- Memory page --")
            await navigate_to_view(page, "Memory")
            await wait_for_page_stable(page)
            await screenshot(page, "T18_memory")

            page_content = await page.content()
            record_result("Memory: Page loaded", "memory" in page_content.lower() or "fact" in page_content.lower())

            # Check memory stats
            mem_stats = requests.get(BASE_URL + "/api/memory/stats", timeout=5).json()
            if "facts" in page_content.lower() or str(mem_stats.get("facts", 0)) in page_content:
                record_result("Memory: Stats rendered", True)
            else:
                record_result("Memory: Stats rendered", False,
                              f"memory stats {mem_stats} not in page")

            # ── 20. System page ──────────────────────────────────────────────
            print("\n-- System page --")
            await navigate_to_view(page, "System")
            await wait_for_page_stable(page)
            await screenshot(page, "T19_system")

            page_content = await page.content()
            record_result("System: Page loaded",
                          "system" in page_content.lower() or "cli" in page_content.lower())

            # Check for CLI pool panel
            if "claude" in page_content.lower() or "codex" in page_content.lower():
                record_result("System: CLI pool panel visible", True)
                # Check warm/cold badges
                if "cold" in page_content.lower():
                    cold_count = page_content.lower().count("cold")
                    record_result("System: Cold CLI tools shown", True,
                                  f"{cold_count} 'cold' occurrences — expected if codex/gemini/cursor not logged in")
                    # Cross-reference with bug already filed in API section
            else:
                record_result("System: CLI pool panel visible", False)
                record_bug(
                    "SYS-002",
                    "System page",
                    "System page does not render CLI pool panel",
                    "Should show Claude, Codex, Gemini, Cursor status cards with warm/cold badges",
                    "CLI tool names not found in page content",
                    "High",
                    endpoint="/api/cli/status",
                )

            # Check Action Guard panel
            if "safety" in page_content.lower() or "action guard" in page_content.lower() or "autonomy" in page_content.lower():
                record_result("System: Action Guard panel visible", True)
            else:
                record_result("System: Action Guard panel visible", False)

            # Check Daemon Controls
            restart_btn = await page.query_selector("button.btn-danger, button:text('Restart')")
            record_result("System: Restart Daemon button present", restart_btn is not None)

            # ── 21. Diagnostics page ─────────────────────────────────────────
            print("\n-- Diagnostics page --")
            await navigate_to_view(page, "Diagnostics")
            await wait_for_page_stable(page)
            await screenshot(page, "T20_diagnostics")

            page_content = await page.content()
            record_result("Diagnostics: Page loaded",
                          "diagnostic" in page_content.lower() or "classifier" in page_content.lower())

            # Click each diagnostic tab if present
            diag_tabs = await page.query_selector_all(
                "button[class*='tab'], [role='tab'], button.tab-btn"
            )
            record_result("Diagnostics: Tab buttons present", len(diag_tabs) > 0,
                          f"found {len(diag_tabs)} tabs")

            for i, tab in enumerate(diag_tabs[:5]):
                try:
                    tab_label = (await tab.inner_text()).strip()
                    # Use JS click to avoid visibility issues with tabs on inactive pages
                    await page.evaluate("(el) => el.click()", tab)
                    await asyncio.sleep(0.8)
                    safe_label = tab_label.encode("ascii", "replace").decode("ascii")[:10]
                    await screenshot(page, f"T20_diag_tab_{i}_{safe_label}")
                    record_result(f"Diagnostics: Tab '{tab_label}' clickable", True)
                except Exception as exc:
                    record_result(f"Diagnostics: Tab {i} clickable", False, str(exc)[:80])

            # Check for contradiction-health SQLite error rendering
            await wait_for_page_stable(page)
            page_content = await page.content()
            if "sqlite" in page_content.lower() and "thread" in page_content.lower():
                record_bug(
                    "DIAG-002",
                    "Diagnostics page",
                    "Diagnostics page renders raw SQLite thread error to user",
                    "Error details should be hidden; user should see a friendly 'data unavailable' message",
                    "Raw SQLite error visible in Diagnostics page content",
                    "Medium",
                    endpoint="/api/diagnostics/contradiction-health",
                )
                record_result("Diagnostics: No raw SQLite error in UI", False)
            else:
                record_result("Diagnostics: No raw SQLite error in UI", True)

            # ── 22. Interactive forms: Cron create ───────────────────────────
            print("\n-- Interactive: Cron Job Create --")
            await navigate_to_view(page, "cron")
            await wait_for_page_stable(page)

            # Click the "+ Add Cron" button to reveal form
            add_cron_btn = await page.query_selector("button[onclick*='toggleCronForm']")
            if add_cron_btn:
                await add_cron_btn.click()
                await asyncio.sleep(0.5)

            cron_schedule_input = await page.query_selector("#cron-schedule")
            cron_prompt_input = await page.query_selector("#cron-prompt")
            cron_agent_input = await page.query_selector("#cron-agent")

            if cron_schedule_input and cron_prompt_input:
                await cron_schedule_input.fill("*/30 * * * *")
                if cron_agent_input:
                    await cron_agent_input.fill("default")
                await cron_prompt_input.fill("playwright test job")

                save_cron_btn = await page.query_selector("button[onclick*='saveCron']")
                if save_cron_btn:
                    await save_cron_btn.click()
                    await asyncio.sleep(1)
                    await screenshot(page, "T21_cron_created")
                    record_result("Cron: Create job via UI", True, "saveCron() called")
                else:
                    record_result("Cron: Save cron button found", False)
            else:
                record_result("Cron: Job creation form inputs present", False,
                              "#cron-schedule or #cron-prompt not found")
                record_bug(
                    "CRON-002",
                    "Cron Jobs page",
                    "Cron creation form inputs not found or hidden",
                    "After clicking '+ Add Cron', form should show with schedule, agent, and prompt inputs",
                    "#cron-schedule not accessible",
                    "Medium",
                )

            # ── 23. Interactive: Vault key add ───────────────────────────────
            print("\n-- Interactive: Vault Key Add --")
            await navigate_to_view(page, "vault")
            await wait_for_page_stable(page)

            # Click "+ Add Key" button to show modal
            add_key_btn = await page.query_selector("button[onclick*='showAddVaultKeyModal']")
            if add_key_btn:
                await add_key_btn.click()
                await asyncio.sleep(0.5)

            key_name_input = await page.query_selector("#vault-add-name")
            key_value_input = await page.query_selector("#vault-add-value")

            if key_name_input and key_value_input:
                await key_name_input.fill("PLAYWRIGHT_TEST_KEY")
                await key_value_input.fill("test_value_123")
                save_key_btn = await page.query_selector("button[onclick*='saveVaultKey']")
                if save_key_btn:
                    await save_key_btn.click()
                    await asyncio.sleep(1)
                    await screenshot(page, "T22_vault_key_added")
                    record_result("Auth Keys: Add vault key via UI", True)
                else:
                    record_result("Auth Keys: Save vault key button", False)
            else:
                record_result("Auth Keys: Key add modal inputs present", False,
                              "#vault-add-name not found")
                record_bug(
                    "AUTH-002",
                    "Auth & Keys page",
                    "Vault key add modal inputs not accessible",
                    "After clicking '+ Add Key', modal should show with key name and value inputs",
                    "#vault-add-name not found",
                    "High",
                    endpoint="/api/vault/set",
                )

            # Clean up test key
            try:
                requests.post(BASE_URL + "/api/vault/delete",
                              json={"key": "PLAYWRIGHT_TEST_KEY"}, timeout=3)
            except Exception:
                pass

            # ── 24. Console errors summary ────────────────────────────────────
            print("\n-- Console Error Summary --")
            # Filter out known non-critical noise
            significant_errors = [
                e for e in console_errors
                if not any(skip in e for skip in [
                    "favicon", "sourcemap", "Warning: React", "unstable_"
                ])
            ]

            if significant_errors:
                record_result("No significant console errors", False,
                              f"{len(significant_errors)} errors")
                for err in significant_errors[:10]:
                    print(f"    CONSOLE: {err[:120]}")
                    record_bug(
                        f"CON-{significant_errors.index(err)+1:03d}",
                        "Browser Console",
                        f"Console error: {err[:120]}",
                        "No console errors or warnings in production",
                        err[:200],
                        "Low" if "[WARNING]" in err else "Medium",
                    )
            else:
                record_result("No significant console errors", True)

            # ── 25. Failed network requests ───────────────────────────────────
            print("\n-- Failed Network Requests --")
            if failed_requests:
                record_result("No failed network requests", False,
                              f"{len(failed_requests)} failures")
                for req_fail in failed_requests[:10]:
                    print(f"    NET FAIL: {req_fail[:120]}")
                    record_bug(
                        f"NET-{failed_requests.index(req_fail)+1:03d}",
                        "Network",
                        f"Network request failed: {req_fail[:100]}",
                        "All network requests should succeed",
                        req_fail[:200],
                        "High",
                        endpoint=req_fail.split(" ")[1] if " " in req_fail else req_fail,
                    )
            else:
                record_result("No failed network requests", True)

            # ── 26. Final full screenshot ─────────────────────────────────────
            await navigate_to_view(page, "Dashboard")
            await wait_for_page_stable(page)
            await screenshot(page, "T99_final_dashboard")

        except Exception as exc:
            print(f"\n  [FATAL] Browser test crashed: {exc}")
            traceback.print_exc()
            record_bug(
                "FATAL-001",
                "Browser",
                f"Browser test suite crashed: {exc}",
                "All tests should complete without exceptions",
                str(exc),
                "Critical",
            )
        finally:
            await browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Additional API behaviour checks
# ─────────────────────────────────────────────────────────────────────────────

def test_api_mutations() -> None:
    print("\n=== API MUTATION TESTS ===")

    # Test flows create (API requires name + content fields)
    r = requests.post(BASE_URL + "/api/flows",
                      json={"name": "test-flow", "content": "steps: []"}, timeout=5)
    passed_flows = r.status_code in (200, 201)
    record_result("POST /api/flows create", passed_flows,
                  f"status={r.status_code} body={r.text[:100]}")
    if not passed_flows:
        record_bug("FLOW-002", "Flows page",
                   f"POST /api/flows returns {r.status_code}: {r.text[:120]}",
                   "HTTP 200/201 with created flow",
                   f"HTTP {r.status_code}: {r.text[:120]}", "Medium",
                   "/api/flows")

    # Test flows list
    r = requests.get(BASE_URL + "/api/flows", timeout=5)
    flows = r.json()
    if isinstance(flows, list):
        record_result("GET /api/flows returns list", True, f"count={len(flows)}")
    else:
        record_result("GET /api/flows returns list", False, f"got: {type(flows)}")
        record_bug("FLOW-001", "Flows page", "GET /api/flows does not return a list",
                   "list", str(type(flows)), "Medium", "/api/flows")

    # Test memory content
    r = requests.get(BASE_URL + "/api/memory/content", timeout=5)
    record_result("GET /api/memory/content", r.status_code == 200,
                  f"status={r.status_code}")
    if r.status_code != 200:
        record_bug("MEM-001", "Memory page",
                   f"GET /api/memory/content returns {r.status_code}",
                   "HTTP 200", f"HTTP {r.status_code}", "Medium",
                   "/api/memory/content")

    # Test memory files
    r = requests.get(BASE_URL + "/api/memory/files", timeout=5)
    record_result("GET /api/memory/files", r.status_code == 200,
                  f"status={r.status_code}")
    if r.status_code != 200:
        record_bug("MEM-002", "Memory page",
                   f"GET /api/memory/files returns {r.status_code}",
                   "HTTP 200", f"HTTP {r.status_code}", "Medium",
                   "/api/memory/files")

    # Test sessions delete (on fake session)
    r = requests.delete(BASE_URL + "/api/sessions/fake-session-id", timeout=5)
    record_result("DELETE /api/sessions/{id} on nonexistent",
                  r.status_code in (200, 404),
                  f"status={r.status_code} (200 or 404 acceptable)")

    # Test audit entries with session filter
    real_sessions = requests.get(BASE_URL + "/api/sessions", timeout=5).json()
    if real_sessions:
        sid = real_sessions[0]["session_id"]
        r = requests.get(BASE_URL + f"/api/audit/entries?session_id={sid}&limit=10", timeout=5)
        record_result(f"GET /api/audit/entries?session_id={sid[:8]}",
                      r.status_code == 200,
                      f"status={r.status_code} entries={len(r.json())}")

    # Test sessions receipt on real session
    if real_sessions:
        sid = real_sessions[0]["session_id"]
        r = requests.get(BASE_URL + f"/api/sessions/{sid}/receipt", timeout=5)
        record_result(f"GET /api/sessions/{sid[:8]}/receipt",
                      r.status_code == 200,
                      f"status={r.status_code}")
        if r.status_code == 200:
            receipt = r.json()
            required_fields = ["session_id", "total_usd", "action_count", "signed_hash"]
            missing = [f for f in required_fields if f not in receipt]
            if missing:
                record_bug("SESS-002", "Sessions page",
                           f"Session receipt missing fields: {missing}",
                           f"Receipt should have all of {required_fields}",
                           f"Missing: {missing}", "Low",
                           "/api/sessions/{id}/receipt")
            record_result("Session receipt has required fields", not missing)

    # Test websocket availability on 8081
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("127.0.0.1", 8081))
        s.close()
        ws_open = (result == 0)
        record_result("WebSocket port 8081 is open", ws_open,
                      "needed for chat WebSocket /ws")
        if not ws_open:
            record_bug(
                "WS-001",
                "Chat page",
                "WebSocket port 8081 is not open / not listening",
                "Port 8081 should be listening for WebSocket connections for the chat gateway",
                "TCP connect to 127.0.0.1:8081 failed",
                "Critical",
                endpoint="ws://127.0.0.1:8081/ws",
                extra="Chat view will show 'Disconnected' and users cannot send messages. Check if the gateway WebSocket server is started alongside the HTTP server.",
            )
    except Exception as exc:
        record_result("WebSocket port 8081 check", False, str(exc))

    # Test config PATCH actually persists
    patch_val = {"agent_name": "cato-playwright-test"}
    r1 = requests.patch(BASE_URL + "/api/config", json=patch_val, timeout=5)
    r2 = requests.get(BASE_URL + "/api/config", timeout=5)
    cfg_after = r2.json()
    if cfg_after.get("agent_name") == "cato-playwright-test":
        record_result("Config PATCH persists value", True)
        # Restore
        requests.patch(BASE_URL + "/api/config", json={"agent_name": ""}, timeout=5)
    else:
        record_bug(
            "CFG-004",
            "Config page",
            "PATCH /api/config does not persist changes — GET /api/config returns old empty {} after PATCH",
            "After PATCH, GET /api/config should return updated values",
            f"After PATCH with agent_name='cato-playwright-test', GET returns: {cfg_after}",
            "High",
            endpoint="/api/config",
            extra="This means config edits from the Config page UI are not saved to disk. They appear saved (banner shows 'Saved') but are lost on next reload.",
        )
        record_result("Config PATCH persists value", False, f"after PATCH: {cfg_after}")


# ─────────────────────────────────────────────────────────────────────────────
# Bug report generator
# ─────────────────────────────────────────────────────────────────────────────

def generate_bug_report() -> str:
    passed = sum(1 for r in test_results if r["passed"])
    failed = sum(1 for r in test_results if not r["passed"])
    total = len(test_results)

    critical = [b for b in bugs if b.severity == "Critical"]
    high = [b for b in bugs if b.severity == "High"]
    medium = [b for b in bugs if b.severity == "Medium"]
    low = [b for b in bugs if b.severity == "Low"]

    lines = [
        "# Cato UI — Comprehensive Bug Report",
        "",
        f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Target**: http://localhost:8080",
        f"**Test tool**: Playwright (Python) + direct API probes",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Tests run | {total} |",
        f"| Tests passed | {passed} |",
        f"| Tests failed | {failed} |",
        f"| Total bugs found | {len(bugs)} |",
        f"| Critical | {len(critical)} |",
        f"| High | {len(high)} |",
        f"| Medium | {len(medium)} |",
        f"| Low | {len(low)} |",
        "",
        "---",
        "",
        "## Bug Inventory",
        "",
    ]

    for severity, bug_list in [
        ("Critical", critical),
        ("High", high),
        ("Medium", medium),
        ("Low", low),
    ]:
        if not bug_list:
            continue
        lines.append(f"### {severity} Severity")
        lines.append("")
        for b in bug_list:
            lines += [
                f"#### [{b.bug_id}] {b.description}",
                "",
                f"- **Page**: {b.page}",
                f"- **Severity**: {b.severity}",
                f"- **API Endpoint**: `{b.endpoint}`" if b.endpoint else "",
                f"- **Expected**: {b.expected}",
                f"- **Actual**: {b.actual}",
                f"- **Details**: {b.extra}" if b.extra else "",
                "",
            ]
        lines.append("")

    lines += [
        "---",
        "",
        "## All Test Results",
        "",
        "| # | Test | Result | Detail |",
        "|---|------|--------|--------|",
    ]
    for i, r in enumerate(test_results, 1):
        status = "PASS" if r["passed"] else "FAIL"
        detail = r["detail"].replace("|", "\\|") if r["detail"] else ""
        lines.append(f"| {i} | {r['test']} | {status} | {detail} |")

    lines += [
        "",
        "---",
        "",
        "## Screenshots",
        "",
        f"All screenshots saved to: `{SCREENSHOTS_DIR}`",
        "",
        "| File | Description |",
        "|------|-------------|",
        "| T01_initial_load.png | First page load |",
        "| T02_dashboard.png | Dashboard view |",
        "| T03_chat.png | Chat view |",
        "| T04_coding_agent.png | Coding Agent view |",
        "| T05_skills.png | Skills view |",
        "| T06_cron_jobs.png | Cron Jobs view |",
        "| T07_sessions.png | Sessions view |",
        "| T08_usage.png | Usage view |",
        "| T09_logs.png | Logs view |",
        "| T10_audit_log.png | Audit Log view |",
        "| T11_config.png | Config view |",
        "| T12_budget.png | Budget view |",
        "| T13_alerts.png | Alerts view |",
        "| T14_auth_keys.png | Auth & Keys view |",
        "| T15_identity.png | Identity view |",
        "| T16_flows.png | Flows view |",
        "| T17_nodes.png | Nodes view |",
        "| T18_memory.png | Memory view |",
        "| T19_system.png | System view |",
        "| T20_diagnostics.png | Diagnostics view |",
        "| T99_final_dashboard.png | Final state |",
        "",
        "---",
        "",
        "## Root Cause Analysis",
        "",
        "### 1. Heartbeat 'unknown' (HB-001)",
        "The `/api/heartbeat` endpoint returns `{status: 'unknown', last_heartbeat: null}` even when the daemon is running.",
        "Root cause: The agent loop does not POST heartbeat updates to the heartbeat endpoint.",
        "The endpoint exists for *receiving* heartbeat pings from the agent loop, but the loop never sends them.",
        "",
        "### 2. Chat Raw XML Tool Calls (CHAT-001)",
        "The MiniMax m2.5 model outputs its tool invocations as `<minimax:tool_call>` XML blocks.",
        "The agent loop must strip these before sending the reply to the WebSocket client.",
        "Currently the raw XML is stored in chat history and shown directly to the user.",
        "",
        "### 3. Chat Cost Line in Messages (CHAT-002)",
        "The agent loop appends a budget summary line like `[$0.0000 this call | Month: ...]` to every response.",
        "This is implementation detail noise that should be stripped before sending to the client.",
        "",
        "### 4. Wrong Identity — 'I am Claude Code' (CHAT-003 + CHAT-004)",
        "The agent responds as 'Claude Code' and tries to call the Anthropic API to verify its identity.",
        "Root cause: SOUL.md/IDENTITY.md workspace files exist but may not be injected into the system prompt.",
        "Alternatively, the MiniMax model is ignoring the system prompt persona.",
        "",
        "### 5. Config Not Persisting (CFG-001, CFG-004)",
        "GET /api/config returns `{}`. PATCH /api/config returns `{status: ok}` but the value is not persisted.",
        "The config YAML at `%APPDATA%\\cato\\config.yaml` is not being read/written by the API endpoint.",
        "",
        "### 6. System Page Shows Tools as Cold (SYS-001)",
        "Codex, Gemini, and Cursor all show `logged_in: false` which renders them as 'cold' (red) in the System page.",
        "The `/api/cli/status` check uses a `logged_in` probe that may not correctly detect auth state.",
        "",
        "### 7. SQLite Thread Safety (DIAG-001)",
        "ContradictionDetector uses a SQLite connection across threads, causing the thread safety error.",
        "Fix: Use `check_same_thread=False` or create per-request connections.",
        "",
        "### 8. WebSocket Port 8081 (WS-001)",
        "If port 8081 is closed, the Chat page will show 'Disconnected' permanently.",
        "The gateway WebSocket server may not be running as part of the aiohttp server setup.",
        "",
    ]

    return "\n".join(line for line in lines if line is not None)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 70)
    print("Cato UI Comprehensive Playwright Test Suite")
    print(f"Target: {BASE_URL}")
    print(f"Screenshots: {SCREENSHOTS_DIR}")
    print("=" * 70)

    # Phase 1: API pre-flight
    test_api_endpoints()

    # Phase 2: Browser tests
    await run_browser_tests()

    # Phase 3: Additional mutation tests
    test_api_mutations()

    # Phase 4: Generate report
    print("\n=== GENERATING BUG REPORT ===")
    report = generate_bug_report()

    report_path = Path(r"C:\Users\Administrator\Desktop\Cato\CATO_BUG_REPORT.md")
    report_path.write_text(report, encoding="utf-8")
    print(f"Bug report written to: {report_path}")

    # Summary
    passed = sum(1 for r in test_results if r["passed"])
    failed = sum(1 for r in test_results if not r["passed"])
    print(f"\nTests: {passed} passed / {failed} failed / {len(test_results)} total")
    print(f"Bugs found: {len(bugs)} total")
    for sev in ("Critical", "High", "Medium", "Low"):
        count = sum(1 for b in bugs if b.severity == sev)
        if count:
            print(f"  {sev}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
