"""t26 HIGH-3 — crash recovery must run at daemon startup, not on first message.

``_surface_unresolved_intents()`` had exactly one call site: the per-message run
path in ``AgentLoop.run``, guarded by ``_recovery_scanned``. The AgentLoop is
built lazily on the first message (``Gateway._ensure_agent_loop``), so an
operator who restarted after a crash and never sent a chat message was never
told an INTENT had been left unresolved — even though the log line says "found
at startup".

These tests use a REAL crashed subprocess to produce the orphan, then prove the
scan surfaces it with NO message sent: no AgentLoop, no gateway ingest, no LLM.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from cato.audit.recovery import (
    get_last_recovery_scan,
    reset_recovery_scan,
    run_startup_recovery_scan,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_CRASH_SCRIPT = textwrap.dedent(
    """
    import os, sys
    from pathlib import Path
    sys.path.insert(0, r"{repo}")
    from cato.audit.ledger import LedgerMiddleware

    led = LedgerMiddleware(db_path=Path(r"{db}"))
    with led.recorded_action(
        tool_name="stripe.create_charge",
        tool_input={{"amount": 4200, "currency": "usd"}},
        agent_session_id="sess-t26-crash",
        policy_decision="allow",
        policy_gate="safety.check_action",
        idempotency_key="t26-crash-key",
    ) as action:
        Path(r"{marker}").write_text(action.action_id)
        os._exit(9)   # hard kill between INTENT and CONFIRMED
    """
)


@pytest.fixture()
def crashed_ledger(tmp_path: Path) -> tuple[Path, str]:
    """A ledger DB left with exactly one orphaned INTENT by a killed process."""
    db = tmp_path / "crash.db"
    marker = tmp_path / "marker.txt"
    script = tmp_path / "crasher.py"
    script.write_text(
        _CRASH_SCRIPT.format(repo=str(REPO_ROOT), db=str(db), marker=str(marker)),
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert proc.returncode == 9, (proc.returncode, proc.stdout, proc.stderr)
    assert marker.exists(), "process died before the INTENT was written"
    return db, marker.read_text(encoding="utf-8").strip()


@pytest.fixture(autouse=True)
def _clean_scan_state():
    reset_recovery_scan()
    yield
    reset_recovery_scan()


# ---------------------------------------------------------------------------
# The scan itself
# ---------------------------------------------------------------------------

class TestRecoveryScan:
    def test_orphaned_intent_is_surfaced_without_any_message(self, crashed_ledger, caplog):
        db, action_id = crashed_ledger

        with caplog.at_level(logging.CRITICAL, logger="cato.audit.recovery"):
            result = run_startup_recovery_scan(db_path=db)

        assert result["clean"] is False
        assert result["error"] is None
        assert result["unresolved_intents"] == 1
        assert result["actions"][0]["tool_name"] == "stripe.create_charge"
        assert result["actions"][0]["action_id"] == action_id

        critical = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert critical, "an unresolved INTENT must be logged at CRITICAL"
        assert "LEDGER RECOVERY" in critical[0].getMessage()
        assert "stripe.create_charge" in critical[0].getMessage()

    def test_scan_needs_no_agent_loop_and_no_llm(self, crashed_ledger):
        """Pin the whole point: no AgentLoop is constructed, no model is called."""
        db, _ = crashed_ledger

        with (
            patch("cato.agent_loop.AgentLoop", side_effect=AssertionError("AgentLoop built")),
            patch(
                "cato.router.ModelRouter",
                side_effect=AssertionError("model router built"),
            ),
        ):
            result = run_startup_recovery_scan(db_path=db)

        assert result["unresolved_intents"] == 1

    def test_clean_ledger_reports_clean(self, tmp_path):
        from cato.audit.ledger import LedgerMiddleware

        db = tmp_path / "clean.db"
        led = LedgerMiddleware(db_path=db)
        with led.recorded_action(
            tool_name="file_read",
            tool_input={"path": "README.md"},
            agent_session_id="sess-ok",
            policy_decision="allow",
            policy_gate="safety.check_action",
            idempotency_key="t26-clean-key",
        ) as action:
            action.confirm({"ok": True})

        result = run_startup_recovery_scan(db_path=db)
        assert result["clean"] is True
        assert result["unresolved_intents"] == 0
        assert result["error"] is None

    def test_scan_failure_does_not_raise_and_is_not_reported_clean(self, tmp_path):
        """Must not block startup — but must not fake a green light either."""
        db = tmp_path / "unreadable.db"

        with patch(
            "cato.audit.ledger.LedgerQuery", side_effect=OSError("disk gone")
        ):
            result = run_startup_recovery_scan(db_path=db)

        assert result["error"] is not None
        assert result["clean"] is False

    def test_result_is_cached_for_health(self, crashed_ledger):
        db, _ = crashed_ledger
        assert get_last_recovery_scan() is None
        run_startup_recovery_scan(db_path=db)
        cached = get_last_recovery_scan()
        assert cached is not None
        assert cached["unresolved_intents"] == 1


# ---------------------------------------------------------------------------
# The startup trigger
# ---------------------------------------------------------------------------

class TestStartupTrigger:
    def test_run_daemon_scans_before_constructing_the_gateway(self):
        """Pin the call site: the scan must not depend on a lazy AgentLoop."""
        from cato import cli as cli_mod

        source = Path(cli_mod.__file__).read_text(encoding="utf-8")
        body = source.split("async def _main(", 1)[1]
        scan_at = body.find("run_startup_recovery_scan()")
        gateway_at = body.find("gateway = Gateway(")
        assert scan_at != -1, "_run_daemon must run the startup recovery scan"
        assert gateway_at != -1
        assert scan_at < gateway_at, "the scan must not wait on gateway/AgentLoop setup"

    def test_agent_loop_is_still_built_lazily(self):
        """The premise of the bug — documented so a regression is visible."""
        from cato import gateway as gateway_mod

        source = Path(gateway_mod.__file__).read_text(encoding="utf-8")
        assert "_ensure_agent_loop" in source


# ---------------------------------------------------------------------------
# The operator-visible surface
# ---------------------------------------------------------------------------

class TestHealthSurface:
    async def _health(self) -> dict:
        from cato.ui.server import create_ui_app

        app = await create_ui_app(gateway=None)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            return await resp.json()

    async def test_health_reports_unresolved_intents_as_degraded(self, crashed_ledger):
        db, action_id = crashed_ledger
        run_startup_recovery_scan(db_path=db)

        payload = await self._health()
        assert payload["status"] == "degraded"
        recovery = payload["ledger_recovery"]
        assert recovery["scanned"] is True
        assert recovery["clean"] is False
        assert recovery["unresolved_intents"] == 1
        assert recovery["actions"][0]["action_id"] == action_id

    async def test_health_is_ok_after_a_clean_scan(self, tmp_path):
        db = tmp_path / "empty.db"
        result = run_startup_recovery_scan(db_path=db)
        assert result["clean"] is True

        payload = await self._health()
        assert payload["status"] == "ok"
        assert payload["ledger_recovery"]["clean"] is True

    async def test_health_no_longer_claims_swarmsync_is_ok(self):
        """MEDIUM-4: /health reported swarmsync_ok=true while the key 401'd."""
        payload = await self._health()
        assert "swarmsync_ok" not in payload
        assert "swarmsync_status" not in payload
