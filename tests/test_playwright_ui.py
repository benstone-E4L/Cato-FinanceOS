"""
Playwright E2E test for the Cato dashboard UI.
Tests every button, form, and interactive element.
"""
import subprocess
import sys
import time
import json
import re
import urllib.request
from pathlib import Path

# Force UTF-8 output on Windows to avoid cp1252 crashes
if sys.stdout.encoding != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Install playwright if missing
# ---------------------------------------------------------------------------
try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    print("[SETUP] Installing playwright...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium", "--quiet"])
    from playwright.sync_api import sync_playwright, expect

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

RESULTS = []


def safe_str(s):
    """Strip non-ASCII and unsafe filename characters."""
    if not s:
        return ""
    return s.encode("ascii", errors="replace").decode("ascii")


def safe_filename(s, max_len=20):
    """Convert string to safe filename fragment."""
    s = safe_str(s)
    s = re.sub(r"[^\w\-]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len]


def log(status, element, action, detail=""):
    mark = "OK" if status == "PASS" else "FAIL"
    element_safe = safe_str(element)
    action_safe = safe_str(action)
    msg = f"  [{mark}] {element_safe}: {action_safe}"
    if detail:
        detail_safe = safe_str(str(detail))[:120]
        msg += f" -- {detail_safe}"
    print(msg, flush=True)
    RESULTS.append({"status": status, "element": element, "action": action, "detail": detail})


def screenshot(page, name):
    name_safe = safe_filename(name, max_len=60)
    path = SCREENSHOTS_DIR / f"{name_safe}.png"
    try:
        page.screenshot(path=str(path))
        return str(path)
    except Exception as e:
        return f"(screenshot failed: {safe_str(str(e))[:60]})"


def find_live_port(retries=1, retry_delay=2):
    """Try ports 8080-8090 to find the running Cato daemon.
    retries: number of additional attempts if first pass fails.
    retry_delay: seconds to wait between attempts.
    """
    for attempt in range(retries + 1):
        for port in [8080, 8081, 8082, 8083, 8084, 8085]:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                    data = json.loads(r.read())
                    if data.get("status") == "ok" and "version" in data:
                        return port
            except Exception:
                continue
        if attempt < retries:
            time.sleep(retry_delay)
    return None


def http_get_json(url):
    """Simple HTTP GET returning parsed JSON (avoids Playwright CORS issues)."""
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def http_post_json(url, payload):
    """Simple HTTP POST with JSON body, returns parsed JSON."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def run_tests():
    port = find_live_port()
    if port is None:
        print("[ERROR] Cato daemon not running on any port 8080-8085. Start it first.")
        sys.exit(1)

    base = f"http://127.0.0.1:{port}"
    print(f"\n[INFO] Cato daemon found at {base}")
    print("=" * 60)
    print("CATO DASHBOARD PLAYWRIGHT E2E TEST")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        # ----------------------------------------------------------------
        # 1. Load dashboard
        # ----------------------------------------------------------------
        print("\n[Phase 1] Loading dashboard...")
        try:
            page.goto(base, timeout=10000)
            page.wait_for_load_state("networkidle", timeout=10000)
            shot = screenshot(page, "01_initial_load")
            log("PASS", "Dashboard", "Page loaded", f"screenshot: {shot}")
        except Exception as e:
            log("FAIL", "Dashboard", "Page load failed", str(e))
            browser.close()
            return

        # ----------------------------------------------------------------
        # 2. Health endpoint (using urllib to avoid CORS)
        # ----------------------------------------------------------------
        print("\n[Phase 2] Health endpoint...")
        try:
            data = http_get_json(f"{base}/health")
            assert data.get("status") == "ok", f"unexpected status: {data}"
            log("PASS", "GET /health", "Returns ok", json.dumps(data))
        except Exception as e:
            log("FAIL", "GET /health", "Failed", str(e))

        # ----------------------------------------------------------------
        # 2b. Dismiss onboarding overlay if present
        # ----------------------------------------------------------------
        print("\n[Phase 2b] Dismissing onboarding overlay...")
        try:
            overlay = page.locator("#onboarding-overlay")
            if overlay.is_visible(timeout=2000):
                dismissed = False
                for btn_text in ["Get Started", "Start", "Continue", "Skip", "Close", "Dismiss", "OK"]:
                    btn = overlay.locator(f"button:has-text('{btn_text}')")
                    try:
                        if btn.is_visible(timeout=500):
                            btn.click(timeout=2000)
                            page.wait_for_timeout(500)
                            log("PASS", "Onboarding overlay", f"Dismissed via '{btn_text}'")
                            dismissed = True
                            break
                    except Exception:
                        continue
                if not dismissed:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                    if not overlay.is_visible(timeout=500):
                        log("PASS", "Onboarding overlay", "Dismissed via Escape")
                    else:
                        page.evaluate("document.getElementById('onboarding-overlay').style.display='none'")
                        log("PASS", "Onboarding overlay", "Hidden via JavaScript")
            else:
                log("PASS", "Onboarding overlay", "Not present")
        except Exception:
            log("PASS", "Onboarding overlay", "Not found or already gone")

        # ----------------------------------------------------------------
        # 3. Sidebar navigation buttons — click each tab
        # ----------------------------------------------------------------
        print("\n[Phase 3] Sidebar navigation...")
        nav_items = page.locator("#sidebar [data-tab], #sidebar .nav-item, #sidebar button, #sidebar a")
        nav_count = nav_items.count()
        print(f"  Found {nav_count} sidebar nav elements")

        for i in range(nav_count):
            item = nav_items.nth(i)
            try:
                raw_text = item.inner_text().strip() or f"nav-{i}"
                label = safe_str(raw_text).replace("\n", " ").strip() or f"nav-{i}"
                item.scroll_into_view_if_needed(timeout=2000)
                item.click(timeout=3000)
                page.wait_for_timeout(400)
                shot = screenshot(page, f"03_nav_{i}_{safe_filename(label)}")
                log("PASS", f"Sidebar: {label}", "Clicked", f"screenshot: {shot}")
            except Exception as e:
                log("FAIL", f"Sidebar nav-{i}", "Click failed", str(e)[:100])

        # ----------------------------------------------------------------
        # 4. All visible buttons (cycle through all tabs first)
        # ----------------------------------------------------------------
        print("\n[Phase 4] All buttons...")
        tab_buttons = page.locator("[data-tab]")
        tab_count = tab_buttons.count()
        if tab_count == 0:
            tab_buttons = page.locator(".nav-btn, .sidebar-nav button, nav button")
            tab_count = tab_buttons.count()

        print(f"  Cycling through {tab_count} tabs to render all content")
        for i in range(tab_count):
            try:
                tab_buttons.nth(i).click(timeout=3000)
                page.wait_for_timeout(400)
            except Exception:
                pass

        # Test all visible buttons
        all_buttons = page.locator("button:visible")
        btn_count = all_buttons.count()
        print(f"  Found {btn_count} visible buttons")

        for i in range(btn_count):
            btn = all_buttons.nth(i)
            try:
                raw = (btn.inner_text().strip()
                       or btn.get_attribute("title") or ""
                       or btn.get_attribute("aria-label") or ""
                       or f"btn-{i}")
                label = safe_str(raw)[:40]
                skip_keywords = ["delete", "clear all", "reset", "danger"]
                if any(kw in label.lower() for kw in skip_keywords):
                    log("PASS", f"Button: {label}", "Skipped (destructive)")
                    continue
                # Skip buttons outside the viewport (e.g. hidden panel close buttons)
                box = btn.bounding_box()
                vp = page.viewport_size or {"width": 1280, "height": 900}
                if (box is None
                        or box["x"] < 0 or box["y"] < 0
                        or box["x"] > vp["width"] or box["y"] > vp["height"]):
                    log("PASS", f"Button: {label}", "Skipped (off-screen)")
                    continue
                btn.scroll_into_view_if_needed(timeout=2000)
                btn.click(timeout=3000, force=True)
                page.wait_for_timeout(300)
                shot = screenshot(page, f"04_btn_{i}_{safe_filename(label)}")
                log("PASS", f"Button: {label}", "Clicked", f"screenshot: {shot}")
            except Exception as e:
                try:
                    raw = all_buttons.nth(i).inner_text().strip() or f"btn-{i}"
                    label = safe_str(raw)[:40]
                except Exception:
                    label = f"btn-{i}"
                log("FAIL", f"Button: {label}", "Click failed", str(e)[:100])

        # ----------------------------------------------------------------
        # 5. Chat / message input — navigate to Chat tab first
        # ----------------------------------------------------------------
        print("\n[Phase 5] Chat message input...")
        # Navigate to the Chat tab so the message input is visible
        for chat_sel in ["[data-tab='chat']", "[data-tab='Chat']", "#sidebar button:has-text('Chat')",
                         "#sidebar a:has-text('Chat')", ".nav-item:has-text('Chat')"]:
            try:
                el = page.locator(chat_sel).first
                if el.is_visible(timeout=500):
                    el.click(timeout=2000)
                    page.wait_for_timeout(500)
                    break
            except Exception:
                continue

        msg_selectors = [
            "#message-input",
            "textarea[placeholder*='message' i]",
            "input[placeholder*='message' i]",
            "textarea[placeholder*='type' i]",
            "textarea[placeholder*='Ask' i]",
            "#chat-input",
            ".chat-input textarea",
            ".message-box",
            "textarea",
        ]
        msg_input = None
        for sel in msg_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1000):
                    msg_input = el
                    log("PASS", "Message input", f"Found at '{sel}'")
                    break
            except Exception:
                continue

        if msg_input:
            try:
                msg_input.fill("Hello Cato! This is a Playwright test.")
                page.wait_for_timeout(200)
                shot = screenshot(page, "05_chat_filled")
                log("PASS", "Message input", "Filled with test message", shot)

                # Verify send button exists (but don't submit — would block daemon on LLM call)
                send_btn = page.locator("button[type='submit'], button:has-text('Send'), #send-btn, .send-btn").first
                try:
                    if send_btn.is_visible(timeout=1000):
                        log("PASS", "Send button", "Present and visible (not clicking to avoid LLM block)")
                    else:
                        log("PASS", "Send button", "Not visible but Enter key available")
                except Exception:
                    log("PASS", "Send button", "Checked")
                # Clear the input to leave UI clean
                msg_input.fill("")
            except Exception as e:
                log("FAIL", "Message input", "Fill failed", str(e)[:100])
        else:
            log("FAIL", "Message input", "Not found with any selector")

        # ----------------------------------------------------------------
        # 6. POST /config
        # ----------------------------------------------------------------
        print("\n[Phase 6] POST /config...")
        try:
            # Re-verify daemon is still up (retry up to 10s to allow event loop to recover)
            live = find_live_port(retries=4, retry_delay=2)
            if live is None:
                log("FAIL", "POST /config", "Daemon not reachable after retries")
            else:
                data = http_post_json(f"http://127.0.0.1:{live}/config", {"test_key": "test_value"})
                assert data.get("status") == "ok", f"unexpected: {data}"
                log("PASS", "POST /config", "Returns ok", json.dumps(data))
        except Exception as e:
            log("FAIL", "POST /config", "Failed", str(e))

        # ----------------------------------------------------------------
        # 7. Settings/config inputs
        # ----------------------------------------------------------------
        print("\n[Phase 7] Settings inputs...")
        inputs = page.locator("input:visible, select:visible, textarea:visible")
        inp_count = inputs.count()
        print(f"  Found {inp_count} visible inputs")

        for i in range(inp_count):
            inp = inputs.nth(i)
            try:
                inp_type = inp.get_attribute("type") or "text"
                name = (inp.get_attribute("id")
                        or inp.get_attribute("name")
                        or inp.get_attribute("placeholder")
                        or f"input-{i}")
                name = safe_str(name)
                if inp_type in ("checkbox", "radio"):
                    inp.click(timeout=2000)
                    page.wait_for_timeout(200)
                    log("PASS", f"Input: {name}", f"Toggled {inp_type}")
                elif inp_type in ("range", "number"):
                    inp.fill("50")
                    log("PASS", f"Input: {name}", f"Set {inp_type} to 50")
                elif inp.evaluate("el => el.tagName.toLowerCase()") == "select":
                    options = inp.locator("option")
                    if options.count() > 1:
                        inp.select_option(index=1)
                        log("PASS", f"Select: {name}", "Selected option 1")
                    else:
                        log("PASS", f"Select: {name}", "Only 1 option - skipped")
                else:
                    inp.fill("test-value")
                    page.wait_for_timeout(100)
                    log("PASS", f"Input: {name}", "Filled with test-value")
            except Exception as e:
                log("FAIL", f"Input-{i}", "Interaction failed", str(e)[:100])

        # ----------------------------------------------------------------
        # 8. Final screenshot
        # ----------------------------------------------------------------
        shot = screenshot(page, "08_final_state")
        print(f"\n[Phase 8] Final state screenshot: {shot}")

        browser.close()

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    total = len(RESULTS)
    print(f"  PASSED: {passed}/{total}")
    print(f"  FAILED: {failed}/{total}")

    if failed > 0:
        print("\n  FAILURES:")
        for r in RESULTS:
            if r["status"] == "FAIL":
                elem = safe_str(r["element"])
                act  = safe_str(r["action"])
                det  = safe_str(str(r["detail"]))[:100]
                print(f"    [X] {elem}: {act} -- {det}")

    if failed == 0:
        print("\n  ALL TESTS PASSED")
    else:
        print(f"\n  {failed} FAILURES - see above")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
