"""
cato/model_policy.py — Deterministic, enforceable model-routing policy.

This module is the SINGLE source of truth for which Anthropic model executes a
given task.  It is policy-as-data, not prose:

  * ``MODEL_REGISTRY``   — hard capability + pricing facts per model.
  * ``ROUTING_TABLE``    — (task_type, risk_band) -> tier, keyed only on facts
                           knowable BEFORE the call.
  * ``route()``          — pure function; the ONLY way to pick a model.
  * ``escalate()``       — bounded tier escalation driven by deterministic
                           validators and ``stop_reason`` — never by a model's
                           self-reported confidence (the API exposes no such
                           signal, and self-assessment is model whim).

ENFORCEABILITY
--------------
Model selection is computed by code from a :class:`TaskDescriptor` built by the
caller *before* the request is dispatched.  Nothing the model emits — text,
tool arguments, JSON — can influence it.  ``TaskDescriptor`` rejects any
model-selection field, and :func:`strip_model_selection_args` scrubs
model-supplied tool arguments of every known override key.

Precedent: a model-supplied ``_approval_granted`` argument was a live
privilege-escalation bypass in this repo's approval gate.  The same shape is
forbidden here.

COST
----
``effort`` and ``task_budget`` are explicitly SOFT hints in the Anthropic API,
not caps.  The only HARD per-request ceilings are ``max_tokens`` and
``stop_sequences``.  Budget enforcement therefore computes a worst-case cost
ceiling BEFORE dispatch (input tokens x input rate + max_tokens x output rate)
and gates on it; ``max_tokens`` is what actually bounds spend.

Pricing carries the Sonnet 5 introductory-price expiry (2026-09-01) as data,
not as "today's price".
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional

# ---------------------------------------------------------------------------
# Model registry — verified capability + pricing facts
# ---------------------------------------------------------------------------


class ModelTier(Enum):
    """Ordered capability tiers.  ``value`` is the ordering key."""

    HAIKU = 1
    SONNET = 2
    OPUS = 3
    FABLE = 4

    def __lt__(self, other: "ModelTier") -> bool:
        return self.value < other.value

    def __le__(self, other: "ModelTier") -> bool:
        return self.value <= other.value


class Provider(Enum):
    """Which API a model is called through."""

    ANTHROPIC = "anthropic"


class ThinkingMode(Enum):
    """Which thinking call-shape a model requires.  These are NOT equivalent."""

    ADAPTIVE = "adaptive"          # thinking: {"type": "adaptive"}
    BUDGET_TOKENS = "budget_tokens"  # thinking: {"type": "enabled", "budget_tokens": N}


@dataclass(frozen=True)
class PriceBand:
    """Per-MTok USD rates effective from ``effective_from`` (inclusive)."""

    effective_from: date
    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class ModelSpec:
    """Hard facts about one model.  No `-latest` aliases exist; ids are pinned."""

    model_id: str
    tier: ModelTier
    context_window: int
    max_output_tokens: int
    prices: tuple[PriceBand, ...]
    supports_effort: bool
    thinking_mode: ThinkingMode
    supports_interleaved_thinking: bool
    rate_limit_note: str = ""
    #: Model execution is direct Anthropic only.
    provider: Provider = Provider.ANTHROPIC

    def price_at(self, when: date) -> PriceBand:
        """Return the price band in force on ``when`` (latest one <= when)."""
        applicable = [p for p in self.prices if p.effective_from <= when]
        if not applicable:
            return self.prices[0]
        return max(applicable, key=lambda p: p.effective_from)


#: Sonnet 5 introductory pricing ends 2026-08-31; list rates apply from 09-01.
SONNET_INTRO_PRICE_ENDS = date(2026, 8, 31)

MODEL_REGISTRY: dict[str, ModelSpec] = {
    "claude-haiku-4-5": ModelSpec(
        model_id="claude-haiku-4-5",
        tier=ModelTier.HAIKU,
        context_window=200_000,
        max_output_tokens=64_000,
        prices=(PriceBand(date(2000, 1, 1), 1.00, 5.00),),
        # Haiku 4.5 does NOT support output_config.effort at all, does NOT
        # support adaptive thinking, and does NOT support interleaved thinking
        # between tool calls.  It is a structurally different call shape.
        supports_effort=False,
        thinking_mode=ThinkingMode.BUDGET_TOKENS,
        supports_interleaved_thinking=False,
    ),
    "claude-sonnet-5": ModelSpec(
        model_id="claude-sonnet-5",
        tier=ModelTier.SONNET,
        context_window=1_000_000,
        max_output_tokens=128_000,
        prices=(
            PriceBand(date(2000, 1, 1), 2.00, 10.00),          # introductory
            PriceBand(date(2026, 9, 1), 3.00, 15.00),          # list price
        ),
        supports_effort=True,
        thinking_mode=ThinkingMode.ADAPTIVE,
        supports_interleaved_thinking=True,
    ),
    "claude-opus-5": ModelSpec(
        model_id="claude-opus-5",
        tier=ModelTier.OPUS,
        context_window=1_000_000,
        max_output_tokens=128_000,
        prices=(PriceBand(date(2000, 1, 1), 5.00, 25.00),),
        supports_effort=True,
        thinking_mode=ThinkingMode.ADAPTIVE,
        supports_interleaved_thinking=True,
    ),
    "claude-fable-5": ModelSpec(
        model_id="claude-fable-5",
        tier=ModelTier.FABLE,
        context_window=1_000_000,
        max_output_tokens=128_000,
        prices=(PriceBand(date(2000, 1, 1), 10.00, 50.00),),
        supports_effort=True,
        thinking_mode=ThinkingMode.ADAPTIVE,
        supports_interleaved_thinking=True,
        rate_limit_note="~4x tighter rate limits than Opus 5",
    ),
}

#: Retired — must never be selected.  Retired 2026-08-05.
RETIRED_MODEL_IDS: frozenset[str] = frozenset({
    "claude-opus-4-1-20250805",
    "claude-opus-4-1",
})

TIER_TO_MODEL: dict[ModelTier, str] = {
    ModelTier.HAIKU: "claude-haiku-4-5",
    ModelTier.SONNET: "claude-sonnet-5",
    ModelTier.OPUS: "claude-opus-5",
    ModelTier.FABLE: "claude-fable-5",
}

#: Direct-Anthropic candidates.  Stored credentials for any other provider do
#: not participate in model selection.
TIER_CANDIDATES: dict[ModelTier, tuple[str, ...]] = {
    ModelTier.HAIKU: ("claude-haiku-4-5",),
    ModelTier.SONNET: ("claude-sonnet-5",),
    ModelTier.OPUS: ("claude-opus-5",),
    ModelTier.FABLE: ("claude-fable-5",),
}

#: Fable 5 is never auto-selected — cost and rate limits make it an explicit,
#: operator-only choice.  Escalation therefore terminates at OPUS.
MAX_AUTO_TIER = ModelTier.OPUS


def select_cheapest_candidate(
    tier: ModelTier,
    available_providers: frozenset[Provider],
    input_tokens: int,
    max_output_tokens: int,
    when: Optional[date] = None,
) -> str:
    """Return the direct-Anthropic model pinned for ``tier``.

    ``available_providers`` remains in the signature for compatibility with
    existing callers, but it cannot broaden the provider set.
    """
    del available_providers, input_tokens, max_output_tokens, when
    return TIER_CANDIDATES[tier][0]


# ---------------------------------------------------------------------------
# Task taxonomy — declared attributes, all knowable BEFORE the call
# ---------------------------------------------------------------------------


class TaskType(Enum):
    """Declared task type.  Chosen by the caller, never by the model."""

    # High-volume mechanical extraction / classification
    INVOICE_LINE_EXTRACTION = "invoice_line_extraction"
    DOCUMENT_CLASSIFICATION = "document_classification"
    FIELD_NORMALIZATION = "field_normalization"

    # Routine analysis and tool-driven work
    RECONCILIATION_ANALYSIS = "reconciliation_analysis"
    GENERAL_TOOL_USE = "general_tool_use"
    DRAFT_CORRESPONDENCE = "draft_correspondence"
    SESSION_COMPACTION = "session_compaction"

    # High-stakes reasoning
    FINANCIAL_REASONING = "financial_reasoning"
    POLICY_INTERPRETATION = "policy_interpretation"
    AUDIT_SYNTHESIS = "audit_synthesis"
    LEDGER_POSTING_DECISION = "ledger_posting_decision"


class RiskBand(Enum):
    """Deterministic financial-risk band.  Ordered; ``value`` is the key."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


#: Risk band alone sets an absolute FLOOR on capability.  A task type can raise
#: the tier above this floor but can never lower it.
RISK_FLOOR: dict[RiskBand, ModelTier] = {
    RiskBand.NONE: ModelTier.HAIKU,
    RiskBand.LOW: ModelTier.HAIKU,
    RiskBand.MEDIUM: ModelTier.SONNET,
    RiskBand.HIGH: ModelTier.OPUS,
    RiskBand.CRITICAL: ModelTier.OPUS,
}

#: Base tier per declared task type.  Static table — not a model's opinion.
TASK_BASE_TIER: dict[TaskType, ModelTier] = {
    TaskType.INVOICE_LINE_EXTRACTION: ModelTier.HAIKU,
    TaskType.DOCUMENT_CLASSIFICATION: ModelTier.HAIKU,
    TaskType.FIELD_NORMALIZATION: ModelTier.HAIKU,
    TaskType.RECONCILIATION_ANALYSIS: ModelTier.SONNET,
    TaskType.GENERAL_TOOL_USE: ModelTier.SONNET,
    TaskType.DRAFT_CORRESPONDENCE: ModelTier.SONNET,
    TaskType.SESSION_COMPACTION: ModelTier.SONNET,
    TaskType.FINANCIAL_REASONING: ModelTier.OPUS,
    TaskType.POLICY_INTERPRETATION: ModelTier.OPUS,
    TaskType.AUDIT_SYNTHESIS: ModelTier.OPUS,
    TaskType.LEDGER_POSTING_DECISION: ModelTier.OPUS,
}

#: Effort is the PRIMARY control (Anthropic guidance: "Tuning effort is often a
#: better lever than switching models").  Fixed per task type + risk so it stays
#: constant across a conversation — changing effort between requests INVALIDATES
#: prompt caching, which is a real cost trap.
TASK_EFFORT: dict[TaskType, str] = {
    TaskType.INVOICE_LINE_EXTRACTION: "low",
    TaskType.DOCUMENT_CLASSIFICATION: "low",
    TaskType.FIELD_NORMALIZATION: "low",
    TaskType.RECONCILIATION_ANALYSIS: "medium",
    TaskType.GENERAL_TOOL_USE: "medium",
    TaskType.DRAFT_CORRESPONDENCE: "medium",
    TaskType.SESSION_COMPACTION: "medium",
    TaskType.FINANCIAL_REASONING: "high",
    TaskType.POLICY_INTERPRETATION: "high",
    TaskType.AUDIT_SYNTHESIS: "high",
    TaskType.LEDGER_POSTING_DECISION: "max",
}

#: Risk band raises effort but never lowers it.
RISK_MIN_EFFORT: dict[RiskBand, str] = {
    RiskBand.NONE: "low",
    RiskBand.LOW: "low",
    RiskBand.MEDIUM: "medium",
    RiskBand.HIGH: "high",
    RiskBand.CRITICAL: "max",
}

_EFFORT_ORDER: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")


def _max_effort(a: str, b: str) -> str:
    return a if _EFFORT_ORDER.index(a) >= _EFFORT_ORDER.index(b) else b


# ---------------------------------------------------------------------------
# Financial context -> risk band (fully deterministic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FinancialContext:
    """Deterministic financial-risk inputs.  All knowable before the call."""

    amount_usd: float = 0.0
    account: str = ""
    materiality_threshold_usd: float = 1_000.0
    posts_to_ledger: bool = False
    period_locked: bool = False

    def amount_is_readable(self) -> bool:
        """True when ``amount_usd`` is a finite number we can reason about."""
        import math

        if isinstance(self.amount_usd, bool) or not isinstance(self.amount_usd, (int, float)):
            return False
        return math.isfinite(float(self.amount_usd))

    def risk_band(self) -> RiskBand:
        """Derive the risk band. Pure function of the fields above.

        An amount we cannot read is treated as MATERIAL, never as zero. A
        ``float('nan')`` amount used to make ``abs(amount) >= threshold`` False,
        so an unparseable financial figure came out MEDIUM (or NONE) instead of
        HIGH/CRITICAL — bad finance data quietly bought a cheaper model and a
        lower risk band for exactly the call that most needed the opposite. A
        non-numeric amount raised TypeError out of a "pure function".
        """
        if not self.amount_is_readable():
            # Unknown magnitude on a ledger-posting or locked-period action is
            # the worst case, not the best one.
            if self.period_locked or self.posts_to_ledger:
                return RiskBand.CRITICAL
            return RiskBand.HIGH
        material = abs(self.amount_usd) >= self.materiality_threshold_usd
        if self.period_locked and self.posts_to_ledger:
            return RiskBand.CRITICAL
        if self.posts_to_ledger and material:
            return RiskBand.HIGH
        if material:
            return RiskBand.HIGH
        if self.posts_to_ledger:
            return RiskBand.MEDIUM
        if self.period_locked:
            return RiskBand.MEDIUM
        if abs(self.amount_usd) > 0:
            return RiskBand.LOW
        return RiskBand.NONE


# ---------------------------------------------------------------------------
# Model-supplied argument scrubbing (enforceability)
# ---------------------------------------------------------------------------

#: Every key a model might emit to try to steer its own execution.  None of
#: these are ever honoured.  Compared case-insensitively, ignoring leading
#: underscores, so `_model`, `Model`, and `USE_MODEL` are all caught.
MODEL_SELECTION_ARG_KEYS: frozenset[str] = frozenset({
    "model", "use_model", "model_id", "model_name", "tier", "model_tier",
    "route_to", "routed_model", "preferred_model", "force_model",
    "downgrade", "downgrade_to", "escalate", "escalate_to", "escalation_level",
    "effort", "output_config", "thinking", "max_tokens", "task_budget",
    "risk_band", "task_type", "cost_ceiling_usd", "_model", "_tier",
})


def _normalize_arg_key(key: str) -> str:
    return str(key).lstrip("_").lower()


def strip_model_selection_args(args: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``args`` with every model-selection key removed.

    Applied to any argument dict that originated from a model.  Model output is
    data, never configuration.
    """
    return {
        k: v for k, v in args.items()
        if _normalize_arg_key(k) not in MODEL_SELECTION_ARG_KEYS
    }


class ModelSelectionOverrideRejected(ValueError):
    """Raised when a caller tries to hand model selection to the model."""


# ---------------------------------------------------------------------------
# Task descriptor — the ONLY input to routing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskDescriptor:
    """Pre-call facts about a task.  Built by code, never by a model.

    Every field is knowable *before* the request is dispatched.  There is
    deliberately no ``confidence`` field: the Anthropic API exposes no
    confidence signal (no logprobs, no calibration score), and a model's
    self-reported confidence is model whim.
    """

    task_type: TaskType
    financial: FinancialContext = field(default_factory=FinancialContext)
    #: Token count of the prompt, from token counting — not a guess.
    input_tokens: int = 0
    #: Hard output ceiling for this request.  This is the real cost cap.
    max_output_tokens: int = 4_096
    requires_tools: bool = False
    #: Tool-use work that needs reasoning *between* tool calls.  Rules out Haiku.
    requires_interleaved_thinking: bool = False
    #: Output must post to a ledger.  Forces the risk floor up.
    posts_to_ledger: bool = False
    #: Hard pre-dispatch spend ceiling in USD.  None = use the policy default.
    cost_ceiling_usd: Optional[float] = None
    #: Escalation count so far.  Set only by :func:`escalate`.
    escalation_level: int = 0
    #: Pre-call LOOKUP of prior failures for this task key, fed by post-call
    #: outcomes.  A pre-call fact, not a self-assessment.
    prior_failure_count: int = 0
    #: Free-form correlation key for logging.
    task_key: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.task_type, TaskType):
            raise ModelSelectionOverrideRejected(
                f"task_type must be a TaskType, got {type(self.task_type).__name__}"
            )
        if self.escalation_level < 0:
            raise ValueError("escalation_level must be >= 0")

    @classmethod
    def build(cls, **kwargs: Any) -> "TaskDescriptor":
        """Construct a descriptor, rejecting any model-selection field.

        This is the constructor call sites should use when *any* part of the
        keyword payload could have originated from model output.
        """
        forbidden = sorted(
            k for k in kwargs
            if _normalize_arg_key(k) in MODEL_SELECTION_ARG_KEYS
            and _normalize_arg_key(k) not in {"task_type", "cost_ceiling_usd"}
        )
        if forbidden:
            raise ModelSelectionOverrideRejected(
                "model selection is not caller-controllable; rejected keys: "
                + ", ".join(forbidden)
            )
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------

#: Default hard pre-dispatch ceiling per request, USD.  Deliberately tight:
#: an over-spend is correctable, a wrong financial answer on a ledger is not,
#: so the gate blocks dispatch rather than silently choosing a weaker model.
DEFAULT_COST_CEILING_USD = 2.50

#: Per-risk-band ceilings.  Higher risk buys more headroom, never less model.
RISK_COST_CEILING_USD: dict[RiskBand, float] = {
    RiskBand.NONE: 0.50,
    RiskBand.LOW: 0.50,
    RiskBand.MEDIUM: 1.50,
    RiskBand.HIGH: 5.00,
    RiskBand.CRITICAL: 10.00,
}


class CostGateExceeded(Exception):
    """Projected worst-case cost exceeds the pre-dispatch ceiling."""

    def __init__(self, projected_usd: float, ceiling_usd: float, model_id: str) -> None:
        super().__init__(
            f"projected worst-case cost ${projected_usd:.4f} exceeds ceiling "
            f"${ceiling_usd:.4f} for {model_id}"
        )
        self.projected_usd = projected_usd
        self.ceiling_usd = ceiling_usd
        self.model_id = model_id


def project_worst_case_cost(
    model_id: str,
    input_tokens: int,
    max_output_tokens: int,
    when: Optional[date] = None,
) -> float:
    """Worst-case USD cost: every input token billed, ``max_tokens`` emitted.

    ``max_tokens`` is the only HARD output cap the API offers, so this is a
    true ceiling rather than an estimate.  Note ``max_tokens`` does NOT consume
    the output-token rate limit, so a generous value has no rate-limit cost —
    only a cost-ceiling cost.
    """
    spec = MODEL_REGISTRY[model_id]
    band = spec.price_at(when or datetime.now(timezone.utc).date())
    return (
        (input_tokens / 1_000_000.0) * band.input_per_mtok
        + (max_output_tokens / 1_000_000.0) * band.output_per_mtok
    )


def actual_cost_from_usage(
    model_id: str,
    usage: Mapping[str, Any],
    when: Optional[date] = None,
) -> float:
    """Actual USD cost from an Anthropic response ``usage`` block.

    Cache reads bill at ~0.1x input and cache writes at ~1.25x input.
    """
    spec = MODEL_REGISTRY[model_id]
    band = spec.price_at(when or datetime.now(timezone.utc).date())
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    return (
        (inp / 1_000_000.0) * band.input_per_mtok
        + (cache_write / 1_000_000.0) * band.input_per_mtok * 1.25
        + (cache_read / 1_000_000.0) * band.input_per_mtok * 0.10
        + (out / 1_000_000.0) * band.output_per_mtok
    )


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

#: Hard cap on tier escalations for a single task.  Escalation MUST terminate.
MAX_ESCALATIONS = 2


class EscalationTrigger(Enum):
    """Deterministic escalation triggers.  No self-reported confidence here."""

    STOP_REASON_REFUSAL = "stop_reason:refusal"
    STOP_REASON_MAX_TOKENS = "stop_reason:max_tokens"
    STOP_REASON_CONTEXT_EXCEEDED = "stop_reason:model_context_window_exceeded"
    SCHEMA_VALIDATION_FAILED = "validator:schema_validation_failed"
    ARITHMETIC_CHECK_FAILED = "validator:arithmetic_check_failed"
    RECONCILIATION_IMBALANCE = "validator:reconciliation_imbalance"


#: Anthropic ``stop_reason`` values that map to an escalation trigger.
STOP_REASON_TRIGGERS: dict[str, EscalationTrigger] = {
    "refusal": EscalationTrigger.STOP_REASON_REFUSAL,
    "max_tokens": EscalationTrigger.STOP_REASON_MAX_TOKENS,
    "model_context_window_exceeded": EscalationTrigger.STOP_REASON_CONTEXT_EXCEEDED,
}


class EscalationExhausted(Exception):
    """The escalation cap was reached; the task must fail loudly, not loop."""

    def __init__(self, task_key: str, level: int, trigger: EscalationTrigger) -> None:
        super().__init__(
            f"escalation cap {MAX_ESCALATIONS} reached for task {task_key!r} "
            f"at level {level} (last trigger: {trigger.value})"
        )
        self.task_key = task_key
        self.level = level
        self.trigger = trigger


def trigger_for_stop_reason(stop_reason: Optional[str]) -> Optional[EscalationTrigger]:
    """Map an Anthropic ``stop_reason`` to a trigger, or None."""
    if not stop_reason:
        return None
    return STOP_REASON_TRIGGERS.get(str(stop_reason))


def escalate(descriptor: TaskDescriptor, trigger: EscalationTrigger) -> TaskDescriptor:
    """Return a descriptor one escalation level higher.

    Raises :class:`EscalationExhausted` once the cap is hit — this is what makes
    the loop terminate.  Callers must not catch-and-retry.
    """
    if not isinstance(trigger, EscalationTrigger):
        raise ValueError("escalation must be driven by an EscalationTrigger")
    next_level = descriptor.escalation_level + 1
    if next_level > MAX_ESCALATIONS:
        raise EscalationExhausted(
            descriptor.task_key or "<unkeyed>", descriptor.escalation_level, trigger
        )
    bumped_tokens = descriptor.max_output_tokens
    if trigger is EscalationTrigger.STOP_REASON_MAX_TOKENS:
        bumped_tokens = min(descriptor.max_output_tokens * 2, 128_000)
    return TaskDescriptor(
        task_type=descriptor.task_type,
        financial=descriptor.financial,
        input_tokens=descriptor.input_tokens,
        max_output_tokens=bumped_tokens,
        requires_tools=descriptor.requires_tools,
        requires_interleaved_thinking=descriptor.requires_interleaved_thinking,
        posts_to_ledger=descriptor.posts_to_ledger,
        cost_ceiling_usd=descriptor.cost_ceiling_usd,
        escalation_level=next_level,
        prior_failure_count=descriptor.prior_failure_count,
        task_key=descriptor.task_key,
    )


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDecision:
    """The selected model plus a full, auditable reconstruction of the choice."""

    model_id: str
    tier: ModelTier
    rule_id: str
    reason: str
    effort: Optional[str]
    thinking_mode: ThinkingMode
    thinking_budget_tokens: Optional[int]
    supports_interleaved_thinking: bool
    max_output_tokens: int
    input_tokens: int
    projected_cost_usd: float
    cost_ceiling_usd: float
    risk_band: RiskBand
    task_type: TaskType
    escalation_level: int
    constraints_applied: tuple[str, ...]
    decision_id: str
    priced_on: date
    provider: Provider = Provider.ANTHROPIC

    def log_record(self) -> dict[str, Any]:
        """Structured record — enough to reconstruct the decision offline."""
        return {
            "decision_id": self.decision_id,
            "model": self.model_id,
            "provider": self.provider.value,
            "tier": self.tier.name,
            "rule": self.rule_id,
            "why": self.reason,
            "task_type": self.task_type.value,
            "risk_band": self.risk_band.name,
            "escalation_level": self.escalation_level,
            "constraints_applied": list(self.constraints_applied),
            "effort": self.effort,
            "thinking_mode": self.thinking_mode.value,
            "thinking_budget_tokens": self.thinking_budget_tokens,
            "interleaved_thinking": self.supports_interleaved_thinking,
            "input_tokens": self.input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "projected_cost_usd": round(self.projected_cost_usd, 6),
            "cost_ceiling_usd": round(self.cost_ceiling_usd, 6),
            "priced_on": self.priced_on.isoformat(),
        }

    def log_line(self) -> str:
        """Single-line, auditor-readable explanation of the model choice."""
        return (
            f"[model-route] decision={self.decision_id} model={self.model_id} "
            f"provider={self.provider.value} tier={self.tier.name} rule={self.rule_id} "
            f"task_type={self.task_type.value} risk={self.risk_band.name} "
            f"escalation={self.escalation_level} effort={self.effort} "
            f"constraints={'|'.join(self.constraints_applied) or 'none'} "
            f"projected_cost=${self.projected_cost_usd:.4f} "
            f"ceiling=${self.cost_ceiling_usd:.4f} why=\"{self.reason}\""
        )


def _tier_at_least(a: ModelTier, b: ModelTier) -> ModelTier:
    return a if a.value >= b.value else b


def route(
    descriptor: TaskDescriptor,
    *,
    when: Optional[date] = None,
    enforce_cost_gate: bool = True,
    available_providers: frozenset[Provider] = frozenset({Provider.ANTHROPIC}),
) -> RoutingDecision:
    """Select the model for ``descriptor``.  The ONLY sanctioned selection path.

    Deterministic: same descriptor in, same decision out.  Takes no model
    parameter, accepts no override, and consults nothing the model emitted.

    ``available_providers`` remains only for call compatibility. It cannot
    broaden execution beyond Anthropic; unrelated stored credentials are
    deliberately ignored.

    Raises :class:`CostGateExceeded` when the projected worst-case cost breaches
    the ceiling — dispatch is blocked, the model is never downgraded to fit.
    """
    if not isinstance(descriptor, TaskDescriptor):
        raise ModelSelectionOverrideRejected(
            "route() accepts only a TaskDescriptor built by code"
        )

    priced_on = when or datetime.now(timezone.utc).date()
    constraints: list[str] = []
    rules: list[str] = []

    # --- 1. Risk band: the strongest key, entirely deterministic -----------
    financial = descriptor.financial
    if descriptor.posts_to_ledger and not financial.posts_to_ledger:
        financial = FinancialContext(
            amount_usd=financial.amount_usd,
            account=financial.account,
            materiality_threshold_usd=financial.materiality_threshold_usd,
            posts_to_ledger=True,
            period_locked=financial.period_locked,
        )
    risk = financial.risk_band()
    floor = RISK_FLOOR[risk]
    rules.append(f"RISK-{risk.name}")

    # --- 2. Declared task type -------------------------------------------
    base = TASK_BASE_TIER[descriptor.task_type]
    rules.append(f"TASK-{descriptor.task_type.name}")
    tier = _tier_at_least(base, floor)
    if floor.value > base.value:
        constraints.append(f"risk_floor:{risk.name}->{floor.name}")

    # --- 3. Capability constraints (rule out models that cannot do it) ----
    # Haiku 4.5 has no interleaved thinking between tool calls.
    if descriptor.requires_interleaved_thinking and tier is ModelTier.HAIKU:
        tier = ModelTier.SONNET
        constraints.append("interleaved_thinking_required:excludes_haiku")
        rules.append("CAP-INTERLEAVED")

    # Context window: Haiku is 200k; everything else is 1M.
    projected_context = descriptor.input_tokens + descriptor.max_output_tokens
    haiku_ctx = MODEL_REGISTRY["claude-haiku-4-5"].context_window
    if tier is ModelTier.HAIKU and projected_context > haiku_ctx:
        tier = ModelTier.SONNET
        constraints.append(
            f"context_window:{projected_context}>{haiku_ctx}:excludes_haiku"
        )
        rules.append("CAP-CONTEXT")

    # Output ceiling: Haiku caps at 64k output.
    haiku_out = MODEL_REGISTRY["claude-haiku-4-5"].max_output_tokens
    if tier is ModelTier.HAIKU and descriptor.max_output_tokens > haiku_out:
        tier = ModelTier.SONNET
        constraints.append(f"max_output:{descriptor.max_output_tokens}>{haiku_out}")
        rules.append("CAP-OUTPUT")

    # --- 4. Failure history (pre-call lookup, fed by post-call outcomes) ---
    if descriptor.prior_failure_count >= 2 and tier.value < MAX_AUTO_TIER.value:
        tier = ModelTier(min(tier.value + 1, MAX_AUTO_TIER.value))
        constraints.append(f"prior_failures:{descriptor.prior_failure_count}")
        rules.append("HIST-FAILURES")

    # --- 5. Escalation ----------------------------------------------------
    if descriptor.escalation_level:
        raised = ModelTier(min(tier.value + descriptor.escalation_level,
                               MAX_AUTO_TIER.value))
        if raised.value > tier.value:
            constraints.append(f"escalation:+{descriptor.escalation_level}")
        tier = raised
        rules.append(f"ESC-{descriptor.escalation_level}")

    model_id = select_cheapest_candidate(
        tier, available_providers, descriptor.input_tokens,
        descriptor.max_output_tokens, priced_on,
    )
    if model_id != TIER_TO_MODEL[tier]:
        rules.append("COST-ARBITRAGE")
        constraints.append(f"cheapest_available:{TIER_TO_MODEL[tier]}->{model_id}")
    if model_id in RETIRED_MODEL_IDS:  # pragma: no cover - defensive
        raise RuntimeError(f"retired model selected: {model_id}")
    spec = MODEL_REGISTRY[model_id]

    # --- 6. Effort — the primary control, fixed per conversation ----------
    effort: Optional[str] = None
    thinking_budget: Optional[int] = None
    if spec.supports_effort:
        effort = _max_effort(
            TASK_EFFORT[descriptor.task_type], RISK_MIN_EFFORT[risk]
        )
    else:
        # Haiku uses the older thinking:{type:"enabled",budget_tokens:N} shape
        # and rejects output_config.effort outright.
        constraints.append("haiku:no_effort_param")
        thinking_budget = max(1024, min(descriptor.max_output_tokens // 2,
                                        spec.max_output_tokens - 1))

    max_out = min(descriptor.max_output_tokens, spec.max_output_tokens)

    # --- 7. Cost gate (computed pre-dispatch; blocks, never downgrades) ---
    ceiling = descriptor.cost_ceiling_usd
    if ceiling is None:
        ceiling = RISK_COST_CEILING_USD.get(risk, DEFAULT_COST_CEILING_USD)
    projected = project_worst_case_cost(
        model_id, descriptor.input_tokens, max_out, priced_on
    )

    reason = (
        f"task_type={descriptor.task_type.value} gives base tier {base.name}; "
        f"risk band {risk.name} (amount=${financial.amount_usd:,.2f}, "
        f"materiality=${financial.materiality_threshold_usd:,.2f}, "
        f"posts_to_ledger={financial.posts_to_ledger}, "
        f"period_locked={financial.period_locked}) sets floor {floor.name}; "
        f"constraints {constraints or ['none']} -> {tier.name} ({model_id})"
    )

    decision = RoutingDecision(
        model_id=model_id,
        tier=tier,
        rule_id="+".join(rules),
        reason=reason,
        effort=effort,
        thinking_mode=spec.thinking_mode,
        thinking_budget_tokens=thinking_budget,
        supports_interleaved_thinking=spec.supports_interleaved_thinking,
        max_output_tokens=max_out,
        input_tokens=descriptor.input_tokens,
        projected_cost_usd=projected,
        cost_ceiling_usd=ceiling,
        risk_band=risk,
        task_type=descriptor.task_type,
        escalation_level=descriptor.escalation_level,
        constraints_applied=tuple(constraints),
        decision_id=uuid.uuid4().hex[:12],
        priced_on=priced_on,
        provider=spec.provider,
    )

    if enforce_cost_gate and projected > ceiling:
        raise CostGateExceeded(projected, ceiling, model_id)
    return decision


def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Translate OpenAI-shaped conversation turns to the Anthropic Messages shape.

    The agent loop keeps history in the OpenAI wire shape: assistant turns carry
    ``tool_calls``, and each tool result is its own ``{"role": "tool"}`` message.
    The Anthropic Messages API has no ``tool`` role — it takes ``tool_use`` content
    blocks on the assistant turn and ``tool_result`` blocks inside the *next user*
    turn. Sending the OpenAI shape verbatim returns
    ``400 invalid_request_error: messages: Unexpected role "tool"``, which killed
    every tool-using conversation on its second turn.

    This is the wire boundary, deliberately mirroring the model-id translation in
    ``cato/router.py``: selection and history stay in one canonical shape and only
    the outbound provider payload is normalised.

    Properties this must keep:
      * **Idempotent.** Messages already in Anthropic shape (list content, no
        ``tool_calls``) pass through untouched.
      * **Grouped.** All ``tool_result`` blocks answering one assistant turn are
        merged into a single user message. Anthropic rejects a ``tool_use`` block
        that is not answered in the immediately following user turn, so a
        multi-tool turn must not become several user messages.
      * **Order preserving.** ``tool_result`` blocks stay in call order.
    """
    out: list[dict[str, Any]] = []
    pending_results: list[dict[str, Any]] = []

    def _flush() -> None:
        if pending_results:
            out.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")

        if role == "tool":
            content = msg.get("content")
            pending_results.append({
                "type": "tool_result",
                "tool_use_id": str(msg.get("tool_call_id") or "unknown"),
                "content": content if isinstance(content, str) else json.dumps(content),
            })
            continue

        _flush()

        if role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            text = msg.get("content")
            if isinstance(text, str) and text.strip():
                blocks.append({"type": "text", "text": text})
            elif isinstance(text, list):
                blocks.extend(b for b in text if isinstance(b, dict))
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
                raw_args = fn.get("arguments", {})
                if isinstance(raw_args, str):
                    try:
                        parsed_args = json.loads(raw_args or "{}")
                    except (json.JSONDecodeError, ValueError):
                        parsed_args = {}
                else:
                    parsed_args = raw_args
                blocks.append({
                    "type": "tool_use",
                    "id": str(tc.get("id") or "unknown"),
                    "name": str(fn.get("name") or ""),
                    "input": parsed_args if isinstance(parsed_args, dict) else {},
                })
            out.append({"role": "assistant", "content": blocks})
            continue

        out.append(msg)

    _flush()
    return out


def build_request_payload(
    decision: RoutingDecision,
    messages: list[dict],
    *,
    system: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    stream: bool = False,
) -> dict[str, Any]:
    """Build the Anthropic Messages API body for ``decision``.

    Encodes the structural difference between tiers: Haiku 4.5 gets the older
    ``thinking:{type:"enabled",budget_tokens:N}`` shape and NO ``output_config``;
    Sonnet/Opus/Fable get adaptive thinking plus ``output_config.effort``.

    Messages are normalised to the Anthropic shape here — this is the last point
    before the wire, so no caller can bypass it.
    """
    payload: dict[str, Any] = {
        "model": decision.model_id,
        "max_tokens": decision.max_output_tokens,   # the only HARD cost cap
        "messages": to_anthropic_messages(messages),
        "stream": stream,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = tools
    if decision.thinking_mode is ThinkingMode.ADAPTIVE:
        payload["thinking"] = {"type": "adaptive"}
        if decision.effort:
            payload["output_config"] = {"effort": decision.effort}
    else:
        if decision.thinking_budget_tokens:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": decision.thinking_budget_tokens,
            }
    return payload
