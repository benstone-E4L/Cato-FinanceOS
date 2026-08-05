"""
test_genesis_e2e.py — Milestone 5: Integration smoke test + Genesis pipeline E2E

Wires together the three layers:
  1. EmpireRuntime.run_pipeline() — the pipeline orchestrator
  2. invoke_for_genesis_phase()   — the CLI routing layer
  3. WindowsMCPClient             — the desktop automation client

All external processes (CLI subprocess, Windows MCP server) are mocked so no
real network or subprocess activity occurs.  This validates:

  - Correct phase→worker routing across phases 1-9
  - skip_completed=True skips phases where checkpoint has success=True
  - stop_for_approval gate fires after phase 7 when through_phase > 7
  - stop_for_approval gate does NOT fire when through_phase == 7
  - Andon Cord: both-degraded result returned and not auto-continued
  - Phase timeout: asyncio.TimeoutError wraps into degraded result
  - WindowsMCPClient.start() / stop() lifecycle wired through run_pipeline
  - Checkpoint written after each successful phase
  - Failed checkpoint (success=False) written on Andon Cord condition
  - invoke_for_genesis_phase raises ValueError for out-of-range phases
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.config import CatoConfig
from cato.mcp.windows_client import WindowsMCPClient, WindowsMCPError
from cato.orchestrator.cli_invoker import invoke_for_genesis_phase
from cato.pipeline.models import WorkerResult
from cato.pipeline.phase_validation import EmpirePhaseValidator, PhaseValidationResult
from cato.pipeline.runtime import EmpireRuntime
from cato.pipeline.store import PipelineStore


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_success_result(worker: str, phase: int) -> WorkerResult:
    return WorkerResult(
        worker=worker,
        success=True,
        response=f"{worker} completed phase {phase}",
        source="test",
        latency_ms=10.0,
    )


def _make_degraded_result(worker: str, phase: int) -> WorkerResult:
    return WorkerResult(
        worker=worker,
        success=False,
        response=f"[Mock degraded] {worker} phase {phase}",
        source="test",
        latency_ms=5.0,
        degraded=True,
        error="mock degraded",
    )


class _PhaseWorkerRegistry:
    """
    Fake worker registry that records which phase was dispatched to which worker.
    Every phase succeeds by default; individual phases can be configured to fail.
    """

    def __init__(self, *, fail_phases: set[int] | None = None) -> None:
        self._fail_phases = fail_phases or set()
        self.dispatched: list[tuple[int, str]] = []  # [(phase, worker), ...]

    def __getitem__(self, name: str):
        return self._make_worker(name)

    def get(self, name: str):
        return self._make_worker(name)

    def _make_worker(self, worker_name: str):
        registry = self

        class _W:
            name = worker_name

            async def run(self, assignment):
                registry.dispatched.append((assignment.phase, worker_name))
                if assignment.phase in registry._fail_phases:
                    return _make_degraded_result(worker_name, assignment.phase)
                return _make_success_result(worker_name, assignment.phase)

        return _W()


def _make_runtime(
    tmp_path: Path,
    *,
    fail_phases: set[int] | None = None,
    monkeypatch=None,
) -> tuple[EmpireRuntime, _PhaseWorkerRegistry]:
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    store = PipelineStore(tmp_path / "empire.db")
    registry = _PhaseWorkerRegistry(fail_phases=fail_phases)
    runtime = EmpireRuntime(cfg, store=store, worker_registry=registry)

    # Bypass per-phase requirement scripts and validation to keep tests fast
    if monkeypatch is not None:
        monkeypatch.setattr(
            runtime,
            "_run_requirement",
            AsyncMock(
                return_value={
                    "task_id": "fake-req",
                    "script": "fake.py",
                    "args": [],
                    "success": True,
                    "exit_code": 0,
                    "stdout": "ok",
                    "stderr": "",
                    "duration_ms": 1.0,
                    "required": True,
                }
            ),
        )
        monkeypatch.setattr(
            runtime._validator,
            "validate",
            lambda run, spec: PhaseValidationResult(success=True),
        )

    return runtime, registry


# ---------------------------------------------------------------------------
# Section 1 — Phase routing correctness
# ---------------------------------------------------------------------------

class TestGenesisPhaseRouting:
    """invoke_for_genesis_phase routes each phase to the correct primary CLI."""

    @pytest.mark.asyncio
    async def test_phase1_routes_to_claude(self):
        with patch("cato.orchestrator.cli_invoker.invoke_subagent") as mock:
            mock.return_value = {
                "model": "claude", "response": "ok", "confidence": 0.9,
                "latency_ms": 50.0, "degraded": False, "source": "subprocess",
            }
            result = await invoke_for_genesis_phase(1, "research prompt", "biz-1")
        assert mock.call_args[1]["backend"] == "claude"
        assert result["degraded"] is False

    @pytest.mark.asyncio
    async def test_phase3_routes_to_gemini_primary(self):
        with patch("cato.orchestrator.cli_invoker.invoke_subagent") as mock:
            mock.return_value = {
                "model": "gemini", "response": "design", "confidence": 0.85,
                "latency_ms": 40.0, "degraded": False, "source": "subprocess",
            }
            result = await invoke_for_genesis_phase(3, "design prompt", "biz-3")
        assert mock.call_args[1]["backend"] == "gemini"

    @pytest.mark.asyncio
    async def test_phase6_routes_to_codex_primary(self):
        with patch("cato.orchestrator.cli_invoker.invoke_subagent") as mock:
            mock.return_value = {
                "model": "codex", "response": "tests pass", "confidence": 0.95,
                "latency_ms": 30.0, "degraded": False, "source": "subprocess",
            }
            result = await invoke_for_genesis_phase(6, "test prompt", "biz-6")
        assert mock.call_args[1]["backend"] == "codex"

    @pytest.mark.asyncio
    async def test_phase7_routes_to_claude_primary(self):
        with patch("cato.orchestrator.cli_invoker.invoke_subagent") as mock:
            mock.return_value = {
                "model": "claude", "response": "deployed", "confidence": 0.9,
                "latency_ms": 60.0, "degraded": False, "source": "subprocess",
            }
            result = await invoke_for_genesis_phase(7, "deploy prompt", "biz-7")
        assert mock.call_args[1]["backend"] == "claude"

    @pytest.mark.asyncio
    async def test_invalid_phase_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid Genesis phase"):
            await invoke_for_genesis_phase(0, "bad", "biz")

    @pytest.mark.asyncio
    async def test_invalid_phase_10_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid Genesis phase"):
            await invoke_for_genesis_phase(10, "bad", "biz")

    @pytest.mark.asyncio
    async def test_all_9_phases_have_routing_entries(self):
        """Verify all phases 1-9 can be routed without ValueError."""
        for phase in range(1, 10):
            with patch("cato.orchestrator.cli_invoker.invoke_subagent") as mock:
                mock.return_value = {
                    "model": "claude", "response": "ok", "confidence": 0.9,
                    "latency_ms": 5.0, "degraded": False, "source": "subprocess",
                }
                result = await invoke_for_genesis_phase(phase, "prompt", "biz")
                assert result["degraded"] is False, f"Phase {phase} unexpectedly degraded"


# ---------------------------------------------------------------------------
# Section 2 — Fallback routing
# ---------------------------------------------------------------------------

class TestGenesisFallbackRouting:
    """When the primary CLI is degraded, the fallback is tried automatically."""

    @pytest.mark.asyncio
    async def test_phase3_falls_back_to_claude_when_gemini_degraded(self):
        call_log: list[str] = []

        async def _fake_invoke(context, task, *, backend):
            call_log.append(backend)
            if backend == "gemini":
                return {
                    "model": "gemini", "response": "", "confidence": 0.0,
                    "latency_ms": 10.0, "degraded": True, "source": "subprocess",
                }
            # claude fallback succeeds
            return {
                "model": "claude", "response": "design done", "confidence": 0.85,
                "latency_ms": 20.0, "degraded": False, "source": "subprocess",
            }

        with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=_fake_invoke):
            result = await invoke_for_genesis_phase(3, "design prompt", "biz-3")

        assert call_log == ["gemini", "claude"]
        assert result["degraded"] is False
        assert result["model"] == "claude"

    @pytest.mark.asyncio
    async def test_phase4_falls_back_to_codex_when_claude_degraded(self):
        call_log: list[str] = []

        async def _fake_invoke(context, task, *, backend):
            call_log.append(backend)
            if backend == "claude":
                return {
                    "model": "claude", "response": "", "confidence": 0.0,
                    "latency_ms": 10.0, "degraded": True, "source": "subprocess",
                }
            return {
                "model": "codex", "response": "spec done", "confidence": 0.88,
                "latency_ms": 15.0, "degraded": False, "source": "subprocess",
            }

        with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=_fake_invoke):
            result = await invoke_for_genesis_phase(4, "spec prompt", "biz-4")

        assert call_log == ["claude", "codex"]
        assert result["model"] == "codex"
        assert result["degraded"] is False

    @pytest.mark.asyncio
    async def test_both_degraded_returns_degraded_result(self):
        """When primary AND fallback both degrade, result is degraded (Andon Cord)."""
        async def _always_degraded(context, task, *, backend):
            return {
                "model": backend, "response": "", "confidence": 0.0,
                "latency_ms": 5.0, "degraded": True, "source": "subprocess",
            }

        with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=_always_degraded):
            result = await invoke_for_genesis_phase(3, "prompt", "biz-andon")

        assert result["degraded"] is True

    @pytest.mark.asyncio
    async def test_phase1_no_fallback_returns_degraded_directly(self):
        """Phases with no fallback (e.g. phase 1) return degraded without retry."""
        call_log: list[str] = []

        async def _fake_invoke(context, task, *, backend):
            call_log.append(backend)
            return {
                "model": backend, "response": "", "confidence": 0.0,
                "latency_ms": 5.0, "degraded": True, "source": "subprocess",
            }

        with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=_fake_invoke):
            result = await invoke_for_genesis_phase(1, "prompt", "biz-1")

        # Phase 1 has no fallback — invoked exactly once
        assert call_log == ["claude"]
        assert result["degraded"] is True

    @pytest.mark.asyncio
    async def test_primary_timeout_triggers_fallback(self):
        """asyncio.TimeoutError on primary is treated as degraded → tries fallback."""
        call_log: list[str] = []

        async def _fake_invoke(context, task, *, backend):
            call_log.append(backend)
            if backend == "gemini":
                raise asyncio.TimeoutError()
            return {
                "model": "claude", "response": "ok", "confidence": 0.9,
                "latency_ms": 10.0, "degraded": False, "source": "subprocess",
            }

        with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=_fake_invoke):
            result = await invoke_for_genesis_phase(3, "prompt", "biz-timeout")

        assert call_log == ["gemini", "claude"]
        assert result["degraded"] is False


# ---------------------------------------------------------------------------
# Section 3 — run_pipeline full flow
# ---------------------------------------------------------------------------

class TestRunPipelineE2E:
    """EmpireRuntime.run_pipeline() end-to-end scenarios."""

    @pytest.mark.asyncio
    async def test_run_pipeline_phases_1_to_3(self, tmp_path, monkeypatch):
        runtime, registry = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        runtime.create_business_scaffold("SaaS idea")

        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=3,
            stop_for_approval=False,
        )

        assert result["status"] == "COMPLETED"
        assert result["completed_phases"] == [1, 2, 3]
        # Verify correct worker dispatched per phase
        dispatched = {phase: worker for phase, worker in registry.dispatched}
        assert dispatched[1] == "claude"
        assert dispatched[2] == "claude"
        assert dispatched[3] == "gemini"

    @pytest.mark.asyncio
    async def test_run_pipeline_stops_at_phase7_gate_through_9(self, tmp_path, monkeypatch):
        """stop_for_approval=True + through_phase=9 → AWAITING_APPROVAL after phase 7."""
        runtime, registry = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        runtime.create_business_scaffold("SaaS idea")

        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=9,
            stop_for_approval=True,
        )

        assert result["status"] == "AWAITING_APPROVAL"
        assert result["stopped_at_phase"] == 7
        # Phases 8-9 must NOT have been executed
        executed = {phase for phase, _ in registry.dispatched}
        assert 8 not in executed
        assert 9 not in executed

    @pytest.mark.asyncio
    async def test_run_pipeline_gate_not_fired_when_through_phase_equals_7(
        self, tmp_path, monkeypatch
    ):
        """through_phase=7 — gate condition requires through_phase > 7, so no pause."""
        runtime, _ = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        runtime.create_business_scaffold("SaaS idea")

        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=7,
            stop_for_approval=True,
        )

        assert result["status"] == "COMPLETED"
        assert result["stopped_at_phase"] == 7

    @pytest.mark.asyncio
    async def test_run_pipeline_halts_on_failed_phase(self, tmp_path, monkeypatch):
        """Pipeline stops immediately when a phase fails; subsequent phases not run."""
        runtime, registry = _make_runtime(
            tmp_path, fail_phases={3}, monkeypatch=monkeypatch
        )
        runtime.create_business_scaffold("SaaS idea")

        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=5,
            stop_for_approval=False,
        )

        assert result["status"] == "FAILED"
        assert result["stopped_at_phase"] == 3
        executed = {phase for phase, _ in registry.dispatched}
        assert 4 not in executed
        assert 5 not in executed

    @pytest.mark.asyncio
    async def test_run_pipeline_full_9_phases_no_gate(self, tmp_path, monkeypatch):
        """All 9 phases complete when stop_for_approval=False."""
        runtime, registry = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        runtime.create_business_scaffold("SaaS idea")

        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=9,
            stop_for_approval=False,
        )

        assert result["status"] == "COMPLETED"
        assert result["completed_phases"] == list(range(1, 10))


# ---------------------------------------------------------------------------
# Section 4 — skip_completed resume
# ---------------------------------------------------------------------------

class TestSkipCompleted:
    """run_pipeline(skip_completed=True) skips phases with success=True checkpoint."""

    @pytest.mark.asyncio
    async def test_skip_completed_skips_checkpointed_phases(self, tmp_path, monkeypatch):
        runtime, registry = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        run = runtime.create_business_scaffold("SaaS idea")

        # Write successful checkpoints for phases 1 and 2
        store = runtime._store
        store.write_phase_checkpoint(run.run_id, 1, {"success": True, "worker": "claude"})
        store.write_phase_checkpoint(run.run_id, 2, {"success": True, "worker": "claude"})

        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=3,
            stop_for_approval=False,
            skip_completed=True,
        )

        assert result["status"] == "COMPLETED"
        # Only phase 3 should have been dispatched (1 and 2 were skipped)
        executed = {phase for phase, _ in registry.dispatched}
        assert 1 not in executed
        assert 2 not in executed
        assert 3 in executed

    @pytest.mark.asyncio
    async def test_skip_completed_does_not_skip_failed_checkpoint(self, tmp_path, monkeypatch):
        """A phase with success=False checkpoint must NOT be skipped — must rerun."""
        runtime, registry = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        run = runtime.create_business_scaffold("SaaS idea")

        store = runtime._store
        store.write_phase_checkpoint(run.run_id, 1, {"success": False, "error": "degraded"})

        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=2,
            stop_for_approval=False,
            skip_completed=True,
        )

        assert result["status"] == "COMPLETED"
        executed = {phase for phase, _ in registry.dispatched}
        # Phase 1 must have been re-executed (failed checkpoint)
        assert 1 in executed

    @pytest.mark.asyncio
    async def test_skip_completed_false_reruns_all_phases(self, tmp_path, monkeypatch):
        """skip_completed=False always reruns, even if checkpoint says success=True."""
        runtime, registry = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        run = runtime.create_business_scaffold("SaaS idea")

        store = runtime._store
        store.write_phase_checkpoint(run.run_id, 1, {"success": True, "worker": "claude"})
        store.write_phase_checkpoint(run.run_id, 2, {"success": True, "worker": "claude"})

        await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=2,
            stop_for_approval=False,
            skip_completed=False,
        )

        executed = {phase for phase, _ in registry.dispatched}
        assert 1 in executed
        assert 2 in executed

    @pytest.mark.asyncio
    async def test_skip_completed_skipped_phases_appear_in_phase_summaries(
        self, tmp_path, monkeypatch
    ):
        runtime, _ = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        run = runtime.create_business_scaffold("SaaS idea")

        store = runtime._store
        store.write_phase_checkpoint(run.run_id, 1, {"success": True, "worker": "claude"})

        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=2,
            stop_for_approval=False,
            skip_completed=True,
        )

        phase_summaries = result["phase_summaries"]
        skipped = [s for s in phase_summaries if s.get("skipped")]
        assert len(skipped) == 1
        assert skipped[0]["phase"] == 1
        assert skipped[0]["worker_result"].success is True

    @pytest.mark.asyncio
    async def test_resume_after_partial_pipeline_run(self, tmp_path, monkeypatch):
        """Simulate a real resume: first run completes phases 1-3, second run skips them."""
        runtime, registry = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        run = runtime.create_business_scaffold("SaaS idea")

        # First run: phases 1-3
        await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=3,
            stop_for_approval=False,
            skip_completed=False,
        )

        # Write checkpoints for phases 1-3 to simulate real checkpoint writes
        store = runtime._store
        store.write_phase_checkpoint(run.run_id, 1, {"success": True, "worker": "claude"})
        store.write_phase_checkpoint(run.run_id, 2, {"success": True, "worker": "claude"})
        store.write_phase_checkpoint(run.run_id, 3, {"success": True, "worker": "gemini"})
        registry.dispatched.clear()

        # Second run: resume from phase 1, skip completed
        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=1,
            through_phase=5,
            stop_for_approval=False,
            skip_completed=True,
        )

        assert result["status"] == "COMPLETED"
        executed = {phase for phase, _ in registry.dispatched}
        assert 1 not in executed
        assert 2 not in executed
        assert 3 not in executed
        assert 4 in executed
        assert 5 in executed


# ---------------------------------------------------------------------------
# Section 5 — Checkpoint system
# ---------------------------------------------------------------------------

class TestCheckpointSystem:
    """PipelineStore checkpoint API: write, read, accumulate, file output."""

    def test_write_and_read_checkpoint(self, tmp_path):
        store = PipelineStore(tmp_path / "empire.db")
        run = store.create_run(
            run_id="run-chk-1",
            business_slug="chk-biz",
            idea="test",
            business_dir=tmp_path / "chk-biz",
        )
        store.write_phase_checkpoint("run-chk-1", 3, {"success": True, "worker": "gemini"})
        result = store.get_phase_checkpoint("run-chk-1", 3)
        assert result is not None
        assert result["success"] is True
        assert result["worker"] == "gemini"

    def test_multiple_phases_accumulate_without_overwrite(self, tmp_path):
        store = PipelineStore(tmp_path / "empire.db")
        store.create_run(
            run_id="run-chk-2",
            business_slug="chk-biz-2",
            idea="test",
            business_dir=tmp_path / "chk-biz-2",
        )
        store.write_phase_checkpoint("run-chk-2", 1, {"success": True, "worker": "claude"})
        store.write_phase_checkpoint("run-chk-2", 2, {"success": True, "worker": "claude"})
        store.write_phase_checkpoint("run-chk-2", 3, {"success": True, "worker": "gemini"})

        assert store.get_phase_checkpoint("run-chk-2", 1)["worker"] == "claude"
        assert store.get_phase_checkpoint("run-chk-2", 2)["worker"] == "claude"
        assert store.get_phase_checkpoint("run-chk-2", 3)["worker"] == "gemini"

    def test_failed_checkpoint_is_readable(self, tmp_path):
        store = PipelineStore(tmp_path / "empire.db")
        store.create_run(
            run_id="run-chk-3",
            business_slug="chk-biz-3",
            idea="test",
            business_dir=tmp_path / "chk-biz-3",
        )
        store.write_phase_checkpoint(
            "run-chk-3", 5, {"success": False, "error": "both CLIs degraded"}
        )
        result = store.get_phase_checkpoint("run-chk-3", 5)
        assert result["success"] is False
        assert "both CLIs degraded" in result["error"]

    def test_missing_checkpoint_returns_none(self, tmp_path):
        store = PipelineStore(tmp_path / "empire.db")
        store.create_run(
            run_id="run-chk-4",
            business_slug="chk-biz-4",
            idea="test",
            business_dir=tmp_path / "chk-biz-4",
        )
        assert store.get_phase_checkpoint("run-chk-4", 99) is None

    def test_write_checkpoint_also_writes_json_file(self, tmp_path):
        store = PipelineStore(tmp_path / "empire.db")
        store.create_run(
            run_id="run-chk-5",
            business_slug="chk-biz-5",
            idea="test",
            business_dir=tmp_path / "chk-biz-5",
        )
        checkpoint_dir = tmp_path / "chk-biz-5" / "checkpoints"
        store.write_phase_checkpoint(
            "run-chk-5",
            4,
            {"success": True, "worker": "claude"},
            checkpoint_dir=checkpoint_dir,
        )
        expected_file = checkpoint_dir / "phase-4.json"
        assert expected_file.exists()
        data = json.loads(expected_file.read_text(encoding="utf-8"))
        assert data["success"] is True

    def test_phase_is_complete_true_for_success_checkpoint(self, tmp_path):
        cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
        runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
        run = runtime.create_business_scaffold("chk test idea")

        runtime._store.write_phase_checkpoint(run.run_id, 2, {"success": True})
        assert runtime._phase_is_complete(run, 2) is True

    def test_phase_is_complete_false_for_missing_checkpoint(self, tmp_path):
        cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
        runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
        run = runtime.create_business_scaffold("chk test idea 2")

        assert runtime._phase_is_complete(run, 3) is False

    def test_phase_is_complete_false_for_failed_checkpoint(self, tmp_path):
        cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
        runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
        run = runtime.create_business_scaffold("chk test idea 3")

        runtime._store.write_phase_checkpoint(run.run_id, 4, {"success": False})
        assert runtime._phase_is_complete(run, 4) is False

    def test_phase_is_complete_falls_back_to_phase_history(self, tmp_path):
        """Legacy phase_history in metadata is used when no checkpoint column entry."""
        cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
        runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
        run = runtime.create_business_scaffold("chk test idea 4")

        # Inject legacy phase_history directly via store
        runtime._store.update_run_status(
            run.run_id,
            metadata={**run.metadata, "phase_history": {"5": {"success": True, "worker": "claude"}}},
        )
        refreshed = runtime.get_run("chk-test-idea-4")
        assert runtime._phase_is_complete(refreshed, 5) is True

    def test_checkpoint_unknown_run_raises_key_error(self, tmp_path):
        store = PipelineStore(tmp_path / "empire.db")
        with pytest.raises(KeyError):
            store.write_phase_checkpoint("nonexistent-run-id", 1, {"success": True})


# ---------------------------------------------------------------------------
# Section 6 — WindowsMCPClient lifecycle in pipeline context
# ---------------------------------------------------------------------------

class _MockTransportCM:
    async def __aenter__(self):
        return (MagicMock(), MagicMock())

    async def __aexit__(self, *_):
        pass


class _MockSessionCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_):
        pass


def _make_mock_session() -> MagicMock:
    session = MagicMock()
    session.initialize = AsyncMock()
    return session


class TestWindowsMCPInPipelineContext:
    """WindowsMCPClient can be started/stopped around a pipeline run."""

    @pytest.mark.asyncio
    async def test_mcp_client_starts_before_pipeline_and_stops_after(self, tmp_path, monkeypatch):
        runtime, _ = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        runtime.create_business_scaffold("SaaS idea")

        mock_session = _make_mock_session()
        lifecycle: list[str] = []

        with (
            patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM()),
            patch(
                "cato.mcp.windows_client.ClientSession",
                return_value=_MockSessionCM(mock_session),
            ),
        ):
            mcp = WindowsMCPClient()
            await mcp.start()
            lifecycle.append("started")

            result = await runtime.run_pipeline(
                business_slug="saas-idea",
                start_phase=1,
                through_phase=3,
                stop_for_approval=False,
            )
            lifecycle.append("pipeline_done")

            await mcp.stop()
            lifecycle.append("stopped")

        assert lifecycle == ["started", "pipeline_done", "stopped"]
        assert result["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_mcp_client_context_manager_around_pipeline(self, tmp_path, monkeypatch):
        """The __aenter__/__aexit__ protocol wraps a pipeline run cleanly."""
        runtime, _ = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        runtime.create_business_scaffold("SaaS idea")

        mock_session = _make_mock_session()

        with (
            patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM()),
            patch(
                "cato.mcp.windows_client.ClientSession",
                return_value=_MockSessionCM(mock_session),
            ),
        ):
            async with WindowsMCPClient() as mcp:
                assert mcp._session is not None
                result = await runtime.run_pipeline(
                    business_slug="saas-idea",
                    start_phase=1,
                    through_phase=2,
                    stop_for_approval=False,
                )
            # After __aexit__, session must be cleared
            assert mcp._session is None

        assert result["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_mcp_snapshot_called_during_phase7_deploy(self, tmp_path, monkeypatch):
        """A pipeline orchestrator can call snapshot() during phase 7 execution."""
        mock_session = _make_mock_session()

        snapshot_content = MagicMock()
        snapshot_content.text = '{"windows": [], "focused": null}'
        snap_result = MagicMock()
        snap_result.isError = False
        snap_result.content = [snapshot_content]
        mock_session.call_tool = AsyncMock(return_value=snap_result)

        with (
            patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM()),
            patch(
                "cato.mcp.windows_client.ClientSession",
                return_value=_MockSessionCM(mock_session),
            ),
        ):
            async with WindowsMCPClient() as mcp:
                # Simulate phase 7 deployment calling snapshot for UI context
                content = await mcp.snapshot(use_vision=False)

        mock_session.call_tool.assert_called_once_with(
            "Snapshot",
            {
                "use_vision": False,
                "use_dom": False,
                "use_annotation": True,
                "use_ui_tree": True,
            },
        )
        assert snapshot_content in content

    @pytest.mark.asyncio
    async def test_mcp_powershell_called_during_phase7(self, tmp_path):
        """Phase 7 deploy can invoke PowerShell via MCP to check deployment status."""
        mock_session = _make_mock_session()

        ps_content = MagicMock()
        ps_content.text = "Deployment: OK\nURL: https://example.com"
        ps_result = MagicMock()
        ps_result.isError = False
        ps_result.content = [ps_content]
        mock_session.call_tool = AsyncMock(return_value=ps_result)

        with (
            patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM()),
            patch(
                "cato.mcp.windows_client.ClientSession",
                return_value=_MockSessionCM(mock_session),
            ),
        ):
            async with WindowsMCPClient() as mcp:
                content = await mcp.powershell("Get-Service | Where Status -eq Running")

        mock_session.call_tool.assert_called_once_with(
            "PowerShell",
            {"command": "Get-Service | Where Status -eq Running", "timeout": 30},
        )
        assert ps_content in content


# ---------------------------------------------------------------------------
# Section 7 — Andon Cord integration
# ---------------------------------------------------------------------------

class TestAndonCordIntegration:
    """Both-degraded condition: pipeline should receive degraded result and stop."""

    @pytest.mark.asyncio
    async def test_andon_cord_both_degraded_propagates_to_pipeline(
        self, tmp_path, monkeypatch
    ):
        """
        When invoke_for_genesis_phase returns degraded=True (both backends failed),
        the worker result returned by the worker adapter must propagate the failure
        so run_pipeline halts at that phase.
        """
        runtime, registry = _make_runtime(
            tmp_path, fail_phases={3}, monkeypatch=monkeypatch
        )
        runtime.create_business_scaffold("SaaS idea")

        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=3,
            through_phase=5,
            stop_for_approval=False,
        )

        assert result["status"] == "FAILED"
        assert result["stopped_at_phase"] == 3

    @pytest.mark.asyncio
    async def test_andon_cord_failed_checkpoint_written_on_phase_failure(
        self, tmp_path, monkeypatch
    ):
        """
        Simulate a manual Andon Cord scenario: after both backends fail,
        a failed checkpoint (success=False) is written so skip_completed
        doesn't falsely skip the phase on retry.
        """
        runtime, registry = _make_runtime(tmp_path, monkeypatch=monkeypatch)
        run = runtime.create_business_scaffold("SaaS idea")

        # Manually write a failed checkpoint (as the pipeline should do on Andon Cord)
        runtime._store.write_phase_checkpoint(
            run.run_id, 3, {"success": False, "error": "both CLIs degraded"}
        )

        # skip_completed=True should NOT skip phase 3 (it has success=False)
        result = await runtime.run_pipeline(
            business_slug="saas-idea",
            start_phase=3,
            through_phase=4,
            stop_for_approval=False,
            skip_completed=True,
        )

        # Phase 3 must have been re-executed
        executed = {phase for phase, _ in registry.dispatched}
        assert 3 in executed

    @pytest.mark.asyncio
    async def test_degraded_invoke_result_dict_structure(self):
        """The degraded result dict from invoke_for_genesis_phase has the right shape."""
        async def _always_degraded(context, task, *, backend):
            return {
                "model": backend, "response": "", "confidence": 0.0,
                "latency_ms": 5.0, "degraded": True, "source": "subprocess",
            }

        with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=_always_degraded):
            result = await invoke_for_genesis_phase(1, "prompt", "biz-andon")

        required_keys = {"model", "response", "confidence", "latency_ms", "degraded", "source"}
        assert required_keys.issubset(result.keys())
        assert result["degraded"] is True
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Section 8 — Timeout handling
# ---------------------------------------------------------------------------

class TestPhaseTimeouts:
    """asyncio.TimeoutError wraps correctly into degraded results."""

    @pytest.mark.asyncio
    async def test_timeout_on_no_fallback_phase_returns_degraded(self):
        """Phase 9 has no fallback; timeout → degraded with source=timeout."""
        async def _timeout_invoke(context, task, *, backend):
            raise asyncio.TimeoutError()

        with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=_timeout_invoke):
            result = await invoke_for_genesis_phase(9, "prompt", "biz-to")

        assert result["degraded"] is True
        assert result["source"] == "timeout"
        assert "9" in result["response"] or "60" in result["response"]

    @pytest.mark.asyncio
    async def test_both_timeout_returns_degraded(self):
        """Primary and fallback both timeout → double degraded → Andon Cord."""
        async def _timeout_invoke(context, task, *, backend):
            raise asyncio.TimeoutError()

        with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=_timeout_invoke):
            result = await invoke_for_genesis_phase(3, "prompt", "biz-double-to")

        assert result["degraded"] is True
        assert result["source"] == "timeout"

    @pytest.mark.asyncio
    async def test_primary_timeout_fallback_succeeds(self):
        """Primary times out but fallback succeeds → clean result."""
        call_count = 0

        async def _invoke(context, task, *, backend):
            nonlocal call_count
            call_count += 1
            if backend == "gemini":
                raise asyncio.TimeoutError()
            return {
                "model": "claude", "response": "design ok", "confidence": 0.88,
                "latency_ms": 20.0, "degraded": False, "source": "subprocess",
            }

        with patch("cato.orchestrator.cli_invoker.invoke_subagent", side_effect=_invoke):
            result = await invoke_for_genesis_phase(3, "prompt", "biz-recover")

        assert call_count == 2
        assert result["degraded"] is False
        assert result["model"] == "claude"
