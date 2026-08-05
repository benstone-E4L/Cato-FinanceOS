"""
tests/test_clawflows.py — Tests for Skill 5: Clawflows Proactive Trigger Registry.

Min 20 tests covering:
- load_flow() parses YAML correctly
- run_flow() executes steps in order (mock dispatch)
- State persisted and resumed after interruption
- on_error: stop halts execution
- on_error: continue skips failed step
- list_flows() scans YAML files
- set_active() toggles active field
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cato.orchestrator.clawflows import FlowEngine, FlowResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_FLOW_YAML = """\
name: test-flow
trigger:
  type: manual
steps:
  - skill: web.search
    args:
      query: "hello"
  - skill: daily_digest
    args: {}
budget_cap: 50
"""

ERROR_STOP_FLOW_YAML = """\
name: error-stop-flow
trigger:
  type: manual
steps:
  - skill: good_step
    args: {}
  - skill: bad_step
    args: {}
    on_error: stop
  - skill: final_step
    args: {}
"""

ERROR_CONTINUE_FLOW_YAML = """\
name: error-continue-flow
trigger:
  type: manual
steps:
  - skill: good_step
    args: {}
  - skill: bad_step
    args: {}
    on_error: continue
  - skill: final_step
    args: {}
"""


@pytest.fixture
def flows_dir(tmp_path):
    """Return a tmp directory with sample flow YAML files."""
    d = tmp_path / "flows"
    d.mkdir()
    (d / "test-flow.yaml").write_text(SIMPLE_FLOW_YAML, encoding="utf-8")
    (d / "error-stop-flow.yaml").write_text(ERROR_STOP_FLOW_YAML, encoding="utf-8")
    (d / "error-continue-flow.yaml").write_text(ERROR_CONTINUE_FLOW_YAML, encoding="utf-8")
    return d


@pytest.fixture
def engine(flows_dir, tmp_path):
    """FlowEngine with tmp flows_dir and tmp db."""
    from cato.platform import get_data_dir
    e = FlowEngine(flows_dir=flows_dir)
    # Override db path to be isolated
    import sqlite3
    e._db_path = tmp_path / "test_flow_runs.db"
    e._conn = e._open_db()
    yield e
    e.close()


# ---------------------------------------------------------------------------
# load_flow()
# ---------------------------------------------------------------------------

class TestLoadFlow:
    def test_load_existing_flow(self, engine):
        """load_flow() returns a dict for existing YAML file."""
        data = engine.load_flow("test-flow")
        assert isinstance(data, dict)

    def test_load_flow_name(self, engine):
        """Loaded flow has correct name."""
        data = engine.load_flow("test-flow")
        assert data.get("name") == "test-flow"

    def test_load_flow_trigger_type(self, engine):
        """Trigger type is parsed correctly."""
        data = engine.load_flow("test-flow")
        trigger = data.get("trigger", {})
        assert trigger.get("type") == "manual"

    def test_load_flow_steps(self, engine):
        """Steps list is parsed correctly."""
        data = engine.load_flow("test-flow")
        steps = data.get("steps", [])
        assert len(steps) == 2
        assert steps[0]["skill"] == "web.search"

    def test_load_flow_budget_cap(self, engine):
        """budget_cap is parsed correctly."""
        data = engine.load_flow("test-flow")
        assert data.get("budget_cap") == 50

    def test_load_nonexistent_flow_raises(self, engine):
        """load_flow() raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            engine.load_flow("does-not-exist")

    def test_load_flow_step_args(self, engine):
        """Step args are parsed correctly."""
        data = engine.load_flow("test-flow")
        step0 = data["steps"][0]
        assert step0["args"].get("query") == "hello"


# ---------------------------------------------------------------------------
# run_flow() — step execution order
# ---------------------------------------------------------------------------

class TestRunFlow:
    @pytest.mark.asyncio
    async def test_run_flow_returns_result(self, engine):
        """run_flow() returns a FlowResult."""
        with patch.object(engine, "_dispatch_step", AsyncMock(return_value="ok")):
            result = await engine.run_flow("test-flow")
        assert isinstance(result, FlowResult)

    @pytest.mark.asyncio
    async def test_run_flow_completed_status(self, engine):
        """Successful flow run has status COMPLETED."""
        with patch.object(engine, "_dispatch_step", AsyncMock(return_value="output")):
            result = await engine.run_flow("test-flow")
        assert result.status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_run_flow_step_count(self, engine):
        """step_outputs has one entry per step."""
        with patch.object(engine, "_dispatch_step", AsyncMock(return_value="ok")):
            result = await engine.run_flow("test-flow")
        assert len(result.step_outputs) == 2  # test-flow has 2 steps

    @pytest.mark.asyncio
    async def test_run_flow_steps_called_in_order(self, engine):
        """Dispatch is called for each step in order."""
        calls = []
        async def mock_dispatch(skill, args, ctx):
            calls.append(skill)
            return f"output-{skill}"
        with patch.object(engine, "_dispatch_step", mock_dispatch):
            await engine.run_flow("test-flow")
        assert calls == ["web.search", "daily_digest"]

    @pytest.mark.asyncio
    async def test_run_missing_flow_returns_failed(self, engine):
        """run_flow() on missing flow returns FlowResult(status=FAILED)."""
        result = await engine.run_flow("does-not-exist")
        assert result.status == "FAILED"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_run_flow_stores_run_id(self, engine):
        """run_flow() returns a run_id."""
        with patch.object(engine, "_dispatch_step", AsyncMock(return_value="ok")):
            result = await engine.run_flow("test-flow")
        assert result.run_id is not None

    @pytest.mark.asyncio
    async def test_run_flow_budget_cap_stops_execution(self, flows_dir):
        """Flow stops when budget_cap would be exceeded mid-run."""
        tight_yaml = """\
name: tight-budget
trigger:
  type: manual
budget_cap: 1
steps:
  - skill: step_a
    args: {}
  - skill: step_b
    args: {}
"""
        (flows_dir / "tight-budget.yaml").write_text(tight_yaml, encoding="utf-8")
        engine = FlowEngine(flows_dir=flows_dir)
        with patch.object(engine, "_dispatch_step", AsyncMock(return_value="ok")):
            result = await engine.run_flow("tight-budget")
        assert result.status == "FAILED"
        assert result.error is not None
        assert "budget" in result.error.lower()


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    @pytest.mark.asyncio
    async def test_run_persisted_to_db(self, engine):
        """Completed run is persisted to flow_runs table."""
        with patch.object(engine, "_dispatch_step", AsyncMock(return_value="ok")):
            result = await engine.run_flow("test-flow")
        row = engine._conn.execute(
            "SELECT * FROM flow_runs WHERE id = ?", (result.run_id,)
        ).fetchone()
        assert row is not None
        assert row["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_step_outputs_serialized(self, engine):
        """step_outputs JSON is stored in DB."""
        with patch.object(engine, "_dispatch_step", AsyncMock(return_value="step-result")):
            result = await engine.run_flow("test-flow")
        row = engine._conn.execute(
            "SELECT step_outputs FROM flow_runs WHERE id = ?", (result.run_id,)
        ).fetchone()
        outputs = json.loads(row["step_outputs"])
        assert "step-result" in outputs

    @pytest.mark.asyncio
    async def test_in_progress_flow_retrievable(self, engine, tmp_path):
        """IN_PROGRESS flows are returned by get_in_progress_flows()."""
        # Manually insert an IN_PROGRESS flow
        import time
        now = time.time()
        engine._conn.execute(
            "INSERT INTO flow_runs (flow_name, current_step, step_outputs, status, started_at, updated_at)"
            " VALUES ('test-flow', 1, '[]', 'IN_PROGRESS', ?, ?)",
            (now, now),
        )
        engine._conn.commit()
        in_progress = engine.get_in_progress_flows()
        assert any(r["flow_name"] == "test-flow" for r in in_progress)


# ---------------------------------------------------------------------------
# on_error: stop
# ---------------------------------------------------------------------------

class TestOnErrorStop:
    @pytest.mark.asyncio
    async def test_on_error_stop_halts_execution(self, engine):
        """on_error: stop causes flow to halt on failed step."""
        call_log = []

        async def mock_dispatch(skill, args, ctx):
            call_log.append(skill)
            if skill == "bad_step":
                raise RuntimeError("simulated failure")
            return f"ok-{skill}"

        with patch.object(engine, "_dispatch_step", mock_dispatch):
            result = await engine.run_flow("error-stop-flow")

        assert result.status == "FAILED"
        assert "final_step" not in call_log

    @pytest.mark.asyncio
    async def test_on_error_stop_error_message(self, engine):
        """FlowResult.error is set when on_error: stop triggers."""
        async def mock_dispatch(skill, args, ctx):
            if skill == "bad_step":
                raise RuntimeError("test error")
            return "ok"

        with patch.object(engine, "_dispatch_step", mock_dispatch):
            result = await engine.run_flow("error-stop-flow")

        assert result.error is not None


# ---------------------------------------------------------------------------
# on_error: continue
# ---------------------------------------------------------------------------

class TestOnErrorContinue:
    @pytest.mark.asyncio
    async def test_on_error_continue_skips_failed_step(self, engine):
        """on_error: continue allows flow to proceed past failed step."""
        call_log = []

        async def mock_dispatch(skill, args, ctx):
            call_log.append(skill)
            if skill == "bad_step":
                raise RuntimeError("fail but continue")
            return f"ok-{skill}"

        with patch.object(engine, "_dispatch_step", mock_dispatch):
            result = await engine.run_flow("error-continue-flow")

        # Final step should still have been called
        assert "final_step" in call_log

    @pytest.mark.asyncio
    async def test_on_error_continue_status_completed(self, engine):
        """Flow with on_error: continue still completes."""
        async def mock_dispatch(skill, args, ctx):
            if skill == "bad_step":
                raise RuntimeError("continue on fail")
            return "ok"

        with patch.object(engine, "_dispatch_step", mock_dispatch):
            result = await engine.run_flow("error-continue-flow")

        assert result.status == "COMPLETED"


# ---------------------------------------------------------------------------
# list_flows()
# ---------------------------------------------------------------------------

class TestListFlows:
    def test_list_flows_returns_all_yamls(self, engine, flows_dir):
        """list_flows() returns all .yaml files in FLOWS_DIR."""
        flows = engine.list_flows()
        names = [f["name"] for f in flows]
        assert "test-flow" in names
        assert "error-stop-flow" in names
        assert "error-continue-flow" in names

    def test_list_flows_structure(self, engine):
        """Each flow dict has required keys."""
        flows = engine.list_flows()
        assert len(flows) > 0
        f = flows[0]
        assert "name" in f
        assert "trigger_type" in f
        assert "step_count" in f

    def test_list_flows_empty_dir(self, tmp_path):
        """list_flows() returns empty list for empty directory."""
        empty_dir = tmp_path / "empty_flows"
        empty_dir.mkdir()
        e = FlowEngine(flows_dir=empty_dir)
        flows = e.list_flows()
        e.close()
        assert flows == []


# ---------------------------------------------------------------------------
# set_active()
# ---------------------------------------------------------------------------

class TestSetActive:
    def test_set_active_true(self, engine, flows_dir):
        """set_active(True) sets active: true in YAML."""
        ok = engine.set_active("test-flow", active=True)
        assert ok is True
        content = (flows_dir / "test-flow.yaml").read_text(encoding="utf-8")
        assert "active: true" in content

    def test_set_active_false(self, engine, flows_dir):
        """set_active(False) sets active: false in YAML."""
        engine.set_active("test-flow", active=True)
        engine.set_active("test-flow", active=False)
        content = (flows_dir / "test-flow.yaml").read_text(encoding="utf-8")
        assert "active: false" in content

    def test_set_active_nonexistent_returns_false(self, engine):
        """set_active() returns False for missing flow."""
        ok = engine.set_active("nonexistent", active=True)
        assert ok is False
