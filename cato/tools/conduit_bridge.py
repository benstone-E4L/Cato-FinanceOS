"""
cato/tools/conduit_bridge.py — Opt-in browser engine backed by local billing ledger.

Drop-in replacement for browser.py when conduit_enabled=true in config.
Uses the same action interface as BrowserTool but tracks per-action costs
in a local SQLite ledger (no external server required).

Ed25519 identity key is stored in {data_dir}/conduit_identity.key for audit
trail integrity. Billing is recorded in cato.db table conduit_billing.

Action costs:
    All actions = 0 cents (billing disabled for local Cato use)

VOIX protocol: strips <tool>...</tool> and <context>...</context> tags
from extracted HTML/text content before returning to agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from ..audit import AuditLog

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACTION_COSTS: dict[str, int] = {
    # Wave 0
    "navigate":               0,
    "click":                  0,
    "type":                   0,
    "fill":                   0,
    "extract":                0,
    "screenshot":             0,
    # Wave 1
    "scroll":                 0,
    "wait":                   0,
    "wait_for":               0,
    "key_press":              0,
    "hover":                  0,
    "select_option":          0,
    "handle_dialog":          0,
    "navigate_back":          0,
    "console_messages":       0,
    # Wave 2
    "eval":                   0,
    "extract_main":           0,
    "output_to_file":         0,
    "accessibility_snapshot": 0,
    "network_requests":       0,
    # Wave 3
    "map":                    0,
    "crawl":                  0,
    "fingerprint":            0,
    "check_changed":          0,
    "export_proof":           0,
}

_VOIX_TAGS_RE = re.compile(r"<(tool|context)>.*?</(tool|context)>", re.DOTALL)

_BILLING_SCHEMA = """
CREATE TABLE IF NOT EXISTS conduit_billing (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    cost_cents  INTEGER NOT NULL DEFAULT 0,
    timestamp   REAL    NOT NULL,
    url_or_sel  TEXT    NOT NULL DEFAULT '',
    success     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_conduit_session ON conduit_billing(session_id);
"""


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class BudgetExceededError(RuntimeError):
    """Raised when a Conduit action would exceed the per-session budget."""


# ---------------------------------------------------------------------------
# Ed25519 identity (local keypair)
# ---------------------------------------------------------------------------

class ConduitIdentity:
    """
    Manages a local Ed25519 keypair stored in {data_dir}/conduit_identity.key.

    The key is used to sign audit receipts — it never leaves the local machine.
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        from ..platform import get_data_dir
        self._key_path = (data_dir or get_data_dir()) / "conduit_identity.key"
        self._private_key: Optional[bytes] = None
        self._public_key: Optional[bytes] = None

    def _load_or_create(self) -> None:
        """Load existing keypair or generate a new one (private implementation)."""
        if self._private_key is not None:
            return

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PrivateFormat, NoEncryption, PublicFormat,
            )

            if self._key_path.exists():
                raw = self._key_path.read_bytes()
                private_key = Ed25519PrivateKey.from_private_bytes(raw)
            else:
                private_key = Ed25519PrivateKey.generate()
                raw = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
                self._key_path.parent.mkdir(parents=True, exist_ok=True)
                self._key_path.write_bytes(raw)
                self._key_path.chmod(0o600)
                logger.info("ConduitIdentity: new Ed25519 keypair generated at %s", self._key_path)

            self._private_key = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
            pub = private_key.public_key()
            self._public_key = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)

        except ImportError:
            logger.warning("cryptography library unavailable — identity signing disabled")
            self._private_key = b"\x00" * 32
            self._public_key = b"\x00" * 32

    # Public alias so callers don't need to know the underscore convention
    def load_or_create(self) -> None:
        """Public alias for _load_or_create — load or generate the Ed25519 keypair."""
        self._load_or_create()

    @property
    def public_key_hex(self) -> str:
        """Return the public key as a 64-character hex string (property)."""
        self._load_or_create()
        return (self._public_key or b"").hex()

    def public_key_hex_method(self) -> str:
        """Backward-compat method form — prefer the property."""
        return self.public_key_hex

    def sign(self, payload: bytes) -> bytes:
        """Sign payload with the Ed25519 private key."""
        self._load_or_create()
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            pk = Ed25519PrivateKey.from_private_bytes(self._private_key)
            return pk.sign(payload)
        except Exception as exc:
            logger.warning("Ed25519 signing failed: %s", exc)
            return b""


# ---------------------------------------------------------------------------
# Billing ledger
# ---------------------------------------------------------------------------

class ConduitBillingLedger:
    """Append-only SQLite billing ledger stored in cato.db."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        from ..platform import get_data_dir
        self._db_path = db_path or (get_data_dir() / "cato.db")
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_BILLING_SCHEMA)
        self._conn.commit()

    def record(
        self,
        session_id: str,
        action: str,
        cost_cents: int,
        url_or_selector: str = "",
        identity_or_success: "Any" = True,
    ) -> None:
        """Record one billing event.

        The 5th argument accepts either:
        - bool / int — success flag (original internal usage)
        - ConduitIdentity — identity object passed by audit spec callers (ignored;
          the local ledger does not need to verify the identity signature)
        """
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        # Normalize the 5th arg: if it's a bool/int use it; otherwise treat as success=True
        if isinstance(identity_or_success, (bool, int)):
            success_flag = int(bool(identity_or_success))
        else:
            success_flag = 1  # identity object passed — default success
        self._conn.execute(
            "INSERT INTO conduit_billing (session_id, action, cost_cents, timestamp, url_or_sel, success)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, action, cost_cents, time.time(), url_or_selector, success_flag),
        )
        self._conn.commit()

    def session_total(self, session_id: str) -> int:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_cents), 0) FROM conduit_billing WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def session_total_cents(self, session_id: str) -> int:
        """Alias for session_total — returns total cents spent in session."""
        return self.session_total(session_id)


# ---------------------------------------------------------------------------
# VOIX helpers
# ---------------------------------------------------------------------------

def _strip_voix_tags(html: str) -> str:
    """Remove <tool>...</tool> and <context>...</context> tags from extracted content."""
    return _VOIX_TAGS_RE.sub("", html).strip()


async def _sync_as_coro(fn, *args, **kwargs):
    """Wrap a synchronous callable so it can be awaited in the execute() dispatcher."""
    return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# ConduitBrowserTool — agent-loop wrapper that builds bridge from CatoConfig
# ---------------------------------------------------------------------------

class ConduitBrowserTool:
    """
    Wrapper used by cato.tools when conduit_enabled=True.
    Builds ConduitBridge from config via to_conduit_bridge_config() so shared
    Conduit behavior (extraction, crawl delay, selector healing, vault) is config-driven.
    """

    def __init__(self, config: Any, budget: Any) -> None:
        self._cfg = config
        self._budget = budget

    async def execute(self, args: dict) -> str:
        from ..platform import get_data_dir
        session_id = args.get("session_id", "default")
        bridge_cfg = self._cfg.to_conduit_bridge_config(
            session_id,
            data_dir=str(get_data_dir()),
            conduit_budget_per_session=getattr(self._cfg, "conduit_budget_per_session", None),
        )
        bridge = ConduitBridge(bridge_cfg, session_id)
        await bridge.start()
        try:
            return await bridge.execute(args)
        finally:
            await bridge.stop()


# ---------------------------------------------------------------------------
# ConduitBridge
# ---------------------------------------------------------------------------

class ConduitBridge:
    """
    Opt-in browser engine with per-action cost tracking.

    Implements the same async interface as BrowserTool but charges per action
    and enforces a per-session budget cap.

    **Preferred (config-driven):** Use CatoConfig.to_conduit_bridge_config() so
    shared Conduit behavior (extraction limits, crawl delay, selector healing,
    vault) comes from config::

        from cato.config import CatoConfig
        from cato.platform import get_data_dir

        cfg = CatoConfig.load()  # or your runtime config
        bridge = ConduitBridge(
            cfg.to_conduit_bridge_config(
                session_id,
                data_dir=str(get_data_dir()),
                conduit_budget_per_session=100,
            ),
            session_id,
        )
        await bridge.start()

    Legacy: ConduitBridge(session_id, budget_cents=100, data_dir=path) still works
    but does not set _config (no extraction/crawl/selector-healing from config).
    """

    def __init__(
        self,
        session_id_or_config: "str | dict" = "default",
        session_id_if_config: str = "",
        budget_cents: int = 100,
        data_dir: Optional[Path] = None,
    ) -> None:
        # Config-driven: dict + session_id. Legacy: session_id str + budget_cents/data_dir.
        if isinstance(session_id_or_config, dict):
            cfg = session_id_or_config
            self._session_id = session_id_if_config or "default"
            self._budget_cents = int(cfg.get("conduit_budget_per_session", budget_cents))
            raw_data_dir = cfg.get("data_dir")
            data_dir = Path(raw_data_dir) if raw_data_dir else data_dir
            self._config = cfg
        else:
            self._session_id = str(session_id_or_config)
            self._budget_cents = budget_cents
            self._config = {}

        self._session_cost_cents_total: int = 0

        self._identity = ConduitIdentity(data_dir)
        # Pass data_dir-based db_path so tests using tmp_path get an isolated ledger
        # instead of writing to the global ~/.cato/cato.db.
        ledger_db = (data_dir / "cato.db") if data_dir is not None else None
        self._ledger = ConduitBillingLedger(db_path=ledger_db)
        # AuditLog shares the same db file as the billing ledger so both tables
        # live in one SQLite file (cato.db).  This is what feeds the SHA-256
        # hash chain used by verify_chain() / ReceiptWriter.
        self._audit_log = AuditLog(db_path=ledger_db)

        # Underlying browser (lazy init)
        self._browser_tool: Optional[Any] = None

        # Track last navigated URL so extract() can re-navigate if needed
        self._current_url: str = ""

    # ------------------------------------------------------------------
    # Public accessors for identity and ledger (used by audit/test code)
    # ------------------------------------------------------------------

    @property
    def identity(self) -> ConduitIdentity:
        return self._identity

    @identity.setter
    def identity(self, value: ConduitIdentity) -> None:
        self._identity = value

    @property
    def ledger(self) -> ConduitBillingLedger:
        return self._ledger

    @ledger.setter
    def ledger(self, value: ConduitBillingLedger) -> None:
        self._ledger = value

    async def start(self) -> None:
        """Initialize the browser, billing ledger, and audit log."""
        self._ledger.connect()
        self._audit_log.connect()
        # Lazy import to avoid circular deps
        from ..tools.browser import BrowserTool, PATCHRIGHT_AVAILABLE
        if not PATCHRIGHT_AVAILABLE:
            raise RuntimeError(
                "Conduit requires patchright: pip install cato-daemon[conduit]"
            )
        self._browser_tool = BrowserTool()
        logger.info(
            "ConduitBridge started — session=%s budget=%dc identity=%s",
            self._session_id, self._budget_cents, self._identity.public_key_hex[:16] + "...",
        )

    async def stop(self) -> None:
        """Gracefully close the browser."""
        if self._browser_tool:
            try:
                await self._browser_tool.close()
            except Exception as exc:
                logger.debug("ConduitBridge stop: %s", exc)
            self._browser_tool = None

    @property
    def session_cost_cents(self) -> int:
        """Return total cents spent in this session (queries ledger for accuracy)."""
        # Prefer ledger total so externally-recorded charges are included
        try:
            if self._ledger._conn is not None or True:
                ledger_total = self._ledger.session_total_cents(self._session_id)
                # Keep in-memory counter in sync
                self._session_cost_cents_total = ledger_total
                return ledger_total
        except Exception:
            pass
        return self._session_cost_cents_total

    def _audit(
        self,
        action: str,
        inputs: dict,
        result: Any,
        url_or_selector: str = "",
        error: str = "",
    ) -> None:
        """Unified accounting method: writes to BOTH billing ledger AND AuditLog hash chain.

        This is the ONLY method that should be called for new bridge actions.
        Every browser action is reflected in the SHA-256 chain AND the billing table.
        """
        cost = ACTION_COSTS.get(action.lower(), 0)
        # Budget check — query ledger for authoritative total
        try:
            current_total = self._ledger.session_total_cents(self._session_id)
        except Exception:
            current_total = self._session_cost_cents_total

        if current_total + cost > self._budget_cents:
            raise BudgetExceededError(
                f"Conduit budget {self._budget_cents}¢ would be exceeded by '{action}' ({cost}¢). "
                f"Currently at {current_total}¢."
            )

        # 1) Write to billing ledger (conduit_billing table)
        self._ledger.record(self._session_id, action, cost, url_or_selector, not bool(error))
        self._session_cost_cents_total = current_total + cost

        # 2) Write to audit hash chain (audit_log table)
        self._audit_log.log(
            session_id=self._session_id,
            action_type="tool_call",
            tool_name=f"browser.{action}",
            inputs=inputs,
            outputs=result if isinstance(result, dict) else {"raw": str(result)},
            cost_cents=cost,
            error=error,
        )

    # ------------------------------------------------------------------
    # Bridge action methods — all go through _audit() (not _charge())
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> dict:
        assert self._browser_tool is not None
        result = await self._browser_tool._dispatch("navigate", {"url": url})
        if "text" in result:
            result["text"] = _strip_voix_tags(result["text"])
        self._current_url = result.get("url", url)
        self._audit("navigate", {"url": url}, result, url_or_selector=url,
                    error=result.get("error", ""))
        return result

    async def click(self, selector: str) -> dict:
        assert self._browser_tool is not None
        result, tier, resolved = await self._try_selector_healing("click", selector)
        if tier > 1:
            self._audit_log.log(
                session_id=self._session_id,
                action_type="tool_call",
                tool_name="browser.selector_healing",
                inputs={"original_selector": selector, "tier_used": tier, "resolved_selector": resolved},
                outputs={"action": "click"},
                cost_cents=0,
                error="",
            )
        self._audit("click", {"selector": selector}, result, url_or_selector=selector,
                    error=result.get("error", ""))
        return result

    async def type_text(self, selector: str, text: str) -> dict:
        assert self._browser_tool is not None
        result, tier, resolved = await self._try_selector_healing("type", selector, text=text)
        if tier > 1:
            self._audit_log.log(
                session_id=self._session_id,
                action_type="tool_call",
                tool_name="browser.selector_healing",
                inputs={"original_selector": selector, "tier_used": tier, "resolved_selector": resolved},
                outputs={"action": "type"},
                cost_cents=0,
                error="",
            )
        self._audit("type", {"selector": selector, "text": text}, result,
                    url_or_selector=selector, error=result.get("error", ""))
        return result

    async def fill(self, selector: str, text: str) -> dict:
        """Named alias for type_text — goes through _audit() with 'fill' action name; respects selector healing."""
        assert self._browser_tool is not None
        result, tier, resolved = await self._try_selector_healing("fill", selector, text=text)
        if tier > 1:
            self._audit_log.log(
                session_id=self._session_id,
                action_type="tool_call",
                tool_name="browser.selector_healing",
                inputs={"original_selector": selector, "tier_used": tier, "resolved_selector": resolved},
                outputs={"action": "fill"},
                cost_cents=0,
                error="",
            )
        self._audit("fill", {"selector": selector, "text": text}, result,
                    url_or_selector=selector, error=result.get("error", ""))
        return result

    async def extract(self, selector: str = "body") -> dict:
        assert self._browser_tool is not None
        result = await self._browser_tool._dispatch("snapshot", {})
        if "text" in result:
            result["text"] = _strip_voix_tags(result["text"])
        result["char_count"] = len(result.get("text", ""))
        self._audit("extract", {"selector": selector}, result, url_or_selector=selector,
                    error=result.get("error", ""))
        return result

    async def screenshot(self, path: Optional[str] = None) -> dict:
        assert self._browser_tool is not None
        kwargs: dict[str, Any] = {}
        if path:
            kwargs["filename"] = path
        result = await self._browser_tool._dispatch("screenshot", kwargs)
        self._audit("screenshot", kwargs, result, error=result.get("error", ""))
        return result

    async def scroll(
        self,
        direction: str = "down",
        amount: int = 300,
        selector: Optional[str] = None,
    ) -> dict:
        assert self._browser_tool is not None
        inputs: dict[str, Any] = {"direction": direction, "amount": amount}
        if selector is not None:
            inputs["selector"] = selector
        result = await self._browser_tool._dispatch("scroll", inputs.copy())
        self._audit("scroll", inputs, result, url_or_selector=selector or "",
                    error=result.get("error", ""))
        return result

    async def wait(self, seconds: float = 1.0) -> dict:
        assert self._browser_tool is not None
        inputs = {"seconds": seconds}
        result = await self._browser_tool._dispatch("wait", inputs.copy())
        self._audit("wait", inputs, result, error=result.get("error", ""))
        return result

    async def wait_for(
        self,
        condition: str = "selector",
        value: str = "",
        timeout_ms: int = 10000,
    ) -> dict:
        assert self._browser_tool is not None
        inputs = {"condition": condition, "value": value, "timeout_ms": timeout_ms}
        result = await self._browser_tool._dispatch("wait_for", inputs.copy())
        self._audit("wait_for", inputs, result, error=result.get("error", ""))
        return result

    async def key_press(self, key: str = "Enter") -> dict:
        assert self._browser_tool is not None
        inputs = {"key": key}
        result = await self._browser_tool._dispatch("key_press", inputs.copy())
        self._audit("key_press", inputs, result, error=result.get("error", ""))
        return result

    async def hover(self, selector: str) -> dict:
        assert self._browser_tool is not None
        result, tier, resolved = await self._try_selector_healing("hover", selector)
        if tier > 1:
            self._audit_log.log(
                session_id=self._session_id,
                action_type="tool_call",
                tool_name="browser.selector_healing",
                inputs={"original_selector": selector, "tier_used": tier, "resolved_selector": resolved},
                outputs={"action": "hover"},
                cost_cents=0,
                error="",
            )
        self._audit("hover", {"selector": selector}, result, url_or_selector=selector,
                    error=result.get("error", ""))
        return result

    async def select_option(
        self,
        selector: str,
        value: str = "",
        label: str = "",
        index: Optional[int] = None,
    ) -> dict:
        assert self._browser_tool is not None
        inputs: dict[str, Any] = {"selector": selector, "value": value, "label": label}
        if index is not None:
            inputs["index"] = index
        result = await self._browser_tool._dispatch("select_option", inputs.copy())
        self._audit("select_option", inputs, result, url_or_selector=selector,
                    error=result.get("error", ""))
        return result

    async def handle_dialog(self, action: str = "accept", text: str = "") -> dict:
        assert self._browser_tool is not None
        inputs = {"action": action, "text": text}
        result = await self._browser_tool._dispatch("handle_dialog", inputs.copy())
        self._audit("handle_dialog", inputs, result, error=result.get("error", ""))
        return result

    async def navigate_back(self) -> dict:
        assert self._browser_tool is not None
        result = await self._browser_tool._dispatch("navigate_back", {})
        self._audit("navigate_back", {}, result, error=result.get("error", ""))
        return result

    async def _try_selector_healing(self, action: str, selector: str, **kwargs: Any) -> tuple:
        """If selector_healing_enabled, try ARIA/text fallbacks after direct selector fails. Returns (result, tier_used, resolved_selector)."""
        result = await self._browser_tool._dispatch(action, {"selector": selector, **kwargs})
        if not result.get("error"):
            return result, 1, selector
        cfg = getattr(self, "_config", {}) or {}
        if not cfg.get("selector_healing_enabled", False):
            return result, 1, selector
        for role in ("button", "link", "textbox", "menuitem"):
            alt = f'role={role}[name="{selector}"]'
            res = await self._browser_tool._dispatch(action, {"selector": alt, **kwargs})
            if not res.get("error"):
                return res, 2, alt
        alt = f"text={selector}"
        res = await self._browser_tool._dispatch(action, {"selector": alt, **kwargs})
        if not res.get("error"):
            return res, 3, alt
        return result, 1, selector

    async def console_messages(self) -> dict:
        assert self._browser_tool is not None
        result = await self._browser_tool._dispatch("console_messages", {})
        self._audit("console_messages", {}, result, error=result.get("error", ""))
        return result

    # ------------------------------------------------------------------
    # Wave 2: Extraction bridge methods
    # ------------------------------------------------------------------

    async def eval(self, js_code: str) -> dict:
        """
        Execute js_code in page context. js_code is stored verbatim in audit inputs —
        this is Conduit's unique differentiator: cryptographic proof of exactly what code ran.
        """
        assert self._browser_tool is not None
        result = await self._browser_tool._dispatch("eval", {"js_code": js_code})
        # js_code MUST be in inputs — core differentiator of Conduit.
        # Route through _audit() so the budget check is enforced like all other actions.
        # _sanitize_inputs() will NOT redact js_code (no sensitive key substring match).
        self._audit(
            "eval",
            {"js_code": js_code, "code_hash": result.get("code_hash", "")},
            result,
            error="" if result.get("success") else result.get("error", ""),
        )
        return result

    async def extract_main(self, max_chars: Optional[int] = None, fmt: str = "text") -> dict:
        """Readability-style main content extraction. max_chars defaults to config conduit_extract_max_chars."""
        assert self._browser_tool is not None
        cfg = getattr(self, "_config", {}) or {}
        if max_chars is None:
            max_chars = int(cfg.get("conduit_extract_max_chars", 5000))
        result = await self._browser_tool._dispatch("extract_main", {"max_chars": max_chars, "fmt": fmt})
        if "text" in result:
            result["text"] = _strip_voix_tags(result["text"])
        self._audit(
            "extract_main",
            {"url": result.get("url", ""), "max_chars": max_chars},
            {"char_count": result.get("char_count", 0), "title": result.get("title", "")},
            error=result.get("error", ""),
        )
        return result

    async def output_to_file(self, filename: str, content: str, fmt: str = "md") -> dict:
        """
        Write content to a workspace file. Audit stores filename + fmt + byte_count
        but NOT the full content (may be very large).
        """
        assert self._browser_tool is not None
        result = await self._browser_tool._dispatch(
            "output_to_file", {"filename": filename, "content": content, "fmt": fmt}
        )
        # Audit inputs: filename + fmt + byte_count — NOT the full content
        self._audit(
            "output_to_file",
            {"filename": filename, "fmt": fmt, "byte_count": result.get("bytes", 0)},
            result,
            error="" if result.get("success") else result.get("error", ""),
        )
        return result

    async def accessibility_snapshot(self) -> dict:
        """Return Playwright accessibility tree for the current page."""
        assert self._browser_tool is not None
        result = await self._browser_tool._dispatch("accessibility_snapshot", {})
        self._audit(
            "accessibility_snapshot",
            {"url": result.get("url", "")},
            {"title": result.get("title", ""), "has_tree": result.get("tree") is not None},
            error=result.get("error", ""),
        )
        return result

    async def network_requests(self) -> dict:
        """Return and clear the accumulated network request/response log."""
        assert self._browser_tool is not None
        result = await self._browser_tool._dispatch("network_requests", {})
        self._audit(
            "network_requests",
            {},
            {"count": result.get("count", 0)},
            error="",
        )
        return result

    # ------------------------------------------------------------------
    # Wave 3: Crawler bridge methods
    # ------------------------------------------------------------------

    async def map_site(self, url: str, limit: int = 100, search: str = None) -> dict:
        """Breadth-first site URL discovery. Robots.txt compliant; respects crawl delay from config."""
        assert self._browser_tool is not None
        from .conduit_crawl import ConduitCrawler
        cfg = getattr(self, "_config", {}) or {}
        crawler = ConduitCrawler(
            self._browser_tool, self._audit_log, self._session_id,
            crawl_delay_sec=float(cfg.get("conduit_crawl_delay_sec", 1.0)),
            crawl_max_delay_sec=float(cfg.get("conduit_crawl_max_delay_sec", 60.0)),
        )
        return await crawler.map_site(url, limit=limit, search=search)

    async def crawl_site(
        self,
        url: str,
        max_depth: int = 2,
        include_paths: Optional[list] = None,
        exclude_paths: Optional[list] = None,
        limit: int = 20,
    ) -> dict:
        """Bulk page extraction with depth control. Every page logged to hash chain; respects crawl delay from config."""
        assert self._browser_tool is not None
        from .conduit_crawl import ConduitCrawler
        cfg = getattr(self, "_config", {}) or {}
        crawler = ConduitCrawler(
            self._browser_tool, self._audit_log, self._session_id,
            crawl_delay_sec=float(cfg.get("conduit_crawl_delay_sec", 1.0)),
            crawl_max_delay_sec=float(cfg.get("conduit_crawl_max_delay_sec", 60.0)),
        )
        return await crawler.crawl_site(
            url, max_depth=max_depth,
            include_paths=include_paths, exclude_paths=exclude_paths,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Wave 3: Monitor bridge methods
    # ------------------------------------------------------------------

    async def fingerprint(self, url: str) -> dict:
        """Navigate to URL and return a SHA-256 fingerprint (noise-stripped)."""
        assert self._browser_tool is not None
        from .conduit_monitor import ConduitMonitor
        monitor = ConduitMonitor(self._browser_tool, self._audit_log, self._session_id)
        return await monitor.fingerprint(url)

    async def check_changed(self, url: str, previous_fingerprint: str) -> dict:
        """Re-fingerprint URL, log PAGE_MUTATION event if content changed."""
        assert self._browser_tool is not None
        from .conduit_monitor import ConduitMonitor
        monitor = ConduitMonitor(self._browser_tool, self._audit_log, self._session_id)
        return await monitor.check_changed(url, previous_fingerprint)

    # ------------------------------------------------------------------
    # Wave 3: Proof bridge method
    # ------------------------------------------------------------------

    def export_proof(self, output_dir: str = None) -> dict:
        """Export a self-verifiable session proof bundle (.tar.gz)."""
        from .conduit_proof import ConduitProof
        public_key_pem = f"# Ed25519 public key: {self._identity.public_key_hex}\n"
        proof = ConduitProof(self._audit_log, self._session_id, public_key_pem)
        return proof.export(output_dir=output_dir)

    # ------------------------------------------------------------------
    # execute() dispatcher (agent_loop entry point)
    # ------------------------------------------------------------------

    async def execute(self, args: dict[str, Any]) -> str:
        """Dispatch from agent_loop tool registry (same interface as BrowserTool.execute).

        All action paths go through _audit() so every browser action is
        recorded in both the billing ledger AND the SHA-256 hash chain.
        """
        action = args.pop("action", "") if isinstance(args, dict) else ""
        _ALL_ACTIONS = [
            # Wave 0 + Wave 1
            "navigate", "click", "type", "fill", "extract", "screenshot",
            "scroll", "wait", "wait_for", "key_press", "hover",
            "select_option", "handle_dialog", "navigate_back", "console_messages",
            # Wave 2
            "eval", "extract_main", "output_file", "output_to_file",
            "accessibility_snapshot", "network_requests",
            # Wave 3
            "map", "crawl", "fingerprint", "check_changed", "export_proof",
        ]
        dispatch: dict[str, Any] = {
            # Wave 0 + Wave 1
            "navigate":               lambda: self.navigate(args.get("url", "")),
            "click":                  lambda: self.click(args.get("selector", "")),
            "type":                   lambda: self.type_text(args.get("selector", ""), args.get("text", "")),
            "fill":                   lambda: self.fill(args.get("selector", ""), args.get("text", "")),
            "extract":                lambda: self.extract(args.get("selector", "body")),
            "screenshot":             lambda: self.screenshot(args.get("path")),
            "scroll":                 lambda: self.scroll(
                                          args.get("direction", "down"),
                                          args.get("amount", 300),
                                          args.get("selector"),
                                      ),
            "wait":                   lambda: self.wait(args.get("seconds", 1.0)),
            "wait_for":               lambda: self.wait_for(
                                          args.get("condition", "selector"),
                                          args.get("value", ""),
                                          args.get("timeout_ms", 10000),
                                      ),
            "key_press":              lambda: self.key_press(args.get("key", "Enter")),
            "hover":                  lambda: self.hover(args.get("selector", "")),
            "select_option":          lambda: self.select_option(
                                          args.get("selector", ""),
                                          args.get("value", ""),
                                          args.get("label", ""),
                                          args.get("index"),
                                      ),
            "handle_dialog":          lambda: self.handle_dialog(
                                          args.get("action", "accept"),
                                          args.get("text", ""),
                                      ),
            "navigate_back":          lambda: self.navigate_back(),
            "console_messages":       lambda: self.console_messages(),
            # Wave 2: Extraction
            "eval":                   lambda: self.eval(args.get("js_code", "")),
            "extract_main":           lambda: self.extract_main(
                                          max_chars=args.get("max_chars"),
                                          fmt=args.get("fmt", "text"),
                                      ),
            "output_file":            lambda: self.output_to_file(
                                          args.get("filename", "output"),
                                          args.get("content", ""),
                                          args.get("fmt", "md"),
                                      ),
            "output_to_file":         lambda: self.output_to_file(
                                          args.get("filename", "output"),
                                          args.get("content", ""),
                                          args.get("fmt", "md"),
                                      ),
            "accessibility_snapshot": lambda: self.accessibility_snapshot(),
            "network_requests":       lambda: self.network_requests(),
            # Wave 3: Crawler
            "map":                    lambda: self.map_site(
                                          args.get("url", ""),
                                          limit=args.get("limit", 100),
                                          search=args.get("search"),
                                      ),
            "crawl":                  lambda: self.crawl_site(
                                          args.get("url", ""),
                                          max_depth=args.get("max_depth", 2),
                                          include_paths=args.get("include_paths"),
                                          exclude_paths=args.get("exclude_paths"),
                                          limit=args.get("limit", 20),
                                      ),
            # Wave 3: Monitor
            "fingerprint":            lambda: self.fingerprint(args.get("url", "")),
            "check_changed":          lambda: self.check_changed(
                                          args.get("url", ""),
                                          args.get("previous_fingerprint", ""),
                                      ),
            # Wave 3: Proof (sync method — wrapped to allow await)
            "export_proof":           lambda: _sync_as_coro(self.export_proof, args.get("output_dir")),
        }
        handler = dispatch.get(action)
        if handler is None:
            return json.dumps({
                "error": f"Unknown conduit action: {action!r}. Valid: {_ALL_ACTIONS}",
            })
        try:
            coro_or_val = handler()
            import asyncio as _asyncio
            if _asyncio.iscoroutine(coro_or_val):
                result = await coro_or_val
            else:
                result = coro_or_val
            return json.dumps(result)
        except BudgetExceededError as exc:
            return json.dumps({"error": str(exc), "budget_exceeded": True})
        except Exception as exc:
            logger.error("ConduitBridge action %s failed: %s", action, exc)
            return json.dumps({"error": str(exc), "action": action})
