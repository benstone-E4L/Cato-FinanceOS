"""
cato/orchestrator/clawflows.py — Clawflows: Proactive Trigger Registry (Skill 5).

Manages YAML-defined flows that execute steps sequentially via skill/tool dispatch.
State is persisted to SQLite after each step, enabling resume-safe execution.

Flow YAML schema::

    name: morning-brief
    trigger:
      type: manual   # manual | cron | event | condition
    steps:
      - skill: web.search
        args: {query: "AI news today"}
      - skill: daily_digest
        args: {}
    budget_cap: 100

SECURITY MODEL
--------------
This module used to be the SEVENTH instance of the defect class this codebase
has now fixed six times: a dispatch entry point that reached real tool handlers
while touching none of the gates. ``_dispatch_step`` pulled the handler straight
out of ``cato.agent_loop._TOOL_REGISTRY`` and awaited it, so a flow step naming
``shell``, ``file``, ``send_email`` or ``genesis`` ran with no STOP check, no
risk classification, no delegation-token authorization, no ActionGuard, no
approval ticket and no ledger entry. Flow YAML is writable over the same
``X-Cato-Token`` surface as cron schedules (``POST /api/flows``), so anything
that could write a flow could run any registered tool unattended.

It is closed the same way the sixth instance was: EVERY step dispatch goes
through :meth:`cato.agent_loop.AgentLoop.guarded_action`, the single shared gate
entry point the interactive tool-call path also uses. A flow step therefore
gets, in this order: STOP file, risk classification (SafetyGuard), token
authorization, ActionGuard, approval policy + ticket, a durable ledger INTENT,
dispatch, then CONFIRMED / FAILED / DENIED.

Two invariants hold here and must keep holding:

  1. A :class:`FlowEngine` with no ``agent_loop`` REFUSES to dispatch. It does
     not fall back to the raw handler. An engine that cannot reach the gate
     chain does not get to run the action instead — that is the whole bypass.
  2. Gating the flow as a whole (``flow.run`` is tier ``dispatch``) is NOT a
     substitute for gating its steps. One approval must never authorize an
     unbounded, unledgered set of tool calls inside the flow.

``dry_run`` (read from the flow YAML or the trigger context) only ever ADDS
``draft_only=True`` to a ``send_email`` step. It is restricting-only: the
approval policy ignores ``dry_run``/``draft_only`` when deciding whether a
human is required (see ``_SIMULATION_ARG_KEYS`` in cato/core/approval_policy.py),
so it cannot be used to talk a gate out of firing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..budget import BudgetExceeded, BudgetManager
from ..platform import get_data_dir

logger = logging.getLogger(__name__)

# Default cents charged per flow step against flow budget_cap
_STEP_COST_CENTS: dict[str, int] = {
    "file.read": 1,
    "file.write": 2,
    "web.search": 3,
    "genesis": 25,
    "send_email": 5,
    "browser": 5,
    "flow.run": 10,
}
_DEFAULT_STEP_COST_CENTS = 5


class FlowGateUnavailable(Exception):
    """Raised when a flow step cannot reach the shared gate chain.

    FAIL CLOSED. A :class:`FlowEngine` built without an ``agent_loop`` cannot
    run SafetyGuard, the token checker, ActionGuard, the approval policy or the
    ledger, so it refuses to dispatch. Falling back to the raw tool handler
    here is precisely the bypass this module exists to have closed.
    """

    def __init__(self, skill_name: str) -> None:
        self.skill_name = skill_name
        super().__init__(
            f"Flow step '{skill_name}' refused: the safety/approval/ledger gate "
            "chain is unavailable (FlowEngine has no agent_loop). An ungated "
            "flow step is exactly the bypass this path exists to prevent."
        )


class FlowStepDenied(Exception):
    """Raised when a gate refused a flow step (safety, auth, guard, approval)."""

    def __init__(self, skill_name: str, action: str, detail: str) -> None:
        self.skill_name = skill_name
        self.action = action
        self.detail = detail
        super().__init__(f"Flow step '{skill_name}' {action}: {detail}")


class FlowBudgetExceeded(Exception):
    """Raised when a clawflow exceeds its YAML budget_cap."""

    def __init__(self, flow_name: str, cap_cents: int, spent_cents: int) -> None:
        self.flow_name = flow_name
        self.cap_cents = cap_cents
        self.spent_cents = spent_cents
        super().__init__(
            f"Flow '{flow_name}' budget cap {cap_cents}¢ exceeded (at {spent_cents}¢)"
        )

_DATA_DIR = get_data_dir()
FLOWS_DIR = _DATA_DIR / "flows"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_name    TEXT    NOT NULL,
    current_step INTEGER NOT NULL DEFAULT 0,
    step_outputs TEXT    NOT NULL DEFAULT '[]',
    status       TEXT    NOT NULL DEFAULT 'IN_PROGRESS',
    started_at   REAL    NOT NULL,
    updated_at   REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flow_runs_name   ON flow_runs(flow_name);
CREATE INDEX IF NOT EXISTS idx_flow_runs_status ON flow_runs(status);
"""


def known_skills() -> set[str]:
    """Every skill name a flow step may legitimately name.

    Returns an EMPTY set when the tool registry has not been populated yet, so
    callers can tell "no such skill" apart from "cannot answer yet". Write-time
    validation is defence in depth only; the real control is the run-time gate
    in :meth:`FlowEngine._dispatch_step`, because flows can already exist on disk.
    """
    try:
        from ..agent_loop import _TOOL_ALIASES, _TOOL_REGISTRY
    except ImportError:  # pragma: no cover — defensive
        return set()
    if not _TOOL_REGISTRY:
        return set()
    return set(_TOOL_REGISTRY) | {
        alias for alias, target in _TOOL_ALIASES.items() if target in _TOOL_REGISTRY
    }


def validate_flow_definition(flow_def: Any) -> list[str]:
    """Return human-readable problems with a flow definition; empty means OK.

    Checks shape (mapping, ``steps`` is a list of mappings each naming a string
    ``skill``) and, when the tool registry is populated, that every step skill
    actually exists. ``POST /api/flows`` used to accept arbitrary skill names
    into stored YAML.
    """
    problems: list[str] = []
    if not isinstance(flow_def, dict):
        return [f"flow must be a YAML mapping, got {type(flow_def).__name__}"]

    steps = flow_def.get("steps")
    if steps is None:
        return ["flow has no 'steps' list"]
    if not isinstance(steps, list):
        return [f"'steps' must be a list, got {type(steps).__name__}"]

    allowed = known_skills()
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            problems.append(f"step {idx}: must be a mapping, got {type(step).__name__}")
            continue
        skill = step.get("skill")
        if not isinstance(skill, str) or not skill.strip():
            problems.append(f"step {idx}: missing or non-string 'skill'")
            continue
        args = step.get("args")
        if args is not None and not isinstance(args, dict):
            problems.append(f"step {idx}: 'args' must be a mapping, got {type(args).__name__}")
        if allowed and skill.strip() not in allowed:
            problems.append(f"step {idx}: unknown skill {skill.strip()!r}")
    if not allowed:
        logger.warning(
            "Flow skill validation skipped: the tool registry is empty, so "
            "unknown skills cannot be detected at write time. The run-time gate "
            "still applies to every step."
        )
    return problems


@dataclass
class FlowResult:
    """Result of a flow execution."""
    flow_name: str
    status: str               # COMPLETED | FAILED | IN_PROGRESS
    step_outputs: list[Any] = field(default_factory=list)
    error: Optional[str] = None
    run_id: Optional[int] = None


class FlowEngine:
    """
    Engine for loading and executing Clawflows.

    Usage::

        engine = FlowEngine()
        flows = engine.list_flows()
        result = await engine.run_flow("morning-brief")
    """

    def __init__(
        self,
        flows_dir: Optional[Path] = None,
        budget: Optional[BudgetManager] = None,
        agent_loop: Optional[Any] = None,
    ) -> None:
        self._flows_dir = (flows_dir or FLOWS_DIR).expanduser().resolve()
        self._flows_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = _DATA_DIR / "flow_runs.db"
        self._conn = self._open_db()
        self._budget = budget
        # The owner of the gate chain. Without it this engine refuses to
        # dispatch — see FlowGateUnavailable and the module docstring.
        self._agent_loop = agent_loop

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------

    def _open_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    # ------------------------------------------------------------------
    # YAML loading
    # ------------------------------------------------------------------

    def load_flow(self, name: str) -> dict:
        """
        Load a flow definition from FLOWS_DIR/<name>.yaml.

        Returns the parsed dict.
        Raises FileNotFoundError if the file does not exist.
        Raises ValueError if YAML is malformed.
        """
        path = self._flows_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Flow file not found: {path}")

        try:
            import yaml  # type: ignore[import]
            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except ImportError:
            # Fallback: minimal YAML parser for simple key:value files
            data = self._parse_yaml_minimal(path)
        except Exception as exc:
            raise ValueError(f"Could not parse flow YAML {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"Flow YAML must be a mapping, got {type(data).__name__}")

        return data

    def _parse_yaml_minimal(self, path: Path) -> dict:
        """Very minimal YAML parser — used as fallback when PyYAML is unavailable."""
        import yaml
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def list_flows(self) -> list[dict]:
        """
        Scan FLOWS_DIR for .yaml files and return summary dicts.

        Each dict: {name, trigger_type, step_count, budget_cap}
        """
        results: list[dict] = []
        for yaml_file in sorted(self._flows_dir.glob("*.yaml")):
            try:
                data = self.load_flow(yaml_file.stem)
            except Exception as exc:
                logger.warning("Could not load flow %s: %s", yaml_file.name, exc)
                continue
            trigger = data.get("trigger", {})
            trigger_type = trigger.get("type", "manual") if isinstance(trigger, dict) else "manual"
            results.append({
                "name": yaml_file.stem,
                "trigger_type": trigger_type,
                "step_count": len(data.get("steps", [])),
                "budget_cap": data.get("budget_cap"),
            })
        return results

    # ------------------------------------------------------------------
    # Flow execution
    # ------------------------------------------------------------------

    async def run_flow(
        self,
        name: str,
        trigger_context: dict | None = None,
        resume_run_id: Optional[int] = None,
        budget_cap_cents: Optional[int] = None,
    ) -> FlowResult:
        """
        Execute flow *name* step by step.

        - State is persisted to SQLite after each step.
        - On error, checks step's 'on_error' field (stop | continue | retry).
        - Returns FlowResult.
        """
        trigger_context = trigger_context or {}

        try:
            flow_def = self.load_flow(name)
        except FileNotFoundError as exc:
            return FlowResult(flow_name=name, status="FAILED", error=str(exc))
        except ValueError as exc:
            return FlowResult(flow_name=name, status="FAILED", error=str(exc))

        flow_def["name"] = name
        try:
            from ..core.night_shift_policy import load_night_shift_policy
            blocked, reason = load_night_shift_policy().blocks_flow_def(flow_def)
            if blocked:
                return FlowResult(flow_name=name, status="FAILED", error=reason)
        except Exception as exc:
            logger.debug("night-shift policy check skipped: %s", exc)

        steps = flow_def.get("steps", [])
        cap_raw = budget_cap_cents if budget_cap_cents is not None else flow_def.get("budget_cap")
        try:
            flow_cap_cents = int(cap_raw) if cap_raw is not None else 0
        except (TypeError, ValueError):
            flow_cap_cents = 0
        flow_spent_cents = 0
        dry_run = bool(flow_def.get("dry_run") or (trigger_context or {}).get("dry_run"))

        now = time.time()

        # Create or resume a run record
        if resume_run_id is not None:
            row = self._conn.execute(
                "SELECT * FROM flow_runs WHERE id = ?", (resume_run_id,)
            ).fetchone()
            if row:
                run_id = resume_run_id
                start_step = row["current_step"]
                step_outputs: list[Any] = json.loads(row["step_outputs"])
            else:
                run_id = resume_run_id
                start_step = 0
                step_outputs = []
        else:
            cur = self._conn.execute(
                "INSERT INTO flow_runs (flow_name, current_step, step_outputs, status, started_at, updated_at)"
                " VALUES (?, 0, '[]', 'IN_PROGRESS', ?, ?)",
                (name, now, now),
            )
            self._conn.commit()
            run_id = cur.lastrowid
            start_step = 0
            step_outputs = []

        error_msg: Optional[str] = None

        for step_idx in range(start_step, len(steps)):
            step = steps[step_idx]
            skill_name = step.get("skill", "")
            args = dict(step.get("args") or {})
            on_error = step.get("on_error", "stop")

            if dry_run and skill_name == "send_email":
                args["draft_only"] = True

            step_cost = _STEP_COST_CENTS.get(skill_name, _DEFAULT_STEP_COST_CENTS)
            if flow_cap_cents > 0 and flow_spent_cents + step_cost > flow_cap_cents:
                error_msg = (
                    f"Flow budget cap {flow_cap_cents}¢ would be exceeded at step {step_idx} "
                    f"({skill_name}, +{step_cost}¢)."
                )
                self._persist_run(run_id, step_idx, step_outputs, "FAILED")
                return FlowResult(
                    flow_name=name,
                    status="FAILED",
                    step_outputs=step_outputs,
                    error=error_msg,
                    run_id=run_id,
                )

            if self._budget is not None and step_cost > 0:
                try:
                    await self._budget.check_and_deduct_usd(
                        step_cost / 100.0,
                        label=f"flow:{name}:{skill_name}",
                    )
                except BudgetExceeded as exc:
                    error_msg = f"Global budget blocked flow step: {exc}"
                    self._persist_run(run_id, step_idx, step_outputs, "FAILED")
                    return FlowResult(
                        flow_name=name,
                        status="FAILED",
                        step_outputs=step_outputs,
                        error=error_msg,
                        run_id=run_id,
                    )

            try:
                output = await self._dispatch_step(skill_name, args, trigger_context)
                flow_spent_cents += step_cost
                step_outputs.append(output)
            except Exception as exc:
                logger.error("Flow %s step %d (%s) failed: %s", name, step_idx, skill_name, exc)
                step_outputs.append(f"ERROR: {exc}")

                if on_error == "stop":
                    error_msg = f"Step {step_idx} ({skill_name}) failed: {exc}"
                    # Persist failure state
                    self._persist_run(run_id, step_idx, step_outputs, "FAILED")
                    return FlowResult(
                        flow_name=name,
                        status="FAILED",
                        step_outputs=step_outputs,
                        error=error_msg,
                        run_id=run_id,
                    )
                elif on_error == "retry":
                    # Simple single retry
                    try:
                        output = await self._dispatch_step(skill_name, args, trigger_context)
                        step_outputs[-1] = output  # Replace error with success
                    except Exception as retry_exc:
                        logger.warning("Retry failed for step %d: %s", step_idx, retry_exc)
                        step_outputs[-1] = f"RETRY_FAILED: {retry_exc}"
                        if on_error == "stop":
                            error_msg = f"Step {step_idx} retry failed: {retry_exc}"
                            self._persist_run(run_id, step_idx, step_outputs, "FAILED")
                            return FlowResult(
                                flow_name=name,
                                status="FAILED",
                                step_outputs=step_outputs,
                                error=error_msg,
                                run_id=run_id,
                            )
                # on_error == "continue": fall through to next step

            # Persist after each step
            self._persist_run(run_id, step_idx + 1, step_outputs, "IN_PROGRESS")

        # All steps completed
        self._persist_run(run_id, len(steps), step_outputs, "COMPLETED")

        return FlowResult(
            flow_name=name,
            status="COMPLETED",
            step_outputs=step_outputs,
            run_id=run_id,
        )

    async def _dispatch_step(self, skill_name: str, args: dict, context: dict) -> Any:
        """Dispatch a single step through the shared pre-action gate chain.

        This never touches ``_TOOL_REGISTRY`` directly. ``guarded_action`` runs
        STOP → SafetyGuard → TokenChecker → ActionGuard → approval → ledger
        INTENT → dispatch → CONFIRMED/FAILED, and then dispatches the registered
        handler itself. A flow step is therefore gated identically to the same
        call made through the model tool-call path.

        Raises :class:`FlowGateUnavailable` when there is no gate chain to run
        (fail closed), and :class:`FlowStepDenied` when a gate refused. Both are
        caught by :meth:`run_flow`'s per-step handler, so ``on_error`` still
        applies — but a refused step is never recorded as a successful output.
        """
        loop = self._agent_loop
        if loop is None:
            logger.error(
                "Flow step %r refused: FlowEngine has no agent_loop, so the "
                "safety/approval/ledger gate chain cannot run.", skill_name,
            )
            raise FlowGateUnavailable(skill_name)

        # The gate must see exactly what the handler will receive.
        merged_args = {**context, **args}
        session_id = str(context.get("session_id") or "flow")

        payload = await loop.guarded_action(skill_name, merged_args, session_id)

        from ..core.scheduled_dispatch import gate_refusal

        refusal = gate_refusal(payload)
        if refusal is not None:
            raise FlowStepDenied(
                skill_name, str(refusal.get("action", "denied")),
                str(refusal.get("detail", "")),
            )
        return payload

    def _persist_run(
        self,
        run_id: int,
        current_step: int,
        step_outputs: list[Any],
        status: str,
    ) -> None:
        """Persist flow run state to SQLite."""
        self._conn.execute(
            "UPDATE flow_runs SET current_step = ?, step_outputs = ?, status = ?, updated_at = ?"
            " WHERE id = ?",
            (current_step, json.dumps(step_outputs, default=str), status, time.time(), run_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Resume pending flows
    # ------------------------------------------------------------------

    def resume_pending_flows(self) -> list[int]:
        """
        Query IN_PROGRESS flows and schedule them for resumption.

        Returns list of run IDs that were resumed.
        """
        rows = self._conn.execute(
            "SELECT id, flow_name, current_step FROM flow_runs WHERE status = 'IN_PROGRESS'"
        ).fetchall()

        run_ids: list[int] = []
        for row in rows:
            logger.info(
                "Resuming flow %s (run_id=%d) from step %d",
                row["flow_name"], row["id"], row["current_step"],
            )
            run_ids.append(row["id"])
            # Schedule as background task if event loop is running
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self.run_flow(row["flow_name"], resume_run_id=row["id"]),
                    name=f"flow-resume-{row['id']}",
                )
            except RuntimeError:
                pass  # No running event loop — caller must handle

        return run_ids

    def get_in_progress_flows(self) -> list[dict]:
        """Return all IN_PROGRESS flow runs."""
        rows = self._conn.execute(
            "SELECT id, flow_name, current_step, status, started_at, updated_at"
            " FROM flow_runs WHERE status = 'IN_PROGRESS'"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # YAML active toggle
    # ------------------------------------------------------------------

    def set_active(self, name: str, active: bool) -> bool:
        """
        Toggle the 'active' field in a flow's YAML file.

        Returns True if the flow file was found and updated, False otherwise.
        """
        path = self._flows_dir / f"{name}.yaml"
        if not path.exists():
            return False

        try:
            content = path.read_text(encoding="utf-8")
            # Simple text replacement for 'active: true/false'
            import re as _re
            if _re.search(r"^active\s*:", content, _re.MULTILINE):
                content = _re.sub(
                    r"^(active\s*:)\s*\S+",
                    f"\\1 {'true' if active else 'false'}",
                    content,
                    flags=_re.MULTILINE,
                )
            else:
                content = content.rstrip() + f"\nactive: {'true' if active else 'false'}\n"
            path.write_text(content, encoding="utf-8")
            return True
        except OSError as exc:
            logger.warning("Could not update %s: %s", path, exc)
            return False

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()
