"""
Comprehensive Playwright E2E test for the Cato Web UI.
Tests all pages, API endpoints, navigation, chat, vault, heartbeat, identity files.
"""
import asyncio
import json
import sys
import time
import traceback
from urllib.request import urlopen, Request
from urllib.error import URLError

# --- API Tests (no browser needed) ---

API_BASE = "http://localhost:8080"

def api_get(path):
    try:
        req = Request(f"{API_BASE}{path}")
        with urlopen(req, timeout=5) as resp:
            data = resp.read().decode()
            return resp.status, json.loads(data) if data else {}
    except Exception as e:
        return 0, str(e)

def api_post(path, body=None):
    try:
        req = Request(f"{API_BASE}{path}", method="POST")
        req.add_header("Content-Type", "application/json")
        payload = json.dumps(body or {}).encode()
        with urlopen(req, data=payload, timeout=5) as resp:
            data = resp.read().decode()
            return resp.status, json.loads(data) if data else {}
    except Exception as e:
        return 0, str(e)

findings = []

def finding(category, desc, severity="BUG"):
    findings.append({"category": category, "desc": desc, "severity": severity})
    print(f"  [{severity}] {category}: {desc}")

def ok(category, desc):
    findings.append({"category": category, "desc": desc, "severity": "OK"})
    print(f"  [OK] {category}: {desc}")


# ============================================================
# PART 1: API Endpoint Tests
# ============================================================

print("\n=== PART 1: API ENDPOINT TESTS ===\n")

# 1. Health endpoint
status, data = api_get("/health")
if status == 200 and data.get("status") == "ok":
    ok("API-HEALTH", f"/health returns 200 OK — uptime={data.get('uptime', '?')}s")
else:
    finding("API-HEALTH", f"/health returned status={status}, data={data}")

# 2. Heartbeat endpoint
status, data = api_get("/api/heartbeat")
if status == 200:
    hb_status = data.get("status")
    last_hb = data.get("last_heartbeat")
    uptime = data.get("uptime_seconds")
    if hb_status == "alive":
        ok("API-HEARTBEAT", f"/api/heartbeat status=alive, uptime={uptime:.0f}s, last={last_hb}")
    elif hb_status == "stale":
        finding("API-HEARTBEAT", f"Heartbeat status is 'stale' — last={last_hb}, uptime={uptime}", "WARN")
    else:
        finding("API-HEARTBEAT", f"Heartbeat status={hb_status}, last={last_hb}")
else:
    finding("API-HEARTBEAT", f"/api/heartbeat returned status={status}")

# 3. Config endpoint
status, data = api_get("/api/config")
if status == 200:
    ok("API-CONFIG", "/api/config returns 200")
    # Check for secret leakage
    config_str = json.dumps(data)
    if "telegram_bot_token" in config_str.lower():
        token_val = data.get("telegram_bot_token", "")
        if token_val and token_val != "null" and len(token_val) > 10:
            finding("SECURITY-CONFIG", f"/api/config leaks telegram_bot_token in plaintext: {token_val[:20]}...", "SECURITY")
    if "api_key" in config_str.lower():
        for k, v in data.items():
            if "key" in k.lower() and "api" in k.lower() and v and v != "null":
                finding("SECURITY-CONFIG", f"/api/config may leak secret: {k}={str(v)[:20]}...", "SECURITY")
else:
    finding("API-CONFIG", f"/api/config returned status={status}")

# 4. Budget endpoint
status, data = api_get("/api/budget/summary")
if status == 200:
    ok("API-BUDGET", f"/api/budget/summary — session_spend={data.get('session_spend')}, monthly_spend={data.get('monthly_spend')}")
else:
    finding("API-BUDGET", f"/api/budget/summary returned status={status}")

# 5. Skills endpoint
status, data = api_get("/api/skills")
if status == 200 and isinstance(data, list):
    ok("API-SKILLS", f"/api/skills returns {len(data)} skills")
else:
    finding("API-SKILLS", f"/api/skills returned status={status}")

# 6. Sessions endpoint
status, data = api_get("/api/sessions")
if status == 200 and isinstance(data, list):
    ok("API-SESSIONS", f"/api/sessions returns {len(data)} sessions")
else:
    finding("API-SESSIONS", f"/api/sessions returned status={status}")

# 7. Vault keys endpoint
status, data = api_get("/api/vault/keys")
if status == 200 and isinstance(data, list):
    ok("API-VAULT", f"/api/vault/keys returns {len(data)} keys: {data}")
else:
    finding("API-VAULT", f"/api/vault/keys returned status={status}")

# 8. CLI status endpoint
status, data = api_get("/api/cli/status")
if status == 200:
    for cli_name, cli_data in data.items():
        installed = cli_data.get("installed", False)
        logged_in = cli_data.get("logged_in", False)
        version = cli_data.get("version", "")
        if installed and not logged_in and not version:
            finding("API-CLI-STATUS", f"{cli_name} CLI: installed=True but logged_in=False — version check failed (timeout or error). The 'logged_in' field is determined solely by whether '--version' succeeds, not actual auth status", "BUG")
        elif installed and logged_in:
            ok("API-CLI-STATUS", f"{cli_name} CLI: installed, version='{version}'")
        else:
            ok("API-CLI-STATUS", f"{cli_name} CLI: installed={installed}")
else:
    finding("API-CLI-STATUS", f"/api/cli/status returned status={status}")

# 9. Usage endpoint
status, data = api_get("/api/usage/summary")
if status == 200:
    ok("API-USAGE", f"/api/usage/summary returns data, total_calls={data.get('total_calls')}")
else:
    finding("API-USAGE", f"/api/usage/summary returned status={status}")

# 10. Logs endpoint
status, data = api_get("/api/logs")
if status == 200 and isinstance(data, list):
    ok("API-LOGS", f"/api/logs returns {len(data)} entries")
else:
    finding("API-LOGS", f"/api/logs returned status={status}")

# 11. Audit entries endpoint
status, data = api_get("/api/audit/entries")
if status == 200 and isinstance(data, list):
    ok("API-AUDIT", f"/api/audit/entries returns {len(data)} entries")
else:
    finding("API-AUDIT", f"/api/audit/entries returned status={status}")

# 12. Adapters endpoint
status, data = api_get("/api/adapters")
if status == 200:
    adapters = data.get("adapters", data) if isinstance(data, dict) else data
    ok("API-ADAPTERS", f"/api/adapters returns adapters: {[a.get('name') for a in adapters] if isinstance(adapters, list) else adapters}")
else:
    finding("API-ADAPTERS", f"/api/adapters returned status={status}")

# 13. Cron jobs endpoint
status, data = api_get("/api/cron/jobs")
if status == 200 and isinstance(data, list):
    ok("API-CRON", f"/api/cron/jobs returns {len(data)} jobs")
else:
    finding("API-CRON", f"/api/cron/jobs returned status={status}")

# 14. Coding agent page
try:
    req = Request(f"{API_BASE}/coding-agent")
    with urlopen(req, timeout=5) as resp:
        content = resp.read().decode()
        if "Cato Coding Agent" in content:
            ok("PAGE-CODING-AGENT", "/coding-agent page loads correctly")
        else:
            finding("PAGE-CODING-AGENT", "/coding-agent page loads but missing expected title")
except Exception as e:
    finding("PAGE-CODING-AGENT", f"/coding-agent failed: {e}")


# ============================================================
# PART 2: Playwright Browser Tests
# ============================================================

print("\n=== PART 2: PLAYWRIGHT BROWSER TESTS ===\n")

async def run_browser_tests():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        # Collect console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        # ---- Test 1: Dashboard loads ----
        print("  Testing dashboard load...")
        await page.goto(f"{API_BASE}/", wait_until="networkidle", timeout=15000)

        # Dismiss onboarding overlay if present
        onboarding = page.locator('#onboarding-overlay')
        if await onboarding.count() > 0:
            is_vis = await onboarding.is_visible()
            if is_vis:
                # Set localStorage and dismiss
                await page.evaluate("localStorage.setItem('cato_onboarded', '1')")
                await page.evaluate("document.getElementById('onboarding-overlay').style.display = 'none'")
                await page.wait_for_timeout(300)
                ok("ONBOARDING", "Onboarding overlay dismissed for testing")
        title = await page.title()
        if "Cato" in title:
            ok("PAGE-DASHBOARD", f"Dashboard loads with title: {title}")
        else:
            finding("PAGE-DASHBOARD", f"Dashboard title unexpected: {title}")

        # ---- Test 2: Sidebar navigation ----
        print("  Testing sidebar navigation...")
        nav_pages = [
            ("chat", "Chat"),
            ("agents", "Agents"),
            ("skills", "Skills"),
            ("cron", "Cron"),
            ("sessions", "Sessions"),
            ("flows", "Flows"),
            ("usage", "Usage"),
            ("audit", "Audit Log"),
            ("memory", "Memory"),
            ("logs", "Logs"),
            ("alerts", "Alerts"),
            ("system", "System"),
            ("diagnostics", "Diagnostics"),
            ("nodes", "Nodes"),
            ("config", "Config"),
            ("budget", "Budget"),
            ("conduit", "Conduit"),
            ("vault", "Vault & Auth"),
            ("identity", "Identity"),
        ]

        for page_id, page_name in nav_pages:
            try:
                nav_item = page.locator(f'[data-page="{page_id}"]')
                if await nav_item.count() > 0:
                    await nav_item.click()
                    await page.wait_for_timeout(300)
                    # Check the page div is visible
                    page_div = page.locator(f"#{page_id}-page")
                    if await page_div.count() > 0:
                        is_visible = await page_div.is_visible()
                        if is_visible:
                            ok("NAV", f"Page '{page_name}' navigates and shows correctly")
                        else:
                            finding("NAV", f"Page '{page_name}' nav item clicked but page div not visible")
                    else:
                        finding("NAV", f"Page '{page_name}' has no #{page_id}-page div", "WARN")
                else:
                    finding("NAV", f"Nav item for '{page_name}' (data-page={page_id}) not found in sidebar")
            except Exception as e:
                finding("NAV", f"Error navigating to '{page_name}': {e}")

        # ---- Test 3: Chat — "AI" vs "Cato" ----
        print("  Testing chat bot name...")
        # Navigate to chat
        chat_nav = page.locator('[data-page="chat"]')
        await chat_nav.click()
        await page.wait_for_timeout(500)

        # Check if message avatars use "AI" text
        # The bot avatar text in rendered messages
        bot_avatars = page.locator('.msg-avatar.bot-av')
        count = await bot_avatars.count()
        if count > 0:
            first_text = await bot_avatars.first.inner_text()
            if first_text.strip() == "AI":
                finding("CHAT-BOT-NAME", 'Bot avatar shows "AI" instead of "Cato" — hardcoded in dashboard.html lines 1432, 1439, 1549 (msg-avatar bot-av uses "AI" literal)')
            else:
                ok("CHAT-BOT-NAME", f"Bot avatar text: '{first_text}'")

        # Also check the source for hardcoded "AI" in bot avatars
        page_content = await page.content()
        ai_avatar_count = page_content.count('>AI</div>')
        if ai_avatar_count > 0:
            finding("CHAT-BOT-NAME-SOURCE", f'Found {ai_avatar_count} instances of ">AI</div>" in page HTML — the typing indicator has hardcoded "AI" text')

        # ---- Test 4: Vault & Auth page ----
        print("  Testing Vault & Auth page...")
        vault_nav = page.locator('[data-page="vault"]')
        await vault_nav.click()
        await page.wait_for_timeout(1000)

        # Check vault keys loaded
        vault_keys = page.locator('.vault-key-row')
        vault_count = await vault_keys.count()
        if vault_count > 0:
            ok("VAULT-KEYS", f"Vault shows {vault_count} keys")
        else:
            finding("VAULT-KEYS", "No vault key rows rendered")

        # Check CLI auth status
        cli_rows = page.locator('.cli-status-row')
        cli_count = await cli_rows.count()
        if cli_count > 0:
            # Check for "Not logged in" badges
            not_logged_badges = page.locator('.cli-status-row .badge-yellow')
            not_logged_count = await not_logged_badges.count()
            logged_badges = page.locator('.cli-status-row .badge-blue')
            logged_count = await logged_badges.count()
            if not_logged_count > 0:
                finding("VAULT-CLI-AUTH", f'{not_logged_count} CLIs show "Not logged in" — the logged_in field is incorrectly determined: server.py line 396 sets logged_in=True only if "--version" command succeeds without exception. For codex/gemini/cursor, the command times out or errors, so they show "Not logged in" even though auth status is not actually checked.')
            ok("VAULT-CLI-AUTH", f"{cli_count} CLI rows rendered, {logged_count} logged in, {not_logged_count} not logged in")
        else:
            finding("VAULT-CLI-AUTH", "No CLI status rows rendered")

        # Check for restart/reconnect buttons
        restart_btns = page.locator('button:has-text("Restart"), button:has-text("Reconnect"), button:has-text("Retry")')
        restart_count = await restart_btns.count()
        if restart_count == 0:
            finding("VAULT-NO-RESTART", 'No restart/reconnect button for LLM connections in Vault & Auth page — users cannot retry failed CLI auth checks', "BUG")
        else:
            ok("VAULT-RESTART", f"Found {restart_count} restart/reconnect buttons")

        # ---- Test 5: Heartbeat display on dashboard ----
        print("  Testing heartbeat display...")
        dash_nav = page.locator('[data-page="dashboard"]')
        if await dash_nav.count() == 0:
            # Try the chat page first, dashboard might be main page
            await page.goto(f"{API_BASE}/", wait_until="networkidle", timeout=10000)
        else:
            await dash_nav.click()
        await page.wait_for_timeout(1000)

        # The dashboard page should have heartbeat info
        hb_body = page.locator('#dash-heartbeat-body')
        if await hb_body.count() > 0:
            hb_text = await hb_body.inner_text()
            if "alive" in hb_text.lower() or "ok" in hb_text.lower():
                ok("HEARTBEAT-DISPLAY", f"Heartbeat shows on dashboard: {hb_text[:100]}")
            elif "stale" in hb_text.lower():
                finding("HEARTBEAT-DISPLAY", f"Heartbeat shows 'stale' on dashboard — the HeartbeatMonitor only fires if agent directories with HEARTBEAT.md exist. Without those, the POST-based fallback shows the last POST timestamp which ages over time.", "BUG")
            elif "unavailable" in hb_text.lower() or "offline" in hb_text.lower():
                finding("HEARTBEAT-DISPLAY", f"Heartbeat shows unavailable/offline on dashboard", "BUG")
            elif "loading" in hb_text.lower():
                finding("HEARTBEAT-DISPLAY", "Heartbeat stuck on 'Loading...' — API call may be failing", "BUG")
            else:
                ok("HEARTBEAT-DISPLAY", f"Heartbeat text: {hb_text[:100]}")
        else:
            finding("HEARTBEAT-DISPLAY", "No #dash-heartbeat-body element found — dashboard may not have loaded the overview page")

        # ---- Test 6: Identity page duplication check ----
        print("  Testing Identity/Agents file duplication...")
        # Navigate to Identity page
        identity_nav = page.locator('[data-page="identity"]')
        await identity_nav.click()
        await page.wait_for_timeout(500)

        # Check identity page has SOUL.md, IDENTITY.md, etc. buttons
        identity_buttons = page.locator('#identity-page button')
        identity_btn_texts = []
        for i in range(await identity_buttons.count()):
            txt = await identity_buttons.nth(i).inner_text()
            identity_btn_texts.append(txt.strip())
        identity_file_btns = [b for b in identity_btn_texts if b.endswith('.md')]

        # Navigate to Agents page
        agents_nav = page.locator('[data-page="agents"]')
        await agents_nav.click()
        await page.wait_for_timeout(500)

        # Check workspace files grid
        ws_grid = page.locator('#workspace-files-grid')
        ws_grid_text = await ws_grid.inner_text() if await ws_grid.count() > 0 else ""
        ws_files = [f.strip() for f in ws_grid_text.split("\n") if f.strip() and f.strip().endswith(".md")]

        # Check for overlap
        identity_set = set(identity_file_btns)
        agents_set = set(ws_files)
        overlap = identity_set & agents_set
        if overlap:
            finding("IDENTITY-DUPLICATION", f"Files {overlap} appear in BOTH the Identity page AND the Agents workspace grid — this is confusing UX duplication. Identity page has buttons for {identity_file_btns}. Agents workspace grid shows {ws_files}.", "BUG")
        elif identity_file_btns and ws_files:
            finding("IDENTITY-DUPLICATION", f"Identity page has {identity_file_btns} buttons. Agents workspace grid shows {ws_files}. Both pages provide editing of workspace/identity files — same functionality duplicated across two navigation sections.", "UX")
        else:
            ok("IDENTITY-DUPLICATION", f"Identity buttons: {identity_file_btns}, Agents workspace files: {ws_files}")

        # ---- Test 7: WebSocket connection ----
        print("  Testing WebSocket connection...")
        # Check if the health-dot in sidebar indicates connected
        health_dot = page.locator('.health-dot')
        if await health_dot.count() > 0:
            classes = await health_dot.get_attribute('class') or ''
            if 'online' in classes:
                ok("WEBSOCKET", "Health dot shows online (WebSocket connected)")
            else:
                finding("WEBSOCKET", "Health dot does NOT show 'online' class — WebSocket may not be connected", "WARN")
        else:
            finding("WEBSOCKET", "No .health-dot element found")

        # ---- Test 8: Skills page ----
        print("  Testing Skills page...")
        skills_nav = page.locator('[data-page="skills"]')
        await skills_nav.click()
        await page.wait_for_timeout(500)
        skill_cards = page.locator('.skill-card')
        skill_count = await skill_cards.count()
        if skill_count > 0:
            ok("SKILLS-PAGE", f"Skills page shows {skill_count} skill cards")
        else:
            skills_count_text = page.locator('#skills-count')
            if await skills_count_text.count() > 0:
                t = await skills_count_text.inner_text()
                ok("SKILLS-PAGE", f"Skills page loaded: {t}")
            else:
                finding("SKILLS-PAGE", "Skills page shows no skill cards")

        # ---- Test 9: Budget page ----
        print("  Testing Budget page...")
        budget_nav = page.locator('[data-page="budget"]')
        await budget_nav.click()
        await page.wait_for_timeout(500)
        budget_page = page.locator('#budget-page')
        if await budget_page.count() > 0 and await budget_page.is_visible():
            ok("BUDGET-PAGE", "Budget page loads and is visible")
        else:
            finding("BUDGET-PAGE", "Budget page not visible after navigation")

        # ---- Test 10: Cron page ----
        print("  Testing Cron page...")
        cron_nav = page.locator('[data-page="cron"]')
        await cron_nav.click()
        await page.wait_for_timeout(500)
        cron_table = page.locator('#cron-table')
        if await cron_table.count() > 0:
            ok("CRON-PAGE", "Cron page loads with cron table")
        else:
            finding("CRON-PAGE", "Cron table not found")

        # ---- Test 11: Config page ----
        print("  Testing Config page...")
        config_nav = page.locator('[data-page="config"]')
        await config_nav.click()
        await page.wait_for_timeout(500)
        config_page = page.locator('#config-page')
        if await config_page.count() > 0 and await config_page.is_visible():
            ok("CONFIG-PAGE", "Config page loads and is visible")
        else:
            finding("CONFIG-PAGE", "Config page not visible after navigation")

        # ---- Test 12: Logs page ----
        print("  Testing Logs page...")
        logs_nav = page.locator('[data-page="logs"]')
        await logs_nav.click()
        await page.wait_for_timeout(500)
        log_output = page.locator('#log-output')
        if await log_output.count() > 0:
            log_text = await log_output.inner_text()
            if len(log_text) > 10:
                ok("LOGS-PAGE", f"Logs page shows log output ({len(log_text)} chars)")
            else:
                finding("LOGS-PAGE", "Logs page loaded but log output is empty", "WARN")
        else:
            finding("LOGS-PAGE", "Log output element not found")

        # ---- Test 13: Audit page ----
        print("  Testing Audit page...")
        audit_nav = page.locator('[data-page="audit"]')
        await audit_nav.click()
        await page.wait_for_timeout(500)
        audit_page = page.locator('#audit-page')
        if await audit_page.count() > 0 and await audit_page.is_visible():
            ok("AUDIT-PAGE", "Audit page loads and is visible")
        else:
            finding("AUDIT-PAGE", "Audit page not visible after navigation")

        # ---- Test 14: System page — Daemon restart button ----
        print("  Testing System page...")
        system_nav = page.locator('[data-page="system"]')
        await system_nav.click()
        await page.wait_for_timeout(500)
        restart_btn = page.locator('button:has-text("Restart Daemon")')
        if await restart_btn.count() > 0:
            ok("SYSTEM-PAGE", "System page has 'Restart Daemon' button")
        else:
            finding("SYSTEM-PAGE", "System page missing 'Restart Daemon' button")

        # ---- Test 15: Search input ----
        print("  Testing search input...")
        search_input = page.locator('#search-input')
        if await search_input.count() > 0:
            await search_input.fill("test search")
            val = await search_input.input_value()
            if val == "test search":
                ok("SEARCH", "Global search input accepts text")
            else:
                finding("SEARCH", "Search input did not accept text properly")
            await search_input.fill("")
        else:
            finding("SEARCH", "Global search input not found")

        # ---- Test 16: Version badge ----
        print("  Testing version badge...")
        version_badge = page.locator('.version-badge')
        if await version_badge.count() > 0:
            ver = await version_badge.inner_text()
            ok("VERSION", f"Version badge shows: {ver}")
        else:
            finding("VERSION", "No version badge in sidebar footer")

        # ---- Test 17: Check for console errors ----
        if console_errors:
            unique_errors = list(set(console_errors))[:10]
            for err in unique_errors:
                finding("CONSOLE-ERROR", f"Browser console error: {err[:200]}", "WARN")
        else:
            ok("CONSOLE", "No browser console errors detected")

        # ---- Test 18: Chat input and send button ----
        print("  Testing chat input...")
        chat_nav = page.locator('[data-page="chat"]')
        await chat_nav.click()
        await page.wait_for_timeout(300)

        chat_input = page.locator('#chat-input')
        send_btn = page.locator('#send-btn')
        if await chat_input.count() > 0 and await send_btn.count() > 0:
            ok("CHAT-INPUT", "Chat input textarea and Send button exist")
        else:
            finding("CHAT-INPUT", "Chat input or Send button not found")

        # ---- Test 19: New session button ----
        new_session_btn = page.locator('#new-session-btn')
        if await new_session_btn.count() > 0:
            ok("NEW-SESSION", "New session button (+) exists")
        else:
            finding("NEW-SESSION", "New session button not found")

        # ---- Test 20: Abort/Stop button ----
        abort_btn = page.locator('#abort-btn')
        if await abort_btn.count() > 0:
            ok("ABORT-BTN", "Stop/Abort button exists in chat")
        else:
            finding("ABORT-BTN", "Stop/Abort button not found in chat")

        # ---- Test 21: Alerts page ----
        print("  Testing Alerts page...")
        alerts_nav = page.locator('[data-page="alerts"]')
        await alerts_nav.click()
        await page.wait_for_timeout(300)
        alerts_page = page.locator('#alerts-page')
        if await alerts_page.count() > 0 and await alerts_page.is_visible():
            ok("ALERTS-PAGE", "Alerts page loads and is visible")
        else:
            finding("ALERTS-PAGE", "Alerts page not visible")

        # ---- Test 22: Memory page ----
        print("  Testing Memory page...")
        memory_nav = page.locator('[data-page="memory"]')
        await memory_nav.click()
        await page.wait_for_timeout(300)
        memory_page = page.locator('#memory-page')
        if await memory_page.count() > 0 and await memory_page.is_visible():
            ok("MEMORY-PAGE", "Memory page loads and is visible")
        else:
            finding("MEMORY-PAGE", "Memory page not visible")

        # ---- Test 23: Conduit page ----
        print("  Testing Conduit page...")
        conduit_nav = page.locator('[data-page="conduit"]')
        await conduit_nav.click()
        await page.wait_for_timeout(300)
        conduit_page = page.locator('#conduit-page')
        if await conduit_page.count() > 0 and await conduit_page.is_visible():
            ok("CONDUIT-PAGE", "Conduit page loads and is visible")
        else:
            finding("CONDUIT-PAGE", "Conduit page not visible")

        # ---- Test 24: Diagnostics page ----
        print("  Testing Diagnostics page...")
        diag_nav = page.locator('[data-page="diagnostics"]')
        await diag_nav.click()
        await page.wait_for_timeout(300)
        diag_page = page.locator('#diagnostics-page')
        if await diag_page.count() > 0 and await diag_page.is_visible():
            ok("DIAGNOSTICS-PAGE", "Diagnostics page loads and is visible")
        else:
            finding("DIAGNOSTICS-PAGE", "Diagnostics page not visible")

        # ---- Test 25: Flows page ----
        print("  Testing Flows page...")
        flows_nav = page.locator('[data-page="flows"]')
        await flows_nav.click()
        await page.wait_for_timeout(300)
        flows_page = page.locator('#flows-page')
        if await flows_page.count() > 0 and await flows_page.is_visible():
            ok("FLOWS-PAGE", "Flows page loads and is visible")
        else:
            finding("FLOWS-PAGE", "Flows page not visible")

        # ---- Test 26: Nodes page ----
        print("  Testing Nodes page...")
        nodes_nav = page.locator('[data-page="nodes"]')
        await nodes_nav.click()
        await page.wait_for_timeout(300)
        nodes_page = page.locator('#nodes-page')
        if await nodes_page.count() > 0 and await nodes_page.is_visible():
            ok("NODES-PAGE", "Nodes page loads and is visible")
        else:
            finding("NODES-PAGE", "Nodes page not visible")

        # ---- Test 27: Identity file loading ----
        print("  Testing Identity file load functionality...")
        identity_nav = page.locator('[data-page="identity"]')
        await identity_nav.click()
        await page.wait_for_timeout(500)

        # Click SOUL.md button
        soul_btn = page.locator('button:has-text("SOUL.md")')
        if await soul_btn.count() > 0:
            await soul_btn.first.click()
            await page.wait_for_timeout(500)
            label = page.locator('#identity-file-label')
            if await label.count() > 0:
                label_text = await label.inner_text()
                if "SOUL.md" in label_text:
                    ok("IDENTITY-LOAD", "Clicking SOUL.md button loads the file label correctly")
                else:
                    finding("IDENTITY-LOAD", f"SOUL.md button clicked but label shows: {label_text}")
            textarea = page.locator('#identity-file-content')
            if await textarea.count() > 0:
                content = await textarea.input_value()
                if len(content) > 0:
                    ok("IDENTITY-CONTENT", f"SOUL.md content loaded ({len(content)} chars)")
                else:
                    finding("IDENTITY-CONTENT", "SOUL.md textarea is empty — file may not exist or API failed", "WARN")

        # ---- Test 28: Coding agent page ----
        print("  Testing Coding Agent page in browser...")
        await page.goto(f"{API_BASE}/coding-agent", wait_until="networkidle", timeout=15000)
        coding_title = await page.title()
        if "Coding Agent" in coding_title:
            ok("CODING-AGENT-PAGE", f"Coding agent page loads: {coding_title}")
        else:
            finding("CODING-AGENT-PAGE", f"Coding agent page title unexpected: {coding_title}")

        # ---- Test 29: Dashboard overview page - check what page loads by default ----
        print("  Testing default page load...")
        await page.goto(f"{API_BASE}/", wait_until="networkidle", timeout=15000)
        await page.wait_for_timeout(500)
        # Check which page is active
        active_page = page.locator('.page.active, #chat-page.active')
        if await active_page.count() > 0:
            active_id = await active_page.first.get_attribute("id")
            ok("DEFAULT-PAGE", f"Default page loads with active page: {active_id}")
        else:
            finding("DEFAULT-PAGE", "No active page found on initial load", "WARN")

        # ---- Test 30: Check sessions page ----
        print("  Testing Sessions page...")
        sessions_nav = page.locator('[data-page="sessions"]')
        await sessions_nav.click()
        await page.wait_for_timeout(500)
        sessions_page = page.locator('#sessions-page')
        if await sessions_page.count() > 0 and await sessions_page.is_visible():
            ok("SESSIONS-PAGE", "Sessions page loads and is visible")
        else:
            finding("SESSIONS-PAGE", "Sessions page not visible after navigation")

        await browser.close()


try:
    asyncio.run(run_browser_tests())
except Exception as e:
    finding("PLAYWRIGHT", f"Browser test failed: {e}\n{traceback.format_exc()}")


# ============================================================
# PART 3: Source Code Analysis
# ============================================================

print("\n=== PART 3: SOURCE CODE ANALYSIS ===\n")

# Check bot avatar hardcoding
with open(r"C:\Users\Administrator\Desktop\Cato\cato\ui\dashboard.html", "r", encoding="utf-8") as f:
    html = f.read()

# Count "AI" hardcoded in bot avatars
import re
ai_avatar_matches = re.findall(r"bot-av['\"]?>AI<", html)
if ai_avatar_matches:
    finding("SOURCE-BOT-NAME", f'Found {len(ai_avatar_matches)} hardcoded "AI" in bot avatar elements. Lines: 1432 (renderMessages), 1439 (typing-indicator), 1549 (startStreaming). Should be "Cato" or configurable.')

# Check for identity file duplication between Agents and Identity pages
# Identity page: buttons for SOUL.md, IDENTITY.md, USER.md, AGENTS.md
# Agents page: workspace files grid showing SOUL.md, IDENTITY.md, etc.
identity_page_files = re.findall(r"loadIdentityFile\('([^']+)'\)", html)
agents_identity_files = re.findall(r"IDENTITY_FILES\s*=\s*\[([^\]]+)\]", html)
if identity_page_files:
    finding("SOURCE-IDENTITY-DUP", f"Identity page has dedicated buttons for: {identity_page_files}. Agents page IDENTITY_FILES list includes: {agents_identity_files[0] if agents_identity_files else 'N/A'}. These two pages overlap in functionality — the same files (SOUL.md, IDENTITY.md, USER.md, AGENTS.md) are editable from both places with different UI patterns.", "UX")

# Check heartbeat display logic
# Dashboard shows heartbeat via loadDashHeartbeat() which calls /api/heartbeat
# The API returns status: "alive"|"stale"|"unknown"
# The dashboard shows a badge but doesn't show last heartbeat TIME or refresh interval
hb_display = re.findall(r'loadDashHeartbeat', html)
if hb_display:
    # Check if the display includes the last heartbeat timestamp
    hb_section = html[html.index('loadDashHeartbeat'):html.index('loadDashHeartbeat')+1000]
    if 'last_heartbeat' not in hb_section and 'last_heartbeat' not in html[html.index('dash-heartbeat-body'):html.index('dash-heartbeat-body')+1500]:
        finding("SOURCE-HEARTBEAT", "Dashboard heartbeat display does not show the 'last_heartbeat' timestamp from the API — user cannot see WHEN the last heartbeat was, only the status badge and uptime", "BUG")
    else:
        ok("SOURCE-HEARTBEAT", "Heartbeat section references last_heartbeat")

# Check CLI login logic
cli_section = html[html.index('loadCliStatus'):html.index('loadCliStatus')+600]
finding("SOURCE-CLI-AUTH", "CLI auth detection in server.py (line 396) equates 'version command succeeded' with 'logged_in=True'. This is incorrect — running 'codex --version' or 'gemini --version' timing out does NOT mean the user is not authenticated. The API should check actual auth state or at minimum not conflate version availability with login status.", "BUG")

# Check for restart button for LLMs
if 'Retry' not in html and 'retry' not in html.lower() and 'reconnect' not in cli_section.lower():
    finding("SOURCE-NO-RETRY", "No retry/reconnect button exists for failed CLI auth checks on the Vault & Auth page. Users cannot re-check CLI status without reloading the entire page.", "BUG")


# ============================================================
# SUMMARY
# ============================================================

print("\n" + "=" * 60)
print("=== COMPREHENSIVE WEB UI AUDIT SUMMARY ===")
print("=" * 60 + "\n")

bugs = [f for f in findings if f["severity"] == "BUG"]
security = [f for f in findings if f["severity"] == "SECURITY"]
warns = [f for f in findings if f["severity"] in ("WARN", "UX")]
oks = [f for f in findings if f["severity"] == "OK"]

print(f"BUGS:     {len(bugs)}")
print(f"SECURITY: {len(security)}")
print(f"WARNINGS: {len(warns)}")
print(f"OK:       {len(oks)}")
print(f"TOTAL:    {len(findings)}")

# Write report
report_lines = ["# Cato Web UI Audit — Task List\n"]
report_lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
report_lines.append(f"**Total findings**: {len(bugs)} bugs, {len(security)} security, {len(warns)} warnings, {len(oks)} passing\n\n")

if security:
    report_lines.append("## SECURITY Issues\n")
    for f in security:
        report_lines.append(f"- [ ] **SECURITY**: {f['category']} — {f['desc']}\n")
    report_lines.append("\n")

if bugs:
    report_lines.append("## Bugs\n")
    for f in bugs:
        report_lines.append(f"- [ ] **BUG**: {f['category']} — {f['desc']}\n")
    report_lines.append("\n")

if warns:
    report_lines.append("## Warnings / UX Issues\n")
    for f in warns:
        report_lines.append(f"- [ ] **{f['severity']}**: {f['category']} — {f['desc']}\n")
    report_lines.append("\n")

if oks:
    report_lines.append("## Passing Checks\n")
    for f in oks:
        report_lines.append(f"- [x] **OK**: {f['category']} — {f['desc']}\n")

report_path = r"C:\Users\Administrator\Desktop\Cato\WEB_UI_AUDIT_TASKS.md"
with open(report_path, "w", encoding="utf-8") as f:
    f.write("".join(report_lines))

print(f"\nReport written to: {report_path}")
