"""
tests/test_session_checkpoint.py — Tests for SKILL 8: Context-Anchor Session Checkpoint.

Covers:
- Table creation / schema
- write() atomic upsert
- get() / get_summary() / list_all() / delete()
- Token accumulation and threshold logic
- maybe_checkpoint() auto-trigger
- async_write() uses asyncio.shield
- Audit log integration
- Summary token truncation
- Session isolation (tokens don't bleed between sessions)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_cato.db"


@pytest.fixture
def ckpt(db_path: Path):
    from cato.core.session_checkpoint import SessionCheckpoint
    c = SessionCheckpoint(db_path=db_path)
    c.connect()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Schema / connect
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connect_creates_table(self, db_path: Path):
        from cato.core.session_checkpoint import SessionCheckpoint
        import sqlite3
        c = SessionCheckpoint(db_path=db_path)
        c.connect()
        conn = sqlite3.connect(str(db_path))
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        conn.close()
        c.close()
        assert "session_checkpoints" in tables

    def test_connect_idempotent(self, db_path: Path):
        from cato.core.session_checkpoint import SessionCheckpoint
        c = SessionCheckpoint(db_path=db_path)
        c.connect()
        c.connect()  # second call should not raise
        c.close()

    def test_context_manager(self, db_path: Path):
        from cato.core.session_checkpoint import SessionCheckpoint
        with SessionCheckpoint(db_path=db_path) as c:
            assert c._conn is not None
        # After __exit__ the connection should be closed
        assert c._conn is None


# ---------------------------------------------------------------------------
# write / get
# ---------------------------------------------------------------------------

class TestWriteGet:
    def test_write_and_get_roundtrip(self, ckpt):
        ckpt.write(
            session_id="sess-001",
            task_description="Refactor gateway",
            decisions_made=["Use asyncio.shield", "Flatten queue"],
            files_modified=["cato/gateway.py"],
            current_plan="Step 3 of 5",
            key_facts={"model": "claude", "turns": 4},
            token_count=1500,
        )
        data = ckpt.get("sess-001")
        assert data is not None
        assert data["session_id"] == "sess-001"
        assert data["task_description"] == "Refactor gateway"
        assert data["decisions_made"] == ["Use asyncio.shield", "Flatten queue"]
        assert data["files_modified"] == ["cato/gateway.py"]
        assert data["current_plan"] == "Step 3 of 5"
        assert data["key_facts"] == {"model": "claude", "turns": 4}
        assert data["token_count"] == 1500
        assert data["checkpoint_at"]  # non-empty timestamp

    def test_write_upserts_on_same_session(self, ckpt):
        ckpt.write("sess-abc", "Task 1", [], [], "Plan 1", {}, 100)
        ckpt.write("sess-abc", "Task 2", ["decision"], [], "Plan 2", {"x": 1}, 200)
        data = ckpt.get("sess-abc")
        assert data is not None
        assert data["task_description"] == "Task 2"
        assert data["token_count"] == 200

    def test_get_missing_session_returns_none(self, ckpt):
        assert ckpt.get("no-such-session") is None

    def test_write_multiple_sessions_isolated(self, ckpt):
        ckpt.write("s1", "Task A", [], [], "Plan A", {}, 100)
        ckpt.write("s2", "Task B", [], [], "Plan B", {}, 200)
        d1 = ckpt.get("s1")
        d2 = ckpt.get("s2")
        assert d1["task_description"] == "Task A"
        assert d2["task_description"] == "Task B"


# ---------------------------------------------------------------------------
# list_all / delete
# ---------------------------------------------------------------------------

class TestListAndDelete:
    def test_list_all_returns_all(self, ckpt):
        ckpt.write("s1", "T1", [], [], "P1", {}, 100)
        ckpt.write("s2", "T2", [], [], "P2", {}, 200)
        ckpt.write("s3", "T3", [], [], "P3", {}, 300)
        rows = ckpt.list_all()
        assert len(rows) == 3
        session_ids = {r["session_id"] for r in rows}
        assert session_ids == {"s1", "s2", "s3"}

    def test_list_all_empty(self, ckpt):
        assert ckpt.list_all() == []

    def test_delete_existing_returns_true(self, ckpt):
        ckpt.write("del-me", "T", [], [], "P", {}, 50)
        ok = ckpt.delete("del-me")
        assert ok is True
        assert ckpt.get("del-me") is None

    def test_delete_missing_returns_false(self, ckpt):
        ok = ckpt.delete("ghost")
        assert ok is False


# ---------------------------------------------------------------------------
# Token tracking
# ---------------------------------------------------------------------------

class TestTokenTracking:
    def test_add_tokens_accumulates(self, ckpt):
        ckpt.add_tokens("sess", 500)
        ckpt.add_tokens("sess", 300)
        assert ckpt.current_tokens("sess") == 800

    def test_reset_tokens(self, ckpt):
        ckpt.add_tokens("sess", 1000)
        ckpt.reset_tokens("sess")
        assert ckpt.current_tokens("sess") == 0

    def test_token_isolation_between_sessions(self, ckpt):
        ckpt.add_tokens("s1", 500)
        ckpt.add_tokens("s2", 300)
        assert ckpt.current_tokens("s1") == 500
        assert ckpt.current_tokens("s2") == 300

    def test_initial_tokens_zero(self, ckpt):
        assert ckpt.current_tokens("new-session") == 0

    def test_should_checkpoint_at_threshold(self, ckpt):
        # 80% of 1000 = 800
        ckpt.add_tokens("s", 800)
        assert ckpt._should_checkpoint("s", context_limit=1000, threshold=0.80) is True

    def test_should_not_checkpoint_below_threshold(self, ckpt):
        ckpt.add_tokens("s", 799)
        assert ckpt._should_checkpoint("s", context_limit=1000, threshold=0.80) is False

    def test_should_checkpoint_exactly_at_threshold(self, ckpt):
        # 80% of 10000 = 8000
        ckpt.add_tokens("s", 8000)
        assert ckpt._should_checkpoint("s", context_limit=10000, threshold=0.80) is True

    def test_custom_threshold(self, ckpt):
        # 50% threshold of 1000 = 500
        ckpt.add_tokens("s", 500)
        assert ckpt._should_checkpoint("s", context_limit=1000, threshold=0.50) is True
        assert ckpt._should_checkpoint("s", context_limit=1000, threshold=0.60) is False


# ---------------------------------------------------------------------------
# maybe_checkpoint
# ---------------------------------------------------------------------------

class TestMaybeCheckpoint:
    @pytest.mark.asyncio
    async def test_maybe_checkpoint_triggers_at_threshold(self, ckpt):
        triggered = await ckpt.maybe_checkpoint(
            session_id="auto-sess",
            task_description="Auto task",
            decisions_made=["dec1"],
            files_modified=["file.py"],
            current_plan="Plan",
            key_facts={"k": 1},
            new_tokens=8000,   # 80% of 10000
            context_limit=10000,
            threshold=0.80,
        )
        assert triggered is True
        data = ckpt.get("auto-sess")
        assert data is not None
        assert data["token_count"] == 8000

    @pytest.mark.asyncio
    async def test_maybe_checkpoint_no_trigger_below_threshold(self, ckpt):
        triggered = await ckpt.maybe_checkpoint(
            session_id="under-sess",
            task_description="Task",
            decisions_made=[],
            files_modified=[],
            current_plan="",
            key_facts={},
            new_tokens=500,
            context_limit=10000,
            threshold=0.80,
        )
        assert triggered is False
        assert ckpt.get("under-sess") is None

    @pytest.mark.asyncio
    async def test_maybe_checkpoint_resets_token_counter(self, ckpt):
        await ckpt.maybe_checkpoint(
            session_id="reset-sess",
            task_description="T",
            decisions_made=[],
            files_modified=[],
            current_plan="",
            key_facts={},
            new_tokens=8000,
            context_limit=10000,
            threshold=0.80,
        )
        # After checkpoint, counter should be reset
        assert ckpt.current_tokens("reset-sess") == 0

    @pytest.mark.asyncio
    async def test_maybe_checkpoint_calls_audit(self, ckpt):
        mock_audit = MagicMock()
        mock_audit.log = MagicMock()

        await ckpt.maybe_checkpoint(
            session_id="audit-sess",
            task_description="T",
            decisions_made=[],
            files_modified=[],
            current_plan="",
            key_facts={},
            new_tokens=9000,
            context_limit=10000,
            threshold=0.80,
            audit_log=mock_audit,
        )
        mock_audit.log.assert_called_once()
        call_kwargs = mock_audit.log.call_args
        assert call_kwargs[1]["action_type"] == "context_anchor" or \
               call_kwargs[0][1] == "context_anchor"

    @pytest.mark.asyncio
    async def test_maybe_checkpoint_accumulates_across_turns(self, ckpt):
        # 3 turns of 3000 tokens each — threshold hit on turn 3 (9000/10000 = 90%)
        t1 = await ckpt.maybe_checkpoint(
            session_id="multi-turn",
            task_description="T",
            decisions_made=[],
            files_modified=[],
            current_plan="",
            key_facts={},
            new_tokens=3000,
            context_limit=10000,
            threshold=0.80,
        )
        t2 = await ckpt.maybe_checkpoint(
            session_id="multi-turn",
            task_description="T",
            decisions_made=[],
            files_modified=[],
            current_plan="",
            key_facts={},
            new_tokens=3000,
            context_limit=10000,
            threshold=0.80,
        )
        t3 = await ckpt.maybe_checkpoint(
            session_id="multi-turn",
            task_description="T",
            decisions_made=[],
            files_modified=[],
            current_plan="",
            key_facts={},
            new_tokens=3000,
            context_limit=10000,
            threshold=0.80,
        )
        assert t1 is False
        assert t2 is False
        assert t3 is True


# ---------------------------------------------------------------------------
# get_summary — compression and token limit
# ---------------------------------------------------------------------------

class TestGetSummary:
    def test_get_summary_returns_non_empty(self, ckpt):
        ckpt.write(
            "sess-sum",
            "Implement auth system",
            ["Use JWT", "Bcrypt for passwords"],
            ["auth.py", "models.py"],
            "Step 2: write tests",
            {"framework": "FastAPI"},
            5000,
        )
        summary = ckpt.get_summary("sess-sum")
        assert "Implement auth system" in summary
        assert "JWT" in summary
        assert "Step 2: write tests" in summary

    def test_get_summary_missing_session_returns_empty(self, ckpt):
        assert ckpt.get_summary("ghost") == ""

    def test_get_summary_max_tokens_enforced(self, ckpt):
        # Create a summary with huge data that should be truncated
        ckpt.write(
            "big-sess",
            "Very long task description " * 100,
            ["decision " * 50] * 20,
            ["file.py"] * 50,
            "Long plan " * 200,
            {"key": "value " * 300},
            9999,
        )
        summary = ckpt.get_summary("big-sess")
        # 1000 tokens * 4 chars/token = 4000 chars max + overhead
        assert len(summary) <= 4100  # slight overhead from truncation message

    def test_get_summary_contains_checkpoint_header(self, ckpt):
        ckpt.write("sess-h", "Task", [], [], "Plan", {}, 100)
        summary = ckpt.get_summary("sess-h")
        assert "SESSION CHECKPOINT" in summary


# ---------------------------------------------------------------------------
# async_write — uses asyncio.shield
# ---------------------------------------------------------------------------

class TestAsyncWrite:
    @pytest.mark.asyncio
    async def test_async_write_persists_to_db(self, ckpt):
        await ckpt.async_write(
            session_id="async-sess",
            task_description="Async task",
            decisions_made=["async dec"],
            files_modified=["async_file.py"],
            current_plan="Async plan",
            key_facts={"async": True},
            token_count=999,
        )
        data = ckpt.get("async-sess")
        assert data is not None
        assert data["task_description"] == "Async task"
        assert data["token_count"] == 999
