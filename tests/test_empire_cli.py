from __future__ import annotations

from click.testing import CliRunner

from cato.cli import main
from cato.config import CatoConfig
from cato.pipeline.models import EmpireRun
from cato.pipeline.runtime import EmpireRuntime
from cato.pipeline.store import PipelineStore


def test_empire_init_command_creates_business(monkeypatch, tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    monkeypatch.setattr("cato.cli.CatoConfig.load", lambda: cfg)

    runner = CliRunner()
    result = runner.invoke(main, ["empire", "init", "AI invoice scanner for freelancers"])

    assert result.exit_code == 0
    assert "ai-invoice-scanner-for-freelancers" in result.output
    assert (tmp_path / "businesses" / "ai-invoice-scanner-for-freelancers").exists()


def test_empire_status_command_lists_runs(monkeypatch, tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
    runtime.create_business_scaffold("AI invoice scanner for freelancers")
    monkeypatch.setattr("cato.cli.CatoConfig.load", lambda: cfg)

    runner = CliRunner()
    result = runner.invoke(main, ["empire", "status"])

    assert result.exit_code == 0
    assert "ai-invoice-scanner-for-freelancers" in result.output


def test_empire_prompt_command_renders_phase_handoff(monkeypatch, tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    runtime = EmpireRuntime(cfg, store=PipelineStore(tmp_path / "empire.db"))
    runtime.create_business_scaffold("AI invoice scanner for freelancers")
    monkeypatch.setattr("cato.cli.CatoConfig.load", lambda: cfg)

    runner = CliRunner()
    result = runner.invoke(main, ["empire", "prompt", "ai-invoice-scanner-for-freelancers", "5"])

    assert result.exit_code == 0
    assert "Ralph Loop" in result.output
    assert "Worker: claude" in result.output


def test_empire_run_command_starts_pipeline(monkeypatch, tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    monkeypatch.setattr("cato.cli.CatoConfig.load", lambda: cfg)

    created = EmpireRun(
        run_id="run-test",
        business_slug="ai-invoice-scanner-for-freelancers",
        idea="AI invoice scanner for freelancers",
        business_dir=tmp_path / "businesses" / "ai-invoice-scanner-for-freelancers",
    )

    monkeypatch.setattr(
        "cato.pipeline.runtime.EmpireRuntime.create_business_scaffold",
        lambda self, idea, business_slug=None: created,
    )
    async def _fake_run_pipeline(self, **kwargs):
        return {
            "status": "AWAITING_APPROVAL",
            "completed_phases": [1, 2, 3, 4, 5, 6, 7],
            "stopped_at_phase": 7,
        }
    monkeypatch.setattr("cato.pipeline.runtime.EmpireRuntime.run_pipeline", _fake_run_pipeline)

    runner = CliRunner()
    result = runner.invoke(main, ["empire", "run", "AI invoice scanner for freelancers"])

    assert result.exit_code == 0
    assert "Pipeline started for" in result.output
    assert "AWAITING_APPROVAL" in result.output


def test_empire_resume_command_runs_from_requested_phase(monkeypatch, tmp_path):
    cfg = CatoConfig(pipeline_root_dir=str(tmp_path / "businesses"))
    monkeypatch.setattr("cato.cli.CatoConfig.load", lambda: cfg)

    async def _fake_run_pipeline(self, **kwargs):
        assert kwargs["start_phase"] == 8
        return {
            "status": "COMPLETED",
            "completed_phases": [8, 9],
            "stopped_at_phase": 9,
        }
    monkeypatch.setattr("cato.pipeline.runtime.EmpireRuntime.run_pipeline", _fake_run_pipeline)

    runner = CliRunner()
    result = runner.invoke(main, ["empire", "resume", "ai-invoice-scanner-for-freelancers", "--phase", "8"])

    assert result.exit_code == 0
    assert "COMPLETED" in result.output
