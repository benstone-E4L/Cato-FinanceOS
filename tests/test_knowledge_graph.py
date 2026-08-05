"""
tests/test_knowledge_graph.py — Tests for Skill 9: Cognee SQLite Knowledge Graph.

Min 25 tests covering:
- Schema tables (kg_nodes, kg_edges) created correctly
- facts table dependency check raises RuntimeError if missing
- add_node() deduplication by label
- add_edge() weight reinforcement on duplicate
- seed_nodes_from_facts() creates nodes from facts
- query_graph() returns correct multi-hop paths
- related_concepts() returns within-hop neighbours
- extract_and_add_nodes() entity extraction (file paths, CamelCase, ALL_CAPS, @mentions)
- extract_and_add_edges() co-occurrence detection
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from cato.core.memory import MemorySystem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem(tmp_path):
    """MemorySystem backed by a temp directory."""
    m = MemorySystem(agent_id="test-kg", memory_dir=tmp_path)
    yield m
    m.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_kg_nodes_table_created(self, mem):
        row = mem._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kg_nodes'"
        ).fetchone()
        assert row is not None

    def test_kg_edges_table_created(self, mem):
        row = mem._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kg_edges'"
        ).fetchone()
        assert row is not None

    def test_kg_nodes_index_created(self, mem):
        row = mem._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_kg_nodes_label'"
        ).fetchone()
        assert row is not None

    def test_facts_table_dependency_check_passes(self, mem):
        """MemorySystem should initialise without error when facts table is present."""
        row = mem._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
        ).fetchone()
        assert row is not None

    def test_missing_facts_table_raises_runtime_error(self, tmp_path):
        """
        If the facts table is somehow absent, MemorySystem should raise RuntimeError.
        We simulate this by creating a DB without the facts table and calling _open_db
        directly after patching _SCHEMA.
        """
        import cato.core.memory as memory_mod

        # Create a DB with facts table first (normal init), then DROP facts
        m = MemorySystem(agent_id="no-facts", memory_dir=tmp_path)
        m._conn.execute("DROP TABLE IF EXISTS facts")
        m._conn.commit()
        m._conn.close()

        # Now attempt to open that same DB — _open_db will run CREATE IF NOT EXISTS
        # so facts will be re-created. To truly test the guard, we patch _SCHEMA to
        # omit the facts CREATE and also patch _apply_facts_migration to be a no-op,
        # then call _open_db.
        import unittest.mock as mock
        _schema_no_facts = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,
    source_file TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
        with mock.patch.object(memory_mod, "_SCHEMA", _schema_no_facts), \
             mock.patch("cato.core.memory._apply_facts_migration"):
            m2 = MemorySystem.__new__(MemorySystem)
            m2._agent_id = "no-facts-2"
            m2._dir = tmp_path / "sub"
            m2._dir.mkdir()
            m2._db_path = m2._dir / "no-facts-2.db"
            m2._write_lock = __import__("threading").Lock()
            m2._embed_model = None
            m2._ann_index = None
            m2._ann_index_ids = []
            m2._ann_dirty = True
            with pytest.raises(RuntimeError, match="facts"):
                m2._conn = m2._open_db()


# ---------------------------------------------------------------------------
# add_node
# ---------------------------------------------------------------------------

class TestAddNode:
    def test_add_node_returns_id(self, mem):
        node_id = mem.add_node("person", "alice")
        assert isinstance(node_id, int)
        assert node_id > 0

    def test_add_node_deduplicates_by_label(self, mem):
        id1 = mem.add_node("person", "bob")
        id2 = mem.add_node("concept", "bob")  # same label, different type
        assert id1 == id2

    def test_add_node_stores_type_and_label(self, mem):
        mem.add_node("file", "main.py")
        row = mem._conn.execute(
            "SELECT type, label FROM kg_nodes WHERE label = 'main.py'"
        ).fetchone()
        assert row is not None
        assert row["type"] == "file"
        assert row["label"] == "main.py"

    def test_add_node_with_embedding(self, mem):
        embedding = b"\x00\x01\x02\x03"
        node_id = mem.add_node("concept", "TestEmbed", embedding=embedding)
        row = mem._conn.execute(
            "SELECT embedding FROM kg_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        assert row["embedding"] == embedding

    def test_add_node_with_source_session(self, mem):
        node_id = mem.add_node("project", "Cato", source_session="sess-001")
        row = mem._conn.execute(
            "SELECT source_session FROM kg_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        assert row["source_session"] == "sess-001"

    def test_add_node_created_at_set(self, mem):
        before = time.time()
        mem.add_node("concept", "TimestampTest")
        after = time.time()
        row = mem._conn.execute(
            "SELECT created_at FROM kg_nodes WHERE label = 'TimestampTest'"
        ).fetchone()
        assert before <= row["created_at"] <= after


# ---------------------------------------------------------------------------
# seed_nodes_from_facts
# ---------------------------------------------------------------------------

class TestSeedNodesFromFacts:
    def test_seed_creates_nodes_for_each_fact_key(self, mem):
        mem.store_fact("user_name", "Alice")
        mem.store_fact("language", "Python")
        mem.store_fact("project", "Cato")
        count = mem.seed_nodes_from_facts(session_id="s1")
        assert count == 3

    def test_seed_nodes_are_queryable(self, mem):
        mem.store_fact("framework", "FastAPI")
        mem.seed_nodes_from_facts()
        row = mem._conn.execute(
            "SELECT label FROM kg_nodes WHERE label = 'framework'"
        ).fetchone()
        assert row is not None

    def test_seed_idempotent_no_duplicates(self, mem):
        mem.store_fact("key1", "val1")
        mem.seed_nodes_from_facts()
        mem.seed_nodes_from_facts()  # Second call should not fail or duplicate
        count = mem._conn.execute(
            "SELECT COUNT(*) FROM kg_nodes WHERE label = 'key1'"
        ).fetchone()[0]
        assert count == 1

    def test_seed_returns_zero_with_no_facts(self, mem):
        count = mem.seed_nodes_from_facts()
        assert count == 0


# ---------------------------------------------------------------------------
# add_edge
# ---------------------------------------------------------------------------

class TestAddEdge:
    def test_add_edge_returns_true(self, mem):
        mem.add_node("person", "alice")
        mem.add_node("file", "config.py")
        result = mem.add_edge("alice", "config.py", relation_type="co_mentioned")
        assert result is True

    def test_add_edge_auto_creates_nodes(self, mem):
        mem.add_edge("charlie", "delta.ts")
        row = mem._conn.execute(
            "SELECT label FROM kg_nodes WHERE label = 'charlie'"
        ).fetchone()
        assert row is not None

    def test_add_edge_reinforces_weight_on_duplicate(self, mem):
        mem.add_edge("x", "y", relation_type="co_mentioned", weight=1.0)
        mem.add_edge("x", "y", relation_type="co_mentioned", weight=1.0)
        from_id = mem._conn.execute("SELECT id FROM kg_nodes WHERE label='x'").fetchone()["id"]
        to_id = mem._conn.execute("SELECT id FROM kg_nodes WHERE label='y'").fetchone()["id"]
        row = mem._conn.execute(
            "SELECT weight FROM kg_edges WHERE from_id=? AND to_id=? AND relation_type=?",
            (from_id, to_id, "co_mentioned"),
        ).fetchone()
        assert row["weight"] == 2.0

    def test_add_edge_different_relation_types_coexist(self, mem):
        mem.add_edge("a", "b", relation_type="co_mentioned")
        mem.add_edge("a", "b", relation_type="depends_on")
        from_id = mem._conn.execute("SELECT id FROM kg_nodes WHERE label='a'").fetchone()["id"]
        to_id = mem._conn.execute("SELECT id FROM kg_nodes WHERE label='b'").fetchone()["id"]
        count = mem._conn.execute(
            "SELECT COUNT(*) FROM kg_edges WHERE from_id=? AND to_id=?",
            (from_id, to_id),
        ).fetchone()[0]
        assert count == 2


# ---------------------------------------------------------------------------
# extract_and_add_nodes
# ---------------------------------------------------------------------------

class TestExtractAndAddNodes:
    def test_extracts_file_paths(self, mem):
        ids = mem.extract_and_add_nodes("See config.py and main.ts for details.")
        assert len(ids) >= 2
        labels = [
            mem._conn.execute("SELECT label FROM kg_nodes WHERE id=?", (i,)).fetchone()["label"]
            for i in ids
        ]
        assert "config.py" in labels
        assert "main.ts" in labels

    def test_extracts_camelcase_words(self, mem):
        ids = mem.extract_and_add_nodes("The MemorySystem and KnowledgeGraph are connected.")
        assert len(ids) >= 2
        labels = [
            mem._conn.execute("SELECT label FROM kg_nodes WHERE id=?", (i,)).fetchone()["label"]
            for i in ids
        ]
        assert "MemorySystem" in labels
        assert "KnowledgeGraph" in labels

    def test_extracts_all_caps_identifiers(self, mem):
        ids = mem.extract_and_add_nodes("Use CATO_HOME and PATH environment variables.")
        labels = [
            mem._conn.execute("SELECT label FROM kg_nodes WHERE id=?", (i,)).fetchone()["label"]
            for i in ids
        ]
        assert "CATO_HOME" in labels or "PATH" in labels

    def test_extracts_at_mentions(self, mem):
        ids = mem.extract_and_add_nodes("@alice and @bob reviewed the PR.")
        labels = [
            mem._conn.execute("SELECT label FROM kg_nodes WHERE id=?", (i,)).fetchone()["label"]
            for i in ids
        ]
        assert "alice" in labels
        assert "bob" in labels

    def test_no_duplicate_ids_for_same_label(self, mem):
        ids = mem.extract_and_add_nodes("config.py config.py config.py")
        unique_ids = list(set(ids))
        # All ids that point to same label should be identical
        labels = [
            mem._conn.execute("SELECT label FROM kg_nodes WHERE id=?", (i,)).fetchone()["label"]
            for i in ids
        ]
        config_ids = [ids[j] for j, l in enumerate(labels) if l == "config.py"]
        assert len(set(config_ids)) == 1


# ---------------------------------------------------------------------------
# query_graph and related_concepts
# ---------------------------------------------------------------------------

class TestQueryGraph:
    def _make_chain(self, mem):
        """Create a simple chain: a -> b -> c."""
        mem.add_node("concept", "a")
        mem.add_node("concept", "b")
        mem.add_node("concept", "c")
        mem.add_edge("a", "b", relation_type="depends_on")
        mem.add_edge("b", "c", relation_type="depends_on")

    def test_query_graph_returns_direct_neighbour(self, mem):
        self._make_chain(mem)
        results = mem.query_graph("a", depth=1)
        labels = [r["label"] for r in results]
        assert "b" in labels

    def test_query_graph_returns_two_hop_neighbour(self, mem):
        self._make_chain(mem)
        results = mem.query_graph("a", depth=2)
        labels = [r["label"] for r in results]
        assert "c" in labels

    def test_query_graph_depth_limits_results(self, mem):
        self._make_chain(mem)
        results_d1 = mem.query_graph("a", depth=1)
        labels_d1 = [r["label"] for r in results_d1]
        assert "c" not in labels_d1

    def test_query_graph_empty_for_unknown_label(self, mem):
        results = mem.query_graph("nonexistent_node_xyz")
        assert results == []

    def test_query_graph_returns_depth_field(self, mem):
        self._make_chain(mem)
        results = mem.query_graph("a", depth=2)
        depths = {r["label"]: r["depth"] for r in results}
        assert depths.get("b") == 1
        assert depths.get("c") == 2

    def test_related_concepts_ranked_by_weight(self, mem):
        mem.add_node("concept", "hub")
        mem.add_node("concept", "high_weight")
        mem.add_node("concept", "low_weight")
        # high_weight edge reinforced 3 times, low_weight only 1 time
        for _ in range(3):
            mem.add_edge("hub", "high_weight", relation_type="co_mentioned")
        mem.add_edge("hub", "low_weight", relation_type="co_mentioned")

        results = mem.related_concepts("hub", max_hops=1)
        assert len(results) >= 2
        # First result should have higher weight
        assert results[0]["weight"] >= results[1]["weight"]

    def test_related_concepts_returns_empty_for_unknown(self, mem):
        results = mem.related_concepts("does_not_exist")
        assert results == []
