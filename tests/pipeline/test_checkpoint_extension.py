"""
Tests for Milestone 2 checkpoint state extension:
- PipelineStore.write_phase_checkpoint() / get_phase_checkpoint()
- Schema migrations (_SCHEMA_MIGRATIONS)
- EmpireRuntime._phase_is_complete()
- run_pipeline(skip_completed=True)
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.pipeline.store import PipelineStore, _SCHEMA_MIGRATIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path) -> PipelineStore:
    return PipelineStore(tmp_path / "empire.db")


def _make_run(store: PipelineStore, tmp_path: Path) -> str:
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    biz_dir = tmp_path / "biz"
    biz_dir.mkdir()
    store.create_run(
        run_id=run_id,
        business_slug="test-biz",
        idea="test idea",
        business_dir=biz_dir,
    )
    return run_id


# ---------------------------------------------------------------------------
# Test 1: _SCHEMA_MIGRATIONS defines exactly the two expected columns
# ---------------------------------------------------------------------------

def test_schema_migrations_declare_expected_columns():
    """_SCHEMA_MIGRATIONS must add checkpoint_json and genesis_phase_map."""
    ddl_combined = " ".join(_SCHEMA_MIGRATIONS).lower()
    assert "checkpoint_json" in ddl_combined, "checkpoint_json column missing from migrations"
    assert "genesis_phase_map" in ddl_combined, "genesis_phase_map column missing from migrations"
    assert len(_SCHEMA_MIGRATIONS) == 2


# ---------------------------------------------------------------------------
# Test 2: columns exist after PipelineStore is constructed
# ---------------------------------------------------------------------------

def test_new_columns_exist_after_init(tmp_path: Path):
    """Both new columns must be present in empire_runs after store init."""
    store = _make_store(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "empire.db"))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(empire_runs)")}
    conn.close()
    assert "checkpoint_json" in cols
    assert "genesis_phase_map" in cols


# ---------------------------------------------------------------------------
# Test 3: write_phase_checkpoint / get_phase_checkpoint round-trip
# ---------------------------------------------------------------------------

def test_checkpoint_roundtrip(tmp_path: Path):
    """write_phase_checkpoint stores data; get_phase_checkpoint retrieves it."""
    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)

    payload = {"success": True, "worker": "claude", "phase": 3}
    store.write_phase_checkpoint(run_id, phase=3, payload=payload)

    retrieved = store.get_phase_checkpoint(run_id, phase=3)
    assert retrieved == payload


def test_checkpoint_absent_returns_none(tmp_path: Path):
    """get_phase_checkpoint returns None when phase has no stored checkpoint."""
    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)

    result = store.get_phase_checkpoint(run_id, phase=5)
    assert result is None


def test_checkpoint_accumulates_across_phases(tmp_path: Path):
    """Multiple phases each get their own checkpoint slot."""
    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)

    store.write_phase_checkpoint(run_id, 1, {"success": True, "phase": 1})
    store.write_phase_checkpoint(run_id, 2, {"success": True, "phase": 2})
    store.write_phase_checkpoint(run_id, 3, {"success": False, "phase": 3})

    assert store.get_phase_checkpoint(run_id, 1)["success"] is True
    assert store.get_phase_checkpoint(run_id, 2)["success"] is True
    assert store.get_phase_checkpoint(run_id, 3)["success"] is False
    # Phase 4 still absent
    assert store.get_phase_checkpoint(run_id, 4) is None


def test_checkpoint_overwrites_same_phase(tmp_path: Path):
    """Writing the same phase twice stores the latest payload."""
    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)

    store.write_phase_checkpoint(run_id, 2, {"success": False, "attempt": 1})
    store.write_phase_checkpoint(run_id, 2, {"success": True, "attempt": 2})

    result = store.get_phase_checkpoint(run_id, 2)
    assert result["success"] is True
    assert result["attempt"] == 2


def test_checkpoint_writes_file_when_dir_provided(tmp_path: Path):
    """write_phase_checkpoint writes a JSON file when checkpoint_dir is given."""
    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)
    ckpt_dir = tmp_path / "checkpoints"

    store.write_phase_checkpoint(
        run_id, phase=4,
        payload={"success": True, "phase": 4},
        checkpoint_dir=ckpt_dir,
    )

    file_path = ckpt_dir / "phase-4.json"
    assert file_path.exists(), "phase-4.json not written"
    data = json.loads(file_path.read_text())
    assert data["success"] is True
    assert data["phase"] == 4


def test_checkpoint_no_file_without_dir(tmp_path: Path):
    """write_phase_checkpoint does NOT create files when checkpoint_dir is None."""
    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)

    store.write_phase_checkpoint(run_id, phase=1, payload={"success": True})

    # No checkpoint directory should exist in tmp_path
    assert not (tmp_path / "checkpoints").exists()


# ---------------------------------------------------------------------------
# Test 4: _phase_is_complete reads checkpoint_json column
# ---------------------------------------------------------------------------

def test_phase_is_complete_true_from_checkpoint(tmp_path: Path):
    """_phase_is_complete returns True when checkpoint records success=True."""
    from cato.pipeline.runtime import EmpireRuntime

    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)
    store.write_phase_checkpoint(run_id, phase=2, payload={"success": True})

    runtime = EmpireRuntime(store=store, worker_registry={})
    run = store.get_run(run_id)
    assert runtime._phase_is_complete(run, 2) is True


def test_phase_is_complete_false_when_absent(tmp_path: Path):
    """_phase_is_complete returns False when no checkpoint stored."""
    from cato.pipeline.runtime import EmpireRuntime

    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)

    runtime = EmpireRuntime(store=store, worker_registry={})
    run = store.get_run(run_id)
    assert runtime._phase_is_complete(run, 1) is False


def test_phase_is_complete_fallback_to_phase_history(tmp_path: Path):
    """_phase_is_complete falls back to metadata phase_history for old runs."""
    from cato.pipeline.runtime import EmpireRuntime

    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)
    # Simulate old-style metadata without checkpoint_json
    store.update_run_status(
        run_id,
        metadata={"phase_history": {"3": {"success": True, "worker": "gemini"}}},
    )

    runtime = EmpireRuntime(store=store, worker_registry={})
    run = store.get_run(run_id)
    assert runtime._phase_is_complete(run, 3) is True
    assert runtime._phase_is_complete(run, 4) is False


# ---------------------------------------------------------------------------
# Test 5: run_pipeline(skip_completed=True) skips phases with success checkpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_pipeline_skips_completed_phases(tmp_path: Path):
    """Phases with success=True checkpoint are skipped; others are executed."""
    from cato.pipeline.runtime import EmpireRuntime

    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)
    # Mark phases 1 and 2 as complete
    store.write_phase_checkpoint(run_id, 1, {"success": True})
    store.write_phase_checkpoint(run_id, 2, {"success": True})

    executed_phases: list[int] = []

    async def fake_execute_phase(*, business_slug, phase, **kwargs):
        executed_phases.append(phase)
        worker_result = MagicMock()
        worker_result.success = True
        return {
            "phase": phase,
            "worker_result": worker_result,
            "requirement_results": [],
            "validation": None,
            "run_status": "RUNNING",
        }

    runtime = EmpireRuntime(store=store, worker_registry={})
    # Patch execute_phase so no real workers are invoked
    with patch.object(runtime, "execute_phase", side_effect=fake_execute_phase):
        # Also patch get_run so it always finds the run
        with patch.object(runtime, "get_run", return_value=store.get_run(run_id)):
            result = await runtime.run_pipeline(
                business_slug="test-biz",
                start_phase=1,
                through_phase=3,
                stop_for_approval=False,
                skip_completed=True,
            )

    # Only phase 3 should have been dispatched; 1 and 2 were skipped
    assert executed_phases == [3], f"Expected only phase 3 executed, got {executed_phases}"
    assert result["status"] in ("COMPLETED", "RUNNING")


@pytest.mark.asyncio
async def test_run_pipeline_skip_completed_false_runs_all_phases(tmp_path: Path):
    """skip_completed=False (default) runs all phases even if checkpointed."""
    from cato.pipeline.runtime import EmpireRuntime

    store = _make_store(tmp_path)
    run_id = _make_run(store, tmp_path)
    store.write_phase_checkpoint(run_id, 1, {"success": True})

    executed_phases: list[int] = []

    async def fake_execute_phase(*, business_slug, phase, **kwargs):
        executed_phases.append(phase)
        worker_result = MagicMock()
        worker_result.success = True
        return {
            "phase": phase,
            "worker_result": worker_result,
            "requirement_results": [],
            "validation": None,
            "run_status": "RUNNING",
        }

    runtime = EmpireRuntime(store=store, worker_registry={})
    with patch.object(runtime, "execute_phase", side_effect=fake_execute_phase):
        with patch.object(runtime, "get_run", return_value=store.get_run(run_id)):
            await runtime.run_pipeline(
                business_slug="test-biz",
                start_phase=1,
                through_phase=2,
                stop_for_approval=False,
                skip_completed=False,
            )

    assert 1 in executed_phases, "Phase 1 should run when skip_completed=False"
    assert 2 in executed_phases


# ---------------------------------------------------------------------------
# Test 6: migration idempotency — running twice doesn't raise
# ---------------------------------------------------------------------------

def test_migrations_are_idempotent(tmp_path: Path):
    """Creating two PipelineStore instances on the same DB doesn't explode."""
    db = tmp_path / "empire.db"
    s1 = PipelineStore(db)
    s2 = PipelineStore(db)  # migrations run again — should be no-op
    # Both are usable
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    biz_dir = tmp_path / "biz2"
    biz_dir.mkdir()
    s2.create_run(run_id=run_id, business_slug="biz2", idea="x", business_dir=biz_dir)
    assert s1.get_run(run_id) is not None
