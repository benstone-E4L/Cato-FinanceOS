"""
cato/router.py — model router for CATO.

The only execution path, :meth:`ModelRouter.complete_message`, calls the Anthropic API
DIRECTLY, with the model chosen by the deterministic policy in
:mod:`cato.model_policy`.  SwarmSync is no longer in the model-execution path.

Model selection on the primary path is made by code from a
:class:`~cato.model_policy.TaskDescriptor` BEFORE dispatch.  Nothing the model
emits can influence it.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from cato.anthropic_client import (
    AnthropicAPIError,
    AnthropicDirectClient,
    CallResult,
)
from cato.model_policy import (
    MAX_ESCALATIONS,
    Provider,
    RoutingDecision,
    TaskDescriptor,
    TaskType,
    escalate,
    route,
    trigger_for_stop_reason,
)
from cato.routing_log import get_persistent_routing_history, record_routing_event

logger = logging.getLogger(__name__)

_LOG_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(bot)\d+:[A-Za-z0-9_-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+"), r"\1[REDACTED]"),
    (
        re.compile(r"(?i)\b([A-Z][A-Z0-9_]{2,}_(?:TOKEN|KEY|SECRET|PASSWORD|PASS)\s*=\s*)\S+"),
        r"\1[REDACTED]",
    ),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})\b"), "[REDACTED-KEY]"),
)


def _scrub_log_text(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in _LOG_SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# Signal regexes for complexity scoring
_RE_REASON = re.compile(r"\b(why|analyze|analyse|compare|explain|evaluate|assess)\b", re.I)
_RE_MATH = re.compile(r"\b(calculate|compute|proof|prove|solve|integral|derivative)\b", re.I)
_RE_MULTI = re.compile(r"\b(then|after that|first[,\s]|second[,\s]|finally|step \d)\b", re.I)
_RE_CREATIVE = re.compile(r"\b(write|generate|create|compose|draft)\b", re.I)
_RE_CODE = re.compile(r"(```|def |class |import |#include|function\s+\w+)", re.I)
_RE_NONENGL = re.compile(r"[^\x00-\x7F]")


# Module-level routing history (ring buffer, max 200 entries)
_routing_history: list[dict] = []
_ROUTING_HISTORY_MAX = 200


def get_routing_history() -> list[dict]:
    """Return the routing decision history buffer."""
    persistent = get_persistent_routing_history(limit=_ROUTING_HISTORY_MAX)
    if persistent:
        return persistent
    return list(_routing_history)


def _coerce_model_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        return [str(key) for key in value.keys()]
    return []


def _extract_cost(data: dict[str, Any], *names: str) -> Any:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    provider_meta = data.get("swarmsync") if isinstance(data.get("swarmsync"), dict) else {}
    for name in names:
        for source in (provider_meta, usage, data):
            if source.get(name) is not None:
                return source[name]
    return None


def _record_routing_decision(record: dict[str, Any]) -> None:
    """Persist one routing decision and keep a short in-memory mirror."""
    normalized = {
        **record,
        "timestamp": record.get("timestamp") or datetime.now(UTC).isoformat(),
        "request_id": str(record.get("request_id") or uuid.uuid4()),
        "routed_model": record.get("routed_model") or record.get("chosen_model") or "",
        "chosen_model": record.get("chosen_model") or record.get("routed_model") or "",
        "raw_model": _scrub_log_text(str(record.get("raw_model") or "")),
        "routing_reason": _scrub_log_text(str(record.get("routing_reason") or "")),
        "considered_models": _coerce_model_list(record.get("considered_models")),
        "fallback_routing": bool(record.get("fallback_routing")),
        "success": bool(record.get("success")),
        "estimated_cost": record.get("estimated_cost"),
        "actual_cost": record.get("actual_cost"),
    }
    status = "ok" if normalized["success"] else "failed"
    if normalized["fallback_routing"]:
        status = "fallback"
    _routing_history.append(normalized)
    if len(_routing_history) > _ROUTING_HISTORY_MAX:
        del _routing_history[:-_ROUTING_HISTORY_MAX]
    record_routing_event(
        {
            "ts": time.time(),
            "request_id": normalized["request_id"],
            "provider": normalized.get("provider", "anthropic"),
            "status": status,
            "success": normalized["success"],
            "routed_model": normalized["routed_model"],
            "raw_model": normalized["raw_model"],
            "routing_reason": normalized["routing_reason"],
            "considered_models": normalized["considered_models"],
            "fallback_routing": normalized["fallback_routing"],
            "estimated_cost": normalized["estimated_cost"],
            "actual_cost": normalized["actual_cost"],
            "complexity": normalized.get("complexity_score", 0.0),
            "has_tools": normalized.get("has_tools", False),
            "msg_count": normalized.get("history_length", 0),
            "http_status": normalized.get("http_status"),
            "content_chars": normalized.get("content_chars", 0),
            "tool_call_count": normalized.get("tool_call_count", 0),
            "error": normalized.get("error", ""),
            "metadata": normalized,
        }
    )


def _anthropic_message_to_openai(result: CallResult) -> dict[str, Any]:
    """Convert an Anthropic response into the OpenAI-style message Cato uses."""
    message: dict[str, Any] = {"role": "assistant", "content": result.text}
    tool_calls: list[dict[str, Any]] = []
    for block in result.tool_uses:
        tool_calls.append(
            {
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input") or {}),
                },
            }
        )
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


class ModelRouter:
    """Routes tasks to a model chosen by deterministic policy, then executes it."""

    def __init__(
        self,
        vault: Any,
        preferred_model: str = "claude-sonnet-5",
        blocked_models: list[str] | None = None,
        max_output_tokens: int = 16384,
        anthropic_client: AnthropicDirectClient | None = None,
    ) -> None:
        self._vault = vault
        # Kept in the constructor only for compatibility with existing callers.
        # Neither value can influence policy selection or provider execution.
        del preferred_model, blocked_models, max_output_tokens

        # Direct Anthropic client — the sole model-execution path.
        self._anthropic = anthropic_client or AnthropicDirectClient(vault=vault)

    async def close(self) -> None:
        """Close the direct Anthropic client."""
        if self._anthropic is not None:
            await self._anthropic.close()

    def score_task(self, message: str, context_tokens: int, history_len: int) -> float:
        """Return 0.0-1.0 complexity score from message signals."""
        s = 0.0
        if len(message) > 500:
            s += 0.10
        if _RE_CODE.search(message):
            s += 0.15
        if _RE_REASON.search(message):
            s += 0.10
        if _RE_MATH.search(message):
            s += 0.15
        if context_tokens > 4000:
            s += 0.10
        if _RE_MULTI.search(message):
            s += 0.10
        if _RE_CREATIVE.search(message):
            s += 0.05
        if _RE_NONENGL.search(message):
            s += 0.10
        if history_len > 10:
            s += 0.05
        return min(1.0, round(s, 4))

    # ------------------------------------------------------------------
    # PRIMARY PATH — deterministic policy routing + direct Anthropic call
    # ------------------------------------------------------------------

    async def complete_message(
        self,
        messages: list[dict],
        descriptor: TaskDescriptor,
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        idempotency_key: str | None = None,
        validator: Any | None = None,
        when: Any | None = None,
    ) -> tuple[str, dict[str, Any], RoutingDecision]:
        """Route by policy, call Anthropic directly, escalate on hard failures.

        ``descriptor`` is built by the caller BEFORE dispatch.  The model is
        selected by :func:`cato.model_policy.route` — this method takes no model
        argument and honours no override, whether from config or model output.

        ``validator`` is an optional callable ``(CallResult) -> EscalationTrigger
        | None`` implementing a deterministic post-call check (schema validation,
        arithmetic reconciliation).  Escalation is driven ONLY by validators and
        ``stop_reason`` — never by a model's self-reported confidence, which the
        API does not expose and which is model whim.

        Escalation terminates: at most ``MAX_ESCALATIONS`` tier bumps, after
        which :class:`EscalationExhausted` propagates and the task fails loudly.

        Returns ``(model_id, openai_style_assistant_message, decision)``.
        """
        # Model execution is direct Anthropic only. Other credentials may be
        # retained for unrelated integrations but can never broaden routing.
        available: frozenset[Provider] = frozenset({Provider.ANTHROPIC})
        current = descriptor
        while True:
            decision = route(current, when=when, available_providers=available)
            record = self._decision_log_base(decision)
            try:
                result = await self._anthropic.call(
                    decision,
                    messages,
                    system=system,
                    tools=tools,
                    idempotency_key=idempotency_key,
                )
            except AnthropicAPIError as exc:
                _record_routing_decision(
                    {
                        **record,
                        "success": False,
                        "http_status": exc.classified.status,
                        "error": _scrub_log_text(str(exc)),
                    }
                )
                raise

            trigger = trigger_for_stop_reason(result.stop_reason)
            if trigger is None and validator is not None:
                trigger = validator(result)

            message = _anthropic_message_to_openai(result)
            _record_routing_decision(
                {
                    **record,
                    "success": trigger is None,
                    "http_status": result.http_status,
                    "actual_cost": result.actual_cost_usd,
                    "content_chars": len(message.get("content", "") or ""),
                    "tool_call_count": len(message.get("tool_calls") or []),
                    "error": f"escalation_trigger:{trigger.value}" if trigger else "",
                }
            )

            if trigger is None:
                return result.model_id, message, decision

            logger.warning(
                "[model-route] decision=%s escalating: trigger=%s level=%d/%d",
                decision.decision_id,
                trigger.value,
                current.escalation_level,
                MAX_ESCALATIONS,
            )
            # Raises EscalationExhausted at the cap — the loop cannot spin.
            current = escalate(current, trigger)

    def _decision_log_base(self, decision: RoutingDecision) -> dict[str, Any]:
        """Routing-log skeleton carrying the full model-choice explanation."""
        rec = decision.log_record()
        return {
            "provider": decision.provider.value,
            "request_id": decision.decision_id,
            "chosen_model": decision.model_id,
            "routed_model": decision.model_id,
            "raw_model": decision.model_id,
            "routing_reason": f"{decision.rule_id}: {decision.reason}",
            "tier": decision.tier.name,
            "considered_models": [decision.model_id],
            "estimated_cost": decision.projected_cost_usd,
            "actual_cost": None,
            "fallback_routing": False,
            "complexity_score": 0.0,
            "history_length": 0,
            "has_tools": bool(decision.task_type is TaskType.GENERAL_TOOL_USE),
            "success": False,
            "policy": rec,
        }

    async def complete(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> None:
        """Fail closed for the removed caller-selected streaming interface.

        Production callers must construct a :class:`TaskDescriptor` and call
        :meth:`complete_message`.  In particular, this compatibility name does
        not accept a model id and cannot dispatch to a provider.
        """
        del messages, tools, stream
        raise RuntimeError(
            "ModelRouter.complete() is disabled; use complete_message() so "
            "model selection is bound to cato.model_policy"
        )
