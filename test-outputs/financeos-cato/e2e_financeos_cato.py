from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


TARGET = "http://127.0.0.1:5173"
ROOT = Path(__file__).resolve().parent
SHOTS = ROOT / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)


def install_desktop_bridge(page: Page) -> None:
    page.add_init_script(
        """
        window.__TAURI_INTERNALS__ = {
          invoke: async (cmd) => cmd === 'get_daemon_status'
            ? { running: true, http_port: 8080, ws_port: 8080, daemon_token: 'e2e-token' }
            : null,
          transformCallback: () => 1
        };
        """
    )
    def fulfill_api(route) -> None:
        path = route.request.url.split("8080", 1)[-1]
        if path.startswith("/api/sessions"):
            payload = []
        elif path.startswith("/api/budget/summary"):
            payload = {"monthly_spend": 3200, "monthly_cap": 10000, "monthly_pct_remaining": 68, "monthly_calls": 42}
        elif path.startswith("/health"):
            payload = {"status": "ok", "version": "0.2.0", "uptime": 7200}
        elif path.startswith("/api/inbox"):
            payload = {"email_drafts": [], "notes": [], "todos": [], "reminders": [], "counts": {"email_drafts": 0, "notes": 0, "todos": 0, "reminders": 0}}
        else:
            payload = {
                "connected": True,
                "status": "ok",
                "db": True,
                "module_layer_wired": True,
                "queue_depth": 4,
                "oldest_hold_age_hours": 2.5,
                "last_xero_sync_at": None,
                "production_write_enabled": False,
                "version": "0.1.0",
            }
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )
    page.route(re.compile(r"http://127\.0\.0\.1:8080/.*"), fulfill_api)


def run_scenario(browser, name, test_fn):
    failures = []
    for attempt in (1, 2):
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        install_desktop_bridge(page)
        errors: list[str] = []
        page.on("console", lambda m: errors.append(f"console:{m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror:{e}"))
        page.on("response", lambda r: errors.append(f"http{r.status}:{r.url}") if r.status >= 500 else None)
        try:
            test_fn(page)
            if errors:
                raise AssertionError("; ".join(errors))
            shot = SHOTS / f"{name}_final.png"
            page.screenshot(path=str(shot), full_page=True)
            context.close()
            return {"result": "PASS" if attempt == 1 else "PASS(flaky)", "evidence": str(shot)}
        except Exception as exc:  # evidence is more important than exception type here
            shot = SHOTS / f"{name}_attempt{attempt}_{int(time.time())}.png"
            page.screenshot(path=str(shot), full_page=True)
            failures.append(f"attempt {attempt}: {exc}; screenshot={shot}")
            context.close()
    return {"result": "FAIL", "evidence": " | ".join(failures)}


def dashboard(page: Page) -> None:
    page.goto(TARGET)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="Good morning, Ben.").wait_for()
    assert page.get_by_text(re.compile("Finance command center", re.I)).is_visible(), "command-center label missing"
    assert page.get_by_text("Operational", exact=True).is_visible()
    assert page.get_by_text("Protected", exact=True).is_visible()
    assert page.get_by_role("button", name="Ask Cato →", exact=True).is_visible()


def workflow_to_chat(page: Page) -> None:
    page.goto(TARGET)
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name=re.compile("Morning finance brief")).click()
    box = page.get_by_role("textbox")
    box.wait_for()
    assert "E4Life" in box.input_value(), "workflow prompt did not carry into chat"
    assert "verified facts" in box.input_value(), "workflow prompt omitted evidence guardrail"


def navigation(page: Page) -> None:
    page.goto(TARGET)
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name=re.compile("Inbox")).click()
    page.get_by_text(re.compile("Inbox|Approval|Review", re.I)).first.wait_for()
    page.get_by_role("button", name=re.compile("Settings")).click()
    page.get_by_text(re.compile("Settings|Configuration", re.I)).first.wait_for()


def mobile_dashboard(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(TARGET)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="Good morning, Ben.").wait_for()
    assert page.locator("body").evaluate("el => el.scrollWidth <= el.clientWidth")
    assert page.get_by_role("button", name="Ask Cato →", exact=True).is_visible()


def no_green_rendered(page: Page) -> None:
    page.goto(TARGET)
    page.wait_for_load_state("networkidle")
    offenders = page.evaluate(
        """
        () => {
          const props = ['color','backgroundColor','borderTopColor','borderRightColor','borderBottomColor','borderLeftColor'];
          const out = [];
          const parse = value => (value.match(/[\\d.]+/g) || []).slice(0,3).map(Number);
          for (const el of document.querySelectorAll('*')) {
            const s = getComputedStyle(el);
            for (const prop of props) {
              const [r,g,b] = parse(s[prop]);
              const max = Math.max(r||0,g||0,b||0), min = Math.min(r||0,g||0,b||0);
              if (g > r * 1.12 && g > b * 1.08 && max - min > 18) out.push(`${el.tagName}.${el.className}:${prop}=${s[prop]}`);
            }
          }
          return [...new Set(out)].slice(0,20);
        }
        """
    )
    assert not offenders, f"green-like rendered colors: {offenders}"


def main() -> int:
    scenarios = [
        ("dashboard", "P0", dashboard),
        ("workflow_to_chat", "P0", workflow_to_chat),
        ("navigation", "P1", navigation),
        ("mobile_dashboard", "P1", mobile_dashboard),
        ("no_green_rendered", "P1", no_green_rendered),
    ]
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, priority, fn in scenarios:
            result = run_scenario(browser, name, fn)
            results.append({"name": name, "priority": priority, **result})
        browser.close()
    (ROOT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 1 if any(r["result"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
