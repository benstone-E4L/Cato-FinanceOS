"""
cato/core/scheduled_dispatch.py — Shared dispatch for YAML schedules and manual cron runs.

SECURITY MODEL
--------------
This module used to be a SIXTH instance of the same defect class this codebase
has now fixed five times: a dispatch entry point that reached real tools while
touching none of the gates. Concretely, before t19 it had zero references to
``SafetyGuard``, ``check_and_confirm``, ``approval_policy``, ``requires_approval``,
``recorded_action`` or ``_guarded_dispatch``, and it:

  * defaulted the ``shell`` skill to ``mode="full"`` — an unrestricted
    ``create_subprocess_shell`` with no allowlist and no workspace clamp; and
  * read ``approved`` straight out of caller-supplied schedule args and passed
    it through to a live integration call (the arbitrage engine's kill-switch
    and write actions — that subsystem was removed in t22, but the defect
    shape was generic and the fix below still is).

Both are now closed the same way: EVERY dispatch out of this module goes
through :meth:`cato.agent_loop.AgentLoop.guarded_action`, the single shared
gate entry point that the interactive tool-call path also uses. That means a
scheduled action gets, in this order: STOP file, risk classification
(SafetyGuard), token authorization, ActionGuard, approval policy + ticket,
a durable ledger INTENT, dispatch, then CONFIRMED / FAILED / DENIED.

Two invariants hold here and must keep holding:

  1. ``mode`` is never read from schedule args as a scope selector. The shell
     skill runs in the most restricted mode; an unrestricted shell needs a
     human-approved ticket (see cato/tools/shell.py).
  2. ``approved`` is never read from schedule args as authorization. It comes
     only from a consumed approval ticket, via the in-process execution grant
     (``take_execution_grant``) that ``OutboundApprovalStore.consume()`` mints
     — the same mechanism cato/tools/integration_tool.py uses. There is no
     third mechanism.

Budget: per-run ``budget_cap`` (cents) is still enforced against the gateway
BudgetManager before routing work into the agent loop or Clawflows.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Optional

from ..budget import BudgetExceeded, BudgetManager

logger = logging.getLogger(__name__)

# Rough per-step reservation when enforcing schedule caps (USD)
_SCHEDULE_RESERVE_USD = 0.05

#: The most restricted shell mode. Scheduled shell runs get this and nothing
#: else — see the module docstring. NEVER read this from schedule args.
_SAFE_SHELL_MODE = "sandbox"

#: Keys a schedule author (or anyone who can write a cron job through the
#: X-Cato-Token API) might use to try to talk a gate out of firing. They are
#: reported and dropped before the args reach any handler. Approval-policy
#: control keys are handled separately by ``detect_bypass_attempt``; these are
#: the SCOPE/TRUST selectors specific to this dispatcher.
_SCOPE_SELECTOR_KEYS = frozenset({
    "approved", "mode", "root", "tier", "override", "force",
    "admin", "trusted", "escalate", "privileged",
})


def _strip_scope_selectors(args: dict) -> tuple[dict, list[str]]:
    """Drop caller-supplied scope/trust selectors. Returns (clean_args, dropped)."""
    dropped = sorted(
        str(k) for k in args
        if str(k).strip().lower() in _SCOPE_SELECTOR_KEYS
        or str(k).strip().lower().startswith(("skip_", "bypass_", "no_"))
    )
    clean = {k: v for k, v in args.items() if str(k) not in dropped}
    return clean, dropped


async def _resolve_gate(gateway: Any) -> Any:
    """Return the AgentLoop that owns the gate chain, or None.

    FAIL CLOSED: when the gate chain cannot be reached, the caller refuses the
    dispatch. A scheduler that cannot run the gates does not get to run the
    action instead.
    """
    loop = getattr(gateway, "_agent_loop", None)
    if loop is not None:
        return loop
    ensure = getattr(gateway, "_ensure_agent_loop", None)
    if ensure is None:
        return None
    try:
        await ensure()
    except Exception as exc:  # pragma: no cover — defensive
        logger.error("Scheduled dispatch could not build the gate chain: %s", exc)
        return None
    return getattr(gateway, "_agent_loop", None)


def _gate_refusal(payload: str) -> Optional[dict[str, Any]]:
    """Parse a guarded_action result; return a refusal dict, or None if allowed.

    Every gate in AgentLoop._guarded_dispatch signals refusal with one of these
    boolean keys plus a human-readable ``error``. Anything unparseable is
    treated as a refusal — we never read a result we cannot understand as
    permission to have acted.
    """
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key, action in (
        ("safety_denied", "safety_blocked"),
        ("auth_denied", "auth_blocked"),
        ("guard_denied", "guard_blocked"),
        ("ledger_denied", "ledger_blocked"),
        ("duplicate_action", "duplicate_blocked"),
    ):
        if data.get(key):
            return {"action": action, "detail": str(data.get("error", key))}
    if data.get("error") == "approval_required" or data.get("approval_required"):
        return {
            "action": "approval_required",
            "detail": str(data.get("message") or data.get("error") or "approval required"),
            "approval_id": data.get("approval_id"),
        }
    return None


async def _guarded(
    gateway: Any,
    *,
    gate_tool: str,
    gate_args: dict,
    session_id: str,
    budget_cap_cents: int,
    run: Callable[[bool], Awaitable[dict[str, Any]]],
    action_label: str,
) -> dict[str, Any]:
    """Run ``run(authorized)`` behind the shared gate chain, or return the refusal.

    ``run`` returns the schedule-result dict. It executes INSIDE the ledger
    INTENT, so the scheduled action produces INTENT + CONFIRMED/FAILED entries
    exactly like a model tool call does.

    ``authorized`` is the redeemed-ticket flag, and it is the scheduler's
    equivalent of ``AgentLoop.execute_approved_tool``. The grant is taken HERE,
    once, before the gates run, because an always-gated skill (a dispatch-tier
    flow) would otherwise be held for approval forever: the operator approves,
    ``consume()`` mints the grant, and the next run would be stopped by the
    approval gate before anything could ever take it. Taking it here converts a
    verified ticket into the same ``human_approved`` replay the interactive
    path uses — STOP still binds, and the ledger still records everything, now
    with ``policy_gate="human_approved"``.

    Taking a grant is destructive and single-use, so it happens exactly once
    per dispatch and the result is handed to ``run``; nothing downstream may
    re-derive authorization for itself.
    """
    loop = await _resolve_gate(gateway)
    if loop is None:
        logger.error(
            "Scheduled skill %r refused: no gate chain available on %s",
            gate_tool, type(gateway).__name__,
        )
        return {
            "ok": False,
            "action": "gate_unavailable",
            "detail": (
                "Scheduled dispatch refused: the safety/approval/ledger gate "
                "chain is unavailable, and an ungated scheduled action is "
                "exactly the bypass this path exists to prevent."
            ),
            "budget_cap_cents": budget_cap_cents,
        }

    # Single-use, payload-bound, minted only by OutboundApprovalStore.consume().
    # Fail closed: any error answers "not authorized".
    try:
        from .approval_policy import take_execution_grant

        authorized = bool(take_execution_grant(gate_tool, gate_args))
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Execution-grant lookup failed (%s); treating as unapproved.", exc)
        authorized = False

    if authorized:
        logger.info(
            "Scheduled %r running under a redeemed approval ticket (single-use grant).",
            gate_tool,
        )

    holder: dict[str, Any] = {}

    async def _dispatch() -> str:
        result = await run(authorized)
        holder["result"] = result
        # The ledger's CONFIRMED/FAILED classification reads this string, so a
        # skill that reports ok:false lands as FAILED, not CONFIRMED.
        return json.dumps({
            "ok": bool(result.get("ok")),
            "error": None if result.get("ok") else str(result.get("detail", "failed"))[:500],
        })

    payload = await loop.guarded_action(
        gate_tool, gate_args, session_id, dispatch=_dispatch,
        human_approved=authorized,
    )
    refusal = _gate_refusal(payload)
    if refusal is not None:
        out = {"ok": False, "budget_cap_cents": budget_cap_cents}
        out.update(refusal)
        return out

    result = holder.get("result")
    if result is None:
        # The gate returned something that is neither a known refusal nor a
        # completed run. Fail closed rather than reporting success.
        return {
            "ok": False,
            "action": "gate_indeterminate",
            "detail": f"gate returned an unrecognised result for {gate_tool!r}",
            "budget_cap_cents": budget_cap_cents,
        }
    result.setdefault("action", action_label)
    result.setdefault("budget_cap_cents", budget_cap_cents)
    return result


#: Public aliases. Other in-tree gate callers — the Clawflows FlowEngine and the
#: ``POST /api/flows/{name}/run`` route — must reuse THIS gate chain rather than
#: grow a second copy of it. The underscore names stay for existing callers.
gate_refusal = _gate_refusal
run_behind_gate = _guarded
resolve_gate = _resolve_gate


async def dispatch_scheduled_skill(
    gateway: Any,
    *,
    skill: str,
    args: Optional[dict] = None,
    session_id: str,
    budget_cap_cents: int = 100,
    channel: str = "cron",
    agent_id: str = "",
) -> dict[str, Any]:
    """
    Dispatch a scheduled skill through the live gateway, behind the full gate chain.

    Returns a result dict with keys: ok, action, detail, budget_cap_cents.
    """
    raw_args = dict(args or {})
    skill = (skill or "").strip()
    if not skill:
        return {"ok": False, "action": "none", "detail": "empty skill", "budget_cap_cents": budget_cap_cents}

    args, dropped = _strip_scope_selectors(raw_args)
    if dropped:
        logger.warning(
            "Scheduled skill %r supplied scope/trust selector(s) %s — dropped. "
            "Authorization comes only from a consumed approval ticket.",
            skill, dropped,
        )

    try:
        from .night_shift_policy import assert_skill_allowed
        assert_skill_allowed(skill, args)
    except PermissionError as exc:
        return {
            "ok": False,
            "action": "policy_blocked",
            "detail": str(exc),
            "budget_cap_cents": budget_cap_cents,
        }

    if skill in ("night_shift.digest", "night-shift-digest"):
        from .night_shift_digest import send_digest_via_gateway

        async def _run(authorized: bool) -> dict[str, Any]:
            await send_digest_via_gateway(gateway)
            return {"ok": True, "detail": "night-shift digest sent or logged"}

        return await _guarded(
            gateway, gate_tool=skill, gate_args=args, session_id=session_id,
            budget_cap_cents=budget_cap_cents, run=_run, action_label="digest",
        )

    if skill in ("site_services.pulse", "site-services-inbox"):
        from .site_services_pulse import run_site_services_inbox_pulse

        async def _run(authorized: bool) -> dict[str, Any]:
            result = await run_site_services_inbox_pulse(
                gateway, notify=True, session_id=session_id,
            )
            return {
                "ok": bool(result.get("ok")),
                "detail": result.get("detail", ""),
                "inbox_count": result.get("inbox_count", 0),
                "stuck_count": result.get("stuck_count", 0),
            }

        return await _guarded(
            gateway, gate_tool=skill, gate_args=args, session_id=session_id,
            budget_cap_cents=budget_cap_cents, run=_run,
            action_label="site_services_pulse",
        )

    if skill in ("site_services.digest", "site-services-digest"):
        from .site_services_digest import send_site_services_digest_via_gateway

        async def _run(authorized: bool) -> dict[str, Any]:
            await send_site_services_digest_via_gateway(gateway)
            return {"ok": True, "detail": "site-services morning digest sent or logged"}

        return await _guarded(
            gateway, gate_tool=skill, gate_args=args, session_id=session_id,
            budget_cap_cents=budget_cap_cents, run=_run,
            action_label="site_services_digest",
        )

    if skill == "shell":
        command = str(raw_args.get("command") or "").strip()
        if command:
            from ..tools.shell import ShellTool

            timeout = min(int(raw_args.get("timeout") or 300), 3600)
            # `mode` is NOT read from the schedule. A scheduled shell runs in
            # the most restricted mode; anything less restricted needs a
            # human-approved ticket, which ShellTool itself enforces.
            shell_args = {
                "command": command,
                "mode": _SAFE_SHELL_MODE,
                "timeout": timeout,
            }

            async def _run(authorized: bool) -> dict[str, Any]:
                output = await ShellTool().execute(shell_args)
                await gateway.send(session_id, output[:3500], channel)
                return {"ok": True, "detail": output[:500]}

            return await _guarded(
                gateway, gate_tool="shell", gate_args=shell_args,
                session_id=session_id, budget_cap_cents=budget_cap_cents,
                run=_run, action_label="shell",
            )

    reserve_usd = min(
        max(budget_cap_cents, 0) / 100.0,
        _SCHEDULE_RESERVE_USD,
    )
    budget: BudgetManager = gateway._budget
    try:
        await budget.check_and_deduct_usd(
            reserve_usd,
            label=f"schedule:{session_id}",
        )
    except BudgetExceeded as exc:
        logger.warning("Schedule %s blocked by budget: %s", session_id, exc)
        return {
            "ok": False,
            "action": "budget_blocked",
            "detail": str(exc),
            "budget_cap_cents": budget_cap_cents,
        }

    # flow.run or flow:<name>
    flow_name = ""
    if skill == "flow.run":
        flow_name = str(args.get("flow") or args.get("name") or "")
    elif skill.startswith("flow:"):
        flow_name = skill.split(":", 1)[1].strip()

    if not flow_name:
        # Named flow file without prefix
        from ..orchestrator.clawflows import FlowEngine

        probe = FlowEngine(budget=budget)
        if skill in {f["name"] for f in probe.list_flows()}:
            flow_name = skill

    if flow_name:
        from ..orchestrator.clawflows import FlowEngine

        async def _run(authorized: bool) -> dict[str, Any]:
            # The flow itself is gated by `_guarded` below (tier `dispatch`).
            # Threading the loop in gates every STEP too — one approval must
            # never authorize an unbounded set of tool calls inside the flow.
            engine = FlowEngine(budget=budget, agent_loop=await _resolve_gate(gateway))
            result = await engine.run_flow(
                flow_name,
                trigger_context={"session_id": session_id, "args": args, "channel": channel},
                budget_cap_cents=budget_cap_cents,
            )
            text = f"Flow '{flow_name}' {result.status}. Steps: {len(result.step_outputs)}."
            if result.error:
                text += f" Error: {result.error}"
            await gateway.send(session_id, text, channel)
            return {
                "ok": result.status == "COMPLETED",
                "detail": text,
                "flow_status": result.status,
            }

        # A flow runs other tools/agents; `clawflows_run` is tier `dispatch`,
        # always gated — identical to the interactive `flow.run` tool call.
        return await _guarded(
            gateway, gate_tool="flow.run", gate_args={"flow": flow_name, **args},
            session_id=session_id, budget_cap_cents=budget_cap_cents,
            run=_run, action_label="flow",
        )

    # Default: agent loop via ingest
    if args:
        prompt = (
            f"[Scheduled task] Execute skill `{skill}` with arguments:\n"
            f"{json.dumps(args, indent=2)}\n"
            "Complete the task and report results."
        )
    else:
        prompt = (
            f"[Scheduled task] Execute skill `{skill}`.\n"
            "Complete the task and report results."
        )

    async def _run_ingest(authorized: bool) -> dict[str, Any]:
        await gateway.ingest(session_id, prompt, channel, agent_id or gateway._cfg.agent_name)
        return {"ok": True, "detail": f"ingested prompt for skill={skill!r}"}

    return await _guarded(
        gateway, gate_tool="schedule.ingest",
        gate_args={"skill": skill, "args": args},
        session_id=session_id, budget_cap_cents=budget_cap_cents,
        run=_run_ingest, action_label="ingest",
    )
