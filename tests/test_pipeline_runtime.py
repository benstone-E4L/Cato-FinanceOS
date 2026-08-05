from __future__ import annotations

from pathlib import Path

import pytest

from cato.config import CatoConfig
from cato.pipeline.models import WorkerResult
from cato.pipeline.phase_validation import EmpirePhaseValidator, PhaseValidationResult
from cato.pipeline.runtime import EmpireRuntime, PhaseRouter
from cato.pipeline.store import PipelineStore


class _FakeWorker:
    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, assignment):
        return WorkerResult(
            worker=self.name,
            success=True,
            response=f"{self.name} completed phase {assignment.phase}",
            source="test",
            latency_ms=5.0,
        )


def test_phase_router_defaults():
    router = PhaseRouter()
    assert router.worker_for(1) == "claude"
    assert router.worker_for(3) == "gemini"
    assert router.worker_for(5) == "claude"


def test_empire_runtime_creates_business_scaffold(tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
    run = runtime.create_business_scaffold("AI invoice scanner for freelancers")

    business_dir = tmp_path / "businesses" / "ai-invoice-scanner-for-freelancers"
    assert run.business_dir == business_dir
    assert (business_dir / "phase_1_outputs").exists()
    assert (business_dir / "phase_2_outputs").exists()
    assert (business_dir / "phase_3_outputs").exists()
    assert (business_dir / "brand").exists()
    assert (business_dir / "website").exists()
    assert (business_dir / "worktrees").exists()
    assert (business_dir / "audit").exists()
    assert (business_dir / "deployment").exists()
    assert (business_dir / "manifest.json").exists()
    assert (tmp_path / "businesses" / "active-tasks.json").exists()


def test_build_phase_prompt_uses_phase_library(tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
    runtime.create_business_scaffold("AI invoice scanner for freelancers")

    bundle = runtime.build_phase_prompt(
        business_slug="ai-invoice-scanner-for-freelancers",
        phase=2,
    )

    assert bundle.spec.worker == "claude"
    assert "Atlas-Luna" in bundle.prompt
    assert any(req.script and req.script.name == "create_checkpoint.py" for req in bundle.requirements)


@pytest.mark.asyncio
async def test_dispatch_phase_records_task_and_result(tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    store = PipelineStore(tmp_path / "empire.db")
    runtime = EmpireRuntime(
        cfg,
        store=store,
        worker_registry={
            "claude": _FakeWorker("claude"),
            "gemini": _FakeWorker("gemini"),
            "codex": _FakeWorker("codex"),
        },
    )
    runtime.create_business_scaffold("AI invoice scanner for freelancers")

    result = await runtime.dispatch_phase(
        business_slug="ai-invoice-scanner-for-freelancers",
        phase=3,
    )

    assert result.success is True
    tasks = runtime.tasks_for("ai-invoice-scanner-for-freelancers")
    assert len(tasks) == 1
    assert tasks[0]["worker"] == "gemini"
    assert tasks[0]["status"] == "done"
    assert Path(tasks[0]["prompt_file"]).exists()


@pytest.mark.asyncio
async def test_execute_phase_runs_requirements(tmp_path, monkeypatch):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    store = PipelineStore(tmp_path / "empire.db")
    runtime = EmpireRuntime(
        cfg,
        store=store,
        worker_registry={
            "claude": _FakeWorker("claude"),
            "gemini": _FakeWorker("gemini"),
            "codex": _FakeWorker("codex"),
        },
    )
    runtime.create_business_scaffold("AI invoice scanner for freelancers")

    async def _fake_requirement(**kwargs):
        return {
            "task_id": "script-task",
            "script": "fake.py",
            "args": ["--phase", "1"],
            "success": True,
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 1.0,
            "required": True,
        }

    monkeypatch.setattr(runtime, "_run_requirement", _fake_requirement)
    monkeypatch.setattr(
        runtime._validator,
        "validate",
        lambda run, spec: PhaseValidationResult(success=True),
    )
    summary = await runtime.execute_phase(
        business_slug="ai-invoice-scanner-for-freelancers",
        phase=1,
    )

    assert summary["worker_result"].success is True
    assert len(summary["requirement_results"]) >= 1
    run = runtime.get_run("ai-invoice-scanner-for-freelancers")
    assert run is not None
    assert run.metadata["phase_history"]["1"]["success"] is True


@pytest.mark.asyncio
async def test_run_pipeline_stops_for_phase7_approval(tmp_path, monkeypatch):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    store = PipelineStore(tmp_path / "empire.db")
    runtime = EmpireRuntime(
        cfg,
        store=store,
        worker_registry={
            "claude": _FakeWorker("claude"),
            "gemini": _FakeWorker("gemini"),
            "codex": _FakeWorker("codex"),
        },
    )
    runtime.create_business_scaffold("AI invoice scanner for freelancers")

    async def _fake_requirement(**kwargs):
        return {
            "task_id": "script-task",
            "script": "fake.py",
            "args": [],
            "success": True,
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 1.0,
            "required": True,
        }

    monkeypatch.setattr(runtime, "_run_requirement", _fake_requirement)
    monkeypatch.setattr(
        runtime._validator,
        "validate",
        lambda run, spec: PhaseValidationResult(success=True),
    )
    summary = await runtime.run_pipeline(
        business_slug="ai-invoice-scanner-for-freelancers",
        start_phase=1,
        through_phase=9,
        stop_for_approval=True,
    )

    assert summary["status"] == "AWAITING_APPROVAL"
    assert summary["stopped_at_phase"] == 7


@pytest.mark.asyncio
async def test_execute_phase_fails_when_validation_fails(tmp_path, monkeypatch):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    store = PipelineStore(tmp_path / "empire.db")
    runtime = EmpireRuntime(
        cfg,
        store=store,
        worker_registry={
            "claude": _FakeWorker("claude"),
            "gemini": _FakeWorker("gemini"),
            "codex": _FakeWorker("codex"),
        },
    )
    runtime.create_business_scaffold("AI invoice scanner for freelancers")

    async def _fake_requirement(**kwargs):
        return {
            "task_id": "script-task",
            "script": "fake.py",
            "args": [],
            "success": True,
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
            "duration_ms": 1.0,
            "required": True,
        }

    monkeypatch.setattr(runtime, "_run_requirement", _fake_requirement)
    monkeypatch.setattr(
        runtime._validator,
        "validate",
        lambda run, spec: PhaseValidationResult(success=False, errors=["missing output"]),
    )
    summary = await runtime.execute_phase(
        business_slug="ai-invoice-scanner-for-freelancers",
        phase=1,
    )

    assert summary["worker_result"].success is False
    assert "missing output" in summary["worker_result"].error


def test_phase5_validator_checks_checkpoint_and_project_shape(tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
    run = runtime.create_business_scaffold("AI invoice scanner for freelancers")
    validator = EmpirePhaseValidator()
    spec = runtime._phase_library.spec_for(5)

    website = run.business_dir / "website"
    (website / ".ralph").mkdir(parents=True, exist_ok=True)
    (website / "specs").mkdir(parents=True, exist_ok=True)
    (website / "src").mkdir(parents=True, exist_ok=True)
    for name in [
        "chunk1-setup.md",
        "chunk2-auth.md",
        "chunk3-core.md",
        "chunk4-ui.md",
        "chunk5-payments.md",
        "chunk6-final.md",
    ]:
        (website / "specs" / name).write_text("# done", encoding="utf-8")
    for name in ("app.ts", "auth.ts", "core.ts", "ui.tsx", "payments.ts"):
        (website / "src" / name).write_text("export const ok = true;", encoding="utf-8")
    (website / "IMPLEMENTATION_PLAN.md").write_text("plan " * 40, encoding="utf-8")
    (website / ".ralph" / "progress.md").write_text(
        "chunk 1 validated\nchunk 2 validated\nchunk 3 validated",
        encoding="utf-8",
    )
    (website / "package.json").write_text(
        '{"scripts":{"build":"next build","test":"vitest","typecheck":"tsc --noEmit"}}',
        encoding="utf-8",
    )
    checkpoints = run.business_dir / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    (checkpoints / "phase_5.json").write_text(
        (
            '{'
            '"verified": true,'
            '"construction_details": {'
            '"chunks_completed": 6,'
            '"all_chunks_passing": true,'
            '"source_code_generated": true'
            '}'
            '}'
        ),
        encoding="utf-8",
    )

    result = validator.validate(run, spec)
    assert result.success is True


def test_phase7_validator_checks_post_deploy_health_and_rollback(tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
    run = runtime.create_business_scaffold("AI invoice scanner for freelancers")
    validator = EmpirePhaseValidator()
    spec = runtime._phase_library.spec_for(7)

    deployment = run.business_dir / "deployment"
    deployment.mkdir(parents=True, exist_ok=True)
    (deployment / "live_url.txt").write_text("https://example.com", encoding="utf-8")
    (deployment / "phase7_devops_e2e.yaml").write_text("status: pass", encoding="utf-8")
    (deployment / "phase7_deploy.yaml").write_text(
        "deployment_id: dep_12345\nurl: https://example.com\n",
        encoding="utf-8",
    )
    (run.business_dir / "post_deploy_validation_results.json").write_text(
        (
            '{'
            '"summary":{"total_tests":7,"passed":7,"failed":0,"warnings":0,"errors":0},'
            '"link_health_report":{"health_percentage":100,"broken_links":0},'
            '"results":['
            '{"name":"Homepage","status":"pass"},'
            '{"name":"Signup","status":"pass"},'
            '{"name":"Login","status":"pass"},'
            '{"name":"Core Feature","status":"pass"},'
            '{"name":"Stripe Checkout","status":"pass"},'
            '{"name":"Database","status":"pass"},'
            '{"name":"Link Health Check","status":"pass"}'
            '],'
            '"auto_rollback":{"status":"not_needed","critical_failures":0}'
            '}'
        ),
        encoding="utf-8",
    )

    result = validator.validate(run, spec)
    assert result.success is True

    (run.business_dir / "post_deploy_validation_results.json").write_text(
        (
            '{'
            '"summary":{"total_tests":7,"passed":5,"failed":1,"warnings":0,"errors":1},'
            '"link_health_report":{"health_percentage":80,"broken_links":3},'
            '"results":['
            '{"name":"Homepage","status":"pass"},'
            '{"name":"Signup","status":"fail"},'
            '{"name":"Login","status":"error"}'
            '],'
            '"auto_rollback":{"status":"triggered_success","critical_failures":2}'
            '}'
        ),
        encoding="utf-8",
    )
    bad = validator.validate(run, spec)
    assert bad.success is False
    assert any("auto rollback" in error.lower() for error in bad.errors)
