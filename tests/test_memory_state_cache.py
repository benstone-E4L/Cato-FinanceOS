"""Tests for MemorySystem's generic namespaced state cache (CHUNK_5_FINANCE_VIEW).

Covers the stale-fallback primitive the FinanceOS control-room proxy uses to
serve a last-known value when FinanceOS is unreachable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cato.core.memory import MemorySystem


@pytest.fixture
def mem(tmp_path: Path) -> MemorySystem:
    return MemorySystem(agent_id="cache-test", memory_dir=tmp_path / "memdb")


def test_get_cache_value_returns_none_when_never_set(mem: MemorySystem):
    assert mem.get_cache_value("financeos", "control_room") is None


def test_set_then_get_cache_value_round_trips(mem: MemorySystem):
    mem.set_cache_value("financeos", "control_room", {"close_status": "open", "holds": 3})
    result = mem.get_cache_value("financeos", "control_room")
    assert result is not None
    assert result["value"] == {"close_status": "open", "holds": 3}
    assert "cached_at" in result and result["cached_at"]


def test_set_cache_value_overwrites_previous_value_not_duplicates(mem: MemorySystem):
    mem.set_cache_value("financeos", "control_room", {"holds": 1})
    mem.set_cache_value("financeos", "control_room", {"holds": 2})
    result = mem.get_cache_value("financeos", "control_room")
    assert result["value"] == {"holds": 2}
    rows = mem._conn.execute(
        "SELECT COUNT(*) AS n FROM kg_nodes WHERE label = ?",
        ("cache:financeos:control_room",),
    ).fetchone()
    assert rows["n"] == 1


def test_cache_namespaces_and_keys_do_not_collide(mem: MemorySystem):
    mem.set_cache_value("financeos", "control_room", {"a": 1})
    mem.set_cache_value("financeos", "integrations_health", {"b": 2})
    mem.set_cache_value("other_namespace", "control_room", {"c": 3})
    assert mem.get_cache_value("financeos", "control_room")["value"] == {"a": 1}
    assert mem.get_cache_value("financeos", "integrations_health")["value"] == {"b": 2}
    assert mem.get_cache_value("other_namespace", "control_room")["value"] == {"c": 3}


def test_cache_value_never_carries_an_embedding(mem: MemorySystem):
    """Cache writes must not call the embedder — this is a plain KV store."""
    mem.set_cache_value("financeos", "control_room", {"a": 1})
    row = mem._conn.execute(
        "SELECT embedding FROM kg_nodes WHERE label = ?",
        ("cache:financeos:control_room",),
    ).fetchone()
    assert row["embedding"] is None
