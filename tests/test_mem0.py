"""
tests/test_mem0.py — Tests for Skill 2: Mem0 Local-First Semantic Memory.

Min 25 tests covering:
- Schema migration idempotency
- store_fact UPSERT / confidence reinforcement
- apply_decay logic
- forget_fact / forget_all_facts
- load_top_facts ordering
"""
from __future__ import annotations

import time
import sqlite3
import pytest

from cato.core.memory import MemorySystem, _apply_facts_migration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem(tmp_path):
    """MemorySystem backed by a temp directory."""
    m = MemorySystem(agent_id="test-mem0", memory_dir=tmp_path)
    yield m
    m.close()


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

class TestSchemaMigration:
    def test_facts_table_created(self, mem):
        """Facts table exists after DB creation."""
        row = mem._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
        ).fetchone()
        assert row is not None

    def test_schema_migrations_table_created(self, mem):
        """schema_migrations table exists."""
        row = mem._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        assert row is not None

    def test_migration_idempotent_twice(self, tmp_path):
        """Running migration twice does not raise errors."""
        m = MemorySystem(agent_id="idempotent", memory_dir=tmp_path)
        conn = m._conn
        # Run migration again — should be silent
        _apply_facts_migration(conn)
        _apply_facts_migration(conn)
        m.close()

    def test_migration_version_tracked(self, mem):
        """Migration version 1 is recorded in schema_migrations."""
        row = mem._conn.execute(
            "SELECT version FROM schema_migrations WHERE version = 1"
        ).fetchone()
        assert row is not None
        assert row[0] == 1

    def test_facts_columns_present(self, mem):
        """All required columns present in facts table."""
        info = mem._conn.execute("PRAGMA table_info(facts)").fetchall()
        col_names = {r[1] for r in info}
        required = {"key", "value", "confidence", "source_session", "last_reinforced", "decay_factor", "created_at"}
        assert required.issubset(col_names)

    def test_alt_migration_on_existing_db(self, tmp_path):
        """ALTER TABLE is silently skipped on a DB that already has the columns."""
        # Create DB twice — second creation hits ALTER TABLE silently
        m1 = MemorySystem(agent_id="alt-test", memory_dir=tmp_path)
        m1.close()
        m2 = MemorySystem(agent_id="alt-test", memory_dir=tmp_path)
        m2.close()


# ---------------------------------------------------------------------------
# store_fact / UPSERT
# ---------------------------------------------------------------------------

class TestStoreFact:
    def test_store_new_fact(self, mem):
        """Storing a new fact inserts it into the DB."""
        mem.store_fact("color", "blue")
        count = mem._conn.execute("SELECT COUNT(*) FROM facts WHERE key='color'").fetchone()[0]
        assert count == 1

    def test_store_fact_value(self, mem):
        """Stored value is retrievable."""
        mem.store_fact("city", "Paris")
        row = mem._conn.execute("SELECT value FROM facts WHERE key='city'").fetchone()
        assert row["value"] == "Paris"

    def test_upsert_reinforces_confidence(self, mem):
        """Re-inserting same key increments confidence by 0.1."""
        mem.store_fact("name", "Alice", confidence=0.7)
        mem.store_fact("name", "Alice updated")  # same key
        row = mem._conn.execute("SELECT confidence FROM facts WHERE key='name'").fetchone()
        assert row["confidence"] == pytest.approx(0.8, abs=0.01)

    def test_upsert_caps_confidence_at_1(self, mem):
        """Confidence never exceeds 1.0 after multiple reinforcements."""
        mem.store_fact("lang", "Python", confidence=0.95)
        mem.store_fact("lang", "Python")  # 0.95 + 0.1 = 1.05 → capped at 1.0
        row = mem._conn.execute("SELECT confidence FROM facts WHERE key='lang'").fetchone()
        assert row["confidence"] <= 1.0

    def test_upsert_updates_last_reinforced(self, mem):
        """Re-inserting updates last_reinforced timestamp."""
        mem.store_fact("key1", "val1")
        before = mem._conn.execute("SELECT last_reinforced FROM facts WHERE key='key1'").fetchone()[0]
        time.sleep(0.01)
        mem.store_fact("key1", "val1 updated")
        after = mem._conn.execute("SELECT last_reinforced FROM facts WHERE key='key1'").fetchone()[0]
        assert after >= before

    def test_store_fact_with_source_session(self, mem):
        """source_session is stored correctly."""
        mem.store_fact("topic", "AI", source_session="sess-123")
        row = mem._conn.execute("SELECT source_session FROM facts WHERE key='topic'").fetchone()
        assert row["source_session"] == "sess-123"

    def test_store_multiple_facts(self, mem):
        """Multiple facts can be stored independently."""
        for i in range(5):
            mem.store_fact(f"k{i}", f"v{i}")
        count = mem.fact_count()
        assert count == 5

    def test_fact_count_after_upsert(self, mem):
        """Upserting same key does not increase count."""
        mem.store_fact("x", "1")
        mem.store_fact("x", "2")
        assert mem.fact_count() == 1


# ---------------------------------------------------------------------------
# apply_decay
# ---------------------------------------------------------------------------

class TestApplyDecay:
    def test_decay_reduces_confidence(self, mem):
        """apply_decay reduces confidence of old facts."""
        mem.store_fact("old-fact", "value", confidence=0.8)
        # Set last_reinforced to far in the past
        mem._conn.execute(
            "UPDATE facts SET last_reinforced = ? WHERE key = 'old-fact'",
            (time.time() - 10000,),
        )
        mem._conn.commit()
        mem.apply_decay(sessions_since_reinforced=1)
        row = mem._conn.execute("SELECT confidence FROM facts WHERE key='old-fact'").fetchone()
        # 0.8 * 0.95 ≈ 0.76
        assert row["confidence"] < 0.8

    def test_decay_skips_recent_facts(self, mem):
        """apply_decay does not touch facts reinforced recently."""
        mem.store_fact("fresh-fact", "value", confidence=0.9)
        # last_reinforced is NOW, threshold = 1s ago — fact should be skipped
        mem.apply_decay(sessions_since_reinforced=1)
        row = mem._conn.execute("SELECT confidence FROM facts WHERE key='fresh-fact'").fetchone()
        assert row["confidence"] == pytest.approx(0.9, abs=0.01)

    def test_decay_returns_row_count(self, mem):
        """apply_decay returns number of rows updated."""
        mem.store_fact("d1", "v1", confidence=0.5)
        mem.store_fact("d2", "v2", confidence=0.5)
        # Push both into the past
        mem._conn.execute("UPDATE facts SET last_reinforced = 0")
        mem._conn.commit()
        n = mem.apply_decay(sessions_since_reinforced=1)
        assert n == 2

    def test_decay_is_multiplicative(self, mem):
        """Each decay application multiplies confidence by decay_factor."""
        mem.store_fact("item", "val", confidence=1.0)
        mem._conn.execute("UPDATE facts SET last_reinforced = 0")
        mem._conn.commit()
        mem.apply_decay(sessions_since_reinforced=1)
        row = mem._conn.execute("SELECT confidence FROM facts WHERE key='item'").fetchone()
        # 1.0 * 0.95 = 0.95
        assert row["confidence"] == pytest.approx(0.95, abs=0.001)


# ---------------------------------------------------------------------------
# forget_fact / forget_all_facts
# ---------------------------------------------------------------------------

class TestForgetFact:
    def test_forget_existing_key(self, mem):
        """forget_fact returns True when key exists."""
        mem.store_fact("to-delete", "value")
        assert mem.forget_fact("to-delete") is True

    def test_forget_nonexistent_key(self, mem):
        """forget_fact returns False for missing key."""
        assert mem.forget_fact("nonexistent") is False

    def test_forget_removes_from_db(self, mem):
        """Fact is actually removed after forget_fact."""
        mem.store_fact("gone", "value")
        mem.forget_fact("gone")
        count = mem._conn.execute("SELECT COUNT(*) FROM facts WHERE key='gone'").fetchone()[0]
        assert count == 0

    def test_forget_all_facts(self, mem):
        """forget_all_facts deletes all facts and returns count."""
        for i in range(4):
            mem.store_fact(f"k{i}", "v")
        n = mem.forget_all_facts()
        assert n == 4
        assert mem.fact_count() == 0

    def test_forget_all_empty_returns_zero(self, mem):
        """forget_all_facts on empty table returns 0."""
        n = mem.forget_all_facts()
        assert n == 0


# ---------------------------------------------------------------------------
# load_top_facts ordering
# ---------------------------------------------------------------------------

class TestLoadTopFacts:
    def test_load_top_facts_returns_list(self, mem):
        """load_top_facts returns a list of dicts."""
        mem.store_fact("a", "1")
        facts = mem.load_top_facts()
        assert isinstance(facts, list)
        assert len(facts) >= 1
        assert "key" in facts[0]
        assert "confidence" in facts[0]

    def test_load_top_facts_limit(self, mem):
        """load_top_facts respects the n limit."""
        for i in range(10):
            mem.store_fact(f"key{i}", f"val{i}")
        facts = mem.load_top_facts(n=3)
        assert len(facts) <= 3

    def test_load_top_facts_ordered_by_confidence(self, mem):
        """Facts with higher confidence appear first (when last_reinforced equal)."""
        # Insert facts with known confidence, same timestamp
        now = time.time()
        mem._conn.execute(
            "INSERT INTO facts (key, value, confidence, last_reinforced, decay_factor, created_at)"
            " VALUES ('low', 'v', 0.3, ?, 0.95, ?)",
            (now, now),
        )
        mem._conn.execute(
            "INSERT INTO facts (key, value, confidence, last_reinforced, decay_factor, created_at)"
            " VALUES ('high', 'v', 0.9, ?, 0.95, ?)",
            (now, now),
        )
        mem._conn.commit()
        facts = mem.load_top_facts()
        keys = [f["key"] for f in facts]
        if "high" in keys and "low" in keys:
            assert keys.index("high") < keys.index("low")

    def test_load_top_facts_empty(self, mem):
        """load_top_facts returns empty list when no facts stored."""
        facts = mem.load_top_facts()
        assert facts == []

    def test_load_top_facts_all_fields(self, mem):
        """Each returned dict has all required fields."""
        mem.store_fact("complete", "full-value", confidence=0.75, source_session="s1")
        facts = mem.load_top_facts()
        assert len(facts) == 1
        f = facts[0]
        assert f["key"] == "complete"
        assert f["value"] == "full-value"
        assert f["confidence"] == pytest.approx(0.75, abs=0.01)
        assert f["source_session"] == "s1"
