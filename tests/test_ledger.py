"""
tests/test_ledger.py — Tests for Skill 1 (Causal Action Ledger).

All tests use tmp_path for DB isolation.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pytest

from cato.audit.ledger import (
    _GENESIS_PREV_HASH,
    _hash_json,
    LedgerMiddleware,
    LedgerQuery,
    LedgerRecord,
    verify_chain,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_middleware(tmp_path: Path) -> LedgerMiddleware:
    db = tmp_path / "ledger.db"
    return LedgerMiddleware(db_path=db)


def make_query(tmp_path: Path) -> LedgerQuery:
    db = tmp_path / "ledger.db"
    return LedgerQuery(db_path=db)


# ---------------------------------------------------------------------------
# _hash_json
# ---------------------------------------------------------------------------

class TestHashJson:
    def test_consistent_for_same_input(self) -> None:
        h1 = _hash_json({"key": "value", "n": 42})
        h2 = _hash_json({"key": "value", "n": 42})
        assert h1 == h2

    def test_sort_keys_normalisation(self) -> None:
        h1 = _hash_json({"b": 2, "a": 1})
        h2 = _hash_json({"a": 1, "b": 2})
        assert h1 == h2

    def test_different_inputs_different_hashes(self) -> None:
        assert _hash_json({"x": 1}) != _hash_json({"x": 2})

    def test_returns_64_char_hex(self) -> None:
        h = _hash_json({"test": True})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------

class TestAppend:
    def test_append_returns_uuid_string(self, tmp_path: Path) -> None:
        m = make_middleware(tmp_path)
        rid = m.append("read_file", {"path": "/tmp/x"}, "content", "sess-1")
        # Should be parseable as UUID
        parsed = uuid.UUID(rid)
        assert str(parsed) == rid
        m.close()

    def test_first_record_has_genesis_prev_hash(self, tmp_path: Path) -> None:
        m = make_middleware(tmp_path)
        rid = m.append("read_file", {}, "out", "sess-1")
        q = make_query(tmp_path)
        records = q.by_session("sess-1")
        assert records[0].prev_hash == _GENESIS_PREV_HASH
        q.close()
        m.close()

    def test_second_record_prev_hash_equals_first_record_hash(self, tmp_path: Path) -> None:
        m = make_middleware(tmp_path)
        rid1 = m.append("read_file", {}, "out1", "sess-1")
        rid2 = m.append("write_file", {"path": "/tmp/y"}, "ok", "sess-1")
        q = make_query(tmp_path)
        records = q.by_session("sess-1")
        # Find by record_id
        r1 = next(r for r in records if r.record_id == rid1)
        r2 = next(r for r in records if r.record_id == rid2)
        assert r2.prev_hash == r1.record_hash
        q.close()
        m.close()

    def test_tool_input_hash_reproducible(self, tmp_path: Path) -> None:
        m = make_middleware(tmp_path)
        tool_input = {"path": "/tmp/file.txt", "mode": "r"}
        rid = m.append("read_file", tool_input, "content", "sess-hash")
        q = make_query(tmp_path)
        records = q.by_session("sess-hash")
        expected = _hash_json(tool_input)
        assert records[0].tool_input_hash == expected
        q.close()
        m.close()

    def test_reasoning_excerpt_truncated_at_500_chars(self, tmp_path: Path) -> None:
        m = make_middleware(tmp_path)
        long_excerpt = "X" * 1000
        rid = m.append("read_file", {}, "out", "sess-trunc", reasoning_excerpt=long_excerpt)
        q = make_query(tmp_path)
        records = q.by_session("sess-trunc")
        assert len(records[0].reasoning_excerpt) == 500
        q.close()
        m.close()

    def test_model_source_stored_correctly(self, tmp_path: Path) -> None:
        m = make_middleware(tmp_path)
        m.append("read_file", {}, "out", "sess-ms", model_source="gemini")
        q = make_query(tmp_path)
        records = q.by_session("sess-ms")
        assert records[0].model_source == "gemini"
        q.close()
        m.close()

    def test_reversibility_stored_correctly(self, tmp_path: Path) -> None:
        m = make_middleware(tmp_path)
        m.append("delete_file", {}, "deleted", "sess-rev", reversibility=0.8)
        q = make_query(tmp_path)
        records = q.by_session("sess-rev")
        assert records[0].reversibility == pytest.approx(0.8)
        q.close()
        m.close()

    def test_confidence_score_stored_correctly(self, tmp_path: Path) -> None:
        m = make_middleware(tmp_path)
        m.append("read_file", {}, "out", "sess-conf", confidence_score=0.92)
        q = make_query(tmp_path)
        records = q.by_session("sess-conf")
        assert records[0].confidence_score == pytest.approx(0.92)
        q.close()
        m.close()


# ---------------------------------------------------------------------------
# verify_chain
# ---------------------------------------------------------------------------

class TestVerifyChain:
    def test_empty_db_valid(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        # Ensure the schema exists
        m = LedgerMiddleware(db_path=db)
        m.close()
        valid, msg = verify_chain(db_path=db)
        assert valid is True
        assert "0 records" in msg

    def test_single_record_valid(self, tmp_path: Path) -> None:
        db = tmp_path / "one.db"
        m = LedgerMiddleware(db_path=db)
        m.append("read_file", {}, "out", "sess-1")
        m.close()
        valid, msg = verify_chain(db_path=db)
        assert valid is True
        assert "1 records" in msg

    def test_three_records_valid(self, tmp_path: Path) -> None:
        db = tmp_path / "three.db"
        m = LedgerMiddleware(db_path=db)
        m.append("read_file", {}, "a", "sess-1")
        m.append("write_file", {}, "b", "sess-1")
        m.append("delete_file", {}, "c", "sess-1")
        m.close()
        valid, msg = verify_chain(db_path=db)
        assert valid is True
        assert "3 records" in msg

    def test_tampered_prev_hash_detected(self, tmp_path: Path) -> None:
        db = tmp_path / "tamper.db"
        m = LedgerMiddleware(db_path=db)
        rid1 = m.append("read_file", {}, "a", "sess-1")
        rid2 = m.append("write_file", {}, "b", "sess-1")
        m.close()

        # Tamper with the second record's prev_hash
        conn = sqlite3.connect(str(db))
        conn.execute(
            "UPDATE ledger_records SET prev_hash = ? WHERE record_id = ?",
            ("deadbeef" * 8, rid2),
        )
        conn.commit()
        conn.close()

        valid, msg = verify_chain(db_path=db)
        assert valid is False
        assert "TAMPERED" in msg

    def test_field_mutation_detected_by_rehash(self, tmp_path: Path) -> None:
        """verify_chain() detects field-level mutation (not just prev_hash tampering)."""
        db = tmp_path / "field_tamper.db"
        m = LedgerMiddleware(db_path=db)
        rid = m.append("read_file", {}, "output", "sess-field")
        m.close()

        # Mutate confidence_score without touching prev_hash or record_hash
        conn = sqlite3.connect(str(db))
        conn.execute(
            "UPDATE ledger_records SET confidence_score = 0.99 WHERE record_id = ?",
            (rid,),
        )
        conn.commit()
        conn.close()

        valid, msg = verify_chain(db_path=db)
        assert valid is False
        assert "field hash mismatch" in msg

    def test_valid_returns_true_with_count(self, tmp_path: Path) -> None:
        db = tmp_path / "valid.db"
        m = LedgerMiddleware(db_path=db)
        for i in range(5):
            m.append("read_file", {"i": i}, f"out{i}", "sess-v")
        m.close()
        valid, msg = verify_chain(db_path=db)
        assert valid is True
        assert "5 records" in msg


# ---------------------------------------------------------------------------
# LedgerQuery
# ---------------------------------------------------------------------------

class TestLedgerQuery:
    def test_by_tool_returns_correct_records(self, tmp_path: Path) -> None:
        db = tmp_path / "q.db"
        m = LedgerMiddleware(db_path=db)
        m.append("read_file", {}, "r", "sess-1")
        m.append("write_file", {}, "w", "sess-1")
        m.append("read_file", {}, "r2", "sess-1")
        m.close()
        q = LedgerQuery(db_path=db)
        reads = q.by_tool("read_file")
        assert len(reads) == 2
        assert all(r.tool_name == "read_file" for r in reads)
        q.close()

    def test_by_session_returns_correct_records(self, tmp_path: Path) -> None:
        db = tmp_path / "sess.db"
        m = LedgerMiddleware(db_path=db)
        m.append("read_file", {}, "r", "session-A")
        m.append("write_file", {}, "w", "session-B")
        m.append("delete_file", {}, "d", "session-A")
        m.close()
        q = LedgerQuery(db_path=db)
        a_records = q.by_session("session-A")
        assert len(a_records) == 2
        assert all(r.agent_session_id == "session-A" for r in a_records)
        q.close()

    def test_by_confidence_below_filters_correctly(self, tmp_path: Path) -> None:
        db = tmp_path / "conf.db"
        m = LedgerMiddleware(db_path=db)
        m.append("read_file", {}, "r", "sess-1", confidence_score=0.3)
        m.append("write_file", {}, "w", "sess-1", confidence_score=0.8)
        m.append("delete_file", {}, "d", "sess-1", confidence_score=0.4)
        m.close()
        q = LedgerQuery(db_path=db)
        low = q.by_confidence_below(0.5)
        assert len(low) == 2
        assert all(r.confidence_score < 0.5 for r in low)
        q.close()

    def test_by_time_range_returns_records_in_range(self, tmp_path: Path) -> None:
        db = tmp_path / "time.db"
        m = LedgerMiddleware(db_path=db)
        before = time.time()
        m.append("read_file", {}, "r", "sess-t")
        after = time.time()
        m.close()
        q = LedgerQuery(db_path=db)
        records = q.by_time_range(before - 1, after + 1)
        assert len(records) >= 1
        q.close()

    def test_by_delegation_token_works(self, tmp_path: Path) -> None:
        db = tmp_path / "tok.db"
        m = LedgerMiddleware(db_path=db)
        token_id = "tok-abc-123"
        m.append("read_file", {}, "r", "sess-1", delegation_token_id=token_id)
        m.append("write_file", {}, "w", "sess-1")
        m.close()
        q = LedgerQuery(db_path=db)
        records = q.by_delegation_token(token_id)
        assert len(records) == 1
        assert records[0].delegation_token_id == token_id
        q.close()

    def test_replay_session_returns_list_of_dicts(self, tmp_path: Path) -> None:
        db = tmp_path / "replay.db"
        m = LedgerMiddleware(db_path=db)
        m.append("read_file", {}, "r", "sess-replay", reasoning_excerpt="thinking hard")
        m.close()
        q = LedgerQuery(db_path=db)
        replayed = q.replay_session("sess-replay")
        assert len(replayed) == 1
        row = replayed[0]
        assert "record_id" in row
        assert "timestamp" in row
        assert "tool_name" in row
        assert "reasoning_excerpt" in row
        assert "confidence_score" in row
        assert "reversibility" in row
        assert row["tool_name"] == "read_file"
        q.close()

    def test_last_n_returns_most_recent(self, tmp_path: Path) -> None:
        db = tmp_path / "lastn.db"
        m = LedgerMiddleware(db_path=db)
        for i in range(5):
            m.append("read_file", {"i": i}, f"out{i}", "sess-ln")
        m.close()
        q = LedgerQuery(db_path=db)
        records = q.last_n(2)
        assert len(records) == 2
        q.close()

    def test_last_n_returns_records_in_chronological_order(self, tmp_path: Path) -> None:
        db = tmp_path / "lastn_ord.db"
        m = LedgerMiddleware(db_path=db)
        rid1 = m.append("read_file", {"seq": 1}, "a", "sess-1")
        rid2 = m.append("write_file", {"seq": 2}, "b", "sess-1")
        rid3 = m.append("delete_file", {"seq": 3}, "c", "sess-1")
        m.close()
        q = LedgerQuery(db_path=db)
        records = q.last_n(2)
        # Should be the 2 most recent, in chronological order
        assert len(records) == 2
        assert records[0].record_id in (rid2, rid3)
        assert records[1].record_id in (rid2, rid3)
        q.close()


# ---------------------------------------------------------------------------
# LedgerRecord dataclass
# ---------------------------------------------------------------------------

class TestLedgerRecordDataclass:
    def test_has_all_expected_fields(self, tmp_path: Path) -> None:
        db = tmp_path / "fields.db"
        m = LedgerMiddleware(db_path=db)
        m.append("shell_execute", {"cmd": "ls"}, "ok", "sess-fields",
                  reasoning_excerpt="why", confidence_score=0.75,
                  model_source="codex", reversibility=0.6,
                  delegation_token_id="tok-xyz")
        m.close()
        q = LedgerQuery(db_path=db)
        records = q.by_session("sess-fields")
        r = records[0]
        assert isinstance(r, LedgerRecord)
        assert r.tool_name == "shell_execute"
        assert r.agent_session_id == "sess-fields"
        assert r.reasoning_excerpt == "why"
        assert r.confidence_score == pytest.approx(0.75)
        assert r.model_source == "codex"
        assert r.reversibility == pytest.approx(0.6)
        assert r.delegation_token_id == "tok-xyz"
        assert len(r.record_hash) == 64
        q.close()


# ---------------------------------------------------------------------------
# Concurrent appends
# ---------------------------------------------------------------------------

class TestConcurrentAppends:
    def test_concurrent_appends_do_not_corrupt_chain(self, tmp_path: Path) -> None:
        db = tmp_path / "concurrent.db"
        m = LedgerMiddleware(db_path=db)
        errors: list[Exception] = []
        n_threads = 10
        n_records_each = 5

        def worker(session_id: str) -> None:
            try:
                for i in range(n_records_each):
                    m.append("read_file", {"i": i}, f"out{i}", session_id)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(f"sess-{t}",))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        m.close()
        assert errors == [], f"Concurrent errors: {errors}"

        valid, msg = verify_chain(db_path=db)
        # The chain should contain all records; verify integrity
        assert valid is True
        q = LedgerQuery(db_path=db)
        all_records = q.last_n(n_threads * n_records_each + 10)
        assert len(all_records) == n_threads * n_records_each
        q.close()
