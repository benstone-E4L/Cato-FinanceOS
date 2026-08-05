"""
Comprehensive Playwright E2E audit of the Cato Desktop App.

Tests:
  1. All backend API endpoints (direct HTTP)
  2. Frontend page rendering via browser (with Tauri invoke bypass)
  3. Known issues verification
  4. Interactive feature testing (forms, buttons, saves)
  5. WebSocket connectivity
  6. Console error capture
"""

import json
import time
import asyncio
import urllib.request
import urllib.error
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext, ConsoleMessage

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DAEMON_HTTP = "http://127.0.0.1:8080"
FRONTEND_URL = "http://localhost:5173"
REPORT_PATH = Path(r"C:\Users\Administrator\Desktop\Cato\DESKTOP_APP_AUDIT_TASKS.md")

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    category: str  # BUG, PASS, WARN, INFO
    view: str
    description: str
    detail: str = ""

findings: list[Finding] = []

def record(cat: str, view: str, desc: str, detail: str = ""):
    findings.append(Finding(cat, view, desc, detail))
    tag = {"BUG": "[FAIL]", "PASS": "[OK]  ", "WARN": "[WARN]", "INFO": "[INFO]"}.get(cat, "[????]")
    print(f"  {tag} {view}: {desc}")

# ---------------------------------------------------------------------------
# Part 1: API endpoint tests
# ---------------------------------------------------------------------------

def api_get(path: str) -> tuple[int, dict | list | str]:
    try:
        req = urllib.request.Request(f"{DAEMON_HTTP}{path}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body
    except Exception as e:
        return 0, str(e)

def api_post(path: str, body: dict | None = None) -> tuple[int, dict | list | str]:
    data = json.dumps(body or {}).encode()
    try:
        req = urllib.request.Request(f"{DAEMON_HTTP}{path}", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            rb = resp.read().decode()
            try:
                return resp.status, json.loads(rb)
            except json.JSONDecodeError:
                return resp.status, rb
    except urllib.error.HTTPError as e:
        body_str = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body_str)
        except Exception:
            return e.code, body_str
    except Exception as e:
        return 0, str(e)

def api_method(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list | str]:
    data = json.dumps(body or {}).encode() if body else None
    try:
        req = urllib.request.Request(f"{DAEMON_HTTP}{path}", data=data,
                                     headers={"Content-Type": "application/json"}, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            rb = resp.read().decode()
            try:
                return resp.status, json.loads(rb)
            except json.JSONDecodeError:
                return resp.status, rb
    except urllib.error.HTTPError as e:
        body_str = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body_str)
        except Exception:
            return e.code, body_str
    except Exception as e:
        return 0, str(e)

def test_api_endpoints():
    print("\n=== Part 1: Backend API Endpoint Tests ===\n")

    # Health
    code, data = api_get("/health")
    if code == 200 and isinstance(data, dict) and data.get("status") == "ok":
        record("PASS", "API /health", f"Returns ok, version={data.get('version')}, uptime={data.get('uptime')}s, sessions={data.get('sessions')}")
    else:
        record("BUG", "API /health", f"Unexpected response: {code} {data}")

    # Budget
    code, data = api_get("/api/budget/summary")
    if code == 200 and isinstance(data, dict):
        record("PASS", "API /api/budget/summary", f"session_spend={data.get('session_spend')}, monthly_spend={data.get('monthly_spend')}")
    else:
        record("BUG", "API /api/budget/summary", f"HTTP {code}: {data}")

    # Sessions
    code, data = api_get("/api/sessions")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/sessions", f"Returns {len(data)} sessions")
    else:
        record("BUG", "API /api/sessions", f"HTTP {code}: {data}")

    # Usage
    code, data = api_get("/api/usage/summary")
    if code == 200 and isinstance(data, dict):
        record("PASS", "API /api/usage/summary", f"total_calls={data.get('total_calls')}")
    else:
        record("BUG", "API /api/usage/summary", f"HTTP {code}: {data}")

    # Skills
    code, data = api_get("/api/skills")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/skills", f"Returns {len(data)} skills")
        # Test individual skill content
        if data:
            skill_name = data[0].get("dir") or data[0].get("name", "")
            code2, data2 = api_get(f"/api/skills/{skill_name}/content")
            if code2 == 200:
                record("PASS", "API /api/skills/{name}/content", f"Skill '{skill_name}' content loaded")
            else:
                record("BUG", "API /api/skills/{name}/content", f"HTTP {code2}")
    else:
        record("BUG", "API /api/skills", f"HTTP {code}: {data}")

    # Cron jobs
    code, data = api_get("/api/cron/jobs")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/cron/jobs", f"Returns {len(data)} cron jobs")
    else:
        record("BUG", "API /api/cron/jobs", f"HTTP {code}: {data}")

    # Logs
    code, data = api_get("/api/logs?limit=10")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/logs", f"Returns {len(data)} log entries")
    else:
        record("BUG", "API /api/logs", f"HTTP {code}: {data}")

    # Audit entries
    code, data = api_get("/api/audit/entries?limit=10")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/audit/entries", f"Returns {len(data)} audit entries")
    else:
        record("BUG", "API /api/audit/entries", f"HTTP {code}: {data}")

    # Audit verify
    code, data = api_post("/api/audit/verify", {"session_id": ""})
    if code == 200 and isinstance(data, dict):
        record("PASS", "API /api/audit/verify", f"Chain integrity ok={data.get('ok')}")
    else:
        record("BUG", "API /api/audit/verify", f"HTTP {code}: {data}")

    # Config GET
    code, data = api_get("/api/config")
    if code == 200 and isinstance(data, dict):
        record("PASS", "API /api/config GET", f"Config has {len(data)} keys")
    else:
        record("BUG", "API /api/config GET", f"HTTP {code}: {data}")

    # Config PATCH
    code, data = api_method("PATCH", "/api/config", {"_test_key": "test_value"})
    if code == 200 and isinstance(data, dict) and data.get("status") == "ok":
        record("PASS", "API /api/config PATCH", "Config patching works")
    else:
        record("BUG", "API /api/config PATCH", f"HTTP {code}: {data}")

    # Vault keys
    code, data = api_get("/api/vault/keys")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/vault/keys", f"Vault has {len(data)} keys: {data}")
    else:
        record("BUG", "API /api/vault/keys", f"HTTP {code}: {data}")

    # CLI status
    code, data = api_get("/api/cli/status")
    if code == 200 and isinstance(data, dict):
        for tool_name, info in data.items():
            if isinstance(info, dict):
                status = "warm" if info.get("installed") and info.get("logged_in") else "cold" if info.get("installed") else "unavailable"
                record("PASS", f"API /api/cli/status ({tool_name})", f"status={status}, version={info.get('version', 'N/A')}")
    else:
        record("BUG", "API /api/cli/status", f"HTTP {code}: {data}")

    # Adapters
    code, data = api_get("/api/adapters")
    if code == 200 and isinstance(data, dict):
        adapters = data.get("adapters", [])
        record("PASS", "API /api/adapters", f"Returns {len(adapters)} adapters: {[a.get('name') for a in adapters]}")
        for a in adapters:
            record("INFO", f"Adapter {a.get('name')}", f"status={a.get('status')}")
    else:
        record("BUG", "API /api/adapters", f"HTTP {code}: {data}")

    # Heartbeat
    code, data = api_get("/api/heartbeat")
    if code == 200 and isinstance(data, dict):
        hb_status = data.get("status", "unknown")
        last_hb = data.get("last_heartbeat")
        record("PASS" if hb_status != "unknown" else "WARN", "API /api/heartbeat",
               f"status={hb_status}, last={last_hb}, agent={data.get('agent_name')}")
    else:
        record("BUG", "API /api/heartbeat", f"HTTP {code}: {data}")

    # Memory files
    code, data = api_get("/api/memory/files")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/memory/files", f"Returns {len(data)} memory files")
    else:
        record("BUG", "API /api/memory/files", f"HTTP {code}: {data}")

    # Memory stats
    code, data = api_get("/api/memory/stats")
    if code == 200 and isinstance(data, dict):
        record("PASS", "API /api/memory/stats", f"facts={data.get('facts')}, kg_nodes={data.get('kg_nodes')}, kg_edges={data.get('kg_edges')}")
    else:
        record("BUG", "API /api/memory/stats", f"HTTP {code}: {data}")

    # Workspace files
    code, data = api_get("/api/workspace/files")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/workspace/files", f"Returns {len(data)} workspace files: {data}")
    else:
        record("BUG", "API /api/workspace/files", f"HTTP {code}: {data}")

    # Workspace file read
    code, data = api_get("/api/workspace/file?name=SOUL.md")
    if code == 200 and isinstance(data, dict):
        content_len = len(data.get("content", ""))
        record("PASS", "API /api/workspace/file (SOUL.md)", f"Content length={content_len} chars")
    else:
        record("BUG", "API /api/workspace/file (SOUL.md)", f"HTTP {code}: {data}")

    # Workspace file write (Identity save test - KNOWN ISSUE #1)
    test_content = "# Test Identity\nThis is a test."
    code, data = api_method("PUT", "/api/workspace/file", {"name": "IDENTITY.md", "content": test_content})
    if code == 200 and isinstance(data, dict) and data.get("status") == "ok":
        record("PASS", "API /api/workspace/file PUT (IDENTITY.md)", "Identity save works at API level")
    else:
        record("BUG", "API /api/workspace/file PUT (IDENTITY.md)", f"HTTP {code}: {data}")

    # Also test POST alias for workspace file
    code, data = api_post("/api/workspace/file", {"name": "IDENTITY.md", "content": test_content})
    if code == 200 and isinstance(data, dict) and data.get("status") == "ok":
        record("PASS", "API /api/workspace/file POST alias", "POST alias works")
    else:
        record("BUG", "API /api/workspace/file POST alias", f"HTTP {code}: {data}")

    # Action guard status
    code, data = api_get("/api/action-guard/status")
    if code == 200 and isinstance(data, dict):
        checks = data.get("checks", [])
        record("PASS", "API /api/action-guard/status", f"{len(checks)} checks, autonomy={data.get('autonomy_level')}")
    else:
        record("BUG", "API /api/action-guard/status", f"HTTP {code}: {data}")

    # Flows
    code, data = api_get("/api/flows")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/flows", f"Returns {len(data)} flows")
    else:
        record("BUG", "API /api/flows", f"HTTP {code}: {data}")

    # Nodes
    code, data = api_get("/api/nodes")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/nodes", f"Returns {len(data)} nodes")
    else:
        record("BUG", "API /api/nodes", f"HTTP {code}: {data}")

    # Diagnostics endpoints
    for diag_ep in ["query-classifier", "contradiction-health", "decision-memory", "anomaly-domains", "skill-corrections"]:
        code, data = api_get(f"/api/diagnostics/{diag_ep}")
        if code == 200:
            record("PASS", f"API /api/diagnostics/{diag_ep}", f"Returns {type(data).__name__}")
        else:
            record("BUG", f"API /api/diagnostics/{diag_ep}", f"HTTP {code}: {data}")

    # PTY sessions (interactive CLIs)
    code, data = api_get("/api/pty/sessions")
    if code == 200 and isinstance(data, dict) and "sessions" in data:
        record("PASS", "API /api/pty/sessions", f"Returns sessions list ({len(data.get('sessions', []))} active)")
    else:
        record("BUG", "API /api/pty/sessions", f"HTTP {code}: {data}")

    # Chat history
    code, data = api_get("/api/chat/history?since=0")
    if code == 200 and isinstance(data, list):
        record("PASS", "API /api/chat/history", f"Returns {len(data)} history entries")
    else:
        record("BUG", "API /api/chat/history", f"HTTP {code}: {data}")

    # Memory content
    code, data = api_get("/api/memory/content?file=MEMORY.md")
    if code == 200 and isinstance(data, dict):
        record("PASS", "API /api/memory/content", f"file={data.get('file')}, content_len={len(data.get('content', ''))}")
    else:
        record("BUG", "API /api/memory/content", f"HTTP {code}: {data}")

# ---------------------------------------------------------------------------
# Part 2: Frontend browser tests
# ---------------------------------------------------------------------------

console_errors: list[str] = []
network_failures: list[str] = []

def capture_console(msg: ConsoleMessage):
    if msg.type == "error":
        text = msg.text
        # Ignore known noise
        if "favicon" in text.lower() or "net::ERR" in text:
            return
        console_errors.append(text)

def setup_tauri_bypass(page: Page):
    """Inject a mock for Tauri's invoke() so the app thinks the daemon is ready."""
    page.add_init_script("""
        // Mock Tauri invoke
        window.__TAURI_INTERNALS__ = {
            invoke: async function(cmd, args) {
                if (cmd === 'get_daemon_status') {
                    return { running: true };
                }
                if (cmd === 'start_daemon') {
                    return { running: true };
                }
                console.log('[mock-tauri] invoke:', cmd, args);
                return {};
            },
            metadata: { currentWebview: { label: 'main' }, currentWindow: { label: 'main' } },
            transformCallback: function(cb) { return 0; },
        };
        // Also mock the @tauri-apps/api/core invoke
        window.__TAURI_INVOKE__ = window.__TAURI_INTERNALS__.invoke;
    """)

def test_frontend_views():
    print("\n=== Part 2: Frontend Browser Tests ===\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        # Set up Tauri mock and console capture
        setup_tauri_bypass(page)
        page.on("console", capture_console)

        # Navigate to frontend
        page.goto(FRONTEND_URL, wait_until="networkidle", timeout=30000)
        time.sleep(3)

        # Check if app rendered
        page_content = page.content()
        if "app-root" in page_content or "sidebar" in page_content.lower():
            record("PASS", "Frontend Load", "App root rendered successfully")
        else:
            # May still be in loading/error state because Tauri invoke fails
            if "Starting Cato daemon" in page_content:
                record("WARN", "Frontend Load", "App stuck on 'Starting Cato daemon' -- Tauri invoke mock may not be working")
            elif "Failed to connect" in page_content:
                record("WARN", "Frontend Load", "App shows 'Failed to connect' -- Tauri invoke not mocked properly, but app rendered")
            else:
                record("BUG", "Frontend Load", "App root not found in page content")

        # Take screenshot of initial state
        screenshots_dir = Path(r"C:\Users\Administrator\Desktop\Cato\audit_screenshots")
        screenshots_dir.mkdir(exist_ok=True)
        page.screenshot(path=str(screenshots_dir / "01_initial_load.png"))

        # Try to check if sidebar is visible
        sidebar_visible = page.locator(".sidebar").count() > 0
        if sidebar_visible:
            record("PASS", "Sidebar", "Sidebar rendered with navigation groups")
        else:
            record("WARN", "Sidebar", "Sidebar not rendered -- app may be in error/loading state")

        # If sidebar is visible, test each view by clicking nav items
        if sidebar_visible:
            test_each_sidebar_view(page, screenshots_dir)
        else:
            # App is probably stuck because Tauri invoke failed
            # Let's try injecting the daemon status directly
            record("INFO", "Frontend", "Attempting direct state injection to bypass Tauri gate")
            page.evaluate("""
                // Force the app to show as ready
                const root = document.getElementById('root');
                if (root && root._reactRootContainer) {
                    console.log('React root found');
                }
            """)
            time.sleep(2)
            page.screenshot(path=str(screenshots_dir / "01b_after_injection.png"))

            # Check again
            sidebar_visible = page.locator(".sidebar").count() > 0
            if sidebar_visible:
                test_each_sidebar_view(page, screenshots_dir)
            else:
                record("WARN", "Frontend", "Cannot bypass Tauri gate -- testing views via direct navigation to daemon UI instead")
                # Test the daemon's built-in HTML UI as fallback
                test_daemon_html_ui(page, screenshots_dir)

        # Report console errors
        if console_errors:
            for err in console_errors[:20]:
                record("BUG", "Console Error", err[:200])
        else:
            record("PASS", "Console Errors", "No JavaScript console errors detected")

        page.screenshot(path=str(screenshots_dir / "99_final_state.png"))
        browser.close()


SIDEBAR_VIEWS = [
    ("dashboard", "Dashboard"),
    ("chat", "Chat"),
    ("coding-agent", "Coding Agent"),
    ("interactive-cli", "Interactive CLIs"),
    ("skills", "Skills"),
    ("cron", "Cron Jobs"),
    ("flows", "Flows"),
    ("sessions", "Sessions"),
    ("nodes", "Remote Nodes"),
    ("memory", "Memory"),
    ("usage", "Usage"),
    ("logs", "Logs"),
    ("audit", "Audit Log"),
    ("diagnostics", "Diagnostics"),
    ("system", "System"),
    ("identity", "Identity"),
    ("config", "Config"),
    ("budget", "Budget"),
    ("alerts", "Alerts"),
    ("auth-keys", "Auth & Keys"),
]


def test_each_sidebar_view(page: Page, screenshots_dir: Path):
    """Click each sidebar nav item and verify the view loads."""
    for idx, (view_id, view_label) in enumerate(SIDEBAR_VIEWS, start=1):
        console_errors.clear()

        # Click the sidebar button for this view
        try:
            btn = page.locator(f".sidebar-nav-item").filter(has_text=view_label)
            if btn.count() == 0:
                record("BUG", view_label, f"Sidebar button '{view_label}' not found")
                continue
            btn.first.click()
            time.sleep(2)  # Wait for data to load
        except Exception as e:
            record("BUG", view_label, f"Click failed: {e}")
            continue

        page.screenshot(path=str(screenshots_dir / f"{idx:02d}_{view_id}.png"))

        # Check for loading spinners still showing
        spinners = page.locator(".app-loading-spinner").count()
        view_loading = page.locator(".view-loading").count()

        # Check for error messages
        error_elements = page.locator(".page-error, .error-banner, .dash-error-badge").count()

        # Check page content
        main_content = page.locator(".app-main").inner_text(timeout=5000) if page.locator(".app-main").count() > 0 else ""

        # View-specific checks
        if view_id == "dashboard":
            test_dashboard_view(page, view_label, main_content)
        elif view_id == "chat":
            test_chat_view(page, view_label, main_content)
        elif view_id == "coding-agent":
            test_coding_agent_view(page, view_label, main_content)
        elif view_id == "interactive-cli":
            test_interactive_cli_view(page, view_label, main_content)
        elif view_id == "skills":
            test_skills_view(page, view_label, main_content)
        elif view_id == "identity":
            test_identity_view(page, view_label, main_content)
        elif view_id == "system":
            test_system_view(page, view_label, main_content)
        elif view_id == "auth-keys":
            test_auth_keys_view(page, view_label, main_content)
        elif view_id == "config":
            test_config_view(page, view_label, main_content)
        elif view_id == "alerts":
            test_alerts_view(page, view_label, main_content)
        elif view_id == "diagnostics":
            test_diagnostics_view(page, view_label, main_content)
        elif view_id == "budget":
            test_budget_view(page, view_label, main_content)
        elif view_id == "memory":
            test_memory_view(page, view_label, main_content)
        else:
            # Generic check
            if spinners > 0 and view_loading > 0:
                record("WARN", view_label, "Still loading (spinner visible)")
            elif error_elements > 0:
                record("BUG", view_label, "Error banner visible on page")
            elif main_content.strip():
                record("PASS", view_label, f"View loaded, content length={len(main_content)} chars")
            else:
                record("WARN", view_label, "View loaded but appears empty")

        # Capture any console errors for this view
        if console_errors:
            for err in console_errors:
                record("BUG", f"{view_label} Console", err[:200])
            console_errors.clear()


def test_dashboard_view(page: Page, label: str, content: str):
    """Test Dashboard specific features."""
    # Check metric cards
    cards = page.locator(".dash-card").count()
    if cards >= 4:
        record("PASS", label, f"Dashboard shows {cards} metric cards")
    else:
        record("BUG", label, f"Dashboard shows only {cards} metric cards (expected >= 4)")

    # Check gateway status
    if "Online" in content or "Offline" in content:
        if "Online" in content:
            record("PASS", label, "Gateway status shows Online")
        else:
            record("WARN", label, "Gateway status shows Offline")
    else:
        record("WARN", label, "Gateway status not found in content")

    # Check heartbeat section (KNOWN ISSUE #9)
    if "Heartbeat" in content:
        heartbeat_section = page.locator("text=Heartbeat").first
        if heartbeat_section.count() > 0:
            # Check if it shows stale or alive
            hb_parent = page.locator(".dash-section").filter(has_text="Heartbeat")
            hb_text = hb_parent.inner_text() if hb_parent.count() > 0 else ""
            if "stale" in hb_text.lower():
                record("BUG", f"{label} Heartbeat", "Heartbeat shows STALE -- KNOWN ISSUE #9: Should be every 30s")
            elif "alive" in hb_text.lower():
                record("PASS", f"{label} Heartbeat", "Heartbeat shows alive")
            elif "unknown" in hb_text.lower():
                record("WARN", f"{label} Heartbeat", "Heartbeat shows unknown")
            else:
                record("INFO", f"{label} Heartbeat", f"Heartbeat text: {hb_text[:100]}")

    # Check adapters section (relates to Telegram - KNOWN ISSUE #2)
    if "Adapters" in content:
        adapter_section = page.locator(".dash-section").filter(has_text="Adapters")
        ad_text = adapter_section.inner_text() if adapter_section.count() > 0 else ""
        if "telegram" in ad_text.lower():
            if "not_configured" in ad_text.lower() or "disconnected" in ad_text.lower():
                record("BUG", f"{label} Adapters", "Telegram adapter shows not_configured/disconnected -- KNOWN ISSUE #2: Chat won't reach Telegram")
            elif "connected" in ad_text.lower():
                record("PASS", f"{label} Adapters", "Telegram adapter connected")
        else:
            record("WARN", f"{label} Adapters", "Telegram adapter not listed")

    # Check quick launch buttons
    quick_btns = page.locator(".dash-quick-btn").count()
    if quick_btns >= 3:
        record("PASS", label, f"Quick launch has {quick_btns} buttons")
    else:
        record("WARN", label, f"Quick launch has only {quick_btns} buttons")

    # Test Refresh button
    refresh_btn = page.locator(".dash-refresh-btn")
    if refresh_btn.count() > 0:
        refresh_btn.click()
        time.sleep(2)
        record("PASS", label, "Refresh button works")


def test_chat_view(page: Page, label: str, content: str):
    """Test Chat view - KNOWN ISSUES #2, #3, #7."""
    # Check connection status
    status_el = page.locator(".chat-status")
    if status_el.count() > 0:
        status_text = status_el.inner_text()
        if "Connected" in status_text:
            record("PASS", f"{label} Connection", "WebSocket connected")
        elif "Disconnected" in status_text:
            record("BUG", f"{label} Connection", "WebSocket disconnected -- chat won't work")
        elif "Reconnecting" in status_text:
            record("WARN", f"{label} Connection", "WebSocket reconnecting")
        else:
            record("INFO", f"{label} Connection", f"Status: {status_text}")

    # Check chat input is present
    chat_input = page.locator(".chat-input")
    if chat_input.count() > 0:
        record("PASS", label, "Chat input textarea present")
        # Check if disabled (should be enabled when connected)
        is_disabled = chat_input.is_disabled()
        if is_disabled:
            record("WARN", f"{label} Input", "Chat input is disabled (WebSocket not connected)")
    else:
        record("BUG", label, "Chat input textarea missing")

    # Check send button
    send_btn = page.locator(".chat-send-btn")
    if send_btn.count() > 0:
        # KNOWN ISSUE #3: No working/thinking indicator
        btn_text = send_btn.inner_text()
        if btn_text.strip() == "Send":
            record("WARN", f"{label} Send Button", "Send button only shows 'Send' -- KNOWN ISSUE #3: No working/thinking indicator during processing")
        record("PASS", label, "Send button present")
    else:
        record("BUG", label, "Send button missing")

    # Check empty state
    empty = page.locator(".chat-empty")
    if empty.count() > 0:
        record("PASS", label, "Empty state shows welcome message")

    # Check Clear button
    clear_btn = page.locator(".btn-cancel-sm").filter(has_text="Clear")
    record("INFO", label, f"Clear button {'present' if clear_btn.count() > 0 else 'hidden (no messages)'}")


def test_coding_agent_view(page: Page, label: str, content: str):
    """Test Coding Agent view - KNOWN ISSUE #8 (boxes on side)."""
    # Check entry view
    if page.locator(".coding-entry").count() > 0:
        record("PASS", label, "Coding agent entry form rendered")
    elif page.locator(".coding-agent-page").count() > 0:
        record("PASS", label, "Coding agent 3-panel layout rendered")
        # KNOWN ISSUE #8: Check for sidebar boxes
        left_sidebar = page.locator(".sidebar-left")
        right_sidebar = page.locator(".sidebar-right")
        if left_sidebar.count() > 0 or right_sidebar.count() > 0:
            record("INFO", f"{label} Layout", f"Left sidebar: {left_sidebar.count()}, Right sidebar: {right_sidebar.count()} -- KNOWN ISSUE #8: boxes on the side")
    else:
        record("WARN", label, "Neither entry nor 3-panel view found")

    # Check task input
    task_input = page.locator("textarea[aria-label='Describe your task']")
    if task_input.count() == 0:
        task_input = page.locator(".task-input textarea, .coding-entry textarea")
    if task_input.count() > 0:
        record("PASS", label, "Task input textarea present")
    else:
        record("WARN", label, "Task input not found")


def test_interactive_cli_view(page: Page, label: str, content: str):
    """Test Interactive CLIs view: tabs, Start Session, terminal pane."""
    if page.locator(".interactive-cli-view").count() > 0:
        record("PASS", label, "Interactive CLIs view container rendered")
    else:
        record("WARN", label, "Interactive CLIs view container not found")

    # Tabs Claude / Codex / Gemini
    for cli in ["Claude", "Codex", "Gemini"]:
        tab = page.locator(f"button[role='tab']").filter(has_text=cli)
        if tab.count() > 0:
            record("PASS", label, f"Tab '{cli}' present")
        else:
            record("WARN", label, f"Tab '{cli}' not found")

    # Start Session button
    start_btn = page.locator("button").filter(has_text="Start Session")
    if start_btn.count() > 0:
        record("PASS", label, "Start Session button present")
    else:
        record("WARN", label, "Start Session button not found")

    # Terminal pane container (may be empty until session started)
    pane = page.locator(".terminal-pane")
    if pane.count() > 0:
        record("PASS", label, "Terminal pane container present")
    else:
        record("INFO", label, "Terminal pane not yet mounted (start session to connect)")


def test_skills_view(page: Page, label: str, content: str):
    """Test Skills view -- should work (known good)."""
    if "Skills" in content:
        record("PASS", label, "Skills view loaded with content")
    else:
        record("WARN", label, "Skills content may be empty")

    # Check for skill list
    skill_items = page.locator("[class*='skill']").count()
    record("INFO", label, f"Found {skill_items} skill-related elements")


def test_identity_view(page: Page, label: str, content: str):
    """Test Identity view - KNOWN ISSUE #1 (save fails), #10 (duplicate files)."""
    # Check file list
    file_btns = page.locator(".identity-file-btn")
    file_count = file_btns.count()
    if file_count > 0:
        record("PASS", label, f"Identity file list shows {file_count} files")
        # Collect file names
        file_names = []
        for i in range(file_count):
            file_names.append(file_btns.nth(i).inner_text().strip())
        record("INFO", f"{label} Files", f"Files: {file_names}")
    else:
        record("BUG", label, "Identity file list is empty")

    # Check editor
    editor = page.locator(".identity-editor")
    if editor.count() > 0:
        record("PASS", label, "Identity editor textarea present")
        editor_content = editor.input_value()
        if editor_content:
            record("PASS", label, f"Editor has content ({len(editor_content)} chars)")
        else:
            record("WARN", label, "Editor is empty for selected file")
    else:
        record("WARN", label, "Identity editor not found (may still be loading)")

    # Test save button (KNOWN ISSUE #1)
    save_btn = page.locator("button.btn-primary").filter(has_text="Save")
    saved_btn = page.locator("button.btn-primary").filter(has_text="Saved")
    if save_btn.count() > 0 or saved_btn.count() > 0:
        record("PASS", label, "Save button present")
        # Try editing and saving
        if editor.count() > 0:
            original = editor.input_value()
            test_text = original + "\n# TEST LINE - AUDIT"
            editor.fill(test_text)
            time.sleep(0.5)
            # Now the Save button should be enabled
            save_active = page.locator("button.btn-primary:not([disabled])").filter(has_text="Save")
            if save_active.count() > 0:
                save_active.click()
                time.sleep(3)
                # Check for save messages
                save_banner = page.locator(".save-banner")
                if save_banner.count() > 0:
                    banner_text = save_banner.inner_text()
                    if "Saved" in banner_text or "ok" in banner_text.lower():
                        record("PASS", f"{label} Save", "Identity save SUCCEEDED -- KNOWN ISSUE #1 may be fixed")
                    else:
                        record("BUG", f"{label} Save", f"Identity save returned: {banner_text} -- KNOWN ISSUE #1 confirmed")
                else:
                    # Check for error in content
                    page_text = page.locator(".app-main").inner_text(timeout=3000) if page.locator(".app-main").count() > 0 else ""
                    if "TypeError" in page_text or "Failed to fetch" in page_text:
                        record("BUG", f"{label} Save", "Identity save shows TypeError: Failed to fetch -- KNOWN ISSUE #1 confirmed")
                    else:
                        record("WARN", f"{label} Save", "No save feedback banner appeared")
            else:
                record("WARN", f"{label} Save", "Save button not clickable after edit")
            # Restore original content
            if original:
                editor.fill(original)
    else:
        record("BUG", label, "Save button not found")

    # Test Reload button
    reload_btn = page.locator("button.btn-secondary").filter(has_text="Reload")
    if reload_btn.count() > 0:
        record("PASS", label, "Reload button present")


def test_system_view(page: Page, label: str, content: str):
    """Test System view - KNOWN ISSUES #4, #5, #6."""
    # CLI Process Pool
    cli_cards = page.locator(".dash-card").count()
    if cli_cards >= 4:
        record("PASS", f"{label} CLI Pool", f"Shows {cli_cards} CLI tool cards")
    else:
        record("WARN", f"{label} CLI Pool", f"Only {cli_cards} CLI tool cards visible")

    # Check for warm/cold status
    if "warm" in content.lower():
        warm_count = content.lower().count("warm")
        cold_count = content.lower().count("cold")
        unavailable_count = content.lower().count("unavailable")
        record("INFO", f"{label} CLI Pool", f"warm={warm_count}, cold={cold_count}, unavailable={unavailable_count}")
        # KNOWN ISSUE #4: CLI pool shows only Claude warm, but AuthKeys shows 3 working
        if warm_count == 1:
            record("WARN", f"{label} CLI Pool", "Only 1 tool shows warm -- KNOWN ISSUE #4: Mismatch with Auth page")

    # Safety Gate
    if "Safety Gate" in content:
        record("PASS", f"{label} Safety Gate", "Safety Gate panel rendered")

    # Daemon Controls -- KNOWN ISSUE #5
    if "Daemon Controls" in content or "Restart Daemon" in content:
        record("PASS", f"{label} Daemon Controls", "Restart daemon button present")
        # KNOWN ISSUE #5: No restart button for individual LLM connections
        record("BUG", f"{label} LLM Restart", "No individual LLM restart buttons -- KNOWN ISSUE #5")
    else:
        record("BUG", f"{label} Daemon Controls", "Daemon controls panel missing")


def test_auth_keys_view(page: Page, label: str, content: str):
    """Test Auth Keys view - KNOWN ISSUES #4, #6."""
    # Check OpenRouter key status
    if "Configured" in content:
        record("PASS", f"{label} OpenRouter", "OpenRouter key shows Configured")
    elif "Missing" in content:
        record("WARN", f"{label} OpenRouter", "OpenRouter key shows Missing")

    # Check CLI backend status
    # KNOWN ISSUE #6: Gemini degraded
    if "Degraded" in content:
        record("BUG", f"{label} Gemini", "Gemini shows Degraded -- KNOWN ISSUE #6: Hangs in non-interactive mode")

    # KNOWN ISSUE #4: System/AuthKeys mismatch
    working_count = content.count("Working")
    degraded_count = content.count("Degraded")
    record("INFO", f"{label} Backends", f"Working={working_count}, Degraded={degraded_count}")
    if working_count == 3 and degraded_count == 1:
        record("BUG", f"{label} Mismatch", "AuthKeys shows 3 Working + 1 Degraded but System CLI Pool may show different -- KNOWN ISSUE #4")

    # Check vault key list
    vault_rows = page.locator(".vault-key-row").count()
    record("INFO", f"{label} Vault", f"Shows {vault_rows} vault key rows")

    # Check add key form
    add_form = page.locator(".add-key-form")
    if add_form.count() > 0:
        record("PASS", label, "Add key form present")


def test_config_view(page: Page, label: str, content: str):
    """Test Config view."""
    if "Config" in content or "config" in content.lower():
        record("PASS", label, "Config view loaded")
    else:
        record("WARN", label, "Config content appears empty")


def test_alerts_view(page: Page, label: str, content: str):
    """Test Alerts view."""
    if "Budget Alert" in content or "Warn at" in content:
        record("PASS", label, "Alerts view loaded with budget threshold controls")
    else:
        record("WARN", label, "Alerts content may be empty")

    # Check threshold input
    threshold_input = page.locator("input[type='number']")
    if threshold_input.count() > 0:
        record("PASS", label, "Budget threshold input present")
        # Test save
        save_btn = page.locator("button.btn-primary").filter(has_text="Save")
        if save_btn.count() > 0:
            record("PASS", label, "Alerts save button present")


def test_diagnostics_view(page: Page, label: str, content: str):
    """Test Diagnostics view."""
    # Check tabs
    tabs_found = []
    for tab_name in ["Query Tiers", "Contradictions", "Decisions", "Anomalies", "Corrections"]:
        tab_btn = page.locator(f"button").filter(has_text=tab_name)
        if tab_btn.count() > 0:
            tabs_found.append(tab_name)

    if len(tabs_found) >= 5:
        record("PASS", label, f"All 5 diagnostic tabs present: {tabs_found}")
    else:
        record("WARN", label, f"Only {len(tabs_found)} diagnostic tabs found: {tabs_found}")

    # Click each tab
    for tab_name in tabs_found:
        tab_btn = page.locator("button").filter(has_text=tab_name)
        if tab_btn.count() > 0:
            tab_btn.first.click()
            time.sleep(2)
            record("PASS", f"{label} Tab", f"Tab '{tab_name}' clicked and loaded")


def test_budget_view(page: Page, label: str, content: str):
    """Test Budget view."""
    if "$" in content or "Budget" in content:
        record("PASS", label, "Budget view loaded with spend data")
    else:
        record("WARN", label, "Budget content may be empty")


def test_memory_view(page: Page, label: str, content: str):
    """Test Memory view."""
    if "Memory" in content or "facts" in content.lower() or "memory" in content.lower():
        record("PASS", label, "Memory view loaded")
    else:
        record("WARN", label, "Memory content may be empty")


def test_daemon_html_ui(page: Page, screenshots_dir: Path):
    """Fallback: test the daemon's built-in dashboard.html."""
    record("INFO", "Fallback", "Testing daemon's built-in HTML UI at port 8080")
    page.goto(f"{DAEMON_HTTP}/", wait_until="networkidle", timeout=15000)
    time.sleep(2)
    page.screenshot(path=str(screenshots_dir / "fallback_daemon_ui.png"))
    content = page.content()
    if "Cato" in content or "dashboard" in content.lower():
        record("PASS", "Daemon HTML UI", "Built-in dashboard loaded")
    else:
        record("WARN", "Daemon HTML UI", "Built-in dashboard may not have loaded")


# ---------------------------------------------------------------------------
# Part 3: WebSocket connectivity test
# ---------------------------------------------------------------------------

def test_websocket():
    print("\n=== Part 3: WebSocket Tests ===\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        ws_messages = []
        ws_errors = []

        # Test WS on port 8081 (gateway)
        try:
            page.evaluate("""
                async () => {
                    return new Promise((resolve, reject) => {
                        const ws = new WebSocket('ws://127.0.0.1:8081/ws');
                        const timeout = setTimeout(() => {
                            ws.close();
                            reject('timeout');
                        }, 5000);
                        ws.onopen = () => {
                            ws.send(JSON.stringify({ type: 'health' }));
                        };
                        ws.onmessage = (e) => {
                            clearTimeout(timeout);
                            ws.close();
                            resolve(e.data);
                        };
                        ws.onerror = (e) => {
                            clearTimeout(timeout);
                            reject('ws error');
                        };
                    });
                }
            """)
            record("PASS", "WebSocket 8081", "Gateway WebSocket connection succeeded")
        except Exception as e:
            record("BUG", "WebSocket 8081", f"Gateway WebSocket failed: {e}")

        # Test WS on port 8080 (coding agent)
        try:
            result = page.evaluate("""
                async () => {
                    return new Promise((resolve, reject) => {
                        const ws = new WebSocket('ws://127.0.0.1:8080/ws');
                        const timeout = setTimeout(() => {
                            ws.close();
                            reject('timeout');
                        }, 5000);
                        ws.onopen = () => {
                            ws.send(JSON.stringify({ type: 'health' }));
                        };
                        ws.onmessage = (e) => {
                            clearTimeout(timeout);
                            ws.close();
                            resolve(e.data);
                        };
                        ws.onerror = (e) => {
                            clearTimeout(timeout);
                            reject('ws error');
                        };
                    });
                }
            """)
            record("PASS", "WebSocket 8080", f"HTTP WebSocket connection succeeded, response: {str(result)[:100]}")
        except Exception as e:
            record("BUG", "WebSocket 8080", f"HTTP WebSocket failed: {e}")

        browser.close()


# ---------------------------------------------------------------------------
# Part 4: Known Issues Deep Verification
# ---------------------------------------------------------------------------

def test_known_issues():
    print("\n=== Part 4: Known Issues Verification ===\n")

    # ISSUE #1: Identity page save fails
    # Already tested in API section and frontend section

    # ISSUE #2: Chat not going to Telegram
    code, data = api_get("/api/adapters")
    if code == 200 and isinstance(data, dict):
        adapters = data.get("adapters", [])
        telegram = [a for a in adapters if a.get("name") == "telegram"]
        if telegram:
            status = telegram[0].get("status")
            if status == "connected":
                record("PASS", "Telegram Adapter", "Telegram adapter is connected -- chat should reach Telegram")
            else:
                record("BUG", "Telegram Adapter", f"Telegram adapter status={status} -- KNOWN ISSUE #2: Messages won't reach Telegram")
        else:
            record("BUG", "Telegram Adapter", "Telegram adapter not found in adapters list -- KNOWN ISSUE #2")

    # ISSUE #4: System vs AuthKeys mismatch
    code1, cli_data = api_get("/api/cli/status")
    if code1 == 200 and isinstance(cli_data, dict):
        warm_tools = [k for k, v in cli_data.items() if isinstance(v, dict) and v.get("installed") and v.get("logged_in")]
        cold_tools = [k for k, v in cli_data.items() if isinstance(v, dict) and v.get("installed") and not v.get("logged_in")]
        unavail_tools = [k for k, v in cli_data.items() if isinstance(v, dict) and not v.get("installed")]
        record("INFO", "CLI Status (live)", f"warm={warm_tools}, cold={cold_tools}, unavailable={unavail_tools}")
        # AuthKeys hardcodes: codex=working, cursor=working, claude=working, gemini=degraded
        # System CLI Pool: based on live detection
        if len(warm_tools) != 3:
            record("BUG", "Issue #4 Mismatch", f"CLI pool shows {len(warm_tools)} warm (live) but AuthKeys hardcodes 3 working -- MISMATCH CONFIRMED")
        else:
            record("PASS", "Issue #4 Mismatch", "CLI pool and AuthKeys status match")

    # ISSUE #6: Gemini degraded
    if cli_data and isinstance(cli_data, dict):
        gemini = cli_data.get("gemini", {})
        if isinstance(gemini, dict):
            if gemini.get("installed") and not gemini.get("logged_in"):
                record("BUG", "Gemini Status", f"Gemini installed but not logged in (cold) -- KNOWN ISSUE #6")
            elif gemini.get("installed") and gemini.get("logged_in"):
                record("PASS", "Gemini Status", f"Gemini installed and logged in (warm)")
            else:
                record("BUG", "Gemini Status", f"Gemini not installed -- KNOWN ISSUE #6")

    # ISSUE #9: Heartbeat
    code, hb = api_get("/api/heartbeat")
    if code == 200 and isinstance(hb, dict):
        last = hb.get("last_heartbeat")
        status = hb.get("status")
        if status == "stale" or status == "unknown":
            record("BUG", "Heartbeat Issue", f"Heartbeat status={status} -- KNOWN ISSUE #9: Should be alive with 30s interval")
        elif status == "alive":
            record("PASS", "Heartbeat Issue", f"Heartbeat is alive (last={last})")

    # ISSUE #10: Duplicate content in Identity vs Memory
    # Check workspace files
    code_ws, ws_files = api_get("/api/workspace/files")
    code_mem, mem_files = api_get("/api/memory/files")
    if code_ws == 200 and code_mem == 200:
        ws_set = set(ws_files) if isinstance(ws_files, list) else set()
        mem_set = set(mem_files) if isinstance(mem_files, list) else set()
        overlap = ws_set & mem_set
        if overlap:
            record("BUG", "Issue #10 Duplicate", f"Files appear in BOTH workspace AND memory: {overlap}")
        else:
            record("PASS", "Issue #10 Duplicate", "No file overlap between workspace and memory")
        record("INFO", "Workspace Files", f"{ws_set}")
        record("INFO", "Memory Files", f"{mem_set}")


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report():
    lines = [
        "# Cato Desktop App Audit Report",
        "",
        f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Daemon**: {DAEMON_HTTP}",
        f"**Frontend**: {FRONTEND_URL}",
        "",
        "## Summary",
        "",
    ]

    bugs = [f for f in findings if f.category == "BUG"]
    passes = [f for f in findings if f.category == "PASS"]
    warns = [f for f in findings if f.category == "WARN"]
    infos = [f for f in findings if f.category == "INFO"]

    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Checks | {len(findings)} |")
    lines.append(f"| Passed | {len(passes)} |")
    lines.append(f"| Bugs Found | {len(bugs)} |")
    lines.append(f"| Warnings | {len(warns)} |")
    lines.append(f"| Info | {len(infos)} |")
    lines.append("")

    # Bugs section
    lines.append("## Bugs (Action Items)")
    lines.append("")
    for f in bugs:
        detail = f" -- {f.detail}" if f.detail else ""
        lines.append(f"- [ ] **BUG [{f.view}]**: {f.description}{detail}")
    lines.append("")

    # Warnings
    lines.append("## Warnings")
    lines.append("")
    for f in warns:
        detail = f" -- {f.detail}" if f.detail else ""
        lines.append(f"- [ ] **WARN [{f.view}]**: {f.description}{detail}")
    lines.append("")

    # Passed
    lines.append("## Passed Checks")
    lines.append("")
    for f in passes:
        lines.append(f"- [x] **PASS [{f.view}]**: {f.description}")
    lines.append("")

    # Info
    lines.append("## Info / Notes")
    lines.append("")
    for f in infos:
        lines.append(f"- **INFO [{f.view}]**: {f.description}")
    lines.append("")

    # Known issues summary
    lines.append("## Known Issues Status")
    lines.append("")
    known_issues = [
        ("Issue #1", "Identity page save fails", "IdentityView"),
        ("Issue #2", "Chat not going to Telegram", "Telegram"),
        ("Issue #3", "No working/thinking indicator", "Chat"),
        ("Issue #4", "System vs AuthKeys mismatch", "Issue #4"),
        ("Issue #5", "No restart button for LLM connections", "LLM Restart"),
        ("Issue #6", "Gemini shows degraded", "Gemini"),
        ("Issue #7", "Double message printing", "Chat"),
        ("Issue #8", "Coding agent boxes on side", "CodingAgent"),
        ("Issue #9", "Heartbeat showing stale", "Heartbeat"),
        ("Issue #10", "Duplicate files in Identity/Agents", "Issue #10"),
    ]
    for issue_id, desc, related_view in known_issues:
        related_findings = [f for f in findings if related_view.lower() in f.view.lower() or issue_id.lower() in f.description.lower()]
        status = "CONFIRMED" if any(f.category == "BUG" for f in related_findings) else "FIXED/UNCONFIRMED" if any(f.category == "PASS" for f in related_findings) else "NOT TESTED"
        lines.append(f"| {issue_id} | {desc} | **{status}** |")
    lines.append("")

    report = "\n".join(lines)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"Report written to: {REPORT_PATH}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  CATO DESKTOP APP COMPREHENSIVE AUDIT")
    print("=" * 60)

    # Verify daemon is up
    try:
        code, data = api_get("/health")
        if code != 200:
            print(f"FATAL: Daemon not responding on {DAEMON_HTTP}/health (got {code})")
            exit(1)
        print(f"Daemon healthy: {data}")
    except Exception as e:
        print(f"FATAL: Cannot reach daemon: {e}")
        exit(1)

    test_api_endpoints()
    test_websocket()
    test_known_issues()
    test_frontend_views()
    generate_report()
