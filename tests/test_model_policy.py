"""
Tests for the deterministic, enforceable model-routing policy.

No live Anthropic API call is made anywhere in this file — the client is driven
through an injected fake transport.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from cato.anthropic_client import (
    AnthropicAPIError,
    AnthropicDirectClient,
    ConflictRequiresResolution,
    RetryClass,
    classify_status,
)
from cato.model_policy import (
    MAX_ESCALATIONS,
    MODEL_REGISTRY,
    RETIRED_MODEL_IDS,
    CostGateExceeded,
    EscalationExhausted,
    EscalationTrigger,
    FinancialContext,
    ModelSelectionOverrideRejected,
    ModelTier,
    RiskBand,
    TaskDescriptor,
    TaskType,
    ThinkingMode,
    actual_cost_from_usage,
    build_request_payload,
    escalate,
    project_worst_case_cost,
    route,
    strip_model_selection_args,
    trigger_for_stop_reason,
)

TODAY = date(2026, 8, 3)


class _TestVault:
    """Explicit value-only test seam; production still requires encrypted Vault."""

    def __init__(self) -> None:
        self.value = uuid4().hex

    def get(self, key: str):
        return self.value if key == "ANTHROPIC_API_KEY" else None


# ---------------------------------------------------------------------------
# 1-6. Representative E4L accounting routing cases
# ---------------------------------------------------------------------------


def test_high_volume_invoice_line_extraction_routes_to_haiku():
    """Mechanical, non-material, non-posting extraction -> cheapest tier."""
    d = TaskDescriptor(
        task_type=TaskType.INVOICE_LINE_EXTRACTION,
        financial=FinancialContext(amount_usd=0.0, materiality_threshold_usd=1_000.0),
        input_tokens=12_000,
        max_output_tokens=4_096,
        task_key="e4l:invoice-batch",
    )
    decision = route(d, when=TODAY)
    assert decision.model_id == "claude-haiku-4-5"
    assert decision.tier is ModelTier.HAIKU
    # Haiku does not support output_config.effort at all.
    assert decision.effort is None
    assert decision.thinking_mode is ThinkingMode.BUDGET_TOKENS
    assert decision.supports_interleaved_thinking is False


def test_routine_reconciliation_and_tool_use_route_to_sonnet():
    recon = route(
        TaskDescriptor(
            task_type=TaskType.RECONCILIATION_ANALYSIS,
            financial=FinancialContext(amount_usd=250.0, materiality_threshold_usd=1_000.0),
            input_tokens=30_000,
            max_output_tokens=8_192,
            task_key="e4l:recon",
        ),
        when=TODAY,
    )
    assert recon.model_id == "claude-sonnet-5"
    assert recon.tier is ModelTier.SONNET
    assert recon.effort == "medium"

    tooling = route(
        TaskDescriptor(
            task_type=TaskType.GENERAL_TOOL_USE,
            input_tokens=20_000,
            max_output_tokens=8_192,
            requires_tools=True,
            requires_interleaved_thinking=True,
            task_key="e4l:tools",
        ),
        when=TODAY,
    )
    assert tooling.model_id == "claude-sonnet-5"


@pytest.mark.parametrize(
    "task_type",
    [
        TaskType.FINANCIAL_REASONING,
        TaskType.POLICY_INTERPRETATION,
        TaskType.AUDIT_SYNTHESIS,
    ],
)
def test_high_risk_financial_work_routes_to_opus(task_type):
    decision = route(
        TaskDescriptor(
            task_type=task_type,
            financial=FinancialContext(
                amount_usd=48_500.00,
                account="2100-Accrued-Liabilities",
                materiality_threshold_usd=5_000.0,
            ),
            input_tokens=60_000,
            max_output_tokens=16_000,
            cost_ceiling_usd=10.0,
            task_key=f"e4l:{task_type.value}",
        ),
        when=TODAY,
    )
    assert decision.model_id == "claude-opus-5"
    assert decision.tier is ModelTier.OPUS
    assert decision.risk_band is RiskBand.HIGH
    assert decision.effort in {"high", "max"}


def test_material_ledger_posting_decision_routes_to_opus_at_max_effort():
    """Material amount + posts to ledger + locked period -> CRITICAL."""
    decision = route(
        TaskDescriptor(
            task_type=TaskType.LEDGER_POSTING_DECISION,
            financial=FinancialContext(
                amount_usd=125_000.00,
                account="4000-Revenue",
                materiality_threshold_usd=5_000.0,
                posts_to_ledger=True,
                period_locked=True,
            ),
            input_tokens=40_000,
            max_output_tokens=16_000,
            posts_to_ledger=True,
            cost_ceiling_usd=10.0,
            task_key="e4l:posting",
        ),
        when=TODAY,
    )
    assert decision.risk_band is RiskBand.CRITICAL
    assert decision.model_id == "claude-opus-5"
    assert decision.effort == "max"


def test_oversized_context_rules_out_haiku_200k_window():
    """A cheap task type still cannot use Haiku past its 200k context window."""
    small = route(
        TaskDescriptor(
            task_type=TaskType.DOCUMENT_CLASSIFICATION,
            input_tokens=150_000,
            max_output_tokens=4_096,
        ),
        when=TODAY,
    )
    assert small.model_id == "claude-haiku-4-5"

    oversized = route(
        TaskDescriptor(
            task_type=TaskType.DOCUMENT_CLASSIFICATION,
            input_tokens=350_000,          # exceeds Haiku's 200k window
            max_output_tokens=4_096,
            cost_ceiling_usd=10.0,
        ),
        when=TODAY,
    )
    assert oversized.model_id == "claude-sonnet-5"
    assert any("context_window" in c for c in oversized.constraints_applied)


def test_interleaved_thinking_requirement_rules_out_haiku():
    """Haiku 4.5 has no interleaved thinking between tool calls."""
    decision = route(
        TaskDescriptor(
            task_type=TaskType.INVOICE_LINE_EXTRACTION,
            input_tokens=5_000,
            max_output_tokens=4_096,
            requires_tools=True,
            requires_interleaved_thinking=True,
        ),
        when=TODAY,
    )
    assert decision.model_id == "claude-sonnet-5"
    assert "interleaved_thinking_required:excludes_haiku" in decision.constraints_applied


def test_validator_failure_escalates_tier_exactly_once():
    base = TaskDescriptor(
        task_type=TaskType.RECONCILIATION_ANALYSIS,
        input_tokens=20_000,
        max_output_tokens=8_192,
        cost_ceiling_usd=10.0,
        task_key="e4l:recon-escalate",
    )
    first = route(base, when=TODAY)
    assert first.model_id == "claude-sonnet-5"
    assert first.escalation_level == 0

    escalated_descriptor = escalate(base, EscalationTrigger.ARITHMETIC_CHECK_FAILED)
    second = route(escalated_descriptor, when=TODAY)
    assert second.model_id == "claude-opus-5"
    assert second.escalation_level == 1
    assert "escalation:+1" in second.constraints_applied


# ---------------------------------------------------------------------------
# Enforceability — a model-supplied argument cannot downgrade selection
# ---------------------------------------------------------------------------


def test_model_supplied_args_cannot_downgrade_model_selection():
    """A model emitting `use_model`/`model`/`tier` cannot weaken the choice.

    Precedent: a model-supplied `_approval_granted` argument was a live
    privilege-escalation bypass in this repo's approval gate.  Same shape,
    same answer: model output is data, never configuration.
    """
    hostile_tool_args = {
        "invoice_id": "INV-9001",
        "model": "claude-haiku-4-5",
        "use_model": "claude-haiku-4-5",
        "_model": "claude-haiku-4-5",
        "Model": "claude-haiku-4-5",
        "tier": "haiku",
        "model_tier": "HAIKU",
        "downgrade_to": "claude-haiku-4-5",
        "escalation_level": 0,
        "effort": "low",
        "max_tokens": 16,
        "cost_ceiling_usd": 0.0,
        "risk_band": "NONE",
    }

    # 1. Scrubbing strips every override key, keeping only real payload.
    clean = strip_model_selection_args(hostile_tool_args)
    assert clean == {"invoice_id": "INV-9001"}

    # 2. Descriptors are built by code from real financial facts.
    descriptor = TaskDescriptor(
        task_type=TaskType.LEDGER_POSTING_DECISION,
        financial=FinancialContext(
            amount_usd=90_000.0,
            materiality_threshold_usd=5_000.0,
            posts_to_ledger=True,
        ),
        input_tokens=10_000,
        max_output_tokens=8_192,
        cost_ceiling_usd=10.0,
    )
    decision = route(descriptor, when=TODAY)
    assert decision.model_id == "claude-opus-5"

    # 3. route() takes no model argument at all — there is no parameter to pass.
    with pytest.raises(TypeError):
        route(descriptor, model="claude-haiku-4-5")  # type: ignore[call-arg]

    # 4. Feeding the hostile args into descriptor construction is rejected.
    with pytest.raises(ModelSelectionOverrideRejected):
        TaskDescriptor.build(
            task_type=TaskType.LEDGER_POSTING_DECISION,
            **{"model": "claude-haiku-4-5", "tier": "haiku"},
        )

    # 5. Even a hand-forged descriptor cannot go below the risk floor: the risk
    #    band comes from the financial facts, and the floor is applied last.
    forced_cheap = TaskDescriptor(
        task_type=TaskType.INVOICE_LINE_EXTRACTION,   # cheapest task type
        financial=FinancialContext(
            amount_usd=90_000.0,
            materiality_threshold_usd=5_000.0,
            posts_to_ledger=True,
        ),
        input_tokens=1_000,
        max_output_tokens=1_024,
        cost_ceiling_usd=10.0,
    )
    assert route(forced_cheap, when=TODAY).model_id == "claude-opus-5"


def test_route_rejects_non_descriptor_input():
    with pytest.raises(ModelSelectionOverrideRejected):
        route({"task_type": "invoice_line_extraction", "model": "claude-haiku-4-5"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Escalation terminates
# ---------------------------------------------------------------------------


def test_escalation_terminates_at_stated_maximum_and_cannot_loop():
    d = TaskDescriptor(
        task_type=TaskType.RECONCILIATION_ANALYSIS,
        input_tokens=1_000,
        max_output_tokens=2_048,
        cost_ceiling_usd=10.0,
        task_key="e4l:loop-guard",
    )
    levels = []
    for _ in range(MAX_ESCALATIONS):
        d = escalate(d, EscalationTrigger.SCHEMA_VALIDATION_FAILED)
        levels.append(d.escalation_level)
    assert levels == list(range(1, MAX_ESCALATIONS + 1))

    with pytest.raises(EscalationExhausted):
        escalate(d, EscalationTrigger.SCHEMA_VALIDATION_FAILED)

    # And an unbounded loop would raise rather than spin forever.
    with pytest.raises(EscalationExhausted):
        for _ in range(10_000):
            d = escalate(d, EscalationTrigger.SCHEMA_VALIDATION_FAILED)

    # Tier never exceeds Opus even at the cap — Fable 5 is operator-only.
    capped = route(
        TaskDescriptor(
            task_type=TaskType.AUDIT_SYNTHESIS,
            input_tokens=1_000,
            max_output_tokens=2_048,
            escalation_level=MAX_ESCALATIONS,
            cost_ceiling_usd=10.0,
        ),
        when=TODAY,
    )
    assert capped.model_id == "claude-opus-5"


def test_escalation_requires_a_deterministic_trigger_not_self_reported_confidence():
    d = TaskDescriptor(task_type=TaskType.GENERAL_TOOL_USE)
    with pytest.raises(ValueError):
        escalate(d, "the model said it was only 40% confident")  # type: ignore[arg-type]


def test_stop_reason_maps_to_escalation_triggers():
    assert trigger_for_stop_reason("refusal") is EscalationTrigger.STOP_REASON_REFUSAL
    assert trigger_for_stop_reason("max_tokens") is EscalationTrigger.STOP_REASON_MAX_TOKENS
    assert (
        trigger_for_stop_reason("model_context_window_exceeded")
        is EscalationTrigger.STOP_REASON_CONTEXT_EXCEEDED
    )
    assert trigger_for_stop_reason("end_turn") is None
    assert trigger_for_stop_reason(None) is None


# ---------------------------------------------------------------------------
# Cost controls
# ---------------------------------------------------------------------------


def test_projected_cost_computed_pre_call_and_gates_dispatch():
    # 200k input + 128k output on Opus 5 ($5 / $25 per MTok)
    projected = project_worst_case_cost("claude-opus-5", 200_000, 128_000, TODAY)
    assert projected == pytest.approx(200_000 / 1e6 * 5.0 + 128_000 / 1e6 * 25.0)
    assert projected == pytest.approx(4.2)

    with pytest.raises(CostGateExceeded) as excinfo:
        route(
            TaskDescriptor(
                task_type=TaskType.AUDIT_SYNTHESIS,
                financial=FinancialContext(
                    amount_usd=1_000_000.0, materiality_threshold_usd=5_000.0
                ),
                input_tokens=200_000,
                max_output_tokens=128_000,
                cost_ceiling_usd=1.00,       # deliberately tight
            ),
            when=TODAY,
        )
    assert excinfo.value.ceiling_usd == 1.00
    assert excinfo.value.projected_usd == pytest.approx(4.2)
    assert excinfo.value.model_id == "claude-opus-5"

    # The gate BLOCKS dispatch; it never downgrades the model to fit the budget.
    permitted = route(
        TaskDescriptor(
            task_type=TaskType.AUDIT_SYNTHESIS,
            financial=FinancialContext(
                amount_usd=1_000_000.0, materiality_threshold_usd=5_000.0
            ),
            input_tokens=200_000,
            max_output_tokens=128_000,
            cost_ceiling_usd=5.00,
        ),
        when=TODAY,
    )
    assert permitted.model_id == "claude-opus-5"
    assert permitted.projected_cost_usd == pytest.approx(4.2)


def test_sonnet_intro_pricing_expires_2026_09_01():
    """The cost model carries the price-change date, not just today's price."""
    intro = project_worst_case_cost("claude-sonnet-5", 1_000_000, 1_000_000, date(2026, 8, 31))
    assert intro == pytest.approx(2.0 + 10.0)

    list_price = project_worst_case_cost(
        "claude-sonnet-5", 1_000_000, 1_000_000, date(2026, 9, 1)
    )
    assert list_price == pytest.approx(3.0 + 15.0)

    later = project_worst_case_cost(
        "claude-sonnet-5", 1_000_000, 1_000_000, date(2027, 1, 1)
    )
    assert later == pytest.approx(18.0)


def test_actual_cost_read_from_usage_fields():
    cost = actual_cost_from_usage(
        "claude-opus-5",
        {
            "input_tokens": 100_000,
            "output_tokens": 10_000,
            "cache_creation_input_tokens": 20_000,
            "cache_read_input_tokens": 500_000,
        },
        TODAY,
    )
    expected = (
        100_000 / 1e6 * 5.0
        + 20_000 / 1e6 * 5.0 * 1.25
        + 500_000 / 1e6 * 5.0 * 0.10
        + 10_000 / 1e6 * 25.0
    )
    assert cost == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Registry facts and call shapes
# ---------------------------------------------------------------------------


def test_registry_encodes_hard_capability_facts():
    haiku = MODEL_REGISTRY["claude-haiku-4-5"]
    assert haiku.context_window == 200_000
    assert haiku.max_output_tokens == 64_000
    assert haiku.supports_effort is False
    assert haiku.supports_interleaved_thinking is False
    assert haiku.thinking_mode is ThinkingMode.BUDGET_TOKENS

    for mid in ("claude-sonnet-5", "claude-opus-5", "claude-fable-5"):
        spec = MODEL_REGISTRY[mid]
        assert spec.context_window == 1_000_000
        assert spec.max_output_tokens == 128_000
        assert spec.supports_effort is True
        assert spec.thinking_mode is ThinkingMode.ADAPTIVE

    assert "claude-opus-4-1-20250805" in RETIRED_MODEL_IDS
    assert not any(m in MODEL_REGISTRY for m in RETIRED_MODEL_IDS)


def test_haiku_payload_omits_effort_and_uses_budget_tokens():
    decision = route(
        TaskDescriptor(
            task_type=TaskType.FIELD_NORMALIZATION,
            input_tokens=2_000,
            max_output_tokens=4_096,
        ),
        when=TODAY,
    )
    payload = build_request_payload(decision, [{"role": "user", "content": "x"}])
    assert payload["model"] == "claude-haiku-4-5"
    assert "output_config" not in payload
    assert payload["thinking"]["type"] == "enabled"
    assert payload["thinking"]["budget_tokens"] >= 1024
    assert payload["max_tokens"] == 4_096   # the only HARD cost cap


def test_opus_payload_uses_adaptive_thinking_and_effort():
    decision = route(
        TaskDescriptor(
            task_type=TaskType.FINANCIAL_REASONING,
            financial=FinancialContext(amount_usd=50_000.0, materiality_threshold_usd=1_000.0),
            input_tokens=2_000,
            max_output_tokens=8_192,
            cost_ceiling_usd=10.0,
        ),
        when=TODAY,
    )
    payload = build_request_payload(decision, [{"role": "user", "content": "x"}])
    assert payload["model"] == "claude-opus-5"
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"]["effort"] in {"high", "max"}


def test_effort_is_fixed_per_task_and_risk_so_caching_is_not_invalidated():
    """Changing effort between requests invalidates prompt caching, so effort
    must be a pure function of the descriptor, not of turn number."""
    d = TaskDescriptor(
        task_type=TaskType.RECONCILIATION_ANALYSIS,
        input_tokens=5_000,
        max_output_tokens=4_096,
        cost_ceiling_usd=10.0,
    )
    efforts = {route(d, when=TODAY).effort for _ in range(5)}
    assert efforts == {"medium"}


# ---------------------------------------------------------------------------
# Decision logging
# ---------------------------------------------------------------------------


def test_every_decision_logs_model_rule_and_why():
    decision = route(
        TaskDescriptor(
            task_type=TaskType.LEDGER_POSTING_DECISION,
            financial=FinancialContext(
                amount_usd=75_000.0,
                account="1200-AR",
                materiality_threshold_usd=5_000.0,
                posts_to_ledger=True,
            ),
            input_tokens=30_000,
            max_output_tokens=8_192,
            cost_ceiling_usd=10.0,
            task_key="e4l:audit",
        ),
        when=TODAY,
    )
    rec = decision.log_record()
    assert rec["model"] == "claude-opus-5"
    assert rec["rule"]                       # which rule fired
    assert "risk band HIGH" in rec["why"]    # why it fired
    assert rec["task_type"] == "ledger_posting_decision"
    assert rec["risk_band"] == "HIGH"
    assert rec["projected_cost_usd"] > 0
    assert rec["cost_ceiling_usd"] > 0
    assert rec["priced_on"] == "2026-08-03"

    line = decision.log_line()
    for token in ("model=claude-opus-5", "rule=", "risk=HIGH", "projected_cost=$", "why="):
        assert token in line


# ---------------------------------------------------------------------------
# Retry contract (no live API calls — fake transport only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        (429, RetryClass.RETRYABLE),
        (500, RetryClass.RETRYABLE),
        (504, RetryClass.RETRYABLE),
        (529, RetryClass.RETRYABLE),
        (400, RetryClass.NOT_RETRYABLE),
        (401, RetryClass.NOT_RETRYABLE),
        (402, RetryClass.NOT_RETRYABLE),
        (403, RetryClass.NOT_RETRYABLE),
        (404, RetryClass.NOT_RETRYABLE),
        (413, RetryClass.NOT_RETRYABLE),
        (409, RetryClass.CONDITIONAL),
    ],
)
def test_retry_contract_classification(status, expected):
    assert classify_status(status).retry_class is expected


@pytest.mark.asyncio
async def test_client_ignores_process_environment_and_fails_closed(monkeypatch):
    process_value = uuid4().hex
    monkeypatch.setenv("ANTHROPIC_API_KEY", process_value)
    client = AnthropicDirectClient(vault=None)
    decision = route(
        TaskDescriptor(
            task_type=TaskType.GENERAL_TOOL_USE,
            input_tokens=1,
            max_output_tokens=64,
            cost_ceiling_usd=10.0,
        ),
        when=TODAY,
    )

    assert client.has_credentials() is False
    with pytest.raises(AnthropicAPIError) as caught:
        await client.call(decision, [])
    assert process_value not in str(caught.value)


async def test_client_retries_429_then_succeeds_without_live_api_call():
    calls: list[dict] = []

    async def fake_transport(url, payload, headers):
        calls.append(payload)
        if len(calls) == 1:
            return 429, {"error": {"type": "rate_limit_error"}}, {"retry-after": "0"}
        return 200, {
            "model": payload["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "reconciled"}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }, {}

    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    client = AnthropicDirectClient(
        vault=_TestVault(), transport=fake_transport, sleep=fake_sleep
    )
    decision = route(
        TaskDescriptor(task_type=TaskType.GENERAL_TOOL_USE, input_tokens=100,
                       max_output_tokens=1_024, cost_ceiling_usd=10.0),
        when=TODAY,
    )
    import os

    os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
    try:
        result = await client.call(decision, [{"role": "user", "content": "hi"}])
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)

    assert result.text == "reconciled"
    assert result.attempts == 2
    assert slept == [0.0]
    # The key is never echoed into the result or the payload.
    assert "test-key-not-real" not in str(result.message)


@pytest.mark.asyncio
async def test_client_does_not_retry_400_and_flags_409_as_conditional(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    decision = route(
        TaskDescriptor(task_type=TaskType.GENERAL_TOOL_USE, input_tokens=10,
                       max_output_tokens=512, cost_ceiling_usd=10.0),
        when=TODAY,
    )

    attempts = {"n": 0}

    async def bad_request(url, payload, headers):
        attempts["n"] += 1
        return 400, {"error": {"type": "invalid_request_error"}}, {}

    client = AnthropicDirectClient(vault=_TestVault(), transport=bad_request)
    with pytest.raises(AnthropicAPIError):
        await client.call(decision, [{"role": "user", "content": "hi"}])
    assert attempts["n"] == 1, "400 invalid_request_error must not be retried"

    async def conflict(url, payload, headers):
        return 409, {"error": {"type": "conflict_error"}}, {}

    client2 = AnthropicDirectClient(vault=_TestVault(), transport=conflict)
    with pytest.raises(ConflictRequiresResolution):
        await client2.call(decision, [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_stop_reason_refusal_escalates_exactly_once_then_succeeds(monkeypatch):
    """A 200 response can still be a failure — stop_reason drives escalation."""
    from cato.router import ModelRouter

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen_models: list[str] = []

    async def fake_transport(url, payload, headers):
        seen_models.append(payload["model"])
        if len(seen_models) == 1:
            return 200, {
                "model": payload["model"],
                "stop_reason": "refusal",
                "content": [],
                "usage": {"input_tokens": 10, "output_tokens": 0},
            }, {}
        return 200, {
            "model": payload["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "done"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }, {}

    router = ModelRouter(
        vault=None,
        anthropic_client=AnthropicDirectClient(vault=_TestVault(), transport=fake_transport),
    )
    model, message, decision = await router.complete_message(
        [{"role": "user", "content": "reconcile"}],
        TaskDescriptor(
            task_type=TaskType.RECONCILIATION_ANALYSIS,
            input_tokens=10,
            max_output_tokens=1_024,
            cost_ceiling_usd=10.0,
            task_key="e4l:refusal",
        ),
        when=TODAY,
    )
    assert seen_models == ["claude-sonnet-5", "claude-opus-5"]
    assert model == "claude-opus-5"
    assert decision.escalation_level == 1
    assert message["content"] == "done"


@pytest.mark.asyncio
async def test_persistent_refusal_stops_at_the_escalation_cap(monkeypatch):
    from cato.router import ModelRouter

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen: list[str] = []

    async def always_refuse(url, payload, headers):
        seen.append(payload["model"])
        return 200, {
            "model": payload["model"],
            "stop_reason": "refusal",
            "content": [],
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }, {}

    router = ModelRouter(
        vault=None,
        anthropic_client=AnthropicDirectClient(vault=_TestVault(), transport=always_refuse),
    )
    with pytest.raises(EscalationExhausted):
        await router.complete_message(
            [{"role": "user", "content": "x"}],
            TaskDescriptor(
                task_type=TaskType.RECONCILIATION_ANALYSIS,
                input_tokens=1,
                max_output_tokens=512,
                cost_ceiling_usd=10.0,
                task_key="e4l:always-refuse",
            ),
            when=TODAY,
        )
    # Bounded: initial call + MAX_ESCALATIONS retries, then it stops.
    assert len(seen) == MAX_ESCALATIONS + 1
