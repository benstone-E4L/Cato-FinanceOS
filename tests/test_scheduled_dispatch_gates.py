"""
tests/test_scheduled_dispatch_gates.py — t19: the scheduler is a gated entry point.

WHY THIS FILE EXISTS
--------------------
Five instances of one defect class had already been found and fixed in this
codebase (``dry_run``/``draft_only``, ``_approval_granted``, ``approved`` in
tool args, ``approved`` in an HTTP body, ``root="absolute"``). The sixth lived
in ``cato/core/scheduled_dispatch.py``, and it survived a control-chain audit
that reported "11/11 escapes held" for exactly one reason: every one of those
tests drove the model tool-call path or the HTTP-integration path. NOTHING
drove the scheduler.

So this file drives the scheduler. Each test creates a real
``cato.core.schedule_manager.Schedule`` (the same object the X-Cato-Token
``POST /api/cron/jobs`` route persists and the YAML ``SchedulerDaemon`` loads),
then runs it through the real ``dispatch_scheduled_skill`` against a REAL gate
chain (see tests/scheduler_gate_harness.py) and asserts the same outcome the
tool-call path produces.

NO NETWORK, NO DAEMON, NO REAL SUBPROCESS. The two attacks below are run for
real against real gates; the only thing faked is the far side of the wire.

Attacks proven refused here:
  1. cron job {"skill":"shell","args":{"mode":"full","command":...}}
  2. cron job {"skill":"flow.run","args":{"approved":true, ...}}

NOTE ON THE ATTACK-2 VEHICLE. Until t22 attack 2 was driven through
``arbitrage.cycle``, because that was the scheduled skill whose ``approved``
flag reached a live third-party engine. The arbitrage subsystem is gone, so
the attack is now driven through ``flow.run`` — the surviving always-gated
(tier ``dispatch``) scheduled skill. The defect under test is unchanged and is
not arbitrage-specific: it is "a caller who can write a cron job supplies
``approved`` in the schedule args and the dispatcher treats it as
authorization". The mechanism that refuses it — ``_strip_scope_selectors``
plus an execution grant minted only by ``OutboundApprovalStore.consume()`` —
is the shared one in ``cato/core/scheduled_dispatch.py``, so every scheduled
skill inherits the proof.
"""
from __future__ import annotations

import json

import pytest

from tests.scheduler_gate_harness import (
    build_scheduler_gate_env,
    ledger_kinds,
    ledger_rows,
)

# A command that would be unmistakable if it ever ran. It never does: every
# assertion below fires before dispatch, and mode="full" is refused inside
# ShellTool as well.
CANARY_CMD = "python -c \"print('T19-CANARY-SHOULD-NEVER-RUN')\""


def _schedule(skill: str, args: dict, name: str = "t19-job"):
    """Build the real Schedule object the cron API persists."""
    from cato.core.schedule_manager import Schedule

    return Schedule.from_dict({
        "name": name,
        "skill": skill,
        "args": args,
        "cron": "*/5 * * * *",
        "enabled": True,
        "budget_cap": 100,
    })


async def _run_schedule(gateway, sched, session_id: str = "cron-manual-t19"):
    """Exactly what cato/ui/server.py::run_cron_job_now does with a Schedule."""
    from cato.core.scheduled_dispatch import dispatch_scheduled_skill

    return await dispatch_scheduled_skill(
        gateway,
        skill=sched.skill,
        args=sched.args,
        session_id=session_id,
        budget_cap_cents=sched.budget_cap,
        channel="cron",
    )


# =============================================================================
# Attack 1 — an unrestricted shell from a cron job
# =============================================================================


class TestScheduledShellCannotGoUnrestricted:
    @pytest.mark.asyncio
    async def test_cron_shell_mode_full_is_denied(self, tmp_path, monkeypatch):
        """{"skill":"shell","args":{"mode":"full"}} must not execute.

        Before t19 this ran ``ShellTool.execute({"mode": "full"})`` directly —
        an unrestricted ``asyncio.create_subprocess_shell`` with no allowlist,
        no workspace clamp, no safety classification, no approval and no ledger
        entry. It now takes the same route a model's shell tool call takes, and
        stops at the same place that path stops: the registered handler is
        ``shell.exec``, which is NOT in ``_DEFAULT_ALLOWED_TOOLS``, so without a
        delegation token the authorization gate refuses it. Denial is denial —
        the outcome asserted here is the one the gate chain actually produces,
        not the one that would read most impressively.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)

        ran: list[str] = []
        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: ran.append(kw.get("command", "")),
        )

        sched = _schedule("shell", {"mode": "full", "command": CANARY_CMD})
        result = await _run_schedule(env.gateway, sched)

        assert result["ok"] is False
        assert result["action"] == "auth_blocked"
        assert ran == [], "the shell command must not have executed"
        assert env.gateway.sent == [], "no output may be broadcast for a refused job"

    @pytest.mark.asyncio
    async def test_cron_shell_never_presents_full_mode_to_any_gate(self, tmp_path, monkeypatch):
        """`mode` is not read from the schedule, so no gate ever sees "full".

        A gate chain that refused the call but recorded/held ``mode=full``
        would just be a slower bypass — one operator tap and the unrestricted
        shell runs. The ledger's redacted input is the durable proof of what
        was actually about to be dispatched.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: pytest.fail("shell must not run"),
        )

        await _run_schedule(env.gateway, _schedule("shell", {"mode": "full", "command": CANARY_CMD}))

        denied = [r for r in ledger_rows(env.ledger_path, "DENIED") if "shell" in r.tool_name]
        assert denied, "the refusal must be in the hash-chained ledger"
        recorded = json.loads(denied[0].tool_input_redacted)
        assert recorded["mode"] == "sandbox", (
            f"the gate was shown mode={recorded['mode']!r}; a scheduled shell "
            "must only ever be dispatchable in the most restricted mode"
        )

    @pytest.mark.asyncio
    async def test_cron_shell_refusal_is_recorded_as_denied(self, tmp_path, monkeypatch):
        """A refused scheduled action must appear in the ledger, like a refused tool call."""
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: pytest.fail("shell must not run"),
        )

        await _run_schedule(env.gateway, _schedule("shell", {"mode": "full", "command": CANARY_CMD}))

        denied = ledger_rows(env.ledger_path, "DENIED")
        assert denied, "the refusal must be in the hash-chained ledger"
        assert any("shell" in r.tool_name for r in denied)
        assert "CONFIRMED" not in ledger_kinds(env.ledger_path)

    @pytest.mark.asyncio
    async def test_shell_tool_refuses_full_mode_without_a_grant(self, tmp_path, monkeypatch):
        """Second layer: ShellTool itself refuses mode='full' from bare arguments.

        Entry-point-independent, so a seventh caller that forgets the gate
        still cannot obtain an unrestricted shell just by asking for one.
        """
        from cato.core.approval_policy import clear_execution_grants
        from cato.tools.shell import ShellTool

        clear_execution_grants()
        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: pytest.fail("full mode must not reach the runner"),
        )

        out = json.loads(await ShellTool().execute({"command": CANARY_CMD, "mode": "full"}))
        assert out["approval_required"] is True
        assert "mode" in out["error"]

    @pytest.mark.asyncio
    async def test_shell_tool_still_runs_restricted_modes(self, tmp_path, monkeypatch):
        """The fix must not brick the tool: gateway mode still works unchanged."""
        from cato.tools.shell import ShellTool

        seen: dict = {}

        async def _fake_run(self, **kw):
            seen.update(kw)
            return {"stdout": "ok", "stderr": "", "returncode": 0, "truncated": False}

        monkeypatch.setattr("cato.tools.shell.ShellTool._run", _fake_run)

        out = json.loads(await ShellTool().execute({"command": "echo hi"}))
        assert out["returncode"] == 0
        assert seen["mode"] == "gateway"


# =============================================================================
# Attack 2 — a cron job that authorizes itself with approved=true
# =============================================================================


def _spy_flow_engine(monkeypatch) -> list[dict]:
    """Replace FlowEngine.run_flow with a recorder. Returns the record list.

    The far side of the wire is the only thing faked: the gate chain, the
    approval store, the execution grant and the ledger are all real.
    """
    from cato.orchestrator.clawflows import FlowEngine, FlowResult

    seen: list[dict] = []

    async def _spy(self, name, trigger_context=None, resume_run_id=None, budget_cap_cents=None):
        seen.append({"name": name, "trigger_context": trigger_context or {}})
        return FlowResult(flow_name=name, status="COMPLETED", step_outputs=[], error=None)

    monkeypatch.setattr(FlowEngine, "run_flow", _spy)
    return seen


class TestScheduledApprovedFlagGrantsNothing:
    @pytest.mark.asyncio
    async def test_cron_approved_true_does_not_dispatch(self, tmp_path, monkeypatch):
        """{"skill":"flow.run","args":{"approved":true}} must not authorize.

        Before t19, ``approved`` was read straight out of caller-supplied
        schedule args and handed to the skill handler as authorization — for
        the arbitrage skill (removed in t22) that flag was passed to
        ``IntegrationRuntime.action(approved=...)`` and turned a plan into a
        live third-party write. Anyone who could write a cron job could
        therefore authorize themselves. ``flow.run`` is tier ``dispatch`` and
        always gated, so it exercises the same refusal.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        seen = _spy_flow_engine(monkeypatch)

        sched = _schedule("flow.run", {"flow": "some-flow", "approved": True})
        result = await _run_schedule(env.gateway, sched)

        assert result["ok"] is False
        assert result["action"] == "approval_required"
        assert seen == [], "a dispatch-tier skill must not run unapproved"

        denied = ledger_rows(env.ledger_path, "DENIED")
        assert any(r.tool_name == "flow.run" for r in denied)

    @pytest.mark.asyncio
    async def test_approved_true_is_not_even_shown_to_the_gate(self, tmp_path, monkeypatch):
        """The gate must never SEE approved=true, not merely decline to honour it.

        A chain that recorded/held ``approved: true`` in the pending ticket
        would be a slower bypass: the operator taps approve on a payload that
        already claims to be approved. The ledger's redacted input is the
        durable proof of what was actually about to be dispatched.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        _spy_flow_engine(monkeypatch)

        await _run_schedule(
            env.gateway,
            _schedule("flow.run", {"flow": "some-flow", "approved": True}),
        )

        denied = [r for r in ledger_rows(env.ledger_path, "DENIED") if r.tool_name == "flow.run"]
        assert denied, "the refusal must be in the hash-chained ledger"
        recorded = json.loads(denied[0].tool_input_redacted)
        assert "approved" not in recorded, (
            f"the gate was shown {recorded!r}; a caller-supplied authorization "
            "flag must be stripped before any gate reads the payload"
        )

    @pytest.mark.asyncio
    async def test_a_consumed_ticket_is_the_only_thing_that_authorizes(self, tmp_path, monkeypatch):
        """Positive control: a real redeemed ticket DOES authorize, args never do.

        Without this, the test above would also pass if the skill were simply
        broken and could never run at all. Here the grant is minted the only
        sanctioned way — OutboundApprovalStore.consume() on a human-approved
        ticket — and the dispatch goes through.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        seen = _spy_flow_engine(monkeypatch)

        # The exact payload the scheduler will present to the gate: scope
        # selectors already stripped, flow name folded in.
        gate_args = {"flow": "some-flow"}
        approval = env.approval_store.create(
            session_id="cron-manual-t19",
            tool_name="flow.run",
            args=gate_args,
        )
        env.approval_store.approve(approval.id, resolved_by="operator-test")
        env.approval_store.consume(approval.id)  # mints the single-use grant

        sched = _schedule("flow.run", {"flow": "some-flow", "approved": True})
        result = await _run_schedule(env.gateway, sched)

        assert result["ok"] is True
        assert [s["name"] for s in seen] == ["some-flow"]

        # And it is SINGLE USE: the second run is held again.
        seen.clear()
        again = await _run_schedule(env.gateway, sched, session_id="cron-manual-t19-b")
        assert again["ok"] is False
        assert again["action"] == "approval_required"
        assert seen == [], "one ticket must authorize exactly one run"

    @pytest.mark.asyncio
    async def test_stop_file_outranks_a_redeemed_ticket(self, tmp_path, monkeypatch):
        """The replay path must not disarm the emergency kill switch.

        ``human_approved`` skips the gates whose job is to obtain consent, and
        an operator already gave that consent. It must NOT skip the STOP file,
        which postdates the approval and is the one control that means "stop
        now, whatever you were told earlier".
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        seen = _spy_flow_engine(monkeypatch)

        gate_args = {"flow": "some-flow"}
        approval = env.approval_store.create(
            session_id="cron-manual-t19",
            tool_name="flow.run",
            args=gate_args,
        )
        env.approval_store.approve(approval.id, resolved_by="operator-test")
        env.approval_store.consume(approval.id)

        (tmp_path / "STOP").write_text("halt", encoding="utf-8")

        result = await _run_schedule(
            env.gateway, _schedule("flow.run", dict(gate_args)),
        )

        assert result["ok"] is False
        assert result["action"] == "safety_blocked"
        assert seen == [], "STOP must outrank a redeemed approval ticket"


# =============================================================================
# The scheduler is ledgered like the tool-call path
# =============================================================================


class TestScheduledDispatchIsLedgered:
    @pytest.mark.asyncio
    async def test_successful_scheduled_run_writes_intent_and_confirmed(self, tmp_path, monkeypatch):
        env = build_scheduler_gate_env(tmp_path, monkeypatch)

        async def _fake_digest(gateway):
            return None

        monkeypatch.setattr(
            "cato.core.night_shift_digest.send_digest_via_gateway", _fake_digest
        )

        result = await _run_schedule(env.gateway, _schedule("night_shift.digest", {}))

        assert result["ok"] is True
        kinds = ledger_kinds(env.ledger_path)
        assert "INTENT" in kinds
        assert "CONFIRMED" in kinds

    @pytest.mark.asyncio
    async def test_failed_scheduled_run_writes_failed_not_confirmed(self, tmp_path, monkeypatch):
        """A scheduled action that reports failure must not land as CONFIRMED."""
        env = build_scheduler_gate_env(tmp_path, monkeypatch)

        async def _failing_pulse(gateway, *, notify, session_id):
            return {"ok": False, "detail": "site-services unreachable"}

        monkeypatch.setattr(
            "cato.core.site_services_pulse.run_site_services_inbox_pulse", _failing_pulse
        )

        result = await _run_schedule(env.gateway, _schedule("site_services.pulse", {}))

        assert result["ok"] is False
        kinds = ledger_kinds(env.ledger_path)
        assert "INTENT" in kinds
        assert "FAILED" in kinds
        assert "CONFIRMED" not in kinds

    @pytest.mark.asyncio
    async def test_stop_file_halts_the_scheduler(self, tmp_path, monkeypatch):
        """The emergency kill switch must bind on cron, not only on chat."""
        env = build_scheduler_gate_env(tmp_path, monkeypatch)
        (tmp_path / "STOP").write_text("halt", encoding="utf-8")

        async def _fake_digest(gateway):
            pytest.fail("digest must not run while STOP is present")

        monkeypatch.setattr(
            "cato.core.night_shift_digest.send_digest_via_gateway", _fake_digest
        )

        result = await _run_schedule(env.gateway, _schedule("night_shift.digest", {}))

        assert result["ok"] is False
        assert result["action"] == "safety_blocked"

    @pytest.mark.asyncio
    async def test_scheduler_fails_closed_without_a_gate_chain(self, tmp_path, monkeypatch):
        """A gateway with no gate chain must refuse, never dispatch ungated."""
        from types import SimpleNamespace

        from cato.core.scheduled_dispatch import dispatch_scheduled_skill

        monkeypatch.setattr(
            "cato.tools.shell.ShellTool._run",
            lambda self, **kw: pytest.fail("ungated dispatch"),
        )

        bare = SimpleNamespace(_budget=None, _cfg=SimpleNamespace(agent_name="x"))
        result = await dispatch_scheduled_skill(
            bare, skill="shell", args={"command": "echo hi"}, session_id="s",
        )

        assert result["ok"] is False
        assert result["action"] == "gate_unavailable"


# =============================================================================
# Scope/trust selectors generally
# =============================================================================


class TestScopeSelectorsAreNeverHonoured:
    @pytest.mark.parametrize(
        "selector",
        [
            {"approved": True},
            {"root": "absolute"},
            {"mode": "full"},
            {"force": True},
            {"trusted": True},
            {"admin": True},
            {"skip_approval": True},
            {"bypass_approval": True},
        ],
    )
    @pytest.mark.asyncio
    async def test_selector_never_reaches_the_handler(self, tmp_path, monkeypatch, selector):
        """No scope/trust-shaped schedule arg survives into the executed call.

        Driven through the fallback ingest path, because that is the branch
        that actually carries the caller's args forward verbatim (into the
        prompt handed to the agent loop). If a selector survives anywhere, it
        survives here.
        """
        env = build_scheduler_gate_env(tmp_path, monkeypatch)

        sched = _schedule("some.unregistered.skill", {"topic": "weekly", **selector})
        result = await _run_schedule(env.gateway, sched)

        assert result["ok"] is True
        assert result["action"] == "ingest"
        assert len(env.gateway.ingested) == 1
        prompt = env.gateway.ingested[0][1]
        assert "weekly" in prompt, "the legitimate arg must still be carried"
        for key in selector:
            assert key not in prompt, (
                f"scope/trust selector {key!r} reached the handler payload"
            )

        # ...and the gate saw the stripped payload too, not the raw one.
        intents = ledger_rows(env.ledger_path, "INTENT")
        assert intents
        recorded = json.loads(intents[-1].tool_input_redacted)
        assert not set(selector) & set(recorded.get("args") or {})
