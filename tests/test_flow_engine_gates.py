"""
tests/test_flow_engine_gates.py — t20: a Clawflow STEP is a gated entry point.

WHY THIS FILE EXISTS
--------------------
Six instances of one defect class had already been found and fixed here. The
seventh lived in ``cato/orchestrator/clawflows.py``:

    from ..agent_loop import _TOOL_REGISTRY
    handler = _TOOL_REGISTRY.get(skill_name)
    if handler is not None:
        return await handler({**context, **args})   # raw handler, no gates

Grepped over that whole file, gate contact was: ``_guarded_dispatch`` 0,
``guarded_action`` 0, ``check_and_confirm`` 0, ``approval_policy`` 0,
``recorded_action`` 0, ``SafetyGuard`` 0, ``TokenChecker`` 0. A flow step naming
``shell``, ``file``, ``send_email`` or ``genesis`` therefore ran with no STOP
check, no risk classification, no delegation-token authorization, no
ActionGuard, no approval ticket and no ledger entry — and flow YAML is writable
over the same ``X-Cato-Token`` surface (``POST /api/flows``) that the cron API
uses.

It was strictly worse than the sixth instance and it DEGRADED that fix: the
cron path gates a flow as tier ``dispatch``, but before t20 a single approval
then authorized an unbounded, unledgered set of tool calls inside it.

Every test below drives a REAL flow through a REAL gate chain
(tests/scheduler_gate_harness.py) and asserts the SAME verdict the model
tool-call path produces for the same call. Denial is denial: the outcomes
asserted here are the ones the gate chain actually produces, not the ones that
would read most impressively.

NO NETWORK, NO DAEMON, NO REAL SUBPROCESS, NO REAL EMAIL.
"""
from __future__ import annotations

import json

import pytest

import cato.agent_loop as agent_loop_mod
from cato.orchestrator.clawflows import FlowEngine
from tests.scheduler_gate_harness import (
    build_scheduler_gate_env,
    ledger_kinds,
    ledger_rows,
)

#: Unmistakable if it ever ran. It never does.
CANARY_CMD = "python -c \"print('T20-CANARY-SHOULD-NEVER-RUN')\""


def _engine(env, tmp_path, yaml_text: str, name: str, *, gated: bool = True) -> FlowEngine:
    """Write a flow YAML and return an engine pointed at an isolated DB.

    ``gated=False`` builds the engine the way a caller that forgot to thread the
    AgentLoop would — which must now refuse to dispatch, not fall back.
    """
    flows = tmp_path / "flows"
    flows.mkdir(exist_ok=True)
    (flows / f"{name}.yaml").write_text(yaml_text, encoding="utf-8")
    loop = env.loop if gated else None
    try:
        engine = FlowEngine(flows_dir=flows, agent_loop=loop)
    except TypeError:
        # The pre-fix FlowEngine has no `agent_loop` parameter. Build it the old
        # way and attach the loop as a plain attribute the pre-fix
        # `_dispatch_step` ignores, so scripts/t20_before_after_evidence.py's
        # BEFORE run exercises the LIVE bypass (canary handlers get called and
        # the assertions fire) instead of dying at construction. A collection
        # error would only prove "the fix is absent"; this proves the hole.
        engine = FlowEngine(flows_dir=flows)
        engine._agent_loop = loop
    engine._db_path = tmp_path / "flow_runs.db"
    engine._conn = engine._open_db()
    return engine


# =============================================================================
# Attack 1 — a flow step that asks for a shell
# =============================================================================


class TestFlowShellStepIsGated:
    @pytest.mark.asyncio
    async def test_shell_step_never_reaches_the_shell_tool(self, tmp_path, monkeypatch):
        """A `skill: shell` step must not execute a command.

        Before t20 this awaited the registered shell handler directly. It now
        takes the route a model's shell tool call takes and stops where that
        path stops: the resolved handler is ``shell.exec``, which is not in
        ``_DEFAULT_ALLOWED_TOOLS``, so with no delegation token the
        authorization gate refuses it.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        ran: list[str] = []
        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: ran.append(kw.get("command", "")),
        )

        engine = _engine(env, tmp_path, f"""\
name: pwn
steps:
  - skill: shell
    args:
      command: {json.dumps(CANARY_CMD)}
""", "pwn")
        result = await engine.run_flow("pwn")
        engine.close()

        assert ran == [], "the flow step must not have executed a shell command"
        assert result.status == "FAILED"
        assert "auth" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_shell_step_refusal_is_recorded_as_denied(self, tmp_path, monkeypatch):
        """The refusal lands in the hash-chained ledger, like a refused tool call."""
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: pytest.fail("shell must not run"),
        )

        engine = _engine(env, tmp_path, f"""\
name: pwn
steps:
  - skill: shell
    args:
      command: {json.dumps(CANARY_CMD)}
""", "pwn")
        await engine.run_flow("pwn")
        engine.close()

        denied = ledger_rows(env.ledger_path, "DENIED")
        assert any("shell" in r.tool_name for r in denied), (
            "a refused flow step must be in the ledger; before t20 the ledger "
            "saw nothing at all"
        )
        assert "CONFIRMED" not in ledger_kinds(env.ledger_path)

    @pytest.mark.asyncio
    async def test_shell_step_verdict_matches_the_tool_call_path(self, tmp_path, monkeypatch):
        """Same (skill, args) → same gate verdict through a flow as through a tool call.

        This is the definition of done: a flow step is gated *identically* to
        the same call made through the model tool-call path.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: pytest.fail("shell must not run"),
        )

        direct = json.loads(
            await env.loop.guarded_action("shell", {"command": CANARY_CMD}, "direct")
        )

        engine = _engine(env, tmp_path, f"""\
name: pwn
steps:
  - skill: shell
    args:
      command: {json.dumps(CANARY_CMD)}
""", "pwn")
        result = await engine.run_flow("pwn")
        engine.close()

        assert direct.get("auth_denied") is True
        assert result.status == "FAILED"
        assert "auth_blocked" in (result.error or "")


# =============================================================================
# Attack 2 — a flow step that writes a file / sends mail / calls Genesis
# =============================================================================


class TestFlowOutboundStepsAreGated:
    @pytest.mark.asyncio
    async def test_file_write_step_is_held_for_approval(self, tmp_path, monkeypatch):
        """A `file` write step is held for a human, and the file is not written."""
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        target = tmp_path / "written-by-an-ungated-flow.txt"

        engine = _engine(env, tmp_path, f"""\
name: writer
steps:
  - skill: file
    args:
      operation: write
      path: {str(target)!r}
      content: "owned"
""", "writer")
        result = await engine.run_flow("writer")
        engine.close()

        assert not target.exists(), "an unapproved flow step wrote to disk"
        assert result.status == "FAILED"
        assert "approval_required" in (result.error or "")

        pending = env.approval_store.list_pending()
        assert any(a.tool_name == "file" for a in pending), (
            "the write must be parked as a pending approval, not silently dropped"
        )

    @pytest.mark.asyncio
    async def test_send_email_step_is_denied(self, tmp_path, monkeypatch):
        """A `send_email` step is refused by the gate chain before any send."""
        env = build_scheduler_gate_env(tmp_path, monkeypatch)

        sent: list[dict] = []

        async def _spy(args: dict) -> str:
            sent.append(dict(args))
            return "sent"

        monkeypatch.setitem(agent_loop_mod._TOOL_REGISTRY, "send_email", _spy)

        engine = _engine(env, tmp_path, """\
name: mailer
steps:
  - skill: send_email
    args:
      to: victim@example.invalid
      subject: t20
      body: t20
""", "mailer")
        result = await engine.run_flow("mailer")
        engine.close()

        assert sent == [], "the send_email handler must never have been reached"
        assert result.status == "FAILED"
        denied = ledger_rows(env.ledger_path, "DENIED")
        assert any(r.tool_name == "send_email" for r in denied)

    @pytest.mark.asyncio
    async def test_genesis_step_is_held_for_approval(self, tmp_path, monkeypatch):
        """A `genesis` step is held for a ticket instead of dispatching an agent."""
        env = build_scheduler_gate_env(tmp_path, monkeypatch)

        called: list[dict] = []

        async def _spy(args: dict) -> str:
            called.append(dict(args))
            return "dispatched"

        monkeypatch.setitem(agent_loop_mod._TOOL_REGISTRY, "genesis", _spy)

        engine = _engine(env, tmp_path, """\
name: genesis-flow
steps:
  - skill: genesis
    args:
      action: dispatch_task
""", "genesis-flow")
        result = await engine.run_flow("genesis-flow")
        engine.close()

        assert called == [], "genesis must not run unapproved from a flow step"
        assert result.status == "FAILED"
        assert "approval_required" in (result.error or "")


# =============================================================================
# Fail closed — an engine with no gate chain refuses to dispatch
# =============================================================================


class TestFlowEngineWithoutAGateChainRefuses:
    @pytest.mark.asyncio
    async def test_no_agent_loop_refuses_instead_of_calling_the_raw_handler(
        self, tmp_path, monkeypatch,
    ):
        """The whole bypass in one test: no gate chain must mean no dispatch.

        A fallback to ``_TOOL_REGISTRY[skill]`` here is exactly what t20 closed.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)

        reached: list[dict] = []

        async def _spy(args: dict) -> str:
            reached.append(dict(args))
            return "ran"

        monkeypatch.setitem(agent_loop_mod._TOOL_REGISTRY, "memory.search", _spy)

        engine = _engine(env, tmp_path, """\
name: ungated
steps:
  - skill: memory.search
    args:
      query: anything
""", "ungated", gated=False)
        result = await engine.run_flow("ungated")
        engine.close()

        assert reached == [], (
            "a FlowEngine with no AgentLoop fell back to the raw handler — this "
            "is the t20 bypass"
        )
        assert result.status == "FAILED"
        assert "gate chain is unavailable" in (result.error or "")
        assert ledger_kinds(env.ledger_path) == []

    @pytest.mark.asyncio
    async def test_dispatch_step_raises_rather_than_returning_a_placeholder(
        self, tmp_path, monkeypatch,
    ):
        """Called directly, ``_dispatch_step`` fails closed rather than faking success."""
        from cato.orchestrator.clawflows import FlowGateUnavailable

        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        engine = _engine(env, tmp_path, "name: x\nsteps: []\n", "x", gated=False)
        try:
            with pytest.raises(FlowGateUnavailable):
                await engine._dispatch_step("shell", {"command": CANARY_CMD}, {})
        finally:
            engine.close()


# =============================================================================
# The ledger sees flow steps
# =============================================================================


class TestFlowStepsAreLedgered:
    @pytest.mark.asyncio
    async def test_allowed_step_produces_intent_and_confirmed(self, tmp_path, monkeypatch):
        """A permitted step is durably recorded before and after it runs.

        Before t20 a flow could run any number of tools and leave the ledger
        completely empty.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)

        engine = _engine(env, tmp_path, """\
name: readonly
steps:
  - skill: memory.search
    args:
      query: hello
""", "readonly")
        result = await engine.run_flow("readonly")
        engine.close()

        assert result.status == "COMPLETED"
        kinds = ledger_kinds(env.ledger_path)
        assert "INTENT" in kinds
        assert "CONFIRMED" in kinds
        intents = ledger_rows(env.ledger_path, "INTENT")
        assert any(r.tool_name == "memory.search" for r in intents)

    @pytest.mark.asyncio
    async def test_every_step_is_gated_not_just_the_first(self, tmp_path, monkeypatch):
        """Per-STEP gating, not per-flow gating.

        The cron path already gates a flow as tier ``dispatch``. If that were
        the only gate, one approval would authorize everything inside. Here the
        first step is permitted and the second is still refused.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: pytest.fail("shell must not run"),
        )

        engine = _engine(env, tmp_path, f"""\
name: mixed
steps:
  - skill: memory.search
    args:
      query: hello
  - skill: shell
    args:
      command: {json.dumps(CANARY_CMD)}
""", "mixed")
        result = await engine.run_flow("mixed")
        engine.close()

        assert result.status == "FAILED"
        kinds = ledger_kinds(env.ledger_path)
        assert "CONFIRMED" in kinds, "the permitted first step should still run"
        assert "DENIED" in kinds, "the second step must be gated independently"


# =============================================================================
# Write-time validation (defence in depth — run-time gating is the real control)
# =============================================================================


class TestFlowDefinitionValidation:
    @staticmethod
    def _validate(flow_def):
        # Imported lazily: the pre-fix module has no validator at all, so the
        # BEFORE run reports a real absence rather than a collection error.
        from cato.orchestrator.clawflows import validate_flow_definition

        return validate_flow_definition(flow_def)

    def test_unknown_skill_is_rejected(self, monkeypatch):
        monkeypatch.setitem(agent_loop_mod._TOOL_REGISTRY, "memory.search", lambda a: None)

        problems = self._validate({
            "steps": [{"skill": "totally.not.a.tool", "args": {}}],
        })

        assert problems
        assert "unknown skill" in problems[0]

    def test_known_skill_is_accepted(self, monkeypatch):
        monkeypatch.setitem(agent_loop_mod._TOOL_REGISTRY, "memory.search", lambda a: None)

        assert self._validate({
            "steps": [{"skill": "memory.search", "args": {"query": "hi"}}],
        }) == []

    def test_malformed_shapes_are_rejected(self, monkeypatch):
        monkeypatch.setitem(agent_loop_mod._TOOL_REGISTRY, "memory.search", lambda a: None)

        assert self._validate("not a mapping")
        assert self._validate({"trigger": {"type": "manual"}})
        assert self._validate({"steps": "nope"})
        assert self._validate({"steps": [{"args": {}}]})
        assert self._validate({
            "steps": [{"skill": "memory.search", "args": "nope"}],
        })
