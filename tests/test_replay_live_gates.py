"""
tests/test_replay_live_gates.py — t20 sweep: the EIGHTH instance of the defect class.

``ReplayEngine._dispatch_live`` (cato/replay.py) was the same shape as the six
before it and the Clawflows step bypass that preceded this file:

    from .agent_loop import _TOOL_REGISTRY
    handler = _TOOL_REGISTRY.get(tool_name)
    result = asyncio.get_event_loop().run_until_complete(handler(inputs))

``cato replay --session <id> --live`` therefore re-executed every recorded
shell command, file write, e-mail and Genesis dispatch of a session with no
STOP check, no risk classification, no delegation-token authorization, no
ActionGuard, no approval ticket and no ledger entry. One "y" at the confirm
prompt replayed the lot. The ``POST /api/sessions/{id}/replay`` route hardcodes
``live=False``, so the X-Cato-Token surface never reached it — which is why it
survived: the well-tested path was the dry-run one.

Recorded ``tool_name``/``inputs`` are REPLAYED INPUT, never authorization.

No network, no daemon, no real subprocess.
"""
from __future__ import annotations

import json

import pytest

import cato.agent_loop as agent_loop_mod
from cato.audit import AuditLog
from cato.replay import ReplayEngine
from tests.scheduler_gate_harness import build_scheduler_gate_env, ledger_rows

CANARY_CMD = "python -c \"print('T20-REPLAY-CANARY-SHOULD-NEVER-RUN')\""


def _audit_with_shell_call(tmp_path, session_id: str = "replay-sess") -> AuditLog:
    """An audit log holding one recorded shell tool_call, ready to be replayed."""
    log = AuditLog(db_path=tmp_path / "audit_replay.db")
    log.connect()
    log.log(session_id, "tool_call", "shell", {"command": CANARY_CMD}, {"stdout": "hi"})
    return log


class TestLiveReplayIsGated:
    def test_live_replay_without_a_gate_chain_refuses(self, tmp_path, monkeypatch):
        """Fail closed: no AgentLoop must mean no re-execution, not a raw handler call."""
        reached: list[dict] = []

        async def _spy(args: dict) -> str:
            reached.append(dict(args))
            return "ran"

        monkeypatch.setitem(agent_loop_mod._TOOL_REGISTRY, "shell", _spy)

        log = _audit_with_shell_call(tmp_path)
        try:
            report = ReplayEngine(audit_log=log).replay("replay-sess", live=True)
        finally:
            log.close()

        assert reached == [], (
            "live replay reached the raw tool handler with no gate chain — this "
            "is the eighth instance of the bypass"
        )
        assert report.total_steps == 1
        payload = json.loads(report.steps[0].replayed_output)
        assert payload["gate_unavailable"] is True

    def test_live_replay_routes_through_the_gate_chain(self, tmp_path, monkeypatch):
        """With a gate chain, a replayed shell call is refused and ledgered."""
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: pytest.fail("replay must not execute a shell command"),
        )

        log = _audit_with_shell_call(tmp_path)
        try:
            report = ReplayEngine(audit_log=log, agent_loop=env.loop).replay(
                "replay-sess", live=True,
            )
        finally:
            log.close()

        assert report.total_steps == 1
        payload = json.loads(report.steps[0].replayed_output)
        assert payload.get("auth_denied") is True, (
            f"expected the authorization gate to refuse the replayed call, got {payload}"
        )

        denied = ledger_rows(env.ledger_path, "DENIED")
        assert any("shell" in r.tool_name for r in denied), (
            "a refused replay step must be in the hash-chained ledger; before "
            "this fix the ledger saw nothing at all"
        )

    def test_dry_run_replay_still_uses_recorded_outputs(self, tmp_path, monkeypatch):
        """The fix must not brick the default mode: dry-run never dispatches."""
        async def _spy(args: dict) -> str:  # pragma: no cover — must not run
            pytest.fail("dry-run replay must not dispatch anything")

        monkeypatch.setitem(agent_loop_mod._TOOL_REGISTRY, "shell", _spy)

        log = _audit_with_shell_call(tmp_path)
        try:
            report = ReplayEngine(audit_log=log).replay("replay-sess", live=False)
        finally:
            log.close()

        assert report.total_steps == 1
        assert report.matched == 1
