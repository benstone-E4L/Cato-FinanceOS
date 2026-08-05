"""
tests/test_cron_scheduler.py — Tests for SKILL 10: YAML-based Cron Scheduler.

Covers:
- Schedule YAML serialisation / deserialisation
- load_all_schedules, toggle_schedule, delete_schedule
- SchedulerDaemon.fire_now()
- SchedulerDaemon.start/stop lifecycle
- Budget-cap propagation
- In-progress guard (double-fire prevention)
- Audit log integration
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def schedules_dir(tmp_path: Path) -> Path:
    d = tmp_path / "schedules"
    d.mkdir()
    return d


def make_yaml(schedules_dir: Path, name: str, **kwargs) -> Path:
    data = {
        "name": name,
        "cron": kwargs.get("cron", "0 8 * * *"),
        "skill": kwargs.get("skill", "daily_digest"),
        "args": kwargs.get("args", {}),
        "budget_cap": kwargs.get("budget_cap", 100),
        "enabled": kwargs.get("enabled", True),
        "created_at": kwargs.get("created_at", time.time()),
    }
    p = schedules_dir / f"{name}.yaml"
    p.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Schedule dataclass
# ---------------------------------------------------------------------------

class TestScheduleDataclass:
    def test_from_dict_defaults(self):
        from cato.core.schedule_manager import Schedule
        s = Schedule.from_dict({"name": "x", "cron": "* * * * *", "skill": "test"})
        assert s.name == "x"
        assert s.cron == "* * * * *"
        assert s.skill == "test"
        assert s.budget_cap == 100
        assert s.enabled is True
        assert isinstance(s.args, dict)

    def test_to_dict_roundtrip(self):
        from cato.core.schedule_manager import Schedule
        s = Schedule(name="morning", cron="0 8 * * *", skill="brief", budget_cap=50)
        d = s.to_dict()
        s2 = Schedule.from_dict(d)
        assert s2.name == s.name
        assert s2.cron == s.cron
        assert s2.skill == s.skill
        assert s2.budget_cap == s.budget_cap

    def test_save_creates_yaml_file(self, schedules_dir: Path):
        from cato.core.schedule_manager import Schedule
        s = Schedule(name="test-sched", cron="0 9 * * 1", skill="email", budget_cap=25)
        s.save(schedules_dir)
        p = schedules_dir / "test-sched.yaml"
        assert p.exists()
        loaded = yaml.safe_load(p.read_text())
        assert loaded["name"] == "test-sched"
        assert loaded["cron"] == "0 9 * * 1"
        assert loaded["budget_cap"] == 25

    def test_from_dict_missing_budget_cap_defaults_to_100(self):
        from cato.core.schedule_manager import Schedule
        # When budget_cap is omitted, should default to 100
        s = Schedule.from_dict({"name": "x", "cron": "* * * * *", "skill": "s"})
        assert s.budget_cap == 100

    def test_from_dict_invalid_budget_cap_raises(self):
        from cato.core.schedule_manager import Schedule
        # int("abc") raises ValueError — this is expected behaviour
        with pytest.raises((ValueError, TypeError)):
            Schedule.from_dict({"name": "x", "cron": "* * * * *", "skill": "s", "budget_cap": "abc"})

    def test_enabled_false(self, schedules_dir: Path):
        from cato.core.schedule_manager import Schedule
        s = Schedule(name="disabled", cron="0 0 * * *", skill="noop", enabled=False)
        s.save(schedules_dir)
        p = schedules_dir / "disabled.yaml"
        data = yaml.safe_load(p.read_text())
        assert data["enabled"] is False


# ---------------------------------------------------------------------------
# load_schedule / load_all_schedules
# ---------------------------------------------------------------------------

class TestLoadSchedules:
    def test_load_single_valid(self, schedules_dir: Path):
        from cato.core.schedule_manager import load_schedule
        p = make_yaml(schedules_dir, "morning")
        s = load_schedule(p)
        assert s is not None
        assert s.name == "morning"

    def test_load_invalid_yaml_returns_none(self, tmp_path: Path):
        from cato.core.schedule_manager import load_schedule
        p = tmp_path / "bad.yaml"
        p.write_text("{{ invalid: yaml: ]]]", encoding="utf-8")
        s = load_schedule(p)
        assert s is None

    def test_load_all_empty_dir(self, schedules_dir: Path):
        from cato.core.schedule_manager import load_all_schedules
        result = load_all_schedules(schedules_dir)
        assert result == []

    def test_load_all_multiple(self, schedules_dir: Path):
        from cato.core.schedule_manager import load_all_schedules
        make_yaml(schedules_dir, "sched-a", cron="0 8 * * *")
        make_yaml(schedules_dir, "sched-b", cron="0 9 * * *")
        make_yaml(schedules_dir, "sched-c", cron="0 10 * * *")
        result = load_all_schedules(schedules_dir)
        assert len(result) == 3
        names = {s.name for s in result}
        assert names == {"sched-a", "sched-b", "sched-c"}

    def test_load_all_skips_non_yaml(self, schedules_dir: Path):
        from cato.core.schedule_manager import load_all_schedules
        make_yaml(schedules_dir, "valid")
        (schedules_dir / "not-yaml.txt").write_text("ignored", encoding="utf-8")
        result = load_all_schedules(schedules_dir)
        assert len(result) == 1

    def test_load_nonexistent_dir(self, tmp_path: Path):
        from cato.core.schedule_manager import load_all_schedules
        result = load_all_schedules(tmp_path / "does_not_exist")
        assert result == []

    def test_shipped_example_schedules_parse_and_name_a_live_skill(self):
        """Every example schedule must parse and must not name a retired skill.

        (t22: this replaced a test that pinned the three Stage-1 arbitrage
        example schedules, deleted along with the arbitrage subsystem. A
        shipped example that names a skill the dispatcher no longer handles
        silently falls through to the generic ingest path, so the check that
        matters now is "no example points at a removed subsystem".)
        """
        from cato.core.schedule_manager import load_schedule

        repo_root = Path(__file__).resolve().parents[1]
        examples = repo_root / "examples" / "schedules"
        files = sorted(examples.glob("*.yaml"))
        assert files, "examples/schedules must not be empty"

        for path in files:
            schedule = load_schedule(path)
            assert schedule is not None, f"{path.name} failed to parse"
            assert schedule.name == path.stem
            assert schedule.skill, f"{path.name} has no skill"
            assert "arbitrage" not in schedule.skill, (
                f"{path.name} references the removed arbitrage subsystem"
            )


# ---------------------------------------------------------------------------
# toggle_schedule / delete_schedule
# ---------------------------------------------------------------------------

class TestToggleAndDelete:
    def test_toggle_enable(self, schedules_dir: Path):
        from cato.core.schedule_manager import toggle_schedule, load_schedule
        make_yaml(schedules_dir, "t1", enabled=False)
        ok = toggle_schedule("t1", enabled=True, schedules_dir=schedules_dir)
        assert ok is True
        s = load_schedule(schedules_dir / "t1.yaml")
        assert s is not None
        assert s.enabled is True

    def test_toggle_disable(self, schedules_dir: Path):
        from cato.core.schedule_manager import toggle_schedule, load_schedule
        make_yaml(schedules_dir, "t2", enabled=True)
        toggle_schedule("t2", enabled=False, schedules_dir=schedules_dir)
        s = load_schedule(schedules_dir / "t2.yaml")
        assert s is not None
        assert s.enabled is False

    def test_toggle_missing_returns_false(self, schedules_dir: Path):
        from cato.core.schedule_manager import toggle_schedule
        ok = toggle_schedule("no-such-schedule", enabled=True, schedules_dir=schedules_dir)
        assert ok is False

    def test_delete_existing(self, schedules_dir: Path):
        from cato.core.schedule_manager import delete_schedule
        make_yaml(schedules_dir, "del-me")
        ok = delete_schedule("del-me", schedules_dir=schedules_dir)
        assert ok is True
        assert not (schedules_dir / "del-me.yaml").exists()

    def test_delete_nonexistent(self, schedules_dir: Path):
        from cato.core.schedule_manager import delete_schedule
        ok = delete_schedule("ghost", schedules_dir=schedules_dir)
        assert ok is False


# ---------------------------------------------------------------------------
# SchedulerDaemon — fire_now
# ---------------------------------------------------------------------------

class TestSchedulerDaemonFireNow:
    @pytest.mark.asyncio
    async def test_fire_now_calls_dispatch(self, schedules_dir: Path):
        from cato.core.schedule_manager import SchedulerDaemon
        make_yaml(schedules_dir, "my-sched", skill="daily_digest")
        calls = []

        async def dispatch_fn(skill, args, session_id, budget_cap):
            calls.append({"skill": skill, "session_id": session_id, "budget_cap": budget_cap})

        daemon = SchedulerDaemon(schedules_dir=schedules_dir, dispatch_fn=dispatch_fn)
        ok = await daemon.fire_now("my-sched")
        assert ok is True
        assert len(calls) == 1
        assert calls[0]["skill"] == "daily_digest"
        assert calls[0]["session_id"] == "sched-my-sched"
        assert calls[0]["budget_cap"] == 100

    @pytest.mark.asyncio
    async def test_fire_now_missing_returns_false(self, schedules_dir: Path):
        from cato.core.schedule_manager import SchedulerDaemon
        daemon = SchedulerDaemon(schedules_dir=schedules_dir)
        ok = await daemon.fire_now("no-such")
        assert ok is False

    @pytest.mark.asyncio
    async def test_fire_now_in_progress_guard(self, schedules_dir: Path):
        """Second concurrent fire_now on the same schedule must be skipped."""
        from cato.core.schedule_manager import SchedulerDaemon
        make_yaml(schedules_dir, "slow-sched")
        calls = []
        block = asyncio.Event()

        async def slow_dispatch(skill, args, session_id, budget_cap):
            calls.append(1)
            await block.wait()

        daemon = SchedulerDaemon(schedules_dir=schedules_dir, dispatch_fn=slow_dispatch)
        # Start first fire without awaiting
        task1 = asyncio.create_task(daemon.fire_now("slow-sched"))
        await asyncio.sleep(0.01)  # let task1 enter dispatch
        # Second fire should see in_progress=True
        daemon._in_progress["slow-sched"] = True
        ok2 = await daemon.fire_now("slow-sched")
        assert ok2 is False
        block.set()
        await task1

    @pytest.mark.asyncio
    async def test_fire_now_respects_budget_cap(self, schedules_dir: Path):
        from cato.core.schedule_manager import SchedulerDaemon
        make_yaml(schedules_dir, "cap-sched", budget_cap=42)
        received_caps = []

        async def dispatch_fn(skill, args, session_id, budget_cap):
            received_caps.append(budget_cap)

        daemon = SchedulerDaemon(schedules_dir=schedules_dir, dispatch_fn=dispatch_fn)
        await daemon.fire_now("cap-sched")
        assert received_caps == [42]

    @pytest.mark.asyncio
    async def test_fire_now_logs_to_audit(self, schedules_dir: Path, tmp_path: Path):
        from cato.core.schedule_manager import SchedulerDaemon
        from cato.audit import AuditLog
        make_yaml(schedules_dir, "audited-sched")
        db = tmp_path / "cato.db"
        audit = AuditLog(db_path=db)
        audit.connect()

        daemon = SchedulerDaemon(
            schedules_dir=schedules_dir,
            audit_log=audit,
        )
        await daemon.fire_now("audited-sched")
        rows = audit.get_session_rows("sched-audited-sched")
        assert len(rows) == 1
        assert rows[0]["action_type"] == "cron_fire"
        audit.close()


# ---------------------------------------------------------------------------
# SchedulerDaemon — start/stop lifecycle
# ---------------------------------------------------------------------------

class TestSchedulerDaemonLifecycle:
    @pytest.mark.asyncio
    async def test_start_spawns_tasks_for_enabled(self, schedules_dir: Path):
        from cato.core.schedule_manager import SchedulerDaemon
        make_yaml(schedules_dir, "enabled-1", enabled=True)
        make_yaml(schedules_dir, "enabled-2", enabled=True)
        make_yaml(schedules_dir, "disabled-1", enabled=False)

        daemon = SchedulerDaemon(schedules_dir=schedules_dir)
        await daemon.start()
        try:
            assert len(daemon._tasks) == 2
            assert "enabled-1" in daemon._tasks
            assert "enabled-2" in daemon._tasks
            assert "disabled-1" not in daemon._tasks
        finally:
            await daemon.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_all_tasks(self, schedules_dir: Path):
        from cato.core.schedule_manager import SchedulerDaemon
        make_yaml(schedules_dir, "task-1")
        make_yaml(schedules_dir, "task-2")

        daemon = SchedulerDaemon(schedules_dir=schedules_dir)
        await daemon.start()
        assert len(daemon._tasks) == 2
        await daemon.stop()
        assert len(daemon._tasks) == 0

    @pytest.mark.asyncio
    async def test_start_idempotent_no_duplicate_tasks(self, schedules_dir: Path):
        from cato.core.schedule_manager import SchedulerDaemon
        make_yaml(schedules_dir, "once")

        daemon = SchedulerDaemon(schedules_dir=schedules_dir)
        await daemon.start()
        try:
            task_before = daemon._tasks.get("once")
            # calling start again should not spawn a duplicate
            await daemon.start()
            task_after = daemon._tasks.get("once")
            assert task_before is task_after
        finally:
            await daemon.stop()

    @pytest.mark.asyncio
    async def test_croniter_not_installed_graceful(self, schedules_dir: Path):
        from cato.core.schedule_manager import SchedulerDaemon
        make_yaml(schedules_dir, "noop")
        daemon = SchedulerDaemon(schedules_dir=schedules_dir)
        with patch("builtins.__import__", side_effect=lambda name, *a, **kw: (_ for _ in ()).throw(ImportError()) if name == "croniter" else __import__(name, *a, **kw)):
            # Should not raise
            await daemon.start()
            assert len(daemon._tasks) == 0
