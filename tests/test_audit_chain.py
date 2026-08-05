"""
tests/test_audit_chain.py

Tests for the critical audit bug fix:
  - ConduitBridge._audit() writes to BOTH conduit_billing AND audit_log tables
  - AuditLog.verify_chain() returns True after a sequence of actions

All tests use an isolated tmp SQLite file so they never touch ~/.cato/cato.db.
No real browser is launched — browser_tool is stubbed/mocked.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — make the Conduit root importable as a package.
# Since conduit_bridge.py uses `from ..audit import AuditLog` (relative import)
# we need a minimal parent package shim.
# ---------------------------------------------------------------------------

CONDUIT_ROOT = Path(__file__).parent.parent / "cato"  # Cato package root

# Insert a fake top-level package "cato" that re-exports what the relative
# imports need.  We patch sys.modules BEFORE importing the real modules.

def _bootstrap_package(tmp_db: Path):
    """Install minimal sys.modules shims so relative imports resolve."""
    # Create a fake 'cato' top-level package
    import types

    # --- cato (top-level) ---
    cato_pkg = types.ModuleType("cato")
    cato_pkg.__path__ = [str(CONDUIT_ROOT)]
    cato_pkg.__package__ = "cato"
    sys.modules.setdefault("cato", cato_pkg)

    # --- cato.platform ---
    # Keep the real platform module when the suite preloaded it. Replacing it
    # here leaked a partial module (without pid_alive) into later tests because
    # this bootstrap runs from a module-scoped fixture.
    platform_mod = sys.modules.get("cato.platform")
    if platform_mod is None:
        platform_mod = types.ModuleType("cato.platform")
        platform_mod.get_data_dir = lambda: tmp_db.parent  # type: ignore[attr-defined]
        sys.modules["cato.platform"] = platform_mod
        cato_pkg.platform = platform_mod  # type: ignore[attr-defined]

    # --- cato.audit (the real file, loaded as cato.audit) ---
    if "cato.audit" not in sys.modules:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cato.audit",
            str(CONDUIT_ROOT / "audit.py"),
            submodule_search_locations=[],
        )
        assert spec and spec.loader
        audit_mod = importlib.util.module_from_spec(spec)
        audit_mod.__package__ = "cato"
        sys.modules["cato.audit"] = audit_mod
        spec.loader.exec_module(audit_mod)  # type: ignore[union-attr]
        cato_pkg.audit = audit_mod  # type: ignore[attr-defined]

    # --- cato.tools (sub-package) ---
    tools_pkg = types.ModuleType("cato.tools")
    tools_pkg.__path__ = [str(CONDUIT_ROOT / "tools")]
    tools_pkg.__package__ = "cato.tools"
    sys.modules.setdefault("cato.tools", tools_pkg)
    cato_pkg.tools = tools_pkg  # type: ignore[attr-defined]

    # --- cato.tools.browser (stub — tests don't launch real browser) ---
    browser_mod = types.ModuleType("cato.tools.browser")
    browser_mod.__package__ = "cato.tools"

    class _StubBrowserTool:
        pass

    browser_mod.BrowserTool = _StubBrowserTool  # type: ignore[attr-defined]
    sys.modules["cato.tools.browser"] = browser_mod

    # --- cato.tools.conduit_bridge (the real file) ---
    if "cato.tools.conduit_bridge" not in sys.modules:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cato.tools.conduit_bridge",
            str(CONDUIT_ROOT / "tools" / "conduit_bridge.py"),
            submodule_search_locations=[],
        )
        assert spec and spec.loader
        bridge_mod = importlib.util.module_from_spec(spec)
        bridge_mod.__package__ = "cato.tools"
        sys.modules["cato.tools.conduit_bridge"] = bridge_mod
        spec.loader.exec_module(bridge_mod)  # type: ignore[union-attr]
        tools_pkg.conduit_bridge = bridge_mod  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory) -> Path:
    db = tmp_path_factory.mktemp("audit_test") / "cato.db"
    _bootstrap_package(db)
    return db


@pytest.fixture(scope="module")
def AuditLog(tmp_db):
    mod = sys.modules["cato.audit"]
    return mod.AuditLog


@pytest.fixture(scope="module")
def ConduitBridge(tmp_db):
    mod = sys.modules["cato.tools.conduit_bridge"]
    return mod.ConduitBridge


@pytest.fixture(scope="module")
def ConduitBillingLedger(tmp_db):
    mod = sys.modules["cato.tools.conduit_bridge"]
    return mod.ConduitBillingLedger


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _count_rows(db: Path, table: str, session_id: str) -> int:
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAuditLog:
    """Unit tests for audit.AuditLog."""

    def test_connect_creates_table(self, tmp_db, AuditLog):
        log = AuditLog(db_path=tmp_db)
        log.connect()
        conn = sqlite3.connect(str(tmp_db))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "audit_log" in tables

    def test_log_returns_int_row_id(self, tmp_db, AuditLog):
        log = AuditLog(db_path=tmp_db)
        row_id = log.log(
            session_id="test-log-1",
            action_type="tool_call",
            tool_name="browser.navigate",
            inputs={"url": "https://example.com"},
            outputs={"title": "Example"},
            cost_cents=0,
        )
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_verify_chain_true_after_single_entry(self, tmp_db, AuditLog):
        log = AuditLog(db_path=tmp_db)
        log.log(
            session_id="test-chain-single",
            action_type="tool_call",
            tool_name="browser.click",
            inputs={"selector": "#btn"},
            outputs={"success": True},
        )
        assert log.verify_chain("test-chain-single") is True

    def test_verify_chain_true_after_sequence(self, tmp_db, AuditLog):
        log = AuditLog(db_path=tmp_db)
        sid = "test-chain-seq"
        actions = [
            ("browser.navigate", {"url": "https://a.com"}, {"title": "A"}),
            ("browser.click",    {"selector": "#x"},       {"success": True}),
            ("browser.type",     {"selector": "#q", "text": "hello"}, {"typed": "hello"}),
            ("browser.navigate", {"url": "https://b.com"}, {"title": "B"}),
            ("browser.screenshot", {}, {"path": "/tmp/s.png"}),
        ]
        for tool, inp, out in actions:
            log.log(session_id=sid, action_type="tool_call", tool_name=tool,
                    inputs=inp, outputs=out)
        assert log.verify_chain(sid) is True

    def test_verify_chain_false_on_tamper(self, tmp_db, AuditLog):
        log = AuditLog(db_path=tmp_db)
        sid = "test-chain-tamper"
        log.log(session_id=sid, action_type="tool_call", tool_name="browser.navigate",
                inputs={"url": "https://evil.com"}, outputs={})
        # Tamper with the row_hash directly in the database
        conn = sqlite3.connect(str(tmp_db))
        conn.execute(
            "UPDATE audit_log SET row_hash = 'aaaa' WHERE session_id = ?", (sid,)
        )
        conn.commit()
        conn.close()
        assert log.verify_chain(sid) is False

    def test_sensitive_inputs_redacted(self, tmp_db, AuditLog):
        log = AuditLog(db_path=tmp_db)
        sid = "test-redact"
        row_id = log.log(
            session_id=sid,
            action_type="tool_call",
            tool_name="browser.type",
            inputs={"selector": "#pw", "password": "s3cr3t"},
            outputs={"success": True},
        )
        conn = sqlite3.connect(str(tmp_db))
        row = conn.execute(
            "SELECT inputs_json FROM audit_log WHERE id = ?", (row_id,)
        ).fetchone()
        conn.close()
        import json
        data = json.loads(row[0])
        assert data["password"] == "[REDACTED]"
        assert data["selector"] == "#pw"

    def test_session_summary_counts_correctly(self, tmp_db, AuditLog):
        log = AuditLog(db_path=tmp_db)
        sid = "test-summary"
        for i in range(3):
            log.log(session_id=sid, action_type="tool_call", tool_name=f"browser.action{i}",
                    inputs={}, outputs={}, cost_cents=i)
        summary = log.session_summary(sid)
        assert summary["action_count"] == 3
        assert summary["count"] == 3
        assert summary["total_cost_cents"] == 0 + 1 + 2


class TestAuditMethod:
    """Tests that ConduitBridge._audit() writes to BOTH tables."""

    def _make_bridge(self, tmp_db, ConduitBridge):
        # Config-driven constructor: dict + session_id
        cfg = {
            "conduit_budget_per_session": 9999,
            "data_dir": str(tmp_db.parent),
        }
        bridge = ConduitBridge(cfg, "audit-method-test")
        # Connect both ledger and audit_log manually (no browser needed)
        bridge._ledger.connect()
        bridge._audit_log.connect()
        return bridge

    def test_audit_writes_billing_ledger(self, tmp_db, ConduitBridge):
        bridge = self._make_bridge(tmp_db, ConduitBridge)
        sid = bridge._session_id
        bridge._audit("navigate", {"url": "https://x.com"}, {"title": "X"},
                      url_or_selector="https://x.com")
        count = _count_rows(tmp_db, "conduit_billing", sid)
        assert count >= 1

    def test_audit_writes_audit_log(self, tmp_db, ConduitBridge):
        bridge = self._make_bridge(tmp_db, ConduitBridge)
        sid = bridge._session_id
        bridge._audit("click", {"selector": "#btn"}, {"success": True},
                      url_or_selector="#btn")
        count = _count_rows(tmp_db, "audit_log", sid)
        assert count >= 1

    def test_audit_writes_both_tables_same_action(self, tmp_db, ConduitBridge):
        """One _audit() call must produce one row in EACH table."""
        import uuid
        sid = f"both-tables-{uuid.uuid4().hex[:8]}"
        cfg = {"conduit_budget_per_session": 9999, "data_dir": str(tmp_db.parent)}
        bridge = ConduitBridge(cfg, sid)
        bridge._ledger.connect()
        bridge._audit_log.connect()

        bridge._audit("screenshot", {}, {"path": "/tmp/s.png"})

        billing_count = _count_rows(tmp_db, "conduit_billing", sid)
        audit_count = _count_rows(tmp_db, "audit_log", sid)
        assert billing_count == 1, f"Expected 1 billing row, got {billing_count}"
        assert audit_count == 1, f"Expected 1 audit_log row, got {audit_count}"

    def test_audit_hash_chain_valid_after_sequence(self, tmp_db, ConduitBridge, AuditLog):
        import uuid
        sid = f"chain-seq-{uuid.uuid4().hex[:8]}"
        cfg = {"conduit_budget_per_session": 9999, "data_dir": str(tmp_db.parent)}
        bridge = ConduitBridge(cfg, sid)
        bridge._ledger.connect()
        bridge._audit_log.connect()

        for action in ["navigate", "click", "type", "screenshot"]:
            bridge._audit(action, {}, {"success": True})

        log = AuditLog(db_path=tmp_db)
        assert log.verify_chain(sid) is True

    def test_audit_error_recorded_in_chain(self, tmp_db, ConduitBridge, AuditLog):
        import uuid
        sid = f"error-chain-{uuid.uuid4().hex[:8]}"
        cfg = {"conduit_budget_per_session": 9999, "data_dir": str(tmp_db.parent)}
        bridge = ConduitBridge(cfg, sid)
        bridge._ledger.connect()
        bridge._audit_log.connect()

        bridge._audit("click", {"selector": "#missing"}, {"success": False},
                      error="Element not found")

        log = AuditLog(db_path=tmp_db)
        assert log.verify_chain(sid) is True
        count = _count_rows(tmp_db, "audit_log", sid)
        assert count == 1


class TestBudgetEnforcement:
    """Budget enforcement still works via _audit()."""

    def test_budget_exceeded_raises(self, tmp_db, ConduitBridge):
        from sys import modules
        BudgetExceededError = modules["cato.tools.conduit_bridge"].BudgetExceededError

        import uuid
        sid = f"budget-{uuid.uuid4().hex[:8]}"
        cfg = {"conduit_budget_per_session": 0, "data_dir": str(tmp_db.parent)}
        bridge = ConduitBridge(cfg, sid)
        bridge._ledger.connect()
        bridge._audit_log.connect()

        # ACTION_COSTS are all 0, so even a 0-budget bridge won't exceed.
        # Set cost manually to test overflow.
        from sys import modules as _mods
        orig = _mods["cato.tools.conduit_bridge"].ACTION_COSTS.copy()
        _mods["cato.tools.conduit_bridge"].ACTION_COSTS["navigate"] = 1
        try:
            with pytest.raises(BudgetExceededError):
                bridge._audit("navigate", {}, {}, url_or_selector="https://x.com")
        finally:
            _mods["cato.tools.conduit_bridge"].ACTION_COSTS["navigate"] = 0
