"""
cato/tools/browser.py — Browser automation using Patchright (stealth Playwright fork).

Actions: navigate, snapshot, click, type, fill, screenshot, pdf, search,
         eval, extract_main, output_to_file, accessibility_snapshot,
         network_requests, scroll, wait, wait_for, key_press, hover,
         select_option, handle_dialog, navigate_back, console_messages
Search engine: DuckDuckGo only (Google/Brave block bots).
Browser: Chromium only with persistent profile at ~/.cato/browser_profile/.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any

from ..platform import get_data_dir

logger = logging.getLogger(__name__)

try:
    import patchright  # noqa: F401 — presence check only
    PATCHRIGHT_AVAILABLE = True
except ImportError:
    PATCHRIGHT_AVAILABLE = False

_CATO_DIR = get_data_dir()
_PROFILE_DIR = _CATO_DIR / "browser_profile"
_SCREENSHOT_DIR = _CATO_DIR / "workspace" / "screenshots"
_PDF_DIR = _CATO_DIR / "workspace" / "pdfs"


class BrowserTool:
    """Browser automation using Patchright (stealth Playwright fork).

    Provides:
    - navigate(url): Go to URL, return page title + visible text
    - snapshot():    Return current page title + text + interactive elements
    - click(selector): Click element by CSS selector or text
    - type(selector, text): Type text into input
    - screenshot():  Take screenshot, save to workspace, return path
    - pdf(filename): Save page as PDF
    - search(query): DuckDuckGo search, return top 5 results

    Uses persistent browser profile at ~/.cato/browser_profile/
    Chromium only (no Firefox, no WebKit)
    """

    def __init__(self) -> None:
        self._browser = None
        self._page = None
        self._playwright = None
        self._network_log: list[dict] = []
        self._console_messages: list[dict] = []
        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        _PDF_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def execute(self, args: dict[str, Any]) -> str:
        """Dispatch from agent_loop tool registry (receives raw args dict)."""
        action = args.pop("action", "") if isinstance(args, dict) else ""
        result = await self._dispatch(action, args)
        return json.dumps(result)

    async def _dispatch(self, action: str, kwargs: dict) -> dict:
        """Ensure browser is running, then dispatch to sub-action."""
        await self._ensure_browser()

        actions = {
            "navigate":               self._navigate,
            "snapshot":               self._snapshot,
            "click":                  self._click,
            "type":                   self._type,
            "fill":                   self._type,           # alias — same page.fill() semantics
            "screenshot":             self._screenshot,
            "pdf":                    self._pdf,
            "search":                 self._search,
            "eval":                   self._eval,
            "extract_main":           self._extract_main,
            "output_to_file":         self._output_to_file,
            "accessibility_snapshot": self._accessibility_snapshot,
            "network_requests":       self._get_network_requests,
            "scroll":                 self._scroll,
            "wait":                   self._wait,
            "wait_for":               self._wait_for,
            "key_press":              self._key_press,
            "hover":                  self._hover,
            "select_option":          self._select_option,
            "handle_dialog":          self._handle_dialog,
            "navigate_back":          self._navigate_back,
            "console_messages":       self._get_console_messages,
        }

        if action not in actions:
            return {"error": f"Unknown browser action: {action!r}. Valid: {list(actions)}"}

        try:
            return await actions[action](**kwargs)
        except Exception as exc:
            logger.error("Browser action %s failed: %s", action, exc)
            return {"error": str(exc), "action": action}

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------

    async def _ensure_browser(self) -> None:
        """Launch Patchright browser if not already running."""
        if self._browser is not None:
            try:
                # self._browser is a BrowserContext (from launch_persistent_context),
                # not a Browser — BrowserContext has no is_connected() method.
                # Use len(pages) > 0 as the liveness check instead.
                if len(self._browser.pages) > 0:
                    return
            except Exception:
                pass

        if not PATCHRIGHT_AVAILABLE:
            raise RuntimeError(
                "Conduit requires patchright: pip install cato-daemon[conduit]"
            )
        from patchright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(_PROFILE_DIR),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self._page = await self._browser.new_page()
        # Register network listeners for network_requests action
        self._page.on("request", lambda req: self._network_log.append({
            "type": "request", "url": req.url, "method": req.method
        }))
        self._page.on("response", lambda res: self._network_log.append({
            "type": "response", "url": res.url, "status": res.status
        }))
        # Register console listener for console_messages action
        self._page.on(
            "console",
            lambda msg: self._console_messages.append({"type": msg.type, "text": msg.text}),
        )
        logger.debug("Patchright browser launched with profile %s", _PROFILE_DIR)

    async def close(self) -> None:
        """Gracefully close the browser and Playwright instance."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._page = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _navigate(self, url: str, wait_until: str = "domcontentloaded") -> dict:
        """Navigate to URL and return title + visible text (first 3000 chars)."""
        # Validate URL scheme (no file://, no internal IPs)
        import ipaddress
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"error": f"Blocked URL scheme: {parsed.scheme}. Only http/https allowed."}
        # Block RFC-1918 and link-local
        try:
            host = parsed.hostname
            addr = ipaddress.ip_address(host) if host else None
            if addr and (addr.is_private or addr.is_link_local or addr.is_loopback):
                return {"error": f"Blocked internal IP: {host}"}
        except ValueError:
            pass  # hostname, not IP — allow

        await self._page.goto(url, wait_until=wait_until, timeout=30000)
        title = await self._page.title()
        text = await self._page.evaluate("document.body.innerText")
        return {
            "title": title,
            "url": self._page.url,
            "text": text[:3000],
        }

    async def _snapshot(self) -> dict:
        """Return current page state: title, URL, visible text, interactive elements."""
        title = await self._page.title()
        text = await self._page.evaluate("document.body.innerText")

        elements = await self._page.evaluate("""
            () => {
                const els = [];
                document.querySelectorAll('a, button, input, select, textarea').forEach(el => {
                    els.push({
                        tag: el.tagName.toLowerCase(),
                        text: (el.innerText || el.value || el.placeholder || '').substring(0, 100),
                        href: el.href || null,
                        id: el.id || null,
                        type: el.type || null
                    });
                });
                return els.slice(0, 50);
            }
        """)

        return {
            "title": title,
            "url": self._page.url,
            "text": text[:2000],
            "elements": elements,
        }

    async def _click(self, selector: str) -> dict:
        """Click element by CSS selector."""
        try:
            await self._page.click(selector, timeout=10000)
            return {"success": True, "selector": selector, "url": self._page.url}
        except Exception as exc:
            return {"success": False, "selector": selector, "error": str(exc)}

    async def _type(self, selector: str, text: str) -> dict:
        """Type text into an input element."""
        try:
            await self._page.fill(selector, text, timeout=10000)
            return {"success": True, "selector": selector, "typed": text}
        except Exception as exc:
            return {"success": False, "selector": selector, "error": str(exc)}

    async def _screenshot(self, filename: str = None) -> dict:
        """Take a full-page screenshot and save to workspace."""
        import time
        if not filename:
            filename = f"screenshot_{int(time.time())}.png"
        # Strip path components to prevent directory traversal
        filename = Path(filename).name
        if not filename.endswith(".png"):
            filename += ".png"

        out_path = _SCREENSHOT_DIR / filename
        # Verify path stays within screenshots dir after resolution
        try:
            out_path.resolve().relative_to(_SCREENSHOT_DIR.resolve())
        except ValueError:
            return {"error": f"Invalid filename: {filename!r}"}
        await self._page.screenshot(path=str(out_path), full_page=True)
        return {"success": True, "path": str(out_path), "url": self._page.url}

    async def _pdf(self, filename: str = None) -> dict:
        """Save the current page as a PDF."""
        import time
        if not filename:
            filename = f"page_{int(time.time())}.pdf"
        # Strip path components to prevent directory traversal
        filename = Path(filename).name
        if not filename.endswith(".pdf"):
            filename += ".pdf"

        out_path = _PDF_DIR / filename
        # Verify path stays within pdfs dir after resolution
        try:
            out_path.resolve().relative_to(_PDF_DIR.resolve())
        except ValueError:
            return {"error": f"Invalid filename: {filename!r}"}
        await self._page.pdf(path=str(out_path))
        return {"success": True, "path": str(out_path), "url": self._page.url}

    async def _eval(self, js_code: str) -> dict:
        """Execute arbitrary JavaScript in page context. Returns result + SHA-256 code hash."""
        import hashlib
        code_hash = hashlib.sha256(js_code.encode()).hexdigest()[:16]
        try:
            result = await self._page.evaluate(js_code)
            return {
                "success": True,
                "result": result,
                "code_hash": code_hash,
                "url": self._page.url,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "code_hash": code_hash}

    async def _extract_main(self) -> dict:
        """Readability-style main content extraction. Removes nav/header/footer noise.

        Operates on a deep clone of <body> so the live DOM is never mutated.
        This is critical for audit integrity: screenshots and evals taken after
        extract_main() still see the original, unmodified page.
        """
        text = await self._page.evaluate("""
            () => {
                // Work on a deep clone — never mutate the live DOM.
                const clone = document.body.cloneNode(true);
                const noise = ['nav','header','footer','aside','[role="banner"]',
                              '[role="navigation"]','[role="complementary"]',
                              '.nav','.header','.footer','.sidebar','.menu',
                              '#nav','#header','#footer','#sidebar'];
                noise.forEach(sel => {
                    clone.querySelectorAll(sel).forEach(el => el.remove());
                });
                const candidates = clone.querySelectorAll('article,main,[role="main"],p,div');
                let best = null, bestScore = 0;
                candidates.forEach(el => {
                    const text = el.innerText || '';
                    const score = text.length - (el.querySelectorAll('a').length * 20);
                    if (score > bestScore) { bestScore = score; best = el; }
                });
                return best ? best.innerText.trim() : clone.innerText.trim();
            }
        """)
        return {
            "text": text[:5000],
            "char_count": len(text),
            "url": self._page.url,
            "title": await self._page.title(),
        }

    async def _output_to_file(self, filename: str, content: str, fmt: str = "md") -> dict:
        """Write content to workspace file. Sanitizes filename to prevent path traversal."""
        from pathlib import Path as _Path
        out_dir = get_data_dir() / "workspace" / ".conduit"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _Path(filename).name  # strip any path traversal
        # Guard against empty or dot-only names (e.g. filename='' or filename='.')
        if not safe_name or safe_name in (".", ".."):
            safe_name = "output"
        if not safe_name.endswith(f".{fmt}"):
            safe_name = f"{safe_name}.{fmt}"
        out_path = out_dir / safe_name
        out_path.write_text(content, encoding="utf-8")
        return {"success": True, "path": str(out_path), "bytes": len(content.encode())}

    async def _accessibility_snapshot(self) -> dict:
        """Return accessibility tree for the current page.

        Uses page.aria_snapshot() (Patchright / Playwright ≥1.35).
        Falls back to the deprecated page.accessibility.snapshot() for
        older Playwright builds that haven't removed it yet.
        """
        try:
            snapshot = await self._page.aria_snapshot()
        except AttributeError:
            # Older Playwright: page.accessibility still present
            snapshot = await self._page.accessibility.snapshot()  # type: ignore[attr-defined]
        return {
            "tree": snapshot,
            "url": self._page.url,
            "title": await self._page.title(),
        }

    async def _get_network_requests(self) -> dict:
        """Return and clear the accumulated network request/response log."""
        reqs = list(self._network_log)
        self._network_log.clear()
        return {"requests": reqs, "count": len(reqs)}

    async def _search(self, query: str) -> dict:
        """DuckDuckGo search — returns top 5 results."""
        search_url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&ia=web"
        await self._page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

        results = await self._page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('[data-testid="result"]').forEach(r => {
                    const titleEl = r.querySelector('h2 a');
                    const snippetEl = r.querySelector('[data-result="snippet"]');
                    if (titleEl) {
                        results.push({
                            title: titleEl.innerText,
                            url: titleEl.href,
                            snippet: snippetEl ? snippetEl.innerText : ''
                        });
                    }
                });
                return results.slice(0, 5);
            }
        """)

        return {"query": query, "results": results}

    # ------------------------------------------------------------------
    # Action implementations (Wave 1 additions: scroll, fill-alias, wait,
    # wait_for, key_press, hover, select_option, handle_dialog,
    # navigate_back, console_messages)
    # ------------------------------------------------------------------

    async def _scroll(self, direction: str = "down", amount: int = 300, selector: str = None) -> dict:
        """Scroll the page or scroll a specific element into view."""
        if selector:
            await self._page.locator(selector).scroll_into_view_if_needed()
            return {"success": True, "action": "scroll_into_view", "selector": selector}
        delta_x = {"left": -amount, "right": amount}.get(direction, 0)
        delta_y = {"up": -amount, "down": amount}.get(direction, 0)
        await self._page.mouse.wheel(delta_x, delta_y)
        return {"success": True, "direction": direction, "amount": amount, "url": self._page.url}

    async def _wait(self, seconds: float = 1.0) -> dict:
        """Wait a fixed number of seconds (capped at 30s)."""
        capped = min(float(seconds), 30.0)
        await asyncio.sleep(capped)
        return {"success": True, "waited_seconds": capped}

    async def _wait_for(
        self,
        condition: str = "selector",
        value: str = "",
        timeout_ms: int = 10000,
    ) -> dict:
        """Wait for a condition: selector | text | network_idle | url."""
        import json as _json
        try:
            if condition == "selector":
                await self._page.wait_for_selector(value, timeout=timeout_ms)
            elif condition == "text":
                await self._page.wait_for_function(
                    f"document.body.innerText.includes({_json.dumps(value)})",
                    timeout=timeout_ms,
                )
            elif condition == "network_idle":
                await self._page.wait_for_load_state("networkidle", timeout=timeout_ms)
            elif condition == "url":
                await self._page.wait_for_url(value, timeout=timeout_ms)
            return {"success": True, "condition": condition, "value": value}
        except Exception as exc:
            return {"success": False, "condition": condition, "value": value, "error": str(exc)}

    async def _key_press(self, key: str = "Enter") -> dict:
        """Press a keyboard key (e.g. 'Enter', 'Tab', 'Escape')."""
        await self._page.keyboard.press(key)
        return {"success": True, "key": key, "url": self._page.url}

    async def _hover(self, selector: str) -> dict:
        """Move the mouse pointer over an element."""
        try:
            await self._page.hover(selector, timeout=10000)
            return {"success": True, "selector": selector}
        except Exception as exc:
            return {"success": False, "selector": selector, "error": str(exc)}

    async def _select_option(
        self,
        selector: str,
        value: str = "",
        label: str = "",
        index: int = None,
    ) -> dict:
        """Select an option in a <select> element by value, visible label, or 0-based index."""
        try:
            if index is not None:
                await self._page.select_option(selector, index=index)
            elif label:
                await self._page.select_option(selector, label=label)
            else:
                await self._page.select_option(selector, value=value)
            return {"success": True, "selector": selector, "value": value or label}
        except Exception as exc:
            return {"success": False, "selector": selector, "error": str(exc)}

    async def _handle_dialog(self, action: str = "accept", text: str = "") -> dict:
        """Register an accept or dismiss handler for the next browser dialog (alert/confirm/prompt)."""
        result: dict = {"handled": False}

        async def on_dialog(dialog):
            if action == "accept":
                await dialog.accept(text) if text else await dialog.accept()
            else:
                await dialog.dismiss()
            result["handled"] = True
            result["message"] = dialog.message
            result["type"] = dialog.type

        self._page.once("dialog", on_dialog)
        return {"success": True, "registered_action": action}

    async def _navigate_back(self) -> dict:
        """Navigate to the previous page in browser history."""
        await self._page.go_back(timeout=15000)
        return {"success": True, "url": self._page.url, "title": await self._page.title()}

    async def _get_console_messages(self) -> dict:
        """Return all buffered console messages and clear the internal buffer."""
        msgs = list(self._console_messages)
        self._console_messages.clear()
        return {"messages": msgs, "count": len(msgs)}
