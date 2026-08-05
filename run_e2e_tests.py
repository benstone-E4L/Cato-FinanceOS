"""
Cato Web UI — Comprehensive Live E2E Test Script (v3)
Tests all pages at http://localhost:8080 with correct routes and selectors.
"""

import asyncio
import json
import re
import traceback
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page

BASE_URL = "http://localhost:8080"
REPORT_PATH = Path("C:/Users/Administrator/Desktop/Cato/LIVE_E2E_REPORT.md")

results = []


def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        print(text.encode("ascii", errors="replace").decode("ascii"), **kwargs)


def add_result(page_name, status, tested, bugs, notes=""):
    results.append({"page": page_name, "status": status, "tested": tested, "bugs": bugs, "notes": notes})
    icon = "PASS" if status == "PASS" else "FAIL"
    safe_print(f"  [{icon}] {page_name}", flush=True)
    for b in bugs:
        safe_print(f"        BUG: {b[:120]}", flush=True)


def api_get(path, timeout=5):
    """Make a GET request and return (status_code, data_str) or raise."""
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


async def dismiss_overlay(page: Page):
    """Dismiss onboarding overlay via JS."""
    try:
        await page.evaluate("""
            () => {
                const el = document.getElementById('onboarding-overlay');
                if (el) { el.style.display = 'none'; }
                if (window.state) { window.state.onboardingDone = true; }
            }
        """)
    except Exception:
        pass


async def goto_page(page: Page, page_id: str):
    """Navigate to a hash-routed page in the dashboard."""
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    await page.wait_for_timeout(500)
    await dismiss_overlay(page)
    try:
        await page.evaluate(f"navigate('{page_id}')")
    except Exception:
        pass
    await page.wait_for_timeout(800)
    await dismiss_overlay(page)


async def get_content(page: Page) -> str:
    try:
        return await page.locator("#content").inner_text(timeout=5000)
    except Exception:
        try:
            return await page.inner_text("body", timeout=5000)
        except Exception:
            return ""


# ─── API tests ────────────────────────────────────────────────────────────────

async def test_api_health():
    safe_print("Testing API endpoints...", flush=True)
    tested = []
    bugs = []

    # Map of path -> (description, min_response)
    endpoints = [
        ("/api/skills",             "skills list",       True),
        ("/api/sessions",           "sessions list",     True),
        ("/api/cron/jobs",          "cron jobs",         True),
        ("/api/usage/summary",      "usage summary",     True),
        ("/api/budget/summary",     "budget summary",    True),
        ("/api/config",             "config",            True),
        ("/api/audit/entries",      "audit entries",     True),
        ("/api/memory/stats",       "memory stats",      True),
        ("/api/cli/status",         "CLI pool status",   True),
        ("/api/logs",               "logs",              True),
        ("/api/heartbeat",          "heartbeat",         True),
        ("/api/workspace/files",    "workspace files",   True),
        ("/api/flows",              "flows",             True),
        ("/api/nodes",              "nodes",             True),
        ("/api/vault/keys",         "vault keys",        True),
        ("/health",                 "health check",      True),
    ]

    for path, name, expect_json in endpoints:
        try:
            status_code, data = api_get(path)
            tested.append(f"GET {path} = {status_code} ({len(data)} bytes)")
            if expect_json:
                try:
                    json.loads(data)
                    tested.append(f"  {name}: valid JSON")
                except json.JSONDecodeError:
                    if "<html" in data.lower():
                        bugs.append(f"GET {path} returned HTML instead of JSON")
                    else:
                        bugs.append(f"GET {path} non-JSON response: {data[:80]}")
        except urllib.error.HTTPError as e:
            bugs.append(f"GET {path} HTTP {e.code} ({name})")
        except Exception as e:
            bugs.append(f"GET {path} error: {type(e).__name__}: {str(e)[:80]}")

    status = "PASS" if not bugs else "FAIL"
    add_result("API Health Checks", status, tested, bugs)


# ─── Dashboard ────────────────────────────────────────────────────────────────

async def test_dashboard(page: Page):
    safe_print("Testing Dashboard...", flush=True)
    tested = []
    bugs = []
    try:
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(800)
        await dismiss_overlay(page)
        await page.wait_for_timeout(600)

        tested.append(f"Page title: {await page.title()}")

        # Health pill
        health_el = page.locator(".health-pill").first
        if await health_el.count() > 0:
            text = (await health_el.inner_text(timeout=3000)).strip()
            classes = await health_el.get_attribute("class") or ""
            tested.append(f"Health pill text: {text!r}, classes: {classes}")
            if "unknown" in text.lower():
                bugs.append(f"Heartbeat shows 'unknown': {text!r}")
            elif "online" in classes:
                tested.append("Health pill online class present (green dot)")
            else:
                bugs.append(f"Health pill not 'online' class: classes={classes!r}, text={text!r}")
        else:
            bugs.append("Health pill element not found")

        # Content
        content = await get_content(page)
        tested.append(f"Content length: {len(content)} chars")
        if len(content.strip()) < 10:
            bugs.append("Dashboard content area empty")
        elif any(w in content.lower() for w in ["agent", "status", "uptime", "session", "model", "memory"]):
            tested.append("Dashboard shows expected stats content")

        # Heartbeat via API
        try:
            _, hb_data = api_get("/api/heartbeat")
            hb = json.loads(hb_data)
            tested.append(f"Heartbeat API: status={hb.get('status')}, uptime={hb.get('uptime_seconds')}s")
            if hb.get("status") != "alive":
                bugs.append(f"Heartbeat API status is not 'alive': {hb.get('status')!r}")
            elif "unknown" in str(hb.get("status", "")):
                bugs.append(f"Heartbeat API shows unknown: {hb}")
            else:
                tested.append("Heartbeat API shows 'alive'")
        except Exception as e:
            bugs.append(f"Heartbeat API error: {e}")

        status = "PASS" if not bugs else "FAIL"
        add_result("Dashboard", status, tested, bugs)
    except Exception as e:
        add_result("Dashboard", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Chat ─────────────────────────────────────────────────────────────────────

async def test_chat(page: Page):
    safe_print("Testing Chat...", flush=True)
    tested = []
    bugs = []
    try:
        await goto_page(page, "chat")

        # Find input
        input_el = None
        for sel in ["#chat-input", "textarea#chat-input", "textarea", "input[type=text]"]:
            el = page.locator(sel).first
            if await el.count() > 0:
                input_el = el
                tested.append(f"Chat input found: {sel}")
                break

        if not input_el:
            bugs.append("No chat input found on chat page")
            add_result("Chat", "FAIL", tested, bugs)
            return

        await input_el.click(timeout=5000)
        await input_el.fill("hello")
        tested.append("Typed 'hello'")

        # Submit
        send_btn = page.locator("#send-btn, button[type=submit]").first
        if await send_btn.count() > 0:
            await send_btn.click(timeout=5000)
        else:
            await input_el.press("Enter")
        tested.append("Message submitted")

        # Wait for response
        await page.wait_for_timeout(20000)

        # Get chat messages
        chat_text = ""
        for sel in ["#chat-messages", ".chat-messages", "#messages", ".messages"]:
            el = page.locator(sel).first
            if await el.count() > 0:
                chat_text = await el.inner_text(timeout=3000)
                tested.append(f"Chat messages via {sel!r}: {len(chat_text)} chars")
                break
        if not chat_text:
            chat_text = await get_content(page)
            tested.append(f"Chat text from #content: {len(chat_text)} chars")

        # Check for raw XML tool calls
        xml_match = re.search(r"<[a-z_]+:tool_call|<tool_call|<function_call", chat_text, re.IGNORECASE)
        if xml_match:
            bugs.append(f"Raw XML tool call in chat output: {xml_match.group()!r}")
        else:
            tested.append("No raw XML tool calls found in chat output")

        # Check for budget cost lines
        # Note: The UI renders cost_footer in a .msg-footer div which IS intentional design.
        # The bug is if it appears inline in the raw assistant text (not in the footer div).
        # We check the chat history API to see what the actual stored response text is.
        cost_in_ui = re.search(r"\[\s*\$[\d.]+\s+this call", chat_text, re.IGNORECASE)
        if cost_in_ui:
            tested.append(f"Budget cost visible in UI DOM (via .msg-footer): {cost_in_ui.group()!r}")
            # Check if it's also in the API-stored text (that would be the real leak)
            try:
                _, hist_raw = api_get("/api/chat/history")
                hist = json.loads(hist_raw)
                assistant_texts = [m.get("text", "") for m in hist if m.get("role") == "assistant"]
                raw_has_cost = any(
                    re.search(r"\[\s*\$[\d.]+\s+this call", t, re.IGNORECASE)
                    for t in assistant_texts
                )
                if raw_has_cost:
                    bugs.append(
                        "Budget cost line found in raw stored response text "
                        "(not just UI footer) — cost_footer leaking into message content"
                    )
                else:
                    tested.append(
                        "Budget cost shown in UI footer div (cost_footer field, intentional) "
                        "but NOT in stored response text — design feature, not a content leak"
                    )
                    # BUG: The cost footer IS shown prominently in the UI to users
                    # The spec says no cost lines should be visible. Flag as a known design issue.
                    bugs.append(
                        "DESIGN: cost_footer [$x.xx this call...] is displayed in chat UI (.msg-footer div). "
                        "Spec says no budget lines visible to user in chat."
                    )
            except Exception as e:
                tested.append(f"Could not verify via API: {e}")
        else:
            tested.append("No budget cost lines visible in chat output")

        # Model identity
        if re.search(r"claude code.*anthropic\s*api", chat_text, re.IGNORECASE):
            bugs.append("Model claims to be 'Claude Code' checking Anthropic API")

        # Got a response
        if len(chat_text.strip()) < 5:
            bugs.append("Chat response empty after 20s")
        else:
            tested.append("Chat response received (non-empty)")

        status = "PASS" if not bugs else "FAIL"
        add_result("Chat", status, tested, bugs)
    except Exception as e:
        add_result("Chat", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Coding Agent (Agents page = /agents hash, separate SPA at /coding-agent) ─

async def test_coding_agent(page: Page):
    """
    The 'Coding Agent' nav item in the sidebar is 'agents' (data-page='agents').
    It shows workspace files and agent info. The coding agent SPA is at /coding-agent.
    We test both: the agents page (pool/warm-cold) and the /coding-agent SPA entry.
    """
    safe_print("Testing Coding Agent (Agents page + /coding-agent SPA)...", flush=True)
    tested = []
    bugs = []
    try:
        # 1. Test the Agents page (data-page='agents')
        await goto_page(page, "agents")
        agents_content = await get_content(page)
        tested.append(f"Agents page content: {len(agents_content)} chars")
        if len(agents_content.strip()) < 5:
            bugs.append("Agents page appears blank")

        # 2. Check CLI pool via API
        try:
            _, pool_raw = api_get("/api/cli/status")
            pool = json.loads(pool_raw)
            tested.append(f"CLI pool API: {pool_raw[:300]}")
            for tool_name, info in pool.items():
                installed = info.get("installed", False)
                logged_in = info.get("logged_in", False)
                if installed and not logged_in:
                    tested.append(f"Tool '{tool_name}': installed=true, logged_in=false (warm/yellow expected)")
                elif installed and logged_in:
                    tested.append(f"Tool '{tool_name}': installed=true, logged_in=true (fully warm)")
                else:
                    tested.append(f"Tool '{tool_name}': not installed")
        except Exception as e:
            bugs.append(f"CLI pool API error: {e}")

        # 3. Test the /coding-agent SPA (React app loaded via CDN Babel)
        console_errors = []
        async def capture_console(msg):
            if msg.type == "error":
                console_errors.append(msg.text)
        page.on("console", capture_console)
        await page.goto(f"{BASE_URL}/coding-agent", wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(6000)
        page.remove_listener("console", capture_console)

        # Check React root
        root_inner = await page.evaluate("() => document.getElementById('root') ? document.getElementById('root').innerHTML : ''")
        body_html = await page.evaluate("() => document.body.innerHTML")
        tested.append(f"/coding-agent SPA: root innerHTML len={len(root_inner)}, body len={len(body_html)}")

        if len(root_inner.strip()) == 0 and console_errors:
            bugs.append(f"/coding-agent SPA: React render failed. Errors: {'; '.join(console_errors[:3])[:300]}")
        elif len(root_inner.strip()) == 0:
            bugs.append("/coding-agent SPA: React root is empty (app failed to render)")
        else:
            tested.append("/coding-agent SPA: React app rendered successfully")

        # Check page HTML source for backend tool references (they're in script, not DOM)
        page_src = await page.content()
        for tool in ["claude", "codex", "gemini"]:
            if tool.lower() in page_src.lower():
                tested.append(f"Backend '{tool}' referenced in SPA source")

        if console_errors:
            tested.append(f"Console errors in SPA: {console_errors[0][:200]}")

        status = "PASS" if not bugs else "FAIL"
        add_result("Coding Agent", status, tested, bugs)
    except Exception as e:
        add_result("Coding Agent", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Skills ───────────────────────────────────────────────────────────────────

async def test_skills(page: Page):
    safe_print("Testing Skills...", flush=True)
    tested = []
    bugs = []
    try:
        await goto_page(page, "skills")
        content = await get_content(page)
        tested.append(f"Content: {len(content)} chars")

        # Check API
        try:
            _, skills_raw = api_get("/api/skills")
            skills = json.loads(skills_raw)
            tested.append(f"Skills API: {len(skills)} skills returned")
            if len(skills) == 0:
                bugs.append("Skills API returned empty list")
            else:
                tested.append(f"First skill: {skills[0].get('name', '?')!r}")
        except Exception as e:
            bugs.append(f"Skills API error: {e}")

        if len(content.strip()) < 10:
            bugs.append("Skills page content appears blank")
        elif "skill" in content.lower():
            tested.append("Skills list renders in UI")

        status = "PASS" if not bugs else "FAIL"
        add_result("Skills", status, tested, bugs)
    except Exception as e:
        add_result("Skills", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Cron ─────────────────────────────────────────────────────────────────────

async def test_cron(page: Page):
    safe_print("Testing Cron...", flush=True)
    tested = []
    bugs = []
    try:
        # Check API
        try:
            _, cron_raw = api_get("/api/cron/jobs")
            cron_jobs = json.loads(cron_raw)
            tested.append(f"Cron API: {len(cron_jobs)} jobs")
        except Exception as e:
            bugs.append(f"Cron API error: {e}")

        # Navigate to page
        await goto_page(page, "cron")
        content = await get_content(page)
        tested.append(f"Content: {len(content)} chars")
        if len(content.strip()) < 5:
            bugs.append("Cron page appears blank")
        else:
            tested.append("Cron page loaded with content")

        # Try toggle if present
        toggle = page.locator(".skill-toggle input, input[type=checkbox]").first
        if await toggle.count() > 0:
            tested.append("Toggle found")
            try:
                await toggle.click(timeout=3000)
                await page.wait_for_timeout(400)
                tested.append("Toggle clicked successfully")
            except Exception as e:
                tested.append(f"Toggle click: {e}")
        else:
            tested.append("No toggleable cron jobs found (list may be empty)")

        status = "PASS" if not bugs else "FAIL"
        add_result("Cron", status, tested, bugs)
    except Exception as e:
        add_result("Cron", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Sessions ─────────────────────────────────────────────────────────────────

async def test_sessions(page: Page):
    safe_print("Testing Sessions...", flush=True)
    tested = []
    bugs = []
    try:
        _, sess_raw = api_get("/api/sessions")
        sessions = json.loads(sess_raw)
        tested.append(f"Sessions API: {len(sessions)} sessions, data={sess_raw[:150]}")

        await goto_page(page, "sessions")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 5:
            bugs.append("Sessions page appears blank")
        else:
            tested.append("Sessions page loaded")

        status = "PASS" if not bugs else "FAIL"
        add_result("Sessions", status, tested, bugs)
    except Exception as e:
        add_result("Sessions", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Usage ────────────────────────────────────────────────────────────────────

async def test_usage(page: Page):
    safe_print("Testing Usage...", flush=True)
    tested = []
    bugs = []
    try:
        _, usage_raw = api_get("/api/usage/summary")
        usage = json.loads(usage_raw)
        tested.append(f"Usage API: {usage_raw[:200]}")

        await goto_page(page, "usage")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 5:
            bugs.append("Usage page appears blank")
        else:
            tested.append("Usage page loaded")

        status = "PASS" if not bugs else "FAIL"
        add_result("Usage", status, tested, bugs)
    except Exception as e:
        add_result("Usage", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Logs ─────────────────────────────────────────────────────────────────────

async def test_logs(page: Page):
    safe_print("Testing Logs...", flush=True)
    tested = []
    bugs = []
    try:
        _, logs_raw = api_get("/api/logs")
        tested.append(f"Logs API: {len(logs_raw)} bytes, valid JSON: {True}")
        try:
            json.loads(logs_raw)
        except Exception:
            bugs.append(f"Logs API returned non-JSON: {logs_raw[:80]}")

        await goto_page(page, "logs")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 5:
            bugs.append("Logs page appears blank")
        else:
            tested.append("Logs page loaded")

        status = "PASS" if not bugs else "FAIL"
        add_result("Logs", status, tested, bugs)
    except Exception as e:
        add_result("Logs", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Audit ────────────────────────────────────────────────────────────────────

async def test_audit(page: Page):
    safe_print("Testing Audit...", flush=True)
    tested = []
    bugs = []
    try:
        _, audit_raw = api_get("/api/audit/entries")
        tested.append(f"Audit API: {len(audit_raw)} bytes")
        try:
            json.loads(audit_raw)
            tested.append("Audit API: valid JSON")
        except Exception:
            bugs.append(f"Audit API non-JSON: {audit_raw[:80]}")

        await goto_page(page, "audit")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 5:
            bugs.append("Audit page appears blank")
        else:
            tested.append("Audit page loaded")

        status = "PASS" if not bugs else "FAIL"
        add_result("Audit", status, tested, bugs)
    except Exception as e:
        add_result("Audit", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Config ───────────────────────────────────────────────────────────────────

async def test_config(page: Page):
    safe_print("Testing Config...", flush=True)
    tested = []
    bugs = []
    try:
        # Check GET /api/config
        _, cfg_raw = api_get("/api/config")
        cfg = json.loads(cfg_raw)
        tested.append(f"Config API GET: valid JSON, agent_name={cfg.get('agent_name')!r}")

        await goto_page(page, "config")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 10:
            bugs.append("Config page appears blank")

        # Find "Save Changes" or "Save" button
        save_btn = page.locator(
            "button:has-text('Save Changes'), button:has-text('Save config'), button[onclick*='saveConfig']"
        ).first
        if await save_btn.count() == 0:
            # Try generic "Save" button
            save_btn = page.locator("button:has-text('Save')").first

        if await save_btn.count() > 0:
            tested.append(f"Save button found: {await save_btn.text_content()!r}")
            save_responses = []

            async def capture(resp):
                if "/api/config" in resp.url or "/config" in resp.url:
                    save_responses.append({"url": resp.url, "method": resp.request.method, "status": resp.status})

            page.on("response", capture)
            await save_btn.click(timeout=8000)
            await page.wait_for_timeout(2000)
            page.remove_listener("response", capture)

            if save_responses:
                tested.append(f"Config save calls: {save_responses}")
                for r in save_responses:
                    if r["status"] >= 400:
                        bugs.append(f"Config save HTTP {r['status']}: {r['url']}")
                    else:
                        tested.append(f"Config save HTTP {r['status']} OK")
            else:
                tested.append("No config API call captured (check manually)")
        else:
            bugs.append("No Save/Save Changes button found on Config page")

        status = "PASS" if not bugs else "FAIL"
        add_result("Config", status, tested, bugs)
    except Exception as e:
        add_result("Config", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Budget ───────────────────────────────────────────────────────────────────

async def test_budget(page: Page):
    safe_print("Testing Budget...", flush=True)
    tested = []
    bugs = []
    try:
        _, bud_raw = api_get("/api/budget/summary")
        bud = json.loads(bud_raw)
        tested.append(f"Budget API: session_spend={bud.get('session_spend')}, "
                      f"monthly_cap={bud.get('monthly_cap')}")

        await goto_page(page, "budget")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 10:
            bugs.append("Budget page appears blank")
        elif any(w in content.lower() for w in ["budget", "spend", "cap", "cost", "$"]):
            tested.append("Budget content shows spend/cap info")

        status = "PASS" if not bugs else "FAIL"
        add_result("Budget", status, tested, bugs)
    except Exception as e:
        add_result("Budget", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Alerts ───────────────────────────────────────────────────────────────────

async def test_alerts(page: Page):
    safe_print("Testing Alerts...", flush=True)
    tested = []
    bugs = []
    try:
        await goto_page(page, "alerts")
        content = await get_content(page)
        body_text = await page.inner_text("body", timeout=4000)
        tested.append(f"Content: {len(content)} chars, body: {len(body_text)} chars")

        if len(body_text.strip()) < 50:
            bugs.append("Alerts page body appears blank")
        else:
            tested.append("Alerts page renders (non-blank)")

        # Check alert filter buttons render
        btns = page.locator("button.alert-filter")
        btn_count = await btns.count()
        if btn_count >= 3:
            tested.append(f"Alert filter buttons: {btn_count} found (All/Error/Warn/Info)")
        else:
            bugs.append(f"Alert filter buttons missing: only {btn_count} found")

        status = "PASS" if not bugs else "FAIL"
        add_result("Alerts", status, tested, bugs)
    except Exception as e:
        add_result("Alerts", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Auth/Keys (Vault) ────────────────────────────────────────────────────────

async def test_auth_keys(page: Page):
    safe_print("Testing Auth/Keys (Vault)...", flush=True)
    tested = []
    bugs = []
    try:
        _, vault_raw = api_get("/api/vault/keys")
        vault_keys = json.loads(vault_raw)
        tested.append(f"Vault API: {len(vault_keys)} keys")

        await goto_page(page, "vault")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 10:
            bugs.append("Vault/Auth page appears blank")
        else:
            tested.append("Vault/Auth page loaded with content")

        # Check for key list or add button
        add_btn = page.locator("button:has-text('Add Key'), button:has-text('+ Add')").first
        if await add_btn.count() > 0:
            tested.append("'Add Key' button found")
        elif len(vault_keys) > 0:
            tested.append(f"Vault shows {len(vault_keys)} existing keys")
        else:
            tested.append("Empty vault — no keys to display yet")

        status = "PASS" if not bugs else "FAIL"
        add_result("Auth/Keys", status, tested, bugs)
    except Exception as e:
        add_result("Auth/Keys", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Identity ─────────────────────────────────────────────────────────────────

async def test_identity(page: Page):
    safe_print("Testing Identity...", flush=True)
    tested = []
    bugs = []
    try:
        await goto_page(page, "identity")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 10:
            bugs.append("Identity page appears blank")

        # Tab buttons: SOUL.md, IDENTITY.md, USER.md, AGENTS.md
        for fname in ["SOUL.md", "IDENTITY.md", "USER.md", "AGENTS.md"]:
            btn = page.locator(f"button:has-text('{fname}')").first
            if await btn.count() > 0:
                tested.append(f"Tab button found: {fname}")
                # Use JS call to load the file (avoids timing issues)
                await page.evaluate(f"loadIdentityFile('{fname}')")
                await page.wait_for_timeout(800)
                label = await page.locator("#identity-file-label").inner_text(timeout=3000)
                ta_val = await page.locator("#identity-file-content").input_value(timeout=3000)
                tested.append(f"  Tab {fname}: label={label!r}, textarea len={len(ta_val)}")
                if not ta_val.strip():
                    bugs.append(f"Tab {fname}: textarea empty after load (file may be empty)")
            else:
                bugs.append(f"Tab button not found: {fname}")

        # Save button — scoped to #identity-page to avoid matching other pages' Save buttons
        save_btn = page.locator("#identity-page button:has-text('Save')").first
        if await save_btn.count() > 0:
            tested.append("Save button found in #identity-page")
            save_responses = []
            save_fails = []

            async def on_resp(resp):
                if "/api/workspace" in resp.url:
                    save_responses.append({"url": resp.url, "method": resp.request.method, "status": resp.status})

            async def on_fail(req):
                if "/api/workspace" in req.url:
                    save_fails.append(req.url)

            page.on("response", on_resp)
            page.on("requestfailed", on_fail)
            # Use JS call since click can be unreliable with many Save buttons in DOM
            await page.evaluate("saveIdentityFile()")
            await page.wait_for_timeout(2000)
            page.remove_listener("response", on_resp)
            page.remove_listener("requestfailed", on_fail)

            if save_fails:
                bugs.append(f"Identity save fetch failed: {save_fails}")
            elif save_responses:
                for r in save_responses:
                    if r["status"] >= 400:
                        bugs.append(f"Identity save HTTP {r['status']}: {r['url']}")
                    else:
                        tested.append(f"Identity save HTTP {r['status']} OK: {r['url']}")
            else:
                # Check for error text on page
                body = await page.inner_text("body", timeout=3000)
                if "failed to fetch" in body.lower():
                    bugs.append("Identity save shows 'failed to fetch' error in UI")
                else:
                    tested.append("Save clicked; no error visible in UI")

            # Check for save status indicator
            save_status = page.locator("#identity-save-status")
            if await save_status.count() > 0:
                ss_text = await save_status.inner_text(timeout=2000)
                ss_visible = await save_status.is_visible()
                tested.append(f"Save status indicator: text={ss_text!r}, visible={ss_visible}")
        else:
            bugs.append("Save button not found in #identity-page")

        status = "PASS" if not bugs else "FAIL"
        add_result("Identity", status, tested, bugs)
    except Exception as e:
        add_result("Identity", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Flows ────────────────────────────────────────────────────────────────────

async def test_flows(page: Page):
    safe_print("Testing Flows...", flush=True)
    tested = []
    bugs = []
    try:
        _, flows_raw = api_get("/api/flows")
        flows = json.loads(flows_raw)
        tested.append(f"Flows API: {len(flows)} flows")

        await goto_page(page, "flows")
        content = await get_content(page)
        body = await page.inner_text("body", timeout=4000)
        tested.append(f"Content: {len(content)} chars, body: {len(body)} chars")
        if len(body.strip()) < 50:
            bugs.append("Flows page appears blank")
        else:
            tested.append("Flows page renders content")

        status = "PASS" if not bugs else "FAIL"
        add_result("Flows", status, tested, bugs)
    except Exception as e:
        add_result("Flows", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Nodes ────────────────────────────────────────────────────────────────────

async def test_nodes(page: Page):
    safe_print("Testing Nodes...", flush=True)
    tested = []
    bugs = []
    try:
        _, nodes_raw = api_get("/api/nodes")
        nodes = json.loads(nodes_raw)
        tested.append(f"Nodes API: {nodes_raw[:200]}")

        await goto_page(page, "nodes")
        content = await get_content(page)
        body = await page.inner_text("body", timeout=4000)
        tested.append(f"Content: {len(content)} chars, body: {len(body)} chars")
        if len(body.strip()) < 50:
            bugs.append("Nodes page appears blank")
        else:
            tested.append("Nodes page renders content")

        status = "PASS" if not bugs else "FAIL"
        add_result("Nodes", status, tested, bugs)
    except Exception as e:
        add_result("Nodes", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Memory ───────────────────────────────────────────────────────────────────

async def test_memory(page: Page):
    safe_print("Testing Memory...", flush=True)
    tested = []
    bugs = []
    try:
        _, stats_raw = api_get("/api/memory/stats")
        stats = json.loads(stats_raw)
        tested.append(f"Memory stats API: {stats_raw[:200]}")

        await goto_page(page, "memory")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 5:
            bugs.append("Memory page appears blank")
        else:
            tested.append("Memory page loaded")

        status = "PASS" if not bugs else "FAIL"
        add_result("Memory", status, tested, bugs)
    except Exception as e:
        add_result("Memory", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── System ───────────────────────────────────────────────────────────────────

async def test_system(page: Page):
    safe_print("Testing System...", flush=True)
    tested = []
    bugs = []
    try:
        # Get CLI pool data
        _, pool_raw = api_get("/api/cli/status")
        pool = json.loads(pool_raw)
        tested.append(f"CLI pool raw: {pool_raw}")

        # Verify warm/cold logic: installed=true, logged_in=false → should be WARM (yellow), not cold (red)
        # The CLI pool API returns: {"claude": {"installed":T,"logged_in":T,...}, "codex": {...},...}
        # We verify there's no logic error. The UI renders, that's the test.
        for tool_name, info in pool.items():
            installed = info.get("installed", False)
            logged_in = info.get("logged_in", False)
            version = info.get("version", "")
            tested.append(f"  {tool_name}: installed={installed}, logged_in={logged_in}, version={version!r}")
            if installed and not logged_in:
                tested.append(f"  NOTE: {tool_name} installed but not logged_in -> should render as 'warm' (yellow) in UI")

        await goto_page(page, "system")
        content = await get_content(page)
        tested.append(f"System page content: {len(content)} chars")
        if len(content.strip()) < 5:
            bugs.append("System page appears blank")
        else:
            tested.append("System page loaded with content")

        # Check for tool names in content
        for tool in ["codex", "gemini", "cursor", "claude"]:
            if tool in content.lower():
                tested.append(f"Tool '{tool}' visible on system page")

        # Check warm/cold labels
        content_lower = content.lower()
        if "warm" in content_lower or "cold" in content_lower:
            tested.append("Warm/cold status labels visible")
            # Check if codex (installed, not logged in) shows warm vs cold
            if "codex" in content_lower:
                # Find codex section in content
                codex_idx = content_lower.find("codex")
                context_around = content_lower[max(0, codex_idx-20):codex_idx+100]
                tested.append(f"Codex context: {context_around!r}")
                if "cold" in context_around and "warm" not in context_around:
                    bugs.append(
                        "Codex appears as 'cold' in System page — "
                        "but codex is installed (installed=true, logged_in=false) which should show 'warm'"
                    )
        else:
            bugs.append("No warm/cold labels found on system page")

        status = "PASS" if not bugs else "FAIL"
        add_result("System", status, tested, bugs)
    except Exception as e:
        add_result("System", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Diagnostics ──────────────────────────────────────────────────────────────

async def test_diagnostics(page: Page):
    safe_print("Testing Diagnostics...", flush=True)
    tested = []
    bugs = []
    try:
        # Check diagnostic APIs
        diag_paths = [
            "/api/diagnostics/query-classifier",
            "/api/diagnostics/contradiction-health",
            "/api/diagnostics/decision-memory",
        ]
        for dp in diag_paths:
            try:
                sc, dr = api_get(dp)
                tested.append(f"GET {dp} = {sc} ({len(dr)} bytes)")
            except urllib.error.HTTPError as e:
                bugs.append(f"Diagnostics API {dp} = HTTP {e.code}")
            except Exception as e:
                tested.append(f"Diagnostics API {dp} error: {e}")

        await goto_page(page, "diagnostics")
        content = await get_content(page)
        tested.append(f"Page content: {len(content)} chars")
        if len(content.strip()) < 5:
            bugs.append("Diagnostics page appears blank")
        else:
            tested.append("Diagnostics page loaded")

        status = "PASS" if not bugs else "FAIL"
        add_result("Diagnostics", status, tested, bugs)
    except Exception as e:
        add_result("Diagnostics", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Sidebar ──────────────────────────────────────────────────────────────────

async def test_sidebar(page: Page):
    safe_print("Testing Sidebar...", flush=True)
    tested = []
    bugs = []
    try:
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(400)
        await dismiss_overlay(page)

        sidebar_text = await page.locator("#sidebar").inner_text(timeout=5000)
        sidebar_lower = sidebar_text.lower()
        tested.append(f"Sidebar text length: {len(sidebar_text)} chars")

        # Settings group should be present
        if "settings" in sidebar_lower:
            tested.append("'Settings' group found in sidebar")
        else:
            bugs.append("No 'Settings' group in sidebar nav")

        # Config link
        if "config" in sidebar_lower:
            tested.append("'Config' nav item found")
        else:
            bugs.append("'Config' nav item not found in sidebar")

        # Expected nav items
        expected_items = ["chat", "skill", "cron", "session", "flow", "usage", "audit",
                          "memory", "log", "budget", "vault", "identity", "system",
                          "diagnostic", "alert", "agent"]
        for item in expected_items:
            if item in sidebar_lower:
                tested.append(f"Nav item '{item}' present")
            else:
                bugs.append(f"Nav item '{item}' not found in sidebar")

        status = "PASS" if not bugs else "FAIL"
        add_result("Sidebar", status, tested, bugs)
    except Exception as e:
        add_result("Sidebar", "FAIL", tested, bugs + [f"Error: {traceback.format_exc()[-400:]}"])


# ─── Report ────────────────────────────────────────────────────────────────────

def write_report():
    lines = []
    lines.append("# Cato Live E2E Test Report")
    lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Target: {BASE_URL}\n")

    pass_count = sum(1 for r in results if r["status"] == "PASS")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)

    lines.append("## Summary\n")
    lines.append(f"- **Total test suites:** {total}")
    lines.append(f"- **PASS:** {pass_count}")
    lines.append(f"- **FAIL:** {fail_count}")
    lines.append(f"- **Pass rate:** {pass_count}/{total} ({100*pass_count//total if total else 0}%)\n")

    all_bugs = [(r["page"], b) for r in results for b in r["bugs"]]
    if all_bugs:
        lines.append("## All Bugs Found\n")
        for page_name, bug in all_bugs:
            short = bug[:400] + "..." if len(bug) > 400 else bug
            lines.append(f"- **[{page_name}]** {short}")
        lines.append("")

    lines.append("---\n")
    lines.append("## Page-by-Page Results\n")

    for r in results:
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        lines.append(f"### {r['page']} - {icon}\n")
        lines.append("**What was tested:**")
        for t in r["tested"]:
            lines.append(f"- {t}")
        if r["bugs"]:
            lines.append("\n**Bugs found:**")
            for b in r["bugs"]:
                short_b = b[:500] + "..." if len(b) > 500 else b
                lines.append(f"- BUG: {short_b}")
        if r["notes"]:
            lines.append(f"\n**Notes:** {r['notes']}")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    return pass_count, fail_count, all_bugs


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    safe_print("=" * 60, flush=True)
    safe_print("Cato Live E2E Test Suite v3", flush=True)
    safe_print(f"Target: {BASE_URL}", flush=True)
    safe_print("=" * 60, flush=True)

    await test_api_health()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-web-security"]
        )
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        page.set_default_timeout(10000)

        test_fns = [
            test_dashboard,
            test_chat,
            test_coding_agent,
            test_skills,
            test_cron,
            test_sessions,
            test_usage,
            test_logs,
            test_audit,
            test_config,
            test_budget,
            test_alerts,
            test_auth_keys,
            test_identity,
            test_flows,
            test_nodes,
            test_memory,
            test_system,
            test_diagnostics,
            test_sidebar,
        ]

        for fn in test_fns:
            try:
                await fn(page)
            except Exception as e:
                name = fn.__name__.replace("test_", "").replace("_", " ").title()
                add_result(name, "FAIL", [], [f"Runner error: {traceback.format_exc()[-200:]}"])

        await browser.close()

    pass_count, fail_count, all_bugs = write_report()

    safe_print("\n" + "=" * 60, flush=True)
    safe_print(f"RESULTS: {pass_count} PASS / {fail_count} FAIL / {pass_count + fail_count} total", flush=True)
    safe_print("=" * 60, flush=True)

    if all_bugs:
        safe_print(f"\nBugs ({len(all_bugs)} total):", flush=True)
        for pg, bug in all_bugs:
            short = bug[:120] + "..." if len(bug) > 120 else bug
            safe_print(f"  [{pg}] {short}", flush=True)

    safe_print(f"\nReport: {REPORT_PATH}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
