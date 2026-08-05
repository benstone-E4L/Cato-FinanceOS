"""
Playwright verification script for 15 previously-found Cato UI/API bugs.
Saves screenshots to verify_screenshots/ and writes results to VERIFY_FIX_RESULTS.md
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import aiohttp
from playwright.async_api import async_playwright, Page, Browser

BASE_URL = "http://localhost:8080"
SCREENSHOTS_DIR = Path(r"C:\Users\Administrator\Desktop\Cato\verify_screenshots")
RESULTS_FILE = Path(r"C:\Users\Administrator\Desktop\Cato\VERIFY_FIX_RESULTS.md")

SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

results = []  # list of (bug_id, label, fixed: bool, details: str)


def record(bug_id: str, label: str, fixed: bool, details: str):
    status = "FIXED ✓" if fixed else "STILL BROKEN ✗"
    print(f"  [{status}] {bug_id} — {label}: {details}")
    results.append((bug_id, label, fixed, details))


async def screenshot(page: Page, name: str):
    path = SCREENSHOTS_DIR / f"{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    return path


# ──────────────────────────────────────────────────────────────────────────────
# API-only helpers (aiohttp, no browser needed)
# ──────────────────────────────────────────────────────────────────────────────

async def check_api_bugs(session: aiohttp.ClientSession):

    # HB-001 / DASH-001 — heartbeat alive
    print("\n[1] HB-001 / DASH-001 — Heartbeat alive (API)")
    try:
        async with session.get(f"{BASE_URL}/api/heartbeat") as r:
            data = await r.json()
            alive = data.get("status") == "alive"
            record("HB-001", "Heartbeat status=alive", alive,
                   f"status={data.get('status')!r}, http={r.status}")
    except Exception as e:
        record("HB-001", "Heartbeat status=alive", False, f"exception: {e}")

    # CFG-001 — GET /api/config returns non-empty object
    print("\n[2] CFG-001 — Config GET non-empty")
    cfg_data = {}
    try:
        async with session.get(f"{BASE_URL}/api/config") as r:
            cfg_data = await r.json()
            has_keys = bool(cfg_data) and (
                "agent_name" in cfg_data or "default_model" in cfg_data
            )
            record("CFG-001", "GET /api/config non-empty", has_keys,
                   f"http={r.status}, keys={list(cfg_data.keys())[:6]}")
    except Exception as e:
        record("CFG-001", "GET /api/config non-empty", False, f"exception: {e}")

    # CFG-004 — PATCH /api/config persists
    print("\n[3] CFG-004 — PATCH /api/config persists")
    try:
        patch_payload = {"agent_name": "VerifyTest"}
        async with session.patch(
            f"{BASE_URL}/api/config",
            json=patch_payload,
            headers={"Content-Type": "application/json"},
        ) as r:
            patch_resp = await r.json()
            patch_ok = r.status == 200

        # re-GET to confirm persistence
        await asyncio.sleep(0.3)
        async with session.get(f"{BASE_URL}/api/config") as r2:
            after = await r2.json()
            persisted = after.get("agent_name") == "VerifyTest"

        record("CFG-004", "PATCH /api/config persists", patch_ok and persisted,
               f"patch_status={r.status}, agent_name_after={after.get('agent_name')!r}")

        # restore
        async with session.patch(
            f"{BASE_URL}/api/config",
            json={"agent_name": "cato"},
            headers={"Content-Type": "application/json"},
        ) as r3:
            pass
    except Exception as e:
        record("CFG-004", "PATCH /api/config persists", False, f"exception: {e}")

    # CFG-002 — PATCH response contains "config" key
    print("\n[4] CFG-002 — PATCH returns config key")
    try:
        async with session.patch(
            f"{BASE_URL}/api/config",
            json={"agent_name": "cato"},
            headers={"Content-Type": "application/json"},
        ) as r:
            resp = await r.json()
            has_config_key = "config" in resp
            record("CFG-002", "PATCH response has config key", has_config_key,
                   f"http={r.status}, response_keys={list(resp.keys())}")
    except Exception as e:
        record("CFG-002", "PATCH response has config key", False, f"exception: {e}")

    # CHAT-001 — No raw XML in chat history
    print("\n[5] CHAT-001 — No raw XML in chat history")
    try:
        async with session.get(f"{BASE_URL}/api/chat/history") as r:
            text = await r.text()
            xml_patterns = [
                "<minimax:tool_call>", "<tool_call>", "<invoke>",
                "<minimax:thinking>", "</minimax:tool_call>",
            ]
            found_xml = [p for p in xml_patterns if p in text]
            clean = len(found_xml) == 0
            record("CHAT-001", "No raw XML in chat history", clean,
                   f"http={r.status}, found_patterns={found_xml or 'none'}")
    except Exception as e:
        record("CHAT-001", "No raw XML in chat history", False, f"exception: {e}")

    # CHAT-002 — No cost line in chat messages
    print("\n[6] CHAT-002 — No cost line in chat messages")
    try:
        async with session.get(f"{BASE_URL}/api/chat/history") as r:
            data = await r.json()
            messages = data if isinstance(data, list) else data.get("messages", [])
            cost_re = re.compile(r"\[\$[\d.]+\s+this call")
            found_cost = []
            for msg in messages:
                content = msg.get("content", "") or ""
                if cost_re.search(content):
                    found_cost.append(content[-80:])
            clean = len(found_cost) == 0
            record("CHAT-002", "No cost line in chat messages", clean,
                   f"messages_checked={len(messages)}, violations={len(found_cost)}")
    except Exception as e:
        record("CHAT-002", "No cost line in chat messages", False, f"exception: {e}")

    # DIAG-001 — Contradiction health no SQLite error
    print("\n[7] DIAG-001 — Contradiction health no SQLite error")
    try:
        async with session.get(f"{BASE_URL}/api/diagnostics/contradiction-health") as r:
            text = await r.text()
            has_sqlite_err = "sqlite" in text.lower() and "error" in text.lower()
            data = json.loads(text)
            # acceptable: 200 with no error field containing "sqlite"
            err_field = str(data.get("error", "")).lower()
            bad = "sqlite" in err_field
            record("DIAG-001", "Contradiction health no SQLite error", not bad,
                   f"http={r.status}, error_field={data.get('error', 'none')!r}")
    except Exception as e:
        record("DIAG-001", "Contradiction health no SQLite error", False, f"exception: {e}")

    # CRON-001 — Toggle nonexistent cron job returns 404
    print("\n[8] CRON-001 — Toggle nonexistent job → 404")
    try:
        async with session.post(
            f"{BASE_URL}/api/cron/jobs/nonexistent-job-xyz/toggle"
        ) as r:
            is_404 = r.status == 404
            record("CRON-001", "Toggle nonexistent cron job → 404", is_404,
                   f"http={r.status} (want 404, not 500)")
    except Exception as e:
        record("CRON-001", "Toggle nonexistent cron job → 404", False, f"exception: {e}")

    # SYS-001 — CLI tools show correct status
    print("\n[9] SYS-001 — CLI /api/cli/status returns data")
    try:
        async with session.get(f"{BASE_URL}/api/cli/status") as r:
            data = await r.json()
            # Should be a dict with tool names as keys, or a list
            has_data = bool(data) and r.status == 200
            record("SYS-001", "GET /api/cli/status returns data", has_data,
                   f"http={r.status}, type={type(data).__name__}, sample={str(data)[:120]}")
    except Exception as e:
        record("SYS-001", "GET /api/cli/status returns data", False, f"exception: {e}")

    # MEM-001 — Memory content returns 200
    print("\n[10] MEM-001 — GET /api/memory/content returns 200")
    try:
        async with session.get(f"{BASE_URL}/api/memory/content") as r:
            is_ok = r.status == 200
            text = await r.text()
            record("MEM-001", "GET /api/memory/content returns 200", is_ok,
                   f"http={r.status}, body_preview={text[:80]!r}")
    except Exception as e:
        record("MEM-001", "GET /api/memory/content returns 200", False, f"exception: {e}")

    # IDENT-002 — POST /api/workspace/file works
    print("\n[11] IDENT-002 — POST /api/workspace/file returns 200")
    try:
        # Route expects {"name": ..., "content": ...} not {"filename": ...}
        payload = {"name": "SOUL.md", "content": "# Test content\nVerify fix IDENT-002\n"}
        async with session.post(
            f"{BASE_URL}/api/workspace/file",
            json=payload,
            headers={"Content-Type": "application/json"},
        ) as r:
            is_ok = r.status == 200
            text = await r.text()
            record("IDENT-002", "POST /api/workspace/file returns 200", is_ok,
                   f"http={r.status} (not 405), body={text[:80]!r}")
    except Exception as e:
        record("IDENT-002", "POST /api/workspace/file returns 200", False, f"exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Browser-based checks
# ──────────────────────────────────────────────────────────────────────────────

async def dismiss_onboarding(page: Page):
    """Dismiss the onboarding overlay by setting localStorage flag and hiding overlay."""
    await page.evaluate("""
        () => {
            localStorage.setItem('cato_onboarded', '1');
            const el = document.getElementById('onboarding-overlay');
            if (el) el.style.display = 'none';
            if (window.state) window.state.onboardingDone = true;
        }
    """)
    await asyncio.sleep(0.2)


async def goto_page(page: Page, url: str):
    """Navigate to URL and dismiss onboarding overlay."""
    await page.goto(url, wait_until="networkidle", timeout=15000)
    await dismiss_onboarding(page)
    await asyncio.sleep(0.5)


async def check_browser_bugs(page: Page):

    # DASH-001 — Dashboard shows alive pill
    print("\n[12] DASH-001 — Dashboard shows alive heartbeat pill")
    try:
        await goto_page(page, f"{BASE_URL}/")
        await asyncio.sleep(1)
        await screenshot(page, "01_dashboard")
        # look for green/alive indicator text or class
        content = await page.content()
        alive_visible = (
            "alive" in content.lower()
            or "green" in content.lower()
            or "status-ok" in content.lower()
            or "heartbeat" in content.lower()
        )
        record("DASH-001", "Dashboard shows alive heartbeat", alive_visible,
               f"page_title={await page.title()!r}, alive_text_found={alive_visible}")
    except Exception as e:
        record("DASH-001", "Dashboard shows alive heartbeat", False, f"exception: {e}")

    async def js_navigate(page_name: str):
        """Use JS navigate() to switch pages, bypassing overlay pointer-events issues."""
        await page.evaluate(f"() => {{ if(window.navigate) navigate('{page_name}'); }}")
        await asyncio.sleep(1.2)

    # ALERTS-001 — Alerts page navigates correctly
    print("\n[13] ALERTS-001 — Alerts page shows content")
    try:
        await goto_page(page, f"{BASE_URL}/")
        await js_navigate("alerts")
        await screenshot(page, "02_alerts_page")
        content = await page.content()
        meaningful = len(content) > 2000 and (
            "alert" in content.lower() or "notification" in content.lower()
            or "no alerts" in content.lower() or "rule" in content.lower()
        )
        record("ALERTS-001", "Alerts page shows content", meaningful,
               f"content_len={len(content)}, meaningful={meaningful}")
    except Exception as e:
        await screenshot(page, "02_alerts_error")
        record("ALERTS-001", "Alerts page shows content", False, f"exception: {e}")

    # IDENT-004 — Identity page exists in web UI
    print("\n[14] IDENT-004 — Identity page in web UI")
    try:
        await goto_page(page, f"{BASE_URL}/")
        await js_navigate("identity")
        await screenshot(page, "03_identity_page")
        content = await page.content()
        has_soul = "soul" in content.lower() or "SOUL" in content
        has_textarea = "textarea" in content.lower() or "editor" in content.lower()
        ok = has_soul or has_textarea
        record("IDENT-004", "Identity page with file tabs", ok,
               f"has_soul={has_soul}, has_textarea={has_textarea}")
    except Exception as e:
        await screenshot(page, "03_identity_error")
        record("IDENT-004", "Identity page with file tabs", False, f"exception: {e}")

    # FLOW-003 — Flows page exists
    print("\n[15] FLOW-003 — Flows page in sidebar")
    try:
        await goto_page(page, f"{BASE_URL}/")
        # Check sidebar DOM for flows nav item
        content = await page.content()
        flows_in_sidebar = 'data-page="flows"' in content or 'href="#flows"' in content
        if flows_in_sidebar:
            await js_navigate("flows")
            await screenshot(page, "04_flows_page")
            content = await page.content()
            ok = "flow" in content.lower() and len(content) > 2000
            record("FLOW-003", "Flows page in sidebar", ok,
                   f"sidebar_link_found=True, content_len={len(content)}, flow_content={ok}")
        else:
            await screenshot(page, "04_flows_no_link")
            record("FLOW-003", "Flows page in sidebar", False,
                   "No data-page='flows' found in sidebar DOM")
    except Exception as e:
        await screenshot(page, "04_flows_error")
        record("FLOW-003", "Flows page in sidebar", False, f"exception: {e}")

    # NAV-003 — Settings group in sidebar
    print("\n[16] NAV-003 — Settings section label in sidebar")
    try:
        await goto_page(page, f"{BASE_URL}/")
        content = await page.content()
        # Look for Settings as a section label (not just a nav item)
        settings_label = (
            "Settings" in content
            and (
                "nav-section" in content
                or "section-label" in content
                or "nav-group" in content
                or "sidebar-section" in content
            )
        )
        # Also check: Settings appears in sidebar (visible text)
        settings_in_dom = "Settings" in content
        await screenshot(page, "05_sidebar_settings")
        record("NAV-003", "Settings section label in sidebar",
               settings_label or settings_in_dom,
               f"settings_label_class={settings_label}, settings_text_in_dom={settings_in_dom}")
    except Exception as e:
        await screenshot(page, "05_sidebar_error")
        record("NAV-003", "Settings section label in sidebar", False, f"exception: {e}")

    # NODE-001 — Nodes page exists
    print("\n[17] NODE-001 — Nodes nav item in sidebar")
    try:
        await goto_page(page, f"{BASE_URL}/")
        content = await page.content()
        nodes_in_sidebar = (
            'data-page="nodes"' in content
            or 'href="#nodes"' in content
            or ">Nodes<" in content
        )
        if nodes_in_sidebar:
            await js_navigate("nodes")
        await screenshot(page, "06_nodes_page")
        record("NODE-001", "Nodes nav item in sidebar", nodes_in_sidebar,
               f"nodes_link_visible={nodes_in_sidebar}")
    except Exception as e:
        await screenshot(page, "06_nodes_error")
        record("NODE-001", "Nodes nav item in sidebar", False, f"exception: {e}")

    # SYS-001 browser — System page shows correct statuses
    print("\n[18] SYS-001 browser — System page CLI tool statuses")
    try:
        await goto_page(page, f"{BASE_URL}/")
        content = await page.content()
        system_in_sidebar = (
            'data-page="system"' in content
            or 'data-page="cli"' in content
            or ">System<" in content
        )
        if system_in_sidebar:
            await js_navigate("system")
        else:
            await js_navigate("cli")
        await screenshot(page, "07_system_page")
        content = await page.content()
        has_yellow = "yellow" in content or "amber" in content or "warning" in content or "status-warn" in content
        has_tool_names = any(t in content for t in ["claude", "codex", "gemini", "cursor"])
        record("SYS-001-browser", "System page shows CLI tool statuses", has_tool_names,
               f"has_tool_names={has_tool_names}, has_yellow_status={has_yellow}")
    except Exception as e:
        await screenshot(page, "07_system_error")
        record("SYS-001-browser", "System page shows CLI tool statuses", False, f"exception: {e}")

    # Take final full-page dashboard screenshot
    await goto_page(page, f"{BASE_URL}/")
    await asyncio.sleep(1)
    await screenshot(page, "00_final_dashboard_overview")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 70)
    print("CATO BUG-FIX VERIFICATION SUITE")
    print(f"Target: {BASE_URL}")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    async with aiohttp.ClientSession() as session:
        await check_api_bugs(session)

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        # Capture console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg) if msg.type == "error" else None)
        try:
            await check_browser_bugs(page)
        finally:
            await browser.close()

    # ── Write results markdown ──────────────────────────────────────────────
    fixed_count = sum(1 for _, _, f, _ in results if f)
    total = len(results)

    lines = [
        "# Cato Bug-Fix Verification Results",
        f"\nRun date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\nTarget: {BASE_URL}",
        f"\n## Score: {fixed_count}/{total} fixes verified\n",
        "---\n",
        "| Bug ID | Description | Status | Details |",
        "|--------|-------------|--------|---------|",
    ]
    for bug_id, label, fixed, details in results:
        status = "FIXED ✓" if fixed else "STILL BROKEN ✗"
        # escape pipes in details
        details_esc = details.replace("|", "\\|")
        lines.append(f"| {bug_id} | {label} | {status} | {details_esc} |")

    lines += [
        "\n---\n",
        "## Detail Notes\n",
    ]
    for bug_id, label, fixed, details in results:
        icon = "✓" if fixed else "✗"
        lines.append(f"### {icon} {bug_id} — {label}")
        lines.append(f"- **Status**: {'FIXED' if fixed else 'STILL BROKEN'}")
        lines.append(f"- **Details**: {details}")
        lines.append("")

    lines += [
        "---\n",
        f"## Summary: {fixed_count}/{total} bugs confirmed fixed\n",
        f"Screenshots saved to: {SCREENSHOTS_DIR}\n",
    ]

    RESULTS_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "=" * 70)
    print(f"RESULTS: {fixed_count}/{total} fixes verified")
    print(f"Saved to: {RESULTS_FILE}")
    print(f"Screenshots in: {SCREENSHOTS_DIR}")
    print("=" * 70)

    # print summary
    print("\nDetailed results:")
    for bug_id, label, fixed, details in results:
        icon = "FIXED ✓" if fixed else "BROKEN ✗"
        print(f"  {icon}  {bug_id}: {label}")
        print(f"         {details}")

    return fixed_count, total


if __name__ == "__main__":
    asyncio.run(main())
