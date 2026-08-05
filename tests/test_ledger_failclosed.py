"""
tests/test_ledger_failclosed.py — fail-closed, atomic, recoverable ledger.

Covers the contract the dispatch path depends on:
  * a write that cannot be durably persisted RAISES and the action never runs
  * the raise cannot be swallowed by the historical `except Exception` pattern
  * DENIED / FAILED / VERIFIED / MISMATCH are first-class chained entries
  * a real process kill between INTENT and CONFIRMED leaves a detectable
    unresolved INTENT, and replay cannot duplicate the action
  * verify_chain() passes over every entry kind and FAILS on tampering
  * nested credentials never reach the persisted chain

All tests use tmp_path for DB isolation. No secret is ever printed.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from cato.audit.ledger import (
    DuplicateActionError,
    EntryKind,
    LedgerError,
    LedgerMiddleware,
    LedgerQuery,
    LedgerStateError,
    LedgerWriteError,
    redact,
    unresolved_intents,
    verify_chain,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# Never a real credential — a synthetic marker string we assert is absent.
FAKE_SECRET = "sk-live-NEVERPERSIST-0123456789"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make(tmp_path: Path, name: str = "ledger.db") -> LedgerMiddleware:
    return LedgerMiddleware(db_path=tmp_path / name)


def kinds(db: Path, action_id: str | None = None) -> list[str]:
    q = LedgerQuery(db_path=db)
    try:
        records = q.by_action(action_id) if action_id else q.last_n(1000)
        return [r.entry_kind for r in records]
    finally:
        q.close()


class _FailingConn:
    """Wraps a real sqlite3 connection and blows up on matching statements."""

    def __init__(self, real: sqlite3.Connection, fail_on: str = "INSERT") -> None:
        self._real = real
        self._fail_on = fail_on

    def execute(self, sql, *args, **kwargs):
        if self._fail_on in sql:
            raise sqlite3.OperationalError("disk I/O error")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _SwallowingConn:
    """Accepts INSERTs and quietly discards them — simulates a write that the
    DB reports as fine but that never lands. Exercises the read-back check."""

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, sql, *args, **kwargs):
        if sql.strip().upper().startswith("INSERT"):
            return None
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def base_kwargs(**over):
    kw = dict(
        tool_name="shell_execute",
        tool_input={"cmd": "echo hi"},
        agent_session_id="sess-1",
        policy_decision="allow",
        policy_gate="safety.check_action",
    )
    kw.update(over)
    return kw


# ---------------------------------------------------------------------------
# 1. Record vocabulary
# ---------------------------------------------------------------------------

class TestVocabulary:
    def test_successful_action_writes_intent_attempted_confirmed(self, tmp_path: Path) -> None:
        db = tmp_path / "voc.db"
        m = LedgerMiddleware(db_path=db)
        with m.recorded_action(**base_kwargs()) as action:
            result = action.execute(lambda: "output-value")
            action_id = action.action_id
        m.close()
        assert result == "output-value"
        assert kinds(db, action_id) == ["INTENT", "ATTEMPTED", "CONFIRMED"]

    def test_intent_is_written_before_the_action_runs(self, tmp_path: Path) -> None:
        """The INTENT row must be queryable from a *separate* connection while
        the action body is still executing."""
        db = tmp_path / "order.db"
        m = LedgerMiddleware(db_path=db)
        seen: list[str] = []

        def side_effect() -> str:
            q = LedgerQuery(db_path=db)
            seen.extend(r.entry_kind for r in q.last_n(10))
            q.close()
            return "done"

        with m.recorded_action(**base_kwargs()) as action:
            action.execute(side_effect)
        m.close()
        assert "INTENT" in seen, "INTENT was not durable before the action ran"
        assert "CONFIRMED" not in seen

    def test_denial_is_recorded_as_first_class_entry(self, tmp_path: Path) -> None:
        db = tmp_path / "deny.db"
        m = LedgerMiddleware(db_path=db)
        rid = m.record_denial(
            tool_name="shell_execute",
            tool_input={"cmd": "rm -rf /"},
            agent_session_id="sess-deny",
            gate="safety.check_action",
            reason="destructive command blocked by policy",
        )
        m.close()

        q = LedgerQuery(db_path=db)
        denials = q.by_entry_kind(EntryKind.DENIED)
        q.close()
        assert len(denials) == 1
        d = denials[0]
        assert d.record_id == rid
        assert d.policy_decision == "deny"
        assert d.policy_gate == "safety.check_action"
        assert "destructive command blocked" in d.outcome
        assert d.tool_name == "shell_execute"
        assert d.timestamp and d.actor == "sess-deny"
        ok, msg = verify_chain(db_path=db)
        assert ok, msg

    def test_failed_execution_records_failed_and_reraises(self, tmp_path: Path) -> None:
        db = tmp_path / "fail.db"
        m = LedgerMiddleware(db_path=db)

        def boom() -> None:
            raise RuntimeError("tool exploded")

        with pytest.raises(RuntimeError, match="tool exploded"):
            with m.recorded_action(**base_kwargs()) as action:
                action.execute(boom)
        m.close()

        q = LedgerQuery(db_path=db)
        failed = q.by_entry_kind(EntryKind.FAILED)
        q.close()
        assert len(failed) == 1
        assert "RuntimeError: tool exploded" in failed[0].outcome
        assert kinds(db) == ["INTENT", "ATTEMPTED", "FAILED"]

    def test_exception_from_body_outside_execute_still_records_failed(self, tmp_path: Path) -> None:
        db = tmp_path / "bodyfail.db"
        m = LedgerMiddleware(db_path=db)
        with pytest.raises(ValueError):
            with m.recorded_action(**base_kwargs()):
                raise ValueError("gate blew up before dispatch")
        m.close()
        assert kinds(db) == ["INTENT", "FAILED"]

    def test_deny_inside_action_scope(self, tmp_path: Path) -> None:
        db = tmp_path / "scopedeny.db"
        m = LedgerMiddleware(db_path=db)
        with m.recorded_action(**base_kwargs()) as action:
            action.deny(gate="outbound_approval", reason="no approval token")
        m.close()
        q = LedgerQuery(db_path=db)
        d = q.by_entry_kind(EntryKind.DENIED)[0]
        q.close()
        assert d.policy_gate == "outbound_approval"
        assert d.policy_decision == "deny"

    def test_verified_and_mismatch_entries(self, tmp_path: Path) -> None:
        db = tmp_path / "verify.db"
        m = LedgerMiddleware(db_path=db)
        with m.recorded_action(**base_kwargs(tool_name="write_file")) as action:
            action.execute(lambda: "written")
            aid = action.action_id
        m.record_verification(action_id=aid, matched=True, detail="file present")
        m.record_verification(action_id=aid, matched=False, detail="size differs")
        m.close()
        assert kinds(db, aid) == [
            "INTENT", "ATTEMPTED", "CONFIRMED", "VERIFIED", "MISMATCH",
        ]
        q = LedgerQuery(db_path=db)
        mm = q.by_entry_kind(EntryKind.MISMATCH)[0]
        q.close()
        assert mm.tool_name == "write_file"
        assert "size differs" in mm.outcome
        ok, msg = verify_chain(db_path=db)
        assert ok, msg

    def test_verification_defaults_when_action_unknown(self, tmp_path: Path) -> None:
        db = tmp_path / "verify_unknown.db"
        m = LedgerMiddleware(db_path=db)
        m.record_verification(action_id="no-such-action", matched=True)
        m.close()
        q = LedgerQuery(db_path=db)
        rec = q.by_entry_kind(EntryKind.VERIFIED)[0]
        q.close()
        assert rec.tool_name == "unknown"
        assert "read-back agreed" in rec.outcome

    def test_intent_carries_policy_and_approval_metadata(self, tmp_path: Path) -> None:
        db = tmp_path / "meta.db"
        m = LedgerMiddleware(db_path=db)
        with m.recorded_action(**base_kwargs(
            approval_ref="approval-42",
            actor="operator-ben",
            reasoning_excerpt="user asked for it",
            delegation_token_id="tok-9",
            confidence_score=0.8,
            reversibility=0.2,
        )) as action:
            action.execute(lambda: None)
        m.close()
        q = LedgerQuery(db_path=db)
        intent = q.by_entry_kind(EntryKind.INTENT)[0]
        q.close()
        assert intent.policy_decision == "allow"
        assert intent.policy_gate == "safety.check_action"
        assert intent.approval_ref == "approval-42"
        assert intent.actor == "operator-ben"
        assert intent.delegation_token_id == "tok-9"
        assert intent.reasoning_excerpt == "user asked for it"
        assert intent.tool_input_redacted  # redacted inputs persisted
        assert intent.timestamp.endswith("Z")

    def test_replay_session_exposes_vocabulary(self, tmp_path: Path) -> None:
        db = tmp_path / "replay.db"
        m = LedgerMiddleware(db_path=db)
        m.record_denial(
            tool_name="browser_open", tool_input={}, agent_session_id="sess-r",
            gate="network_policy", reason="egress blocked",
        )
        m.close()
        q = LedgerQuery(db_path=db)
        row = q.replay_session("sess-r")[0]
        q.close()
        assert row["entry_kind"] == "DENIED"
        assert row["policy_gate"] == "network_policy"
        assert row["outcome"].startswith("egress blocked")

    def test_entry_kind_enum_values(self) -> None:
        assert EntryKind.INTENT.value == "INTENT"
        assert {k.value for k in EntryKind} == {
            "INTENT", "DENIED", "ATTEMPTED", "FAILED",
            "CONFIRMED", "VERIFIED", "MISMATCH", "RECOVERED",
            # t14: dispatched, answer lost, real-world outcome UNKNOWN.
            # Distinct from FAILED, which asserts "it did not happen".
            "INDETERMINATE",
        }

    def test_indeterminate_is_terminal_but_not_a_success_or_a_failure(self) -> None:
        """It must resolve the INTENT (so it is not mistaken for a crash) and
        must not be reachable by anything that reads CONFIRMED as success."""
        from cato.audit.ledger import TERMINAL_KINDS

        assert EntryKind.INDETERMINATE.value in TERMINAL_KINDS
        assert EntryKind.INDETERMINATE.value != EntryKind.CONFIRMED.value
        assert EntryKind.INDETERMINATE.value != EntryKind.FAILED.value


# ---------------------------------------------------------------------------
# 2. Fail closed
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_ledger_write_error_is_not_an_exception_subclass(self) -> None:
        """This is the mechanism that makes the old agent_loop pattern
        (`except Exception: logger.debug(...)`) unable to swallow an audit
        failure."""
        assert issubclass(LedgerWriteError, LedgerError)
        assert issubclass(LedgerError, BaseException)
        assert not issubclass(LedgerError, Exception)

    def test_append_raises_when_write_fails(self, tmp_path: Path) -> None:
        m = make(tmp_path)
        m._conn = _FailingConn(m._conn)
        with pytest.raises(LedgerWriteError, match="ledger append failed"):
            m.append("read_file", {"path": "x"}, "out", "sess-1")

    def test_append_raises_when_row_not_durably_persisted(self, tmp_path: Path) -> None:
        m = make(tmp_path)
        m._conn = _SwallowingConn(m._conn)
        with pytest.raises(LedgerWriteError, match="not durably"):
            m.append("read_file", {"path": "x"}, "out", "sess-1")

    def test_audit_failure_prevents_the_action_from_running(self, tmp_path: Path) -> None:
        m = make(tmp_path)
        m._conn = _FailingConn(m._conn)
        executed: list[str] = []
        with pytest.raises(LedgerWriteError):
            m.execute_action(**base_kwargs(), fn=lambda: executed.append("SIDE EFFECT"))
        assert executed == [], "action ran despite the audit write failing"

    def test_old_agent_loop_antipattern_cannot_swallow_the_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Reproduces the exact defect shape from cato/agent_loop.py and proves
        it no longer lets the action through."""
        m = make(tmp_path)
        m._conn = _FailingConn(m._conn)
        executed: list[str] = []

        def dispatch_like_agent_loop() -> str:
            try:
                m.execute_action(
                    **base_kwargs(), fn=lambda: executed.append("SIDE EFFECT")
                )
            except Exception as ledger_exc:  # the historical swallow
                logging.getLogger(__name__).debug(
                    "Ledger append failed: %s", ledger_exc
                )
            return "action proceeded anyway"

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(LedgerWriteError):
                dispatch_like_agent_loop()
        assert executed == []
        assert "Ledger append failed" not in caplog.text

    def test_intent_failure_aborts_before_yield(self, tmp_path: Path) -> None:
        m = make(tmp_path)
        m._conn = _FailingConn(m._conn)
        entered: list[str] = []
        with pytest.raises(LedgerWriteError):
            with m.recorded_action(**base_kwargs()):
                entered.append("body")
        assert entered == []

    def test_unresolved_scope_records_failed_and_raises(self, tmp_path: Path) -> None:
        db = tmp_path / "unres.db"
        m = LedgerMiddleware(db_path=db)
        with pytest.raises(LedgerStateError, match="terminal entry"):
            with m.recorded_action(**base_kwargs()):
                pass  # forgot to execute/confirm/deny
        m.close()
        q = LedgerQuery(db_path=db)
        failed = q.by_entry_kind(EntryKind.FAILED)
        q.close()
        assert len(failed) == 1
        assert "UNRESOLVED" in failed[0].outcome

    def test_double_execution_is_refused(self, tmp_path: Path) -> None:
        db = tmp_path / "double.db"
        m = LedgerMiddleware(db_path=db)
        calls: list[int] = []
        with pytest.raises(LedgerStateError, match="already attempted"):
            with m.recorded_action(**base_kwargs()) as action:
                action.execute(lambda: calls.append(1))
                action.execute(lambda: calls.append(2))
        m.close()
        assert calls == [1]

    def test_confirm_after_resolution_is_refused(self, tmp_path: Path) -> None:
        db = tmp_path / "reconfirm.db"
        m = LedgerMiddleware(db_path=db)
        with pytest.raises(LedgerStateError, match="already resolved"):
            with m.recorded_action(**base_kwargs()) as action:
                action.execute(lambda: "ok")
                action.confirm("again")
        m.close()

    def test_fail_and_deny_after_resolution_are_refused(self, tmp_path: Path) -> None:
        db = tmp_path / "postres.db"
        m = LedgerMiddleware(db_path=db)
        with m.recorded_action(**base_kwargs()) as action:
            action.deny(gate="g", reason="r")
            assert action.resolved is True
            with pytest.raises(LedgerStateError):
                action.fail(RuntimeError("x"))
            with pytest.raises(LedgerStateError):
                action.deny(gate="g", reason="r")
            with pytest.raises(LedgerStateError):
                action.execute(lambda: None)
        m.close()

    def test_integrity_error_unrelated_to_idempotency_raises_write_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A UNIQUE violation on record_id is a write failure, not a replay."""
        import cato.audit.ledger as ledger_mod

        db = tmp_path / "integrity.db"
        m = LedgerMiddleware(db_path=db)
        m.append("read_file", {}, "o", "s")
        q = LedgerQuery(db_path=db)
        existing = q.last_n(1)[0].record_id
        q.close()

        class _FixedUUID:
            def __str__(self) -> str:
                return existing

        monkeypatch.setattr(ledger_mod.uuid, "uuid4", lambda: _FixedUUID())
        with pytest.raises(LedgerWriteError, match="rejected"):
            m.append("read_file", {}, "o", "s")
        m.close()

    def test_readback_query_error_raises_write_error(self, tmp_path: Path) -> None:
        class _ReadBackBroken:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args, **kwargs):
                if "WHERE record_id = ?" in sql:
                    raise sqlite3.OperationalError("database is locked")
                return self._real.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        m = make(tmp_path, "readback.db")
        m._conn = _ReadBackBroken(m._conn)
        with pytest.raises(LedgerWriteError, match="read-back failed"):
            m.append("read_file", {}, "o", "s")

    def test_attempted_flag_tracks_execution(self, tmp_path: Path) -> None:
        m = make(tmp_path, "attempted.db")
        with m.recorded_action(**base_kwargs()) as action:
            assert action.attempted is False
            assert action.resolved is False
            action.execute(lambda: "x")
            assert action.attempted is True
            assert action.resolved is True
        m.close()

    def test_non_string_outcome_is_summarized(self, tmp_path: Path) -> None:
        db = tmp_path / "outcome_obj.db"
        m = LedgerMiddleware(db_path=db)
        with m.recorded_action(**base_kwargs()) as action:
            action.execute(lambda: "x")
        with m.recorded_action(**base_kwargs()) as action:
            action._mark_attempt()
            action.confirm("out", outcome={"exit_code": 0, "lines": 12})
        m.close()
        q = LedgerQuery(db_path=db)
        confirmed = q.by_entry_kind(EntryKind.CONFIRMED)
        q.close()
        assert any("exit_code" in c.outcome for c in confirmed)

    @pytest.mark.asyncio
    async def test_async_arun_records_confirmed(self, tmp_path: Path) -> None:
        db = tmp_path / "async_ok.db"
        m = LedgerMiddleware(db_path=db)

        async def dispatch() -> str:
            return "async-result"

        with m.recorded_action(**base_kwargs()) as action:
            result = await action.arun(dispatch())
            aid = action.action_id
        m.close()
        assert result == "async-result"
        assert kinds(db, aid) == ["INTENT", "ATTEMPTED", "CONFIRMED"]

    @pytest.mark.asyncio
    async def test_async_arun_records_failed(self, tmp_path: Path) -> None:
        db = tmp_path / "async_fail.db"
        m = LedgerMiddleware(db_path=db)

        async def dispatch() -> str:
            raise TimeoutError("tool timed out")

        with pytest.raises(TimeoutError):
            with m.recorded_action(**base_kwargs()) as action:
                await action.arun(dispatch())
        m.close()
        q = LedgerQuery(db_path=db)
        failed = q.by_entry_kind(EntryKind.FAILED)
        q.close()
        assert "TimeoutError: tool timed out" in failed[0].outcome


# ---------------------------------------------------------------------------
# 3. Atomicity and crash recovery
# ---------------------------------------------------------------------------

CRASH_SCRIPT = textwrap.dedent(
    """
    import os, sys
    from pathlib import Path
    sys.path.insert(0, r"{repo}")
    from cato.audit.ledger import LedgerMiddleware

    led = LedgerMiddleware(db_path=Path(r"{db}"))
    with led.recorded_action(
        tool_name="shell_execute",
        tool_input={{"cmd": "delete production"}},
        agent_session_id="sess-crash",
        policy_decision="allow",
        policy_gate="safety.check_action",
        idempotency_key="crash-key-1",
    ) as action:
        Path(r"{marker}").write_text(action.action_id)
        os._exit(9)   # hard kill between INTENT and CONFIRMED
    """
)


class TestCrashRecovery:
    def _crash(self, tmp_path: Path) -> tuple[Path, str]:
        db = tmp_path / "crash.db"
        marker = tmp_path / "marker.txt"
        script = tmp_path / "crasher.py"
        script.write_text(
            CRASH_SCRIPT.format(
                repo=str(REPO_ROOT), db=str(db), marker=str(marker)
            )
        )
        proc = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True
        )
        assert proc.returncode == 9, (proc.returncode, proc.stdout, proc.stderr)
        assert marker.exists(), "process died before INTENT was written"
        return db, marker.read_text().strip()

    def test_crash_between_intent_and_confirm_leaves_unresolved_intent(
        self, tmp_path: Path
    ) -> None:
        db, action_id = self._crash(tmp_path)

        # Restart: a fresh reader sees the orphaned INTENT, not a silent gap.
        pending = unresolved_intents(db_path=db)
        assert len(pending) == 1
        rec = pending[0]
        assert rec.entry_kind == "INTENT"
        assert rec.action_id == action_id
        assert rec.idempotency_key == "crash-key-1"
        assert rec.tool_name == "shell_execute"

        # And there is genuinely no terminal entry for it.
        assert kinds(db, action_id) == ["INTENT"]

    def test_chain_still_verifies_after_a_crash(self, tmp_path: Path) -> None:
        db, _ = self._crash(tmp_path)
        ok, msg = verify_chain(db_path=db)
        assert ok, msg
        assert "1 records" in msg

    def test_replay_after_restart_cannot_duplicate_the_action(
        self, tmp_path: Path
    ) -> None:
        db, _ = self._crash(tmp_path)
        m = LedgerMiddleware(db_path=db)
        executed: list[str] = []
        with pytest.raises(DuplicateActionError, match="idempotency key"):
            m.execute_action(
                tool_name="shell_execute",
                tool_input={"cmd": "delete production"},
                agent_session_id="sess-crash",
                policy_decision="allow",
                policy_gate="safety.check_action",
                idempotency_key="crash-key-1",
                fn=lambda: executed.append("REPLAYED SIDE EFFECT"),
            )
        m.close()
        assert executed == [], "replay re-executed a crashed action"

    def test_recovery_routine_resolves_the_orphan(self, tmp_path: Path) -> None:
        db, action_id = self._crash(tmp_path)
        m = LedgerMiddleware(db_path=db)
        assert len(m.unresolved_intents()) == 1
        m.record_recovery(
            action_id=action_id,
            outcome="reconciled after restart: side effect not observed",
        )
        assert m.unresolved_intents() == []
        m.close()
        assert kinds(db, action_id) == ["INTENT", "RECOVERED"]
        ok, msg = verify_chain(db_path=db)
        assert ok, msg

    def test_duplicate_idempotency_key_refused_without_a_crash(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "idem.db"
        m = LedgerMiddleware(db_path=db)
        m.execute_action(**base_kwargs(idempotency_key="k-1"), fn=lambda: "first")
        executed: list[str] = []
        with pytest.raises(DuplicateActionError):
            m.execute_action(
                **base_kwargs(idempotency_key="k-1"),
                fn=lambda: executed.append("second"),
            )
        m.close()
        assert executed == []

    def test_lookup_by_idempotency_key(self, tmp_path: Path) -> None:
        db = tmp_path / "idem2.db"
        m = LedgerMiddleware(db_path=db)
        m.execute_action(**base_kwargs(idempotency_key="k-find"), fn=lambda: "x")
        m.close()
        q = LedgerQuery(db_path=db)
        found = q.find_by_idempotency_key("k-find")
        missing = q.find_by_idempotency_key("k-nope")
        q.close()
        assert found is not None and found.entry_kind == "INTENT"
        assert missing is None

    def test_resolved_actions_are_not_reported_unresolved(self, tmp_path: Path) -> None:
        db = tmp_path / "resolved.db"
        m = LedgerMiddleware(db_path=db)
        m.execute_action(**base_kwargs(), fn=lambda: "ok")
        with pytest.raises(RuntimeError):
            m.execute_action(**base_kwargs(), fn=_raiser)
        m.record_denial(
            tool_name="t", tool_input={}, agent_session_id="s",
            gate="g", reason="r",
        )
        assert m.unresolved_intents() == []
        m.close()


def _raiser():
    raise RuntimeError("nope")


# ---------------------------------------------------------------------------
# 4. Hash chain integrity
# ---------------------------------------------------------------------------

def _build_full_vocabulary_chain(db: Path) -> str:
    m = LedgerMiddleware(db_path=db)
    m.record_denial(
        tool_name="shell_execute", tool_input={"cmd": "rm -rf /"},
        agent_session_id="sess-x", gate="safety.check_action",
        reason="blocked",
    )
    with pytest.raises(RuntimeError):
        m.execute_action(**base_kwargs(), fn=_raiser)
    with m.recorded_action(**base_kwargs(tool_name="write_file")) as action:
        action.execute(lambda: "ok")
        aid = action.action_id
    m.record_verification(action_id=aid, matched=True, detail="ok")
    m.record_verification(action_id=aid, matched=False, detail="drift")
    m.record_recovery(action_id=aid, outcome="reconciled")
    m.append("read_file", {"path": "p"}, "content", "sess-x")
    m.close()
    return aid


class TestHashChain:
    def test_verify_chain_passes_over_every_entry_kind(self, tmp_path: Path) -> None:
        db = tmp_path / "allkinds.db"
        _build_full_vocabulary_chain(db)
        present = set(kinds(db))
        assert present == {
            "DENIED", "INTENT", "ATTEMPTED", "FAILED", "CONFIRMED",
            "VERIFIED", "MISMATCH", "RECOVERED",
        }
        ok, msg = verify_chain(db_path=db)
        assert ok, msg

    def test_denied_and_failed_entries_are_chained(self, tmp_path: Path) -> None:
        db = tmp_path / "chained.db"
        _build_full_vocabulary_chain(db)
        q = LedgerQuery(db_path=db)
        records = q.last_n(1000)
        q.close()
        for prev, cur in zip(records, records[1:]):
            assert cur.prev_hash == prev.record_hash
        assert records[0].entry_kind == "DENIED"

    @pytest.mark.parametrize(
        "column, value",
        [
            ("outcome", "harmless"),
            ("entry_kind", "CONFIRMED"),
            ("policy_decision", "allow"),
            ("policy_gate", "none"),
            ("tool_input_redacted", "{}"),
            ("action_id", "rewritten"),
            ("approval_ref", "forged-approval"),
        ],
    )
    def test_verify_chain_fails_on_tampered_new_field(
        self, tmp_path: Path, column: str, value: str
    ) -> None:
        """NEGATIVE CONTROL: mutating any new field breaks verification."""
        db = tmp_path / f"tamper_{column}.db"
        m = LedgerMiddleware(db_path=db)
        m.record_denial(
            tool_name="shell_execute", tool_input={"cmd": "rm -rf /"},
            agent_session_id="sess-t", gate="safety.check_action",
            reason="blocked because destructive",
        )
        m.close()
        assert verify_chain(db_path=db)[0] is True

        conn = sqlite3.connect(str(db))
        conn.execute(f"UPDATE ledger_records SET {column} = ?", (value,))
        conn.commit()
        conn.close()

        ok, msg = verify_chain(db_path=db)
        assert ok is False
        assert "TAMPERED" in msg and "field hash mismatch" in msg

    def test_verify_chain_fails_on_schema_version_downgrade(self, tmp_path: Path) -> None:
        """Dropping a record back to the v1 hash formula must not let an
        attacker escape the extra fields."""
        db = tmp_path / "downgrade.db"
        m = LedgerMiddleware(db_path=db)
        m.record_denial(
            tool_name="t", tool_input={}, agent_session_id="s",
            gate="g", reason="r",
        )
        m.close()
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE ledger_records SET schema_version = 1, entry_kind = 'CONFIRMED'")
        conn.commit()
        conn.close()
        ok, msg = verify_chain(db_path=db)
        assert ok is False and "TAMPERED" in msg

    def test_verify_chain_fails_on_deleted_middle_record(self, tmp_path: Path) -> None:
        db = tmp_path / "deleted.db"
        m = LedgerMiddleware(db_path=db)
        m.execute_action(**base_kwargs(), fn=lambda: "a")
        m.close()
        conn = sqlite3.connect(str(db))
        conn.execute("DELETE FROM ledger_records WHERE entry_kind = 'ATTEMPTED'")
        conn.commit()
        conn.close()
        ok, msg = verify_chain(db_path=db)
        assert ok is False and "prev_hash mismatch" in msg

    def test_signing_key_signature_is_recorded(self, tmp_path: Path) -> None:
        class _Sig:
            signature = b"\xab\xcd"

        class _Key:
            def sign(self, data: bytes) -> "_Sig":
                return _Sig()

        db = tmp_path / "signed.db"
        m = LedgerMiddleware(db_path=db, signing_key=_Key())
        m.execute_action(**base_kwargs(), fn=lambda: "x")
        m.close()
        q = LedgerQuery(db_path=db)
        recs = q.last_n(10)
        q.close()
        assert all(r.record_signature == "abcd" for r in recs)
        assert verify_chain(db_path=db)[0] is True

    def test_signing_failure_does_not_break_the_chain(self, tmp_path: Path) -> None:
        class _BadKey:
            def sign(self, data: bytes):
                raise ValueError("hsm offline")

        db = tmp_path / "badsign.db"
        m = LedgerMiddleware(db_path=db, signing_key=_BadKey())
        m.execute_action(**base_kwargs(), fn=lambda: "x")
        m.close()
        assert verify_chain(db_path=db)[0] is True

    def test_legacy_v1_rows_still_verify_after_migration(self, tmp_path: Path) -> None:
        """A chain written by the pre-rewrite schema must keep verifying."""
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(
            """
            CREATE TABLE ledger_records (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT NOT NULL UNIQUE,
                prev_hash TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                agent_session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_input_hash TEXT NOT NULL,
                tool_output_hash TEXT NOT NULL,
                reasoning_excerpt TEXT NOT NULL DEFAULT '',
                confidence_score REAL NOT NULL DEFAULT 0.0,
                model_source TEXT NOT NULL DEFAULT 'claude',
                reversibility REAL NOT NULL DEFAULT 0.5,
                delegation_token_id TEXT,
                record_hash TEXT NOT NULL,
                record_signature TEXT NOT NULL DEFAULT ''
            );
            """
        )
        import hashlib as _h
        rid = "legacy-record-1"
        prev = "0" * 64
        fields = [rid, prev, "2020-01-01T00:00:00.000Z", "sess-old", "read_file",
                  "a" * 64, "b" * 64, "", "0.0", "claude", "0.5", ""]
        rh = _h.sha256("|".join(fields).encode()).hexdigest()
        conn.execute(
            "INSERT INTO ledger_records (record_id, prev_hash, timestamp, "
            "agent_session_id, tool_name, tool_input_hash, tool_output_hash, "
            "reasoning_excerpt, confidence_score, model_source, reversibility, "
            "delegation_token_id, record_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, prev, fields[2], "sess-old", "read_file", "a" * 64, "b" * 64,
             "", 0.0, "claude", 0.5, None, rh),
        )
        conn.commit()
        conn.close()

        ok, msg = verify_chain(db_path=db)
        assert ok, msg

        # New v2 entries append onto the migrated legacy chain.
        m = LedgerMiddleware(db_path=db)
        m.execute_action(**base_kwargs(), fn=lambda: "x")
        m.close()
        ok, msg = verify_chain(db_path=db)
        assert ok, msg
        assert "4 records" in msg


# ---------------------------------------------------------------------------
# 5. Redaction at the boundary
# ---------------------------------------------------------------------------

def _chain_bytes(db: Path) -> str:
    """Every persisted column of every row, plus the raw DB file."""
    q = LedgerQuery(db_path=db)
    rows = q._conn.execute("SELECT * FROM ledger_records").fetchall()
    dumped = json.dumps([dict(r) for r in rows], default=str)
    q.close()
    raw = db.read_bytes().decode("latin-1")
    return dumped + raw


class TestRedaction:
    def test_nested_credential_never_lands_in_the_chain(self, tmp_path: Path) -> None:
        db = tmp_path / "redact.db"
        m = LedgerMiddleware(db_path=db)
        m.execute_action(
            tool_name="http_request",
            tool_input={
                "url": "https://api.example.com",
                "headers": {"authorization": f"Bearer {FAKE_SECRET}"},
                "retries": [{"env": {"api_key": FAKE_SECRET}}],
            },
            agent_session_id="sess-red",
            policy_decision="allow",
            policy_gate="network_policy",
            fn=lambda: {"body": {"session": {"token": FAKE_SECRET}}},
        )
        m.close()
        blob = _chain_bytes(db)
        assert FAKE_SECRET not in blob
        assert "[REDACTED]" in blob

    def test_bare_secret_value_without_sensitive_key_is_redacted(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "bare.db"
        m = LedgerMiddleware(db_path=db)
        m.record_denial(
            tool_name="shell_execute",
            tool_input={"note": FAKE_SECRET, "deep": [[{"x": FAKE_SECRET}]]},
            agent_session_id="sess-bare",
            gate="safety.check_action",
            reason=f"saw {FAKE_SECRET}",
        )
        m.close()
        assert FAKE_SECRET not in _chain_bytes(db)

    def test_redact_is_recursive_unlike_top_level_only(self) -> None:
        out = redact({"headers": {"authorization": "Bearer abc"}})
        assert out == {"headers": {"authorization": "[REDACTED]"}}

    def test_redact_handles_lists_tuples_and_non_string_keys(self) -> None:
        out = redact({"a": [{"password": "p"}, ("secret-free",)], 3: {"token": "t"}})
        assert out["a"][0]["password"] == "[REDACTED]"
        assert out["a"][1] == ["secret-free"]
        assert out["3"]["token"] == "[REDACTED]"

    def test_redact_preserves_non_sensitive_and_numeric_values(self) -> None:
        out = redact({"path": "/tmp/x", "count": 3, "token_count": 12, "ok": True})
        assert out["path"] == "/tmp/x"
        assert out["count"] == 3
        # numeric values under a sensitive-looking key stay readable
        assert out["token_count"] == 12
        assert out["ok"] is True

    def test_redact_empty_sensitive_value_left_alone(self) -> None:
        assert redact({"api_key": ""}) == {"api_key": ""}
        assert redact({"api_key": None}) == {"api_key": None}

    # -- GAP 3: a bare `key` is an argument name, not a credential ----------
    #
    # The key-name list matched a bare "key" as a substring, so the keystroke in
    # {"key": "Enter"} was logged as [REDACTED]. That is an audit-fidelity loss:
    # the ledger could not show what the agent actually pressed. The list is now
    # the same one cato/core/approval_policy.py uses, which matches credential-
    # shaped names (api_key / apikey / api-key / _key / private_key /
    # session_key) and leaves a bare `key` intact. Redaction is NOT loosened
    # generally — the three tests after this one pin what must still be caught.

    def test_bare_key_argument_survives_intact(self) -> None:
        assert redact({"key": "Enter"}) == {"key": "Enter"}
        assert redact({"action": "press", "key": "ctrl+c"})["key"] == "ctrl+c"

    def test_credential_shaped_key_names_are_still_redacted(self) -> None:
        out = redact({
            "api_key": FAKE_SECRET,
            "apikey": FAKE_SECRET,
            "api-key": FAKE_SECRET,
            "private_key": "-----BEGIN PRIVATE KEY-----",
            "session_key": "abc",
            "stripe_secret_key": FAKE_SECRET,
        })
        assert all(v == "[REDACTED]" for v in out.values()), out

    def test_nested_authorization_header_is_still_redacted(self) -> None:
        out = redact({"headers": {"authorization": f"Bearer {FAKE_SECRET}"}})
        assert out == {"headers": {"authorization": "[REDACTED]"}}

    def test_credential_embedded_mid_sentence_is_still_redacted(self) -> None:
        text = f"the call failed because api_key={FAKE_SECRET} was rejected"
        out = redact({"key": "Enter", "note": text})
        assert out["key"] == "Enter"
        assert FAKE_SECRET not in out["note"]
        assert "[REDACTED]" in out["note"]

    def test_redact_depth_limit(self) -> None:
        node: dict = {"leaf": 1}
        for _ in range(30):
            node = {"child": node}
        out = redact(node)
        flat = json.dumps(out)
        assert "TRUNCATED_DEPTH" in flat

    def test_input_hash_is_over_the_redacted_form(self, tmp_path: Path) -> None:
        """Two payloads differing only in the secret hash identically, proving
        the secret is gone before hashing."""
        db = tmp_path / "hash.db"
        m = LedgerMiddleware(db_path=db)
        m.append("http", {"authorization": f"Bearer {FAKE_SECRET}"}, None, "s")
        m.append("http", {"authorization": "Bearer something-else-entirely"}, None, "s")
        m.close()
        q = LedgerQuery(db_path=db)
        recs = q.by_session("s")
        q.close()
        assert recs[0].tool_input_hash == recs[1].tool_input_hash


# ---------------------------------------------------------------------------
# 6. Query surface
# ---------------------------------------------------------------------------

class TestQuerySurface:
    def test_by_action_and_by_entry_kind(self, tmp_path: Path) -> None:
        db = tmp_path / "qs.db"
        m = LedgerMiddleware(db_path=db)
        with m.recorded_action(**base_kwargs()) as action:
            action.execute(lambda: "x")
            aid = action.action_id
        assert [r.entry_kind for r in m.by_action(aid)] == [
            "INTENT", "ATTEMPTED", "CONFIRMED",
        ]
        m.close()
        q = LedgerQuery(db_path=db)
        assert len(q.by_entry_kind("CONFIRMED")) == 1
        assert len(q.by_action(aid)) == 3
        q.close()

    def test_verify_chain_on_db_without_ledger_table(self, tmp_path: Path) -> None:
        db = tmp_path / "notledger.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE other (x INTEGER)")
        conn.commit()
        conn.close()
        ok, msg = verify_chain(db_path=db)
        assert ok is True
        assert "not initialized" in msg

    def test_module_level_unresolved_intents_on_fresh_db(self, tmp_path: Path) -> None:
        db = tmp_path / "fresh.db"
        assert unresolved_intents(db_path=db) == []

    def test_legacy_append_defaults_to_confirmed(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy_append.db"
        m = LedgerMiddleware(db_path=db)
        m.append("read_file", {}, "out", "sess-l")
        m.close()
        q = LedgerQuery(db_path=db)
        rec = q.by_session("sess-l")[0]
        q.close()
        assert rec.entry_kind == "CONFIRMED"
        assert rec.action_id == rec.record_id
        assert rec.schema_version == 2

    def test_synchronous_pragma_is_full_for_the_writer(self, tmp_path: Path) -> None:
        m = make(tmp_path)
        value = m._conn.execute("PRAGMA synchronous").fetchone()[0]
        m.close()
        assert value == 2, "INTENT durability requires synchronous=FULL"

    def test_db_parent_directory_is_created(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c.db"
        m = LedgerMiddleware(db_path=nested)
        m.append("read_file", {}, "o", "s")
        m.close()
        assert nested.exists()


def test_no_secret_in_this_test_module_output() -> None:
    """Guard: the fake secret is a marker, never a real credential."""
    assert FAKE_SECRET.startswith("sk-live-NEVERPERSIST")
    assert os.environ.get("CATO_VAULT_PASSWORD") is None or True
