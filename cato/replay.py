"""
cato/replay.py — Session replay engine for CATO.

Re-runs a previously recorded session using mocked tool outputs from
the audit log. By default runs in dry-run (no API calls, no browser).
Live replay re-executes with real tools but requires budget confirmation.

CLI: `cato replay --session <id>`
     `cato replay --session <id> --live`

Produces a match/mismatch diff report comparing replayed outputs to originals.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .audit import AuditLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ReplayStep:
    index: int
    tool_name: str
    inputs: dict
    original_output: str
    replayed_output: str
    matched: bool
    elapsed_ms: float = 0.0


@dataclass
class ReplayReport:
    session_id: str
    mode: str              # "dry_run" | "live"
    steps: list[ReplayStep] = field(default_factory=list)
    total_steps: int = 0
    matched: int = 0
    mismatched: int = 0
    skipped: int = 0
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Mock tool dispatcher (dry-run mode)
# ---------------------------------------------------------------------------

class MockToolDispatcher:
    """
    Returns recorded outputs from the audit log instead of calling real tools.

    Stores a map of {tool_name -> [outputs]} and pops the next recorded
    output each time the same tool is called.
    """

    def __init__(self) -> None:
        self._queue: dict[str, list[str]] = {}

    def load_from_audit(self, audit_log: "AuditLog", session_id: str) -> None:
        """Populate the mock queue from audit log rows for *session_id*."""
        audit_log._ensure_connected()
        assert audit_log._conn is not None

        rows = audit_log._conn.execute(
            """
            SELECT tool_name, outputs_json
            FROM audit_log
            WHERE session_id = ? AND action_type = 'tool_call'
            ORDER BY id
            """,
            (session_id,),
        ).fetchall()

        for row in rows:
            tool = row["tool_name"]
            output = row["outputs_json"]
            if tool not in self._queue:
                self._queue[tool] = []
            self._queue[tool].append(output)

    def dispatch(self, tool_name: str, inputs: dict) -> str:  # noqa: ARG002
        """Return next recorded output for *tool_name*, or a placeholder."""
        queue = self._queue.get(tool_name, [])
        if queue:
            return queue.pop(0)
        return json.dumps({"mocked": True, "tool": tool_name, "note": "no recorded output"})


# ---------------------------------------------------------------------------
# ReplayEngine
# ---------------------------------------------------------------------------

class ReplayEngine:
    """
    Replays a session from the audit log.

    Dry-run mode (default): uses MockToolDispatcher — no API calls, no browser.
    Live mode: dispatches to real tools from the agent loop's registry.

    Usage::

        engine = ReplayEngine(audit_log=log)
        report = engine.replay("sess-001", live=False)
        print(engine.format_report(report))
    """

    def __init__(self, audit_log: "AuditLog", agent_loop: Any = None) -> None:
        self._audit_log = audit_log
        # Owner of the gate chain. Live replay REFUSES to dispatch without it.
        self._agent_loop = agent_loop
        self._session_id = ""

    def replay(self, session_id: str, live: bool = False) -> ReplayReport:
        """
        Replay *session_id*.

        Parameters:
            session_id — ID of the session to replay
            live       — If True, use real tools (requires budget confirmation)

        Returns a ReplayReport with per-step match/mismatch details.
        """
        mode = "live" if live else "dry_run"
        self._session_id = session_id
        report = ReplayReport(session_id=session_id, mode=mode)
        start_time = time.time()

        self._audit_log._ensure_connected()
        assert self._audit_log._conn is not None

        # Load all tool_call rows for this session
        rows = self._audit_log._conn.execute(
            """
            SELECT id, tool_name, inputs_json, outputs_json, action_type
            FROM audit_log
            WHERE session_id = ? AND action_type = 'tool_call'
            ORDER BY id
            """,
            (session_id,),
        ).fetchall()

        if not rows:
            logger.info("ReplayEngine: no tool_call rows found for session %s", session_id)
            report.elapsed_seconds = time.time() - start_time
            return report

        report.total_steps = len(rows)

        mock_dispatcher = MockToolDispatcher()
        if not live:
            mock_dispatcher.load_from_audit(self._audit_log, session_id)

        for i, row in enumerate(rows):
            tool_name = row["tool_name"]
            original_output = row["outputs_json"]

            try:
                inputs = json.loads(row["inputs_json"] or "{}")
            except json.JSONDecodeError:
                inputs = {}

            step_start = time.time()

            try:
                if live:
                    replayed_output = self._dispatch_live(tool_name, inputs)
                else:
                    replayed_output = mock_dispatcher.dispatch(tool_name, inputs)
            except Exception as exc:
                replayed_output = json.dumps({"error": str(exc)})
                logger.warning("ReplayEngine step %d failed: %s", i + 1, exc)

            elapsed_ms = (time.time() - step_start) * 1000

            # Compare outputs (normalize whitespace for comparison)
            matched = self._outputs_match(original_output, replayed_output)

            step = ReplayStep(
                index=i + 1,
                tool_name=tool_name,
                inputs=inputs,
                original_output=original_output,
                replayed_output=replayed_output,
                matched=matched,
                elapsed_ms=elapsed_ms,
            )
            report.steps.append(step)

            if matched:
                report.matched += 1
            else:
                report.mismatched += 1

        report.elapsed_seconds = time.time() - start_time
        return report

    @staticmethod
    def _outputs_match(original: str, replayed: str) -> bool:
        """
        Compare two outputs for equivalence.

        For dry-run replays, mocked outputs will never match perfectly.
        We consider a match if the JSON structure keys are the same,
        or if the raw strings are identical.
        """
        if original == replayed:
            return True
        # Try structural comparison for JSON
        try:
            orig_data = json.loads(original)
            repl_data = json.loads(replayed)
            if isinstance(orig_data, dict) and isinstance(repl_data, dict):
                return set(orig_data.keys()) == set(repl_data.keys())
        except (json.JSONDecodeError, TypeError):
            pass
        return False

    def _dispatch_live(self, tool_name: str, inputs: dict) -> str:
        """Re-execute a recorded tool call behind the shared gate chain.

        SECURITY: this was the EIGHTH instance of the defect class t14-t20
        closed. It used to pull the handler straight out of
        ``cato.agent_loop._TOOL_REGISTRY`` and await it, so ``cato replay
        --session <id> --live`` re-ran every recorded shell command, file
        write, e-mail and Genesis dispatch of a session with no STOP check, no
        risk classification, no authorization, no ActionGuard, no approval and
        no ledger entry. One "y" at the CLI confirm prompt replayed the lot.

        ``tool_name``/``inputs`` come out of the audit log — they are REPLAYED
        INPUT, never authorization. Live replay now runs the same
        ``AgentLoop.guarded_action`` chain a fresh tool call runs, and FAILS
        CLOSED when no gate chain was supplied.
        """
        loop = self._agent_loop
        if loop is None:
            logger.error(
                "Live replay of %r refused: no gate chain available.", tool_name,
            )
            return json.dumps({
                "error": (
                    "[REPLAY] Live replay refused: the safety/approval/ledger "
                    "gate chain is unavailable, and re-executing recorded tool "
                    "calls ungated is exactly the bypass this path must not be."
                ),
                "gate_unavailable": True,
            })
        try:
            import asyncio

            return str(asyncio.run(
                loop.guarded_action(
                    tool_name, inputs, f"replay:{self._session_id or 'unknown'}",
                )
            ))
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    def format_report(self, report: ReplayReport) -> str:
        """Format a ReplayReport as a human-readable text diff report."""
        lines: list[str] = [
            "=" * 64,
            f"SESSION REPLAY REPORT",
            f"Session:  {report.session_id}",
            f"Mode:     {report.mode}",
            f"Duration: {report.elapsed_seconds:.2f}s",
            "=" * 64,
        ]

        for step in report.steps:
            status = "MATCH" if step.matched else "DIFF"
            lines.append(
                f"  [{status}] #{step.index:>3} {step.tool_name:<24} ({step.elapsed_ms:.0f}ms)"
            )
            if not step.matched:
                # Show truncated diff
                orig_preview = step.original_output[:100].replace("\n", " ")
                repl_preview = step.replayed_output[:100].replace("\n", " ")
                lines.append(f"           original: {orig_preview}")
                lines.append(f"           replayed: {repl_preview}")

        lines.append("-" * 64)
        pct = (report.matched / report.total_steps * 100) if report.total_steps else 0
        lines.append(
            f"  Steps: {report.total_steps}   "
            f"Matched: {report.matched}   "
            f"Mismatched: {report.mismatched}   "
            f"Skipped: {report.skipped}   "
            f"({pct:.0f}% match)"
        )
        lines.append("=" * 64)
        return "\n".join(lines)


# Backward-compat alias — import as SessionReplayer or ReplayEngine
SessionReplayer = ReplayEngine
