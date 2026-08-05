"""
cato/core/schedule_manager.py — YAML-based cron schedule manager for Cato.

Manages per-schedule YAML files in ~/.cato/schedules/.
Each schedule is an independent asyncio task that fires at the given cron expression.

File format (``~/.cato/schedules/<name>.yaml``):
    name: morning-brief
    cron: "0 8 * * *"
    skill: daily_digest
    args: {}
    budget_cap: 50
    enabled: true

All scheduling logic uses croniter (already a dependency).
Every execution is recorded in the AuditLog.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from ..audit import AuditLog
from ..platform import get_data_dir

logger = logging.getLogger(__name__)

_SCHEDULES_DIR = get_data_dir() / "schedules"
_AUDIT_SESSION = "cato-scheduler"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Schedule:
    """In-memory representation of a schedule YAML file."""
    name: str
    cron: str
    skill: str
    args: dict = field(default_factory=dict)
    budget_cap: int = 100          # cents
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    # ---- serialisation helpers ----

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "cron": self.cron,
            "skill": self.skill,
            "args": self.args,
            "budget_cap": self.budget_cap,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Schedule":
        return cls(
            name=str(d.get("name", "")),
            cron=str(d.get("cron", "")),
            skill=str(d.get("skill", "")),
            args=d.get("args") or {},
            budget_cap=int(d.get("budget_cap", 100)),
            enabled=bool(d.get("enabled", True)),
            created_at=float(d.get("created_at", time.time())),
        )

    def save(self, schedules_dir: Optional[Path] = None) -> None:
        d = schedules_dir or _SCHEDULES_DIR
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{self.name}.yaml"
        path.write_text(
            yaml.dump(self.to_dict(), default_flow_style=False, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Schedule loader
# ---------------------------------------------------------------------------

def load_schedule(path: Path) -> Optional[Schedule]:
    """Load a single schedule YAML file.  Returns None on parse error."""
    try:
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Schedule.from_dict(raw)
    except Exception as exc:
        logger.warning("Could not parse schedule %s: %s", path, exc)
        return None


def load_all_schedules(schedules_dir: Optional[Path] = None) -> list[Schedule]:
    """Return all valid schedules from the schedules directory."""
    d = schedules_dir or _SCHEDULES_DIR
    if not d.exists():
        return []
    schedules: list[Schedule] = []
    for p in sorted(d.glob("*.yaml")):
        s = load_schedule(p)
        if s is not None:
            schedules.append(s)
    return schedules


def delete_schedule(name: str, schedules_dir: Optional[Path] = None) -> bool:
    """Remove a schedule YAML file.  Returns True if the file existed."""
    d = schedules_dir or _SCHEDULES_DIR
    path = d / f"{name}.yaml"
    if path.exists():
        path.unlink()
        return True
    return False


def toggle_schedule(name: str, enabled: bool, schedules_dir: Optional[Path] = None) -> bool:
    """Enable or disable a schedule.  Returns True if found and updated."""
    d = schedules_dir or _SCHEDULES_DIR
    path = d / f"{name}.yaml"
    if not path.exists():
        return False
    s = load_schedule(path)
    if s is None:
        return False
    s.enabled = enabled
    s.save(d)
    return True


# ---------------------------------------------------------------------------
# Scheduler daemon
# ---------------------------------------------------------------------------

class SchedulerDaemon:
    """
    Asyncio-based scheduler that runs all enabled schedules concurrently.

    Usage (inside an async context)::

        daemon = SchedulerDaemon()
        await daemon.start()
        ...
        await daemon.stop()

    Each schedule gets its own asyncio.Task.  Tasks are cancelled on stop().
    A per-schedule *in-progress* flag prevents overlapping executions.
    """

    def __init__(
        self,
        schedules_dir: Optional[Path] = None,
        audit_log: Optional[AuditLog] = None,
        dispatch_fn: Optional[Any] = None,
    ) -> None:
        self._dir = schedules_dir or _SCHEDULES_DIR
        self._audit = audit_log
        self._dispatch_fn = dispatch_fn      # async callable(skill, args, session_id)
        self._tasks: dict[str, asyncio.Task] = {}
        self._in_progress: dict[str, bool] = {}

    async def start(self) -> None:
        """Load all schedules and spawn an asyncio task per enabled schedule."""
        try:
            from croniter import croniter as _croniter  # noqa: F401
        except ImportError:
            logger.warning("croniter not installed — SchedulerDaemon disabled")
            return

        schedules = load_all_schedules(self._dir)
        logger.info("SchedulerDaemon: loaded %d schedule(s)", len(schedules))
        for sched in schedules:
            if sched.enabled:
                self._spawn_task(sched)

    def _spawn_task(self, sched: Schedule) -> None:
        """Create and track an asyncio.Task for one schedule."""
        if sched.name in self._tasks and not self._tasks[sched.name].done():
            return  # already running
        self._in_progress[sched.name] = False
        task = asyncio.create_task(
            self._run_schedule(sched),
            name=f"schedule-{sched.name}",
        )
        self._tasks[sched.name] = task

    async def _run_schedule(self, sched: Schedule) -> None:
        """
        Loop forever: sleep until next_fire, then dispatch the skill.
        Reloads the YAML file each iteration so edits take effect without restart.
        """
        try:
            from croniter import croniter
        except ImportError:
            return

        logger.info("Schedule task started: name=%s cron=%s", sched.name, sched.cron)

        while True:
            try:
                # Reload schedule from disk so runtime changes are respected
                path = self._dir / f"{sched.name}.yaml"
                if path.exists():
                    fresh = load_schedule(path)
                    if fresh is not None:
                        sched = fresh

                if not sched.enabled:
                    logger.info("Schedule %s disabled — sleeping 60s", sched.name)
                    await asyncio.sleep(60)
                    continue

                now = time.time()
                try:
                    next_ts = croniter(sched.cron, now).get_next(float)
                except Exception as exc:
                    logger.warning("Invalid cron expression for %s: %s", sched.name, exc)
                    await asyncio.sleep(60)
                    continue

                sleep_secs = max(0.0, next_ts - time.time())
                logger.debug("Schedule %s: next fire in %.1fs", sched.name, sleep_secs)
                await asyncio.sleep(sleep_secs)

                # Skip if previous run still in progress
                if self._in_progress.get(sched.name):
                    logger.warning("Schedule %s: previous run still in progress — skipping", sched.name)
                    continue

                # Fire
                self._in_progress[sched.name] = True
                try:
                    await self._fire(sched)
                finally:
                    self._in_progress[sched.name] = False

            except asyncio.CancelledError:
                logger.info("Schedule task cancelled: %s", sched.name)
                return
            except Exception as exc:
                logger.error("Schedule %s error: %s", sched.name, exc, exc_info=True)
                await asyncio.sleep(60)

    async def _fire(self, sched: Schedule) -> None:
        """Execute one schedule firing: check budget, dispatch, audit."""
        session_id = f"sched-{sched.name}"
        logger.info("Firing schedule: name=%s skill=%s", sched.name, sched.skill)

        # Audit: record start
        if self._audit:
            try:
                self._audit.log(
                    session_id=session_id,
                    action_type="cron_fire",
                    tool_name=f"schedule.{sched.name}",
                    inputs={"skill": sched.skill, "args": sched.args, "cron": sched.cron},
                    outputs={"status": "fired"},
                )
            except Exception as exc:
                logger.warning("Audit log failed for schedule %s: %s", sched.name, exc)

        # Dispatch to registered handler or log fallback
        if self._dispatch_fn is not None:
            try:
                await self._dispatch_fn(
                    skill=sched.skill,
                    args=sched.args,
                    session_id=session_id,
                    budget_cap=sched.budget_cap,
                )
            except Exception as exc:
                logger.error("Schedule dispatch failed %s: %s", sched.name, exc)
                if self._audit:
                    try:
                        self._audit.log(
                            session_id=session_id,
                            action_type="cron_fire",
                            tool_name=f"schedule.{sched.name}",
                            inputs={"skill": sched.skill},
                            outputs={"status": "error"},
                            error=str(exc),
                        )
                    except Exception:
                        pass
        else:
            logger.debug("No dispatch_fn — schedule %s fired (no-op)", sched.name)

    async def reload(self) -> None:
        """Cancel all tasks and restart from current schedules on disk."""
        await self.stop()
        await self.start()

    async def fire_now(self, name: str) -> bool:
        """Immediately fire a named schedule, bypassing the cron timing.  Returns False if not found."""
        sched = self._load_by_name(name)
        if sched is None:
            return False
        if self._in_progress.get(name):
            logger.warning("Schedule %s already in progress", name)
            return False
        self._in_progress[name] = True
        try:
            await self._fire(sched)
        finally:
            self._in_progress[name] = False
        return True

    def _load_by_name(self, name: str) -> Optional[Schedule]:
        path = self._dir / f"{name}.yaml"
        if not path.exists():
            return None
        return load_schedule(path)

    async def stop(self) -> None:
        """Cancel all running schedule tasks and wait for them to finish."""
        tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._in_progress.clear()
        logger.info("SchedulerDaemon stopped")
