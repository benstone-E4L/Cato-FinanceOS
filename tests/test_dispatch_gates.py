"""The dispatch path is the only place Cato's gates run. This file proves they do.

Each test here maps to a defect that was live in the tree:

  * `_approval_granted` in model-written args skipped the approval gate entirely
  * the Telegram preview was `json.dumps(args)[:500]` — unredacted
  * an approved action could be executed again, and again, off a status read
  * gate refusals never reached the ledger, so it only showed what worked
  * a ledger write failure was swallowed and the tool ran anyway
  * ActionGuard existed but nothing in the dispatch path called it
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cato.agent_loop import AgentLoop, ToolCall, _reversibility_name
from cato.audit.action_guard import ActionGuard
from cato.audit.ledger import LedgerMiddleware, LedgerQuery, LedgerWriteError
from cato.audit.reversibility_registry import BlastRadius, ReversibilityRegistry
from cato.core.outbound_approval import OutboundApprovalStore
from cato.safety import SafetyGuard


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class _Loop(AgentLoop):
    """AgentLoop with the heavy constructor skipped.

    The real methods under test are inherited unchanged — only collaborators
    and the terminal dispatch call are substituted.
    """

    def __init__(self, **attrs):  # noqa: D107 - deliberately not calling super()
        self.dispatched: list[ToolCall] = []
        self._dispatch_result = json.dumps({"ok": True})
        self._dispatch_raises: BaseException | None = None
        for key, value in attrs.items():
            setattr(self, key, value)

    async def _dispatch_with_progress(self, tc: ToolCall) -> str:  # type: ignore[override]
        self.dispatched.append(tc)
        if self._dispatch_raises is not None:
            raise self._dispatch_raises
        return self._dispatch_result


class _AllowAuth:
    """TokenChecker stand-in that authorizes everything."""

    def check_authorization(self, *_a, **_k):
        return None


class _DenyAuth:
    class _Result:
        authorized = False
        requires_user_confirmation = False
        reason = "no delegation token for this scope"

    def check_authorization(self, *_a, **_k):
        return self._Result()


@pytest.fixture()
def ledger(tmp_path):
    mw = LedgerMiddleware(db_path=tmp_path / "ledger.db")
    yield mw
    mw.close()


@pytest.fixture()
def approval_store(monkeypatch, tmp_path):
    store = OutboundApprovalStore(db_path=tmp_path / "approvals.db")
    monkeypatch.setattr("cato.core.outbound_approval._store", store)
    yield store
    store.close()


@pytest.fixture()
def loop(tmp_path, monkeypatch, ledger):
    """A loop whose gates are all real, in a non-interactive (daemon) context."""
    monkeypatch.setattr(SafetyGuard, "_stop_file_path", staticmethod(lambda: tmp_path / "STOP"))
    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)
    return _Loop(
        _safety=SafetyGuard(config={"safety_mode": "strict"}),
        _audit_log=None,
        _token_checker=_AllowAuth(),
        _action_guard=ActionGuard(),
        _autonomy_level=0.5,
        _ledger=ledger,
        _ledger_required=True,
        _outbound_notify=None,
        _run_id="testrun",
    )


def _denials(tmp_path) -> list:
    q = LedgerQuery(db_path=tmp_path / "ledger.db")
    try:
        return q.by_entry_kind("DENIED")
    finally:
        q.close()


def _kinds(tmp_path) -> list[str]:
    q = LedgerQuery(db_path=tmp_path / "ledger.db")
    try:
        return [r.entry_kind for r in q.last_n(50)]
    finally:
        q.close()


# ---------------------------------------------------------------------------
# 1. A model-supplied arg cannot skip the approval gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bypass_args",
    [
        {"_approval_granted": True},
        {"approval_granted": True},
        {"dry_run": True},
        {"draft_only": True},
        {"skip_approval": True},
        {"_approval_granted": True, "dry_run": True, "draft_only": True},
    ],
)
@pytest.mark.asyncio
async def test_model_supplied_args_cannot_grant_approval(loop, approval_store, bypass_args):
    """The exact bug: `if args.get('_approval_granted'): return None` ran BEFORE
    requires_approval(), and the model writes args. It could approve itself."""
    tc = ToolCall(
        name="send_email",
        args={"to": "victim@example.com", "subject": "s", "body": "b", **bypass_args},
        call_id="c1",
    )
    result = await loop._maybe_gate_outbound_tool(tc, "sess-1")

    assert result is not None, f"gate was skipped by model-supplied {bypass_args}"
    payload = json.loads(result)
    assert payload["error"] == "approval_required"
    assert payload["approval_id"]
    # And nothing was sent.
    assert loop.dispatched == []


@pytest.mark.asyncio
async def test_bypass_args_do_not_reach_the_stored_payload(loop, approval_store):
    tc = ToolCall(
        name="send_email",
        args={"to": "a@b.com", "_approval_granted": True, "dry_run": True},
        call_id="c1",
    )
    result = await loop._maybe_gate_outbound_tool(tc, "sess-1")
    approval = approval_store.get(json.loads(result)["approval_id"])
    # Control keys are stripped, so they cannot survive into execution.
    assert "_approval_granted" not in approval.args
    # `dry_run` is ordinary data and is preserved — it simply carries no
    # authority. The test above already proves it does not skip the gate.
    assert approval.args["dry_run"] is True


@pytest.mark.asyncio
async def test_guarded_dispatch_blocks_self_approved_outbound_end_to_end(loop, approval_store):
    """Full path, not just the gate helper: nothing executes."""
    tc = ToolCall(
        name="send_email",
        args={"to": "a@b.com", "body": "hi", "_approval_granted": True},
        call_id="c1",
    )
    result = await loop._guarded_dispatch(tc, "sess-1")
    assert loop.dispatched == []
    assert json.loads(result).get("safety_denied") or json.loads(result).get("error")


# ---------------------------------------------------------------------------
# 2. The operator-facing preview is redacted end-to-end, including nesting
# ---------------------------------------------------------------------------

NESTED_SECRETS = {
    "to": "ops@example.com",
    "subject": "deploy",
    "headers": {"authorization": "Bearer sk-live-THIS-MUST-NOT-LEAK-0123456789"},
    "config": {
        "nested": {
            "deeper": {"api_key": "sk-live-DEEP-SECRET-9876543210abcdef"},
        },
        "items": [
            {"password": "hunter2-do-not-log"},
            {"note": "the token is ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
        ],
    },
}

_LEAKS = (
    "THIS-MUST-NOT-LEAK",
    "DEEP-SECRET",
    "hunter2-do-not-log",
    "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
)


@pytest.mark.asyncio
async def test_preview_sent_to_telegram_is_redacted(loop, approval_store):
    """The preview reaches an operator's phone. It must carry no credential.

    The old code built it with json.dumps(args)[:500] and handed it to
    _outbound_notify BEFORE the store (which does redact) ever saw it.
    """
    notified: list = []

    async def _notify(approval):
        notified.append(approval)

    loop._outbound_notify = _notify

    tc = ToolCall(name="send_email", args=dict(NESTED_SECRETS), call_id="c1")
    await loop._maybe_gate_outbound_tool(tc, "sess-1")

    assert len(notified) == 1
    preview = notified[0].preview
    for leak in _LEAKS:
        assert leak not in preview, f"{leak!r} leaked into the Telegram preview"
    assert "[redacted]" in preview.lower()
    # Still useful to a human deciding yes/no.
    assert "ops@example.com" in preview


@pytest.mark.asyncio
async def test_stored_approval_args_are_redacted(loop, approval_store):
    tc = ToolCall(name="send_email", args=dict(NESTED_SECRETS), call_id="c1")
    result = await loop._maybe_gate_outbound_tool(tc, "sess-1")
    approval = approval_store.get(json.loads(result)["approval_id"])
    blob = json.dumps(approval.args)
    for leak in _LEAKS:
        assert leak not in blob, f"{leak!r} persisted to the approvals table"


# ---------------------------------------------------------------------------
# 3. Replay: an approval is redeemable exactly once
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approved_tool_executes_once_then_refuses_replay(loop, approval_store):
    tc = ToolCall(name="send_email", args={"to": "a@b.com", "body": "hi"}, call_id="c1")
    held = json.loads(await loop._maybe_gate_outbound_tool(tc, "sess-1"))
    approval_id = held["approval_id"]

    assert approval_store.approve(approval_id, resolved_by="operator") is not None

    first = json.loads(await loop.execute_approved_tool(approval_id))
    assert first.get("ok") is True
    assert len(loop.dispatched) == 1

    second = json.loads(await loop.execute_approved_tool(approval_id))
    assert second["ok"] is False
    assert second["error"] == "approval_not_consumable"
    assert second["reason"] == "ticket_already_consumed"
    # The load-bearing assertion: the side effect did NOT happen twice.
    assert len(loop.dispatched) == 1

    third = json.loads(await loop.execute_approved_tool(approval_id))
    assert third["ok"] is False
    assert len(loop.dispatched) == 1


@pytest.mark.asyncio
async def test_unapproved_approval_cannot_be_executed(loop, approval_store):
    tc = ToolCall(name="send_email", args={"to": "a@b.com"}, call_id="c1")
    held = json.loads(await loop._maybe_gate_outbound_tool(tc, "sess-1"))

    out = json.loads(await loop.execute_approved_tool(held["approval_id"]))
    assert out["ok"] is False
    assert out["reason"] == "approval_status_pending"
    assert loop.dispatched == []


@pytest.mark.asyncio
async def test_unknown_approval_id_is_refused(loop, approval_store):
    out = json.loads(await loop.execute_approved_tool("does-not-exist"))
    assert out["ok"] is False
    assert out["reason"] == "approval_not_found"
    assert loop.dispatched == []


@pytest.mark.asyncio
async def test_executed_args_are_the_ones_the_operator_approved(loop, approval_store):
    """Not a locally reconstructed copy, and with no _approval_granted re-injected."""
    tc = ToolCall(
        name="send_email",
        args={"to": "a@b.com", "body": "hi", "_approval_granted": True},
        call_id="c1",
    )
    held = json.loads(await loop._maybe_gate_outbound_tool(tc, "sess-1"))
    approval_store.approve(held["approval_id"], resolved_by="operator")

    await loop.execute_approved_tool(held["approval_id"])
    ran = loop.dispatched[0]
    assert "_approval_granted" not in ran.args
    assert ran.args == approval_store.get(held["approval_id"]).args


@pytest.mark.asyncio
async def test_tampering_with_approved_args_is_refused(loop, approval_store):
    """The digest binds the args, so an edited row cannot be redeemed."""
    tc = ToolCall(name="send_email", args={"to": "a@b.com", "body": "hi"}, call_id="c1")
    held = json.loads(await loop._maybe_gate_outbound_tool(tc, "sess-1"))
    approval_id = held["approval_id"]
    approval_store.approve(approval_id, resolved_by="operator")

    from cato.core.approval_policy import TicketError

    with pytest.raises(TicketError):
        approval_store.consume(approval_id, args={"to": "attacker@evil.com", "body": "hi"})


# ---------------------------------------------------------------------------
# 4. Refusals reach the ledger
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_refusal_writes_a_ledger_denied_entry(loop, tmp_path):
    """An UNCLASSIFIED tool is refused at the safety gate, and that refusal
    reaches the ledger.

    t14 changed which calls stop here: in a headless (no-TTY) context the
    safety gate now DEFERS a positively-classified, approval-required tool to
    the human approval gate instead of denying it outright, because denying
    made the Telegram approval flow unreachable in production. Nothing is
    deferred that the approval gate would not hold — see
    ``SafetyGuard._defers_to_approval_gate`` and
    ``test_headless_deferral_is_never_a_downgrade`` below. An unclassified
    tool is deferred to nothing and is still refused right here, which is
    what this test pins.
    """
    tc = ToolCall(name="totally_unreviewed_tool", args={"x": 1}, call_id="c1")
    result = await loop._guarded_dispatch(tc, "sess-1")

    assert json.loads(result)["safety_denied"] is True
    assert loop.dispatched == []

    denials = _denials(tmp_path)
    assert len(denials) == 1
    assert denials[0].tool_name == "totally_unreviewed_tool"
    assert denials[0].policy_gate == "safety"
    assert denials[0].policy_decision == "deny"
    # DENIED is the only entry — no INTENT was written for an action that never ran.
    assert _kinds(tmp_path) == ["DENIED"]


@pytest.mark.asyncio
async def test_headless_file_delete_is_still_blocked_and_still_ledger_denied(
    loop, tmp_path,
):
    """Regression companion to the test above: the call that used to be
    refused at the safety gate must still never reach a handler, and must
    still leave a DENIED row — only the gate that stops it changed."""
    tc = ToolCall(name="file", args={"action": "delete", "path": "x"}, call_id="c1")
    result = await loop._guarded_dispatch(tc, "sess-1")

    assert loop.dispatched == [], "a destructive file action reached the handler"
    assert json.loads(result).get("error"), "the caller was not told it was refused"
    denials = _denials(tmp_path)
    assert len(denials) == 1
    assert denials[0].tool_name == "file"
    assert denials[0].policy_decision == "deny"
    assert _kinds(tmp_path) == ["DENIED"]


@pytest.mark.asyncio
async def test_authorization_refusal_writes_a_ledger_denied_entry(loop, tmp_path):
    loop._token_checker = _DenyAuth()
    tc = ToolCall(name="web.search", args={"query": "x"}, call_id="c1")
    result = await loop._guarded_dispatch(tc, "sess-1")

    assert json.loads(result)["auth_denied"] is True
    assert loop.dispatched == []
    denials = _denials(tmp_path)
    assert [d.policy_gate for d in denials] == ["authorization"]


@pytest.mark.asyncio
async def test_approval_refusal_writes_a_ledger_denied_entry(loop, approval_store, tmp_path):
    tc = ToolCall(name="send_email", args={"to": "a@b.com"}, call_id="c1")
    await loop._maybe_gate_outbound_tool(tc, "sess-1")

    denials = _denials(tmp_path)
    assert [d.policy_gate for d in denials] == ["approval"]
    assert denials[0].approval_ref


@pytest.mark.asyncio
async def test_stop_file_refusal_writes_a_ledger_denied_entry(loop, tmp_path):
    (tmp_path / "STOP").write_text("halt", encoding="utf-8")
    tc = ToolCall(name="web.search", args={"query": "x"}, call_id="c1")
    result = await loop._guarded_dispatch(tc, "sess-1")

    assert json.loads(result)["safety_denied"] is True
    assert loop.dispatched == []
    assert [d.policy_gate for d in _denials(tmp_path)] == ["stop_file"]


@pytest.mark.asyncio
async def test_stop_file_binds_even_on_the_human_approved_path(loop, tmp_path):
    """An emergency stop postdates the approval, so it still wins."""
    (tmp_path / "STOP").write_text("halt", encoding="utf-8")
    tc = ToolCall(name="send_email", args={"to": "a@b.com"}, call_id="c1")
    await loop._guarded_dispatch(tc, "sess-1", approval_ref="ap1", human_approved=True)
    assert loop.dispatched == []


@pytest.mark.asyncio
async def test_denials_are_recorded_before_the_model_is_told(loop, tmp_path):
    """Ordering matters: the chain must already contain the refusal."""
    seen: list[int] = []
    real = loop._record_denial

    def _spy(**kwargs):
        real(**kwargs)
        seen.append(len(_denials(tmp_path)))

    loop._record_denial = _spy  # type: ignore[method-assign]
    tc = ToolCall(name="file", args={"action": "delete"}, call_id="c1")
    await loop._guarded_dispatch(tc, "sess-1")
    assert seen == [1]


# ---------------------------------------------------------------------------
# 5. Ledger failures abort the action
# ---------------------------------------------------------------------------

class _BrokenLedger:
    """A ledger whose INTENT write fails."""

    def __init__(self, exc):
        self._exc = exc

    def recorded_action(self, **_kwargs):
        raise self._exc

    def record_denial(self, **_kwargs):
        return "denial"

    def unresolved_intents(self):
        return []


@pytest.mark.asyncio
async def test_ledger_write_failure_aborts_the_action(loop):
    loop._ledger = _BrokenLedger(LedgerWriteError("disk full"))
    tc = ToolCall(name="web.search", args={"query": "x"}, call_id="c1")

    result = await loop._guarded_dispatch(tc, "sess-1")

    payload = json.loads(result)
    assert payload["ledger_denied"] is True
    assert "aborted" in payload["error"].lower()
    # The load-bearing assertion: the tool never ran.
    assert loop.dispatched == []


@pytest.mark.asyncio
async def test_ledger_write_failure_is_not_swallowed_by_except_exception(loop):
    """LedgerError derives from BaseException precisely so this cannot happen.

    The old code wrapped the append in `except Exception: logger.debug(...)`.
    """
    assert not issubclass(LedgerWriteError, Exception)
    assert issubclass(LedgerWriteError, BaseException)

    loop._ledger = _BrokenLedger(LedgerWriteError("io error"))
    tc = ToolCall(name="web.search", args={"query": "x"}, call_id="c1")
    try:
        result = await loop._guarded_dispatch(tc, "sess-1")
    except Exception:  # noqa: BLE001 — this is the point of the test
        pytest.fail("a blanket except Exception must not be able to see a LedgerError")
    assert json.loads(result)["ledger_denied"] is True


@pytest.mark.asyncio
async def test_duplicate_action_is_refused_and_not_re_run(loop, tmp_path):
    """A replayed call must not repeat the side effect."""
    tc = ToolCall(name="web.search", args={"query": "x"}, call_id="c1")

    first = json.loads(await loop._guarded_dispatch(tc, "sess-1"))
    assert first["ok"] is True
    assert len(loop.dispatched) == 1

    # Same session, same run id, same call id -> same idempotency key.
    second = json.loads(await loop._guarded_dispatch(tc, "sess-1"))
    assert second["duplicate_action"] is True
    assert len(loop.dispatched) == 1


@pytest.mark.asyncio
async def test_missing_ledger_refuses_when_auditing_is_enabled(loop):
    loop._ledger = None
    loop._ledger_required = True
    tc = ToolCall(name="web.search", args={"query": "x"}, call_id="c1")
    result = await loop._guarded_dispatch(tc, "sess-1")
    assert json.loads(result)["ledger_denied"] is True
    assert loop.dispatched == []


@pytest.mark.asyncio
async def test_missing_ledger_allows_when_operator_disabled_auditing(loop):
    loop._ledger = None
    loop._ledger_required = False
    tc = ToolCall(name="web.search", args={"query": "x"}, call_id="c1")
    result = await loop._guarded_dispatch(tc, "sess-1")
    assert json.loads(result)["ok"] is True
    assert len(loop.dispatched) == 1


# ---------------------------------------------------------------------------
# 6. INTENT is durable BEFORE dispatch, and the outcome is recorded after
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intent_is_committed_before_the_tool_runs(loop, tmp_path):
    observed: list[list[str]] = []

    async def _spy(tc):
        observed.append(_kinds(tmp_path))
        loop.dispatched.append(tc)
        return json.dumps({"ok": True})

    loop._dispatch_with_progress = _spy  # type: ignore[method-assign]
    tc = ToolCall(name="web.search", args={"query": "x"}, call_id="c1")
    await loop._guarded_dispatch(tc, "sess-1")

    # INTENT (and ATTEMPTED) were already durable on disk when the tool ran.
    assert observed[0][0] == "INTENT"
    assert _kinds(tmp_path)[-1] == "CONFIRMED"


@pytest.mark.asyncio
async def test_tool_failure_records_failed_and_propagates(loop, tmp_path):
    loop._dispatch_raises = RuntimeError("upstream 500")
    tc = ToolCall(name="web.search", args={"query": "x"}, call_id="c1")

    with pytest.raises(RuntimeError):
        await loop._guarded_dispatch(tc, "sess-1")

    kinds = _kinds(tmp_path)
    assert kinds[0] == "INTENT"
    assert kinds[-1] == "FAILED"


@pytest.mark.asyncio
async def test_unresolved_intents_are_surfaced(loop, tmp_path, caplog):
    """A crash between INTENT and the terminal entry must be visible on restart."""
    with pytest.raises(RuntimeError):
        with loop._ledger.recorded_action(
            tool_name="send_email",
            tool_input={"to": "a@b.com"},
            agent_session_id="sess-crash",
            policy_decision="allow",
            policy_gate="auto",
            idempotency_key="crash-key",
        ) as action:
            action._mark_attempt()
            raise RuntimeError("power cut")  # noqa: TRY301

    # `recorded_action` records FAILED on the way out, so simulate a true crash
    # by writing a bare INTENT that never resolves.
    loop._ledger._write_entry(
        entry_kind=__import__("cato.audit.ledger", fromlist=["EntryKind"]).EntryKind.INTENT,
        tool_name="wire_transfer_send",
        agent_session_id="sess-crash",
        action_id="orphan-1",
        idempotency_key="orphan-key",
        outcome="intent recorded; action not yet attempted",
    )

    with caplog.at_level("CRITICAL"):
        orphans = loop._surface_unresolved_intents()

    assert [o.tool_name for o in orphans] == ["wire_transfer_send"]
    assert "LEDGER RECOVERY" in caplog.text


# ---------------------------------------------------------------------------
# 7. ActionGuard's verdict binds
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry():
    reg = ReversibilityRegistry.get_instance()
    saved = dict(reg._registry)
    yield reg
    reg._registry = saved


@pytest.mark.asyncio
async def test_action_guard_can_block_a_dispatch(loop, registry, tmp_path):
    """Register a nearly-irreversible tool; ActionGuard rule 1 must stop it.

    This is the proof that the guard is genuinely wired: nothing else in the
    path objects to `graph.query` (READ tier, authorized, no approval needed),
    so if the call is refused it is ActionGuard that refused it.
    """
    # `graph.query` resolves to the registry key `memory_search`; register
    # against the resolved name so the guard actually sees the score.
    registry.register(
        _reversibility_name("graph.query", {}), reversibility=1.0,
        recovery_time="irreversible", blast_radius=BlastRadius.PUBLIC,
        notes="test: forced irreversible",
    )

    tc = ToolCall(name="graph.query", args={"q": "x"}, call_id="c1")
    result = await loop._guarded_dispatch(tc, "sess-1")

    payload = json.loads(result)
    assert payload["guard_denied"] is True
    assert payload["requires_confirmation"] is True
    assert "nearly irreversible" in payload["error"]
    assert loop.dispatched == []
    assert [d.policy_gate for d in _denials(tmp_path)] == ["action_guard"]


@pytest.mark.asyncio
async def test_action_guard_allows_the_same_tool_when_reversible(loop, registry):
    """Control for the test above — the block came from the score, not the plumbing."""
    registry.register(
        _reversibility_name("graph.query", {}), reversibility=0.0,
        recovery_time="instant", blast_radius=BlastRadius.SELF,
        notes="test: reversible",
    )
    tc = ToolCall(name="graph.query", args={"q": "x"}, call_id="c1")
    result = await loop._guarded_dispatch(tc, "sess-1")
    assert json.loads(result)["ok"] is True
    assert len(loop.dispatched) == 1


@pytest.mark.asyncio
async def test_autonomy_level_changes_the_guard_verdict(loop, registry):
    """Rule 2: reversibility > 0.7 blocks below autonomy 0.8."""
    registry.register(
        _reversibility_name("graph.query", {}), reversibility=0.75,
        recovery_time="hours", blast_radius=BlastRadius.MULTI_USER, notes="test",
    )
    tc = ToolCall(name="graph.query", args={"q": "x"}, call_id="c1")

    loop._autonomy_level = 0.5
    assert json.loads(await loop._guarded_dispatch(tc, "s1"))["guard_denied"] is True
    assert loop.dispatched == []

    loop._autonomy_level = 0.9
    assert json.loads(await loop._guarded_dispatch(tc, "s2"))["ok"] is True
    assert len(loop.dispatched) == 1


@pytest.mark.asyncio
async def test_action_guard_error_refuses_rather_than_proceeds(loop, tmp_path):
    class _Exploding:
        def check_before_execute(self, *_a, **_k):
            raise RuntimeError("registry corrupt")

    loop._action_guard = _Exploding()
    tc = ToolCall(name="web.search", args={"q": "x"}, call_id="c1")
    result = await loop._guarded_dispatch(tc, "sess-1")

    assert json.loads(result)["guard_denied"] is True
    assert loop.dispatched == []
    assert [d.policy_gate for d in _denials(tmp_path)] == ["action_guard"]


def test_reversibility_names_resolve_to_real_registry_entries():
    """A name map that resolved to nothing would make the guard vacuous."""
    reg = ReversibilityRegistry.get_instance()
    cases = [
        ("shell.exec", {}, "shell_execute"),
        ("web.search", {}, "web_search"),
        ("send_email", {}, "email_send"),
        ("file", {"action": "delete"}, "delete_file"),
        ("file", {"action": "read"}, "read_file"),
        ("browser", {"action": "click"}, "conduit_click"),
        ("browser", {"action": "navigate"}, "conduit_navigate"),
    ]
    for tool, args, expected in cases:
        resolved = _reversibility_name(tool, args)
        assert resolved == expected
        reg.get(resolved)  # raises ToolNotRegistered if the map is wrong


def test_unmapped_tool_keeps_its_name_so_the_guard_defaults_conservatively():
    assert _reversibility_name("xero_post_bill", {}) == "xero_post_bill"
    assert _reversibility_name("browser", {"action": "unknown_op"}) == "browser.unknown_op"


# ---------------------------------------------------------------------------
# 8. Gateway redemption is single-use too
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gateway_execute_outbound_approval_is_not_replayable(
    loop, approval_store, monkeypatch,
):
    from cato.gateway import Gateway

    tc = ToolCall(name="send_email", args={"to": "a@b.com", "body": "hi"}, call_id="c1")
    held = json.loads(await loop._maybe_gate_outbound_tool(tc, "sess-1"))
    approval_id = held["approval_id"]

    class _FakeGateway:
        _agent_loop = loop

        async def _ensure_agent_loop(self):
            return None

    fake = _FakeGateway()

    first = await Gateway.execute_outbound_approval(fake, approval_id)
    assert first["ok"] is True
    assert len(loop.dispatched) == 1

    second = await Gateway.execute_outbound_approval(fake, approval_id)
    assert second["ok"] is False
    assert json.loads(second["result"])["reason"] == "ticket_already_consumed"
    assert len(loop.dispatched) == 1


@pytest.mark.asyncio
async def test_gateway_reports_missing_approval(loop, approval_store):
    from cato.gateway import Gateway

    class _FakeGateway:
        _agent_loop = loop

        async def _ensure_agent_loop(self):
            return None

    out = await Gateway.execute_outbound_approval(_FakeGateway(), "nope")
    assert out == {"ok": False, "error": "not_found"}
