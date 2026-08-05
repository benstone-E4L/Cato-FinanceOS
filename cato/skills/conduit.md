# Conduit Browser
**Version:** 2.0.0
**Capabilities:** Full headless browser automation with stealth, CAPTCHA solving, proxy rotation,
cookie/auth management, site crawling, page monitoring, structured extraction, proof bundles,
multi-engine web search, and academic search.

## Trigger Phrases
"browse", "navigate to", "click", "type", "fill", "extract", "screenshot", "search the web",
"crawl", "map site", "monitor page", "fingerprint", "take screenshot", "pdf", "scroll",
"hover", "select", "open url", "web page", "solve captcha", "rotate proxy", "save cookies"

<!-- COLD -->
## Overview
Conduit is Cato's built-in headless browser engine. Every action is:
- SHA-256 hash-chained and Ed25519-signed in the audit log
- Budget-checked before execution
- Sensitive inputs (password, token, api_key, secret, etc.) auto-redacted in logs

All browser calls go through `ConduitBridge.execute(args)` where `args` is a dict with an
`action` key plus action-specific parameters.

---

## Quick Reference — All Actions

### Wave 0 — Core
| Action | Key params | Notes |
|--------|-----------|-------|
| `navigate` | `url` | Blocks RFC-1918/loopback IPs; detects CAPTCHA post-load |
| `click` | `selector` | 3-tier self-healing: CSS → ARIA → text substring |
| `type` | `selector`, `text` | Human-like char-by-char typing, 50–150ms/key; `:visible` recommended |
| `fill` | `selector`, `text` | Instant fill (no typing delay); use for non-human-detected fields |
| `extract` | `selector` (opt, default: `body`) | Returns `text`, `char_count` |
| `screenshot` | `path` (opt) | Returns base64 or saved path |
| `pdf` | `path` (opt) | Saves full-page PDF |
| `search` | `query` | Legacy DDG browser fallback (prefer `web_search`) |

### Wave 1 — Interaction
| Action | Key params | Notes |
|--------|-----------|-------|
| `scroll` | `direction` (`up`/`down`), `amount` (px) | Smooth scroll |
| `wait` | `seconds` | Sleep; default 1.0s |
| `wait_for` | `selector`, `state` (`visible`/`hidden`/`attached`) | Wait for element state |
| `key_press` | `key` (e.g. `Enter`, `Tab`, `Escape`) | Keyboard event |
| `hover` | `selector` | Bezier-curve mouse movement before hover |
| `select_option` | `selector`, `value` | `<select>` dropdown |
| `handle_dialog` | `action` (`accept`/`dismiss`), `text` (opt) | Browser alert/confirm/prompt |
| `navigate_back` | — | Browser back button |
| `console_messages` | — | Returns JS console log entries |

### Wave 2 — Extraction
| Action | Key params | Notes |
|--------|-----------|-------|
| `eval` | `js_code` | JS source stored verbatim in audit chain |
| `extract_main` | `max_chars` (opt, 5000), `fmt` (`text`/`html`), `provenance_mode` (bool) | Main content extraction; clones DOM before cleaning |
| `extract_structured` | `schema` (dict) | Extract + Claude validates against JSON schema |
| `output_to_file` | `filename`, `content`, `fmt` (`md`/`txt`/`json`) | Saves to `~/.cato/workspace/.conduit/` |
| `accessibility_snapshot` | — | ARIA tree (3-tier fallback: aria_snapshot → accessibility.snapshot → DOM) |
| `network_requests` | — | Returns logged network requests/responses |

### Wave 3 — Advanced
| Action | Key params | Notes |
|--------|-----------|-------|
| `map` | `url`, `limit` (100), `search` (opt substring filter) | BFS URL discovery; robots.txt compliant |
| `crawl` | `url`, `max_depth` (2), `limit` (20), `include_paths`, `exclude_paths` | Bulk page extraction; each page logged |
| `fingerprint` | `url` | SHA-256 page fingerprint (timestamps/nonces stripped) |
| `check_changed` | `url`, `previous_fingerprint` | Re-fingerprint; logs `PAGE_MUTATION` if changed |
| `export_proof` | `session_id` (opt), `output_path` (opt) | Self-verifiable `.tar.gz` proof bundle |

### Anti-Detection & Stealth
| Action | Key params | Notes |
|--------|-----------|-------|
| `detect_captcha` | — | Scans current page for CAPTCHA signals |
| `solve_captcha` | — | Auto-solve via CapSolver API (reCAPTCHA v2, hCaptcha, Turnstile) |
| `solve_captcha_vision` | — | Fallback: screenshot → Claude vision → type answer |
| `rotate_proxy` | — | Round-robin from `CONDUIT_PROXY_LIST` env var |

### Cookie & Auth Management
| Action | Key params | Notes |
|--------|-----------|-------|
| `save_cookies` | `label` (default: `"default"`) | Serialize cookies to `~/.cato/sessions/{label}.json` |
| `load_cookies` | `label` (default: `"default"`) | Restore cookies from file |
| `check_session` | `url` | Check for auth wall; returns `{authenticated, redirect_url}` |
| `login` | `url`, `credential_key` | Env-var based login (`CONDUIT_CRED_{KEY}_USER` / `_PASS`) |

### Search
| Action | Key params | Notes |
|--------|-----------|-------|
| `web_search` | `query`, `query_type` (opt: `code`/`news`/`academic`/`general`) | Multi-engine: DDG API → Brave → Exa → Tavily → browser fallback |
| `academic_search` | `query`, `source` (`arxiv`/`semantic_scholar`/`pubmed`/`auto`) | Academic papers with DOI, citation count, PDF URL |

---

## Method Names (ConduitBridge Python API)

When calling via Python directly (not the `execute()` dispatcher), use these method names:

```python
await bridge.navigate(url)
await bridge.click(selector)
await bridge.type_text(selector, text)      # human-like typing
await bridge.fill(selector, text)           # instant fill
await bridge.extract(selector="body")
await bridge.screenshot(path=None)
await bridge.scroll(direction="down", amount=300)
await bridge.wait(seconds=1.0)
await bridge.wait_for(selector, state="visible")
await bridge.key_press(key="Enter")
await bridge.hover(selector)
await bridge.select_option(selector, value)
await bridge.handle_dialog(action="accept", text="")
await bridge.navigate_back()
await bridge.console_messages()
await bridge.eval(js_code)
await bridge.extract_main(max_chars=5000, fmt="text", provenance_mode=False)
await bridge.extract_structured(schema)
await bridge.output_to_file(filename, content, fmt="md")
await bridge.accessibility_snapshot()
await bridge.network_requests()
await bridge.map_site(url, limit=100, search=None)
await bridge.crawl_site(url, max_depth=2, limit=20, include_paths=None, exclude_paths=None)
await bridge.fingerprint(url)
await bridge.check_changed(url, previous_fingerprint)
await bridge.web_search(query, query_type=None)
await bridge.academic_search(query, source="auto")
await bridge.save_cookies(label="default")
await bridge.load_cookies(label="default")
await bridge.check_session(url)
await bridge.login(url, credential_key)
```

---

## Selector Tips

- **Always use `:visible`** when a page has duplicate DOM elements (e.g. React apps with hidden panels):
  ```python
  await bridge.type_text('input[type="email"]:visible', email)
  await bridge.click('button:has-text("Sign in"):visible')
  ```
- **Self-healing** kicks in automatically on failure: CSS → ARIA tree → text substring match
- **3-tier fallback is logged** to the audit chain: `{original_selector, tier_used, resolved_selector}`

---

## Bootstrapping Conduit from an External Script

Any script outside the Conduit package must use the conftest bootstrap shim:

```python
import sys, importlib.util
from pathlib import Path

CONDUIT_ROOT = Path(r"C:\Users\Administrator\Desktop\Conduit")
sys.path.insert(0, str(CONDUIT_ROOT))

spec = importlib.util.spec_from_file_location(
    "conftest", str(CONDUIT_ROOT / "tests" / "conftest.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.bootstrap_cato()

ConduitBridge = sys.modules["cato.tools.conduit_bridge"].ConduitBridge
```

Then use it:

```python
import asyncio

async def main():
    bridge = ConduitBridge("my-session", budget_cents=99999, data_dir=None)
    await bridge.start()
    try:
        r = await bridge.navigate("https://example.com")
        print(r["title"])
        r = await bridge.extract_main()
        print(r["text"][:500])
    finally:
        await bridge.stop()

asyncio.run(main())
```

---

## IdeaBrowser Integration

The IdeaBrowser nightly job uses Conduit for all browser automation:

- **Scraper**: `C:\Users\Administrator\Desktop\Ideabrowser Ideas\worker\ideabrowser_scraper.py`
  - Bootstraps Conduit, logs in to ideabrowser.com, extracts Idea of the Day + 7 sub-pages
  - Uses `:visible` selectors to handle React hidden-DOM duplicates
  - Saves JSON + Markdown to `ideas/IdeaBrowser/{date} - {title}/`

- **Analyst**: `C:\Users\Administrator\Desktop\Ideabrowser Ideas\worker\ideabrowser_analyst.py`
  - Reads `latest.md`, sends to Claude CLI for GO/NO-GO analysis
  - Sends Telegram notification via Bot API (chat ID: 5846582379)
  - No external dependencies — uses stdlib `urllib` for Telegram

- **Scheduled Task**: `\IdeaBrowser Nightly` — runs at midnight via Windows Task Scheduler
  - Runs: `ideabrowser_run.bat` → scraper → analyst → greg_isenberg_scraper → exploding_topics_scraper

---

## Storage Locations

| Item | Path |
|------|------|
| SQLite database | `~/.cato/cato.db` |
| Ed25519 identity key | `~/.cato/conduit_identity.key` |
| Screenshots | `~/.cato/workspace/screenshots/` |
| File outputs | `~/.cato/workspace/.conduit/` |
| Proof bundles | `~/.cato/proofs/` |
| Browser profile | `~/.cato/browser_profile/` |
| Session cookies | `~/.cato/sessions/{label}.json` |

---

## Audit Trail

Every action is written to the append-only SHA-256 hash-chained audit log in SQLite.
Each row's hash includes the previous row — tamper-evident across the full session history.

```bash
cato audit --session <id>    # full action-by-action replay
cato audit --verify          # tamper detection across all sessions
cato receipt --session <id>  # signed receipt with line-item log
```

---

## Safety

- RFC-1918 / loopback IPs blocked in `_navigate()` — no SSRF
- Sensitive input keys auto-redacted: `password`, `token`, `api_key`, `secret`, `key`,
  `authorization`, `bearer`, `credential`, `passwd`, `passphrase`
- `output_to_file` filenames sanitized via `Path(filename).name` — no directory traversal
- Crawlers always bounded by `limit` param; always check `robots.txt` before each URL
- Budget cap enforced before every action via `ConduitBridge._audit()`

---

## Known Limitations (this environment)

- **`add_init_script()` disabled**: Patchright + Windows Server corrupts DNS. Stealth JS is
  injected via `page.on("load")` event handler calling `page.evaluate()` instead.
- **arXiv academic search**: SSL certificate verification fails on this Windows Server.
  PubMed and Semantic Scholar work fine.
- **Sec-Ch-Ua header**: Still reveals `HeadlessChrome` (requires HTTP interception to fix,
  not JS injection). Minor fingerprint leak.
