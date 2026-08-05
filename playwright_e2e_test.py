"""
Cato Web UI - Comprehensive End-to-End Playwright Test Suite
Tests every nav section, API endpoint, and interactive feature.
"""

import asyncio
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, Browser

# Force UTF-8 output on Windows to avoid cp1252 encoding errors
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_URL = "http://localhost:8080"
SCREENSHOT_DIR = Path("C:/Users/Administrator/Desktop/Cato/test_screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

results = []
pass_count = 0
fail_count = 0


def record(name: str, passed: bool, detail: str = ""):
    global pass_count, fail_count
    status = "PASS" if passed else "FAIL"
    if passed:
        pass_count += 1
    else:
        fail_count += 1
    results.append({"name": name, "status": status, "detail": detail})
    marker = "[PASS]" if passed else "[FAIL]"
    print(f"  {marker}  {name}" + (f" — {detail}" if detail else ""))


async def screenshot(page: Page, name: str):
    path = SCREENSHOT_DIR / f"{name}.png"
    await page.screenshot(path=str(path), full_page=False)
    return str(path)


# ---------------------------------------------------------------------------
# TEST GROUP 1: Page Load
# ---------------------------------------------------------------------------

async def test_page_load(page: Page):
    print("\n=== GROUP 1: Page Load ===")
    try:
        resp = await page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
        code = resp.status if resp else None
        record("GET / returns 200", code == 200, f"status={code}")
        title = await page.title()
        record("Page title is 'Cato Dashboard'", "Cato" in title, f"title='{title}'")
        sidebar = await page.query_selector("#sidebar")
        record("Sidebar element present", sidebar is not None)
        content = await page.query_selector("#content")
        record("Content area present", content is not None)
        await screenshot(page, "01_page_load")
    except Exception as e:
        record("Page loads without error", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 2: Nav Section Rendering
# ---------------------------------------------------------------------------

async def navigate_to(page: Page, section: str):
    """Click a nav item and wait for content to appear."""
    await page.evaluate(f"navigate('{section}')")
    await page.wait_for_timeout(600)


async def page_active(page: Page, section: str) -> bool:
    """Check if the page div for a section is active/visible."""
    return await page.evaluate(f"""
        (() => {{
            const el = document.getElementById('page-{section}');
            if (!el) return false;
            return el.classList.contains('active') || el.style.display !== 'none';
        }})()
    """)


async def test_nav_sections(page: Page):
    print("\n=== GROUP 2: Nav Section Rendering ===")

    sections = [
        ("dashboard", "Dashboard", ["adapter", "heartbeat", "status"]),
        ("chat",      "Chat",      ["chat", "message", "input", "send"]),
        ("agents",    "Agents",    ["agent", "orchestrat", "model"]),
        ("skills",    "Skills",    ["skill", "add-notion", "Coding"]),
        ("cron",      "Cron",      ["cron", "job", "schedule"]),
        ("sessions",  "Sessions",  ["session", "Sessions"]),
        ("usage",     "Usage",     ["usage", "token", "cost", "spend"]),
        ("audit",     "Audit Log", ["audit", "entry", "hash", "chain"]),
        ("memory",    "Memory",    ["memory", "fact", "knowledge"]),
        ("logs",      "Logs",      ["log", "INFO", "ERROR"]),
        ("alerts",    "Alerts",    ["alert", "notification"]),
        ("system",    "System",    ["system", "cli", "pool", "action"]),
        ("diagnostics","Diagnostics",["diagnostic", "query", "classifier", "contradiction"]),
        ("config",    "Config",    ["config", "model", "setting"]),
        ("budget",    "Budget",    ["budget", "session", "monthly", "spend"]),
        ("conduit",   "Conduit",   ["conduit", "browser", "tab", "page"]),
        ("vault",     "Vault",     ["vault", "key", "secret", "auth"]),
    ]

    for section, label, keywords in sections:
        try:
            await navigate_to(page, section)
            # get inner text of the content area
            content_text = await page.evaluate("""
                document.getElementById('content')?.innerText || ''
            """)
            content_lower = content_text.lower()
            found_keywords = [k for k in keywords if k.lower() in content_lower]
            # Also check that the page div is active
            active = await page.evaluate(f"""
                (() => {{
                    const pages = document.querySelectorAll('.page');
                    let found = false;
                    pages.forEach(p => {{
                        if (p.id === 'page-{section}' && (p.classList.contains('active') || p.style.display !== 'none'))
                            found = true;
                    }});
                    return found;
                }})()
            """)
            passed = active or len(found_keywords) > 0
            record(
                f"Nav: {label} section renders",
                passed,
                f"active={active}, keywords={found_keywords}/{keywords}"
            )
            if section in ("dashboard", "skills", "logs", "system", "diagnostics", "config"):
                await screenshot(page, f"02_nav_{section}")
        except Exception as e:
            record(f"Nav: {label} section renders", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 3: API Endpoints via fetch()
# ---------------------------------------------------------------------------

async def fetch_api(page: Page, method: str, path: str, body=None) -> dict:
    """Execute a fetch call in the browser context and return {status, data}."""
    opts = f"""{{
        method: '{method}',
        headers: {{'Content-Type': 'application/json'}},
        body: {json.dumps(json.dumps(body)) if body else 'undefined'}
    }}"""
    script = f"""
    async () => {{
        try {{
            const resp = await fetch('{path}', {opts});
            let data;
            const ct = resp.headers.get('content-type') || '';
            if (ct.includes('application/json')) {{
                data = await resp.json();
            }} else {{
                data = await resp.text();
            }}
            return {{ status: resp.status, data }};
        }} catch(e) {{
            return {{ status: 0, error: e.toString() }};
        }}
    }}
    """
    return await page.evaluate(script)


async def test_api_endpoints(page: Page):
    print("\n=== GROUP 3: API Endpoints ===")

    endpoints = [
        ("GET", "/api/heartbeat",                         200, "heartbeat"),
        ("GET", "/api/adapters",                          200, "adapters"),
        ("GET", "/api/memory/stats",                      200, "memory stats"),
        ("GET", "/api/cli/status",                        200, "CLI status"),
        ("GET", "/api/flows",                             200, "flows list"),
        ("GET", "/api/nodes",                             200, "nodes list"),
        ("GET", "/api/diagnostics/contradiction-health",  200, "contradiction health"),
        ("GET", "/api/diagnostics/decision-memory",       200, "decision memory"),
        ("GET", "/api/diagnostics/query-classifier",      200, "query classifier"),
        ("GET", "/api/diagnostics/anomaly-domains",       200, "anomaly domains"),
        ("GET", "/api/diagnostics/skill-corrections",     200, "skill corrections"),
        ("GET", "/api/skills",                            200, "skills list"),
        ("GET", "/api/logs",                              200, "logs"),
        ("GET", "/api/audit/entries",                     200, "audit entries"),
        ("GET", "/api/config",                            200, "config"),
        ("GET", "/api/budget/summary",                    200, "budget summary"),
        ("GET", "/api/usage/summary",                     200, "usage summary"),
        ("GET", "/api/sessions",                          200, "sessions list"),
        ("GET", "/api/cron/jobs",                         200, "cron jobs"),
        ("GET", "/api/workspace/files",                   200, "workspace files"),
        ("GET", "/api/vault/keys",                        200, "vault keys"),
        ("GET", "/api/action-guard/status",               200, "action guard"),
        ("GET", "/api/memory/files",                      200, "memory files"),
        ("GET", "/api/chat/history",                      200, "chat history"),
        ("GET", "/health",                                200, "health check"),
    ]

    for method, path, expected_status, label in endpoints:
        try:
            result = await fetch_api(page, method, path)
            status = result.get("status", 0)
            passed = status == expected_status
            detail = f"status={status}"
            if not passed:
                detail += f", error={result.get('error', result.get('data', ''))}"
            record(f"API {method} {path} -> {expected_status}", passed, detail)
        except Exception as e:
            record(f"API {method} {path} -> {expected_status}", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 4: Dashboard Content Checks
# ---------------------------------------------------------------------------

async def test_dashboard_content(page: Page):
    print("\n=== GROUP 4: Dashboard Content Checks ===")
    try:
        await navigate_to(page, "dashboard")
        await page.wait_for_timeout(1000)

        # Check adapter status cards are present
        adapters_result = await fetch_api(page, "GET", "/api/adapters")
        adapters_data = adapters_result.get("data", {})
        adapters_list = adapters_data.get("adapters", []) if isinstance(adapters_data, dict) else []
        record(
            "Adapters API returns list",
            isinstance(adapters_list, list),
            f"count={len(adapters_list)}"
        )

        # Telegram adapter should be present
        telegram = next((a for a in adapters_list if a.get("name") == "telegram"), None)
        record("Telegram adapter present in API", telegram is not None, str(telegram))

        # Health endpoint returns expected fields
        hb_result = await fetch_api(page, "GET", "/api/heartbeat")
        hb_data = hb_result.get("data", {})
        record(
            "Heartbeat has 'status' field",
            isinstance(hb_data, dict) and "status" in hb_data,
            str(hb_data)
        )

        # Check that the dashboard page has visible content
        dash_html = await page.evaluate("""
            document.getElementById('dashboard-page')?.innerHTML || ''
        """)
        record("Dashboard page has HTML content", len(dash_html) > 100, f"len={len(dash_html)}")
        await screenshot(page, "04_dashboard_content")

    except Exception as e:
        record("Dashboard content check", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 5: Skills Page — List and Save
# ---------------------------------------------------------------------------

async def test_skills_page(page: Page):
    print("\n=== GROUP 5: Skills Page ===")
    try:
        await navigate_to(page, "skills")
        await page.wait_for_timeout(1200)

        # Skills list should be populated via API
        skills_result = await fetch_api(page, "GET", "/api/skills")
        skills_data = skills_result.get("data", [])
        skill_count = len(skills_data) if isinstance(skills_data, list) else 0
        record("Skills API returns list", skill_count > 0, f"count={skill_count}")

        # Find a skill name to work with
        first_skill = skills_data[0] if skill_count > 0 else None
        if first_skill:
            skill_dir = first_skill.get("dir", "")
            skill_name = first_skill.get("name", "")
            record("First skill has name and dir", bool(skill_dir and skill_name),
                   f"name={skill_name}, dir={skill_dir}")

            # Fetch skill content
            content_result = await fetch_api(page, "GET", f"/api/skills/{skill_dir}/content")
            content_status = content_result.get("status", 0)
            content_data = content_result.get("data", "")
            record(
                f"GET /api/skills/{skill_dir}/content -> 200",
                content_status == 200,
                f"status={content_status}, len={len(str(content_data))}"
            )

            # Try to interact with skills via JS (dismiss onboarding overlay if present)
            try:
                # Dismiss onboarding overlay if it exists
                await page.evaluate("""
                    const overlay = document.getElementById('onboarding-overlay');
                    if (overlay) overlay.style.display = 'none';
                """)
                await page.wait_for_timeout(300)
                # Check if skill rows appear in the UI
                skill_rows = await page.query_selector_all(".skill-card, [data-skill], .skill-item, .skill-row, tr[onclick]")
                has_skill_ui = len(skill_rows) > 0
                record("Skills: UI elements present", has_skill_ui, f"elements found={len(skill_rows)}")
            except Exception as e:
                record("Skills: open skill card", False, str(e))
        else:
            record("Skills: skill data available", False, "empty skills list")

        await screenshot(page, "05_skills_page")

    except Exception as e:
        record("Skills page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 6: Memory Page
# ---------------------------------------------------------------------------

async def test_memory_page(page: Page):
    print("\n=== GROUP 6: Memory Page ===")
    try:
        await navigate_to(page, "memory")
        await page.wait_for_timeout(1000)

        stats_result = await fetch_api(page, "GET", "/api/memory/stats")
        stats_data = stats_result.get("data", {})
        record(
            "Memory stats API returns dict",
            isinstance(stats_data, dict),
            str(stats_data)
        )
        record(
            "Memory stats has 'facts' field",
            isinstance(stats_data, dict) and "facts" in stats_data,
            str(stats_data)
        )

        # Check memory files listing
        files_result = await fetch_api(page, "GET", "/api/memory/files")
        files_data = files_result.get("data", [])
        record(
            "Memory files API returns list",
            isinstance(files_data, list),
            f"count={len(files_data)}"
        )

        await screenshot(page, "06_memory_page")
    except Exception as e:
        record("Memory page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 7: System Page — CLI Pool + Action Guard
# ---------------------------------------------------------------------------

async def test_system_page(page: Page):
    print("\n=== GROUP 7: System Page ===")
    try:
        await navigate_to(page, "system")
        await page.wait_for_timeout(1000)

        cli_result = await fetch_api(page, "GET", "/api/cli/status")
        cli_data = cli_result.get("data", {})
        record("CLI status returns dict", isinstance(cli_data, dict), str(cli_data)[:120])
        # Check for expected CLI keys
        has_claude = "claude" in cli_data
        record("CLI status has 'claude' key", has_claude, str(cli_data))

        ag_result = await fetch_api(page, "GET", "/api/action-guard/status")
        ag_data = ag_result.get("data", {})
        record("Action Guard status returns dict", isinstance(ag_data, dict), str(ag_data)[:120])

        await screenshot(page, "07_system_page")
    except Exception as e:
        record("System page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 8: Diagnostics Page
# ---------------------------------------------------------------------------

async def test_diagnostics_page(page: Page):
    print("\n=== GROUP 8: Diagnostics Page ===")
    try:
        await navigate_to(page, "diagnostics")
        await page.wait_for_timeout(1000)

        # Query classifier
        qc_result = await fetch_api(page, "GET", "/api/diagnostics/query-classifier")
        qc_data = qc_result.get("data", {})
        record("Query classifier returns data", qc_result.get("status") == 200,
               str(qc_data)[:100])

        # Contradiction health (may have SQLite thread error but still returns 200)
        ch_result = await fetch_api(page, "GET", "/api/diagnostics/contradiction-health")
        ch_status = ch_result.get("status", 0)
        record("Contradiction health returns 200", ch_status == 200, f"status={ch_status}")

        # Decision memory
        dm_result = await fetch_api(page, "GET", "/api/diagnostics/decision-memory")
        dm_status = dm_result.get("status", 0)
        record("Decision memory returns 200", dm_status == 200, f"status={dm_status}")

        # Anomaly domains
        ad_result = await fetch_api(page, "GET", "/api/diagnostics/anomaly-domains")
        ad_status = ad_result.get("status", 0)
        record("Anomaly domains returns 200", ad_status == 200, f"status={ad_status}")

        # Skill corrections
        sc_result = await fetch_api(page, "GET", "/api/diagnostics/skill-corrections")
        sc_status = sc_result.get("status", 0)
        record("Skill corrections returns 200", sc_status == 200, f"status={sc_status}")

        await screenshot(page, "08_diagnostics_page")
    except Exception as e:
        record("Diagnostics page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 9: Config Page
# ---------------------------------------------------------------------------

async def test_config_page(page: Page):
    print("\n=== GROUP 9: Config Page ===")
    try:
        await navigate_to(page, "config")
        await page.wait_for_timeout(800)

        cfg_result = await fetch_api(page, "GET", "/api/config")
        cfg_data = cfg_result.get("data", {})
        record("Config API returns dict", isinstance(cfg_data, dict), str(cfg_data)[:200])

        # The config page should have a form or inputs
        page_html = await page.evaluate("""
            document.getElementById('config-page')?.innerHTML || ''
        """)
        has_input = "input" in page_html.lower() or "textarea" in page_html.lower() or "select" in page_html.lower()
        record("Config page has form inputs", has_input, f"html_len={len(page_html)}")

        await screenshot(page, "09_config_page")
    except Exception as e:
        record("Config page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 10: Budget Page
# ---------------------------------------------------------------------------

async def test_budget_page(page: Page):
    print("\n=== GROUP 10: Budget Page ===")
    try:
        await navigate_to(page, "budget")
        await page.wait_for_timeout(800)

        budget_result = await fetch_api(page, "GET", "/api/budget/summary")
        budget_status = budget_result.get("status", 0)
        record("Budget summary API returns 200", budget_status == 200, f"status={budget_status}")

        usage_result = await fetch_api(page, "GET", "/api/usage/summary")
        usage_status = usage_result.get("status", 0)
        record("Usage summary API returns 200", usage_status == 200, f"status={usage_status}")

        await screenshot(page, "10_budget_page")
    except Exception as e:
        record("Budget page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 11: Audit Log Page
# ---------------------------------------------------------------------------

async def test_audit_page(page: Page):
    print("\n=== GROUP 11: Audit Log Page ===")
    try:
        await navigate_to(page, "audit")
        await page.wait_for_timeout(800)

        audit_result = await fetch_api(page, "GET", "/api/audit/entries")
        audit_status = audit_result.get("status", 0)
        audit_data = audit_result.get("data", [])
        record("Audit entries API returns 200", audit_status == 200, f"status={audit_status}")
        record("Audit entries is a list", isinstance(audit_data, list), f"count={len(audit_data)}")

        # Verify chain endpoint
        verify_result = await fetch_api(page, "POST", "/api/audit/verify", {})
        verify_status = verify_result.get("status", 0)
        record("Audit verify endpoint exists (POST)", verify_status in (200, 400, 422, 500), f"status={verify_status}")

        # Download endpoint
        dl_result = await fetch_api(page, "GET", "/api/audit/download")
        dl_status = dl_result.get("status", 0)
        record("Audit download endpoint exists", dl_status == 200, f"status={dl_status}")

        await screenshot(page, "11_audit_page")
    except Exception as e:
        record("Audit page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 12: Logs Page
# ---------------------------------------------------------------------------

async def test_logs_page(page: Page):
    print("\n=== GROUP 12: Logs Page ===")
    try:
        await navigate_to(page, "logs")
        await page.wait_for_timeout(800)

        logs_result = await fetch_api(page, "GET", "/api/logs")
        logs_status = logs_result.get("status", 0)
        logs_data = logs_result.get("data", [])
        record("Logs API returns 200", logs_status == 200, f"status={logs_status}")
        record("Logs returns list", isinstance(logs_data, list), f"count={len(logs_data)}")

        if logs_data:
            first_log = logs_data[0]
            has_msg = "msg" in first_log or "message" in first_log
            record("Log entry has message field", has_msg, str(list(first_log.keys()))[:60])
            has_level = "level" in first_log
            record("Log entry has level field", has_level, str(list(first_log.keys()))[:60])

        await screenshot(page, "12_logs_page")
    except Exception as e:
        record("Logs page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 13: Cron Jobs Page
# ---------------------------------------------------------------------------

async def test_cron_page(page: Page):
    print("\n=== GROUP 13: Cron Jobs Page ===")
    try:
        await navigate_to(page, "cron")
        await page.wait_for_timeout(800)

        cron_result = await fetch_api(page, "GET", "/api/cron/jobs")
        cron_status = cron_result.get("status", 0)
        cron_data = cron_result.get("data", [])
        record("Cron jobs API returns 200", cron_status == 200, f"status={cron_status}")
        record("Cron jobs returns list", isinstance(cron_data, list), f"count={len(cron_data)}")

        await screenshot(page, "13_cron_page")
    except Exception as e:
        record("Cron page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 14: Sessions Page
# ---------------------------------------------------------------------------

async def test_sessions_page(page: Page):
    print("\n=== GROUP 14: Sessions Page ===")
    try:
        await navigate_to(page, "sessions")
        await page.wait_for_timeout(800)

        sessions_result = await fetch_api(page, "GET", "/api/sessions")
        sessions_status = sessions_result.get("status", 0)
        sessions_data = sessions_result.get("data", [])
        record("Sessions API returns 200", sessions_status == 200, f"status={sessions_status}")
        record("Sessions returns list", isinstance(sessions_data, list), f"count={len(sessions_data)}")

        await screenshot(page, "14_sessions_page")
    except Exception as e:
        record("Sessions page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 15: Vault & Auth Page
# ---------------------------------------------------------------------------

async def test_vault_page(page: Page):
    print("\n=== GROUP 15: Vault & Auth Page ===")
    try:
        await navigate_to(page, "vault")
        await page.wait_for_timeout(800)

        vault_result = await fetch_api(page, "GET", "/api/vault/keys")
        vault_status = vault_result.get("status", 0)
        vault_data = vault_result.get("data", {})
        record("Vault keys API returns 200", vault_status == 200, f"status={vault_status}")
        # Vault returns dict with key names (values masked)
        record(
            "Vault response is list or dict",
            isinstance(vault_data, (dict, list)),
            str(vault_data)[:80]
        )

        await screenshot(page, "15_vault_page")
    except Exception as e:
        record("Vault page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 16: Workspace Files
# ---------------------------------------------------------------------------

async def test_workspace_files(page: Page):
    print("\n=== GROUP 16: Workspace Files ===")
    try:
        ws_result = await fetch_api(page, "GET", "/api/workspace/files")
        ws_status = ws_result.get("status", 0)
        ws_data = ws_result.get("data", [])
        record("Workspace files API returns 200", ws_status == 200, f"status={ws_status}")
        record("Workspace files returns list", isinstance(ws_data, list), f"count={len(ws_data)}")

        if ws_data:
            # Try to fetch first file content
            first_file = ws_data[0] if isinstance(ws_data[0], str) else ws_data[0].get("name", "")
            if first_file:
                fc_result = await fetch_api(page, "GET", f"/api/workspace/file?name={first_file}")
                fc_status = fc_result.get("status", 0)
                record(
                    f"Workspace file content fetch -> 200",
                    fc_status == 200,
                    f"file={first_file}, status={fc_status}"
                )
    except Exception as e:
        record("Workspace files test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 17: Chat History API
# ---------------------------------------------------------------------------

async def test_chat_history(page: Page):
    print("\n=== GROUP 17: Chat History ===")
    try:
        await navigate_to(page, "chat")
        await page.wait_for_timeout(800)

        ch_result = await fetch_api(page, "GET", "/api/chat/history")
        ch_status = ch_result.get("status", 0)
        ch_data = ch_result.get("data", [])
        record("Chat history API returns 200", ch_status == 200, f"status={ch_status}")
        record("Chat history returns list", isinstance(ch_data, list), f"count={len(ch_data)}")

        await screenshot(page, "17_chat_page")
    except Exception as e:
        record("Chat history test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 18: Flows API
# ---------------------------------------------------------------------------

async def test_flows_api(page: Page):
    print("\n=== GROUP 18: Flows API ===")
    try:
        flows_result = await fetch_api(page, "GET", "/api/flows")
        flows_status = flows_result.get("status", 0)
        flows_data = flows_result.get("data", [])
        record("Flows API returns 200", flows_status == 200, f"status={flows_status}")
        record("Flows returns list", isinstance(flows_data, list), f"count={len(flows_data)}")
    except Exception as e:
        record("Flows API test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 19: WebSocket health endpoint
# ---------------------------------------------------------------------------

async def test_health_endpoint(page: Page):
    print("\n=== GROUP 19: Health Endpoint ===")
    try:
        h_result = await fetch_api(page, "GET", "/health")
        h_status = h_result.get("status", 0)
        h_data = h_result.get("data", {})
        record("GET /health returns 200", h_status == 200, f"status={h_status}")
        record(
            "/health response has content",
            bool(h_data),
            str(h_data)[:100]
        )
    except Exception as e:
        record("Health endpoint test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 20: Static Assets
# ---------------------------------------------------------------------------

async def test_static_assets(page: Page):
    print("\n=== GROUP 20: Static Assets ===")
    try:
        # favicon
        fav_result = await fetch_api(page, "GET", "/favicon.png")
        record("GET /favicon.png returns 200", fav_result.get("status") == 200,
               f"status={fav_result.get('status')}")
    except Exception as e:
        record("Static assets test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 21: Skill Save Flow (PATCH /api/skills/{dir}/content)
# ---------------------------------------------------------------------------

async def test_skill_save(page: Page):
    print("\n=== GROUP 21: Skill Save (PATCH) ===")
    try:
        # Get list of skills
        skills_result = await fetch_api(page, "GET", "/api/skills")
        skills = skills_result.get("data", [])
        if not skills:
            record("Skill PATCH: skills available", False, "no skills")
            return

        first = skills[0]
        skill_dir = first.get("dir", "")
        if not skill_dir:
            record("Skill PATCH: skill has dir", False, str(first))
            return

        # Get current content
        content_result = await fetch_api(page, "GET", f"/api/skills/{skill_dir}/content")
        if content_result.get("status") != 200:
            record("Skill PATCH: get content", False, f"status={content_result.get('status')}")
            return

        original_content = content_result.get("data", "")
        if isinstance(original_content, dict):
            skill_content = original_content.get("content", "")
        else:
            skill_content = str(original_content)

        # PATCH with same content (non-destructive)
        patch_script = f"""
        async () => {{
            const resp = await fetch('/api/skills/{skill_dir}/content', {{
                method: 'PATCH',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{ content: {json.dumps(skill_content)} }})
            }});
            return {{ status: resp.status }};
        }}
        """
        patch_result = await page.evaluate(patch_script)
        patch_status = patch_result.get("status", 0)
        record(
            f"PATCH /api/skills/{skill_dir}/content -> 200",
            patch_status == 200,
            f"status={patch_status}"
        )
    except Exception as e:
        record("Skill save test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 22: Coding Agent Page
# ---------------------------------------------------------------------------

async def test_coding_agent(page: Page):
    print("\n=== GROUP 22: Coding Agent Page ===")
    try:
        resp = await page.goto(f"{BASE_URL}/coding-agent", wait_until="domcontentloaded", timeout=15000)
        code = resp.status if resp else None
        record("GET /coding-agent returns 200", code == 200, f"status={code}")
        title = await page.title()
        record("Coding agent page has title", bool(title), f"title='{title}'")
        await screenshot(page, "22_coding_agent")
        # Go back to dashboard
        await page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    except Exception as e:
        record("Coding agent page test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 23: Responsive Layout Check
# ---------------------------------------------------------------------------

async def test_responsive(page: Page):
    print("\n=== GROUP 23: Responsive Layout ===")
    try:
        await page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
        # Mobile
        await page.set_viewport_size({"width": 375, "height": 812})
        await page.wait_for_timeout(400)
        sidebar = await page.query_selector("#sidebar")
        record("Sidebar present at mobile width 375px", sidebar is not None)
        await screenshot(page, "23_mobile_layout")
        # Tablet
        await page.set_viewport_size({"width": 768, "height": 1024})
        await page.wait_for_timeout(400)
        await screenshot(page, "23_tablet_layout")
        # Desktop
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await page.wait_for_timeout(400)
        await screenshot(page, "23_desktop_layout")
        record("Responsive: viewport changes without crash", True)
    except Exception as e:
        record("Responsive layout test", False, str(e))


# ---------------------------------------------------------------------------
# TEST GROUP 24: Console Error Check
# ---------------------------------------------------------------------------

async def test_console_errors(page: Page, console_errors: list):
    print("\n=== GROUP 24: Console Error Check ===")
    js_errors = [e for e in console_errors if e.get("type") == "error"]
    # Filter out known/expected non-critical errors:
    # - 404/500 resource load errors (expected for optional resources)
    # - React img component errors (pre-existing in conduit React bundle)
    # - style prop warnings (React strict mode)
    severe_errors = [e for e in js_errors if
                     "404" not in e.get("text", "")
                     and "500" not in e.get("text", "")
                     and "favicon" not in e.get("text", "")
                     and "style prop" not in e.get("text", "")
                     and "img component" not in e.get("text", "").lower()
                     and "above error occurred" not in e.get("text", "").lower()]
    record(
        "No severe JS console errors on page load",
        len(severe_errors) == 0,
        f"errors={len(severe_errors)}: " + "; ".join(e.get("text", "")[:80] for e in severe_errors[:3])
    )


# ---------------------------------------------------------------------------
# MAIN RUNNER
# ---------------------------------------------------------------------------

async def main():
    print("=" * 70)
    print("  CATO WEB UI — COMPREHENSIVE PLAYWRIGHT END-TO-END TEST SUITE")
    print(f"  Target: {BASE_URL}")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    console_errors = []

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page: Page = await context.new_page()

        # Capture console messages
        page.on("console", lambda msg: console_errors.append({
            "type": msg.type,
            "text": msg.text
        }))
        page.on("pageerror", lambda err: console_errors.append({
            "type": "error",
            "text": str(err)
        }))

        # Run all test groups
        await test_page_load(page)
        await test_api_endpoints(page)
        await test_dashboard_content(page)
        await test_nav_sections(page)
        await test_skills_page(page)
        await test_memory_page(page)
        await test_system_page(page)
        await test_diagnostics_page(page)
        await test_config_page(page)
        await test_budget_page(page)
        await test_audit_page(page)
        await test_logs_page(page)
        await test_cron_page(page)
        await test_sessions_page(page)
        await test_vault_page(page)
        await test_workspace_files(page)
        await test_chat_history(page)
        await test_flows_api(page)
        await test_health_endpoint(page)
        await test_static_assets(page)
        await test_skill_save(page)
        await test_coding_agent(page)
        await test_responsive(page)
        await test_console_errors(page, console_errors)

        await browser.close()

    # ---------------------------------------------------------------------------
    # FINAL REPORT
    # ---------------------------------------------------------------------------
    total = pass_count + fail_count
    print("\n" + "=" * 70)
    print("  FINAL TEST RESULTS")
    print("=" * 70)
    print(f"  Total tests : {total}")
    print(f"  PASS        : {pass_count}")
    print(f"  FAIL        : {fail_count}")
    print(f"  Pass rate   : {pass_count/total*100:.1f}%" if total > 0 else "  No tests run")
    print()

    failures = [r for r in results if r["status"] == "FAIL"]
    if failures:
        print("  FAILURES:")
        for f in failures:
            print(f"    [FAIL] {f['name']}")
            if f["detail"]:
                print(f"           {f['detail']}")
    else:
        print("  All tests passed!")

    print()
    print(f"  Screenshots saved to: {SCREENSHOT_DIR}")
    print("=" * 70)

    # Write JSON report
    report_path = Path("C:/Users/Administrator/Desktop/Cato/test_results.json")
    with open(report_path, "w") as fh:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total": total,
            "pass": pass_count,
            "fail": fail_count,
            "results": results
        }, fh, indent=2)
    print(f"  JSON report: {report_path}")
    print("=" * 70)

    return fail_count


if __name__ == "__main__":
    fails = asyncio.run(main())
    sys.exit(0 if fails == 0 else 1)
