"""
cato/anthropic_client.py — Direct Anthropic Messages API client.

Replaces SwarmSync in Cato's active model-execution path.  Model selection is
NOT made here — it is made by :mod:`cato.model_policy` before this module is
called.  This module only executes the decision, applies the retry contract,
and records actual cost.

RETRY CONTRACT (implemented exactly)
------------------------------------
retryable      429 rate_limit_error (honour ``retry-after``), 500 api_error,
               504 timeout_error, 529 overloaded_error, connection errors
NOT retryable  400 invalid_request_error, 401 authentication_error,
               402 billing_error, 403 permission_error, 404 not_found_error,
               413 request_too_large
conditional    409 conflict_error — resolve, then retry (never a blind retry)

Anthropic has NO idempotency mechanism: a retried 5xx can double-bill.  Cato's
idempotency therefore sits ABOVE this module (the caller supplies an
``idempotency_key`` and is responsible for de-duplicating side effects).

A streaming response can fail AFTER a 200, so ``stop_reason`` is inspected on
every completed call — HTTP status alone is not sufficient.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from .model_policy import (
    RoutingDecision,
    actual_cost_from_usage,
    build_request_payload,
)

logger = logging.getLogger(__name__)

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

#: Hard cap on transport retries per request.  Retries must terminate.
MAX_TRANSPORT_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0


class RetryClass(Enum):
    RETRYABLE = "retryable"
    NOT_RETRYABLE = "not_retryable"
    CONDITIONAL = "conditional"


#: status -> (error_type, retry class).  Verified against Anthropic's error docs.
_STATUS_CONTRACT: dict[int, tuple[str, RetryClass]] = {
    400: ("invalid_request_error", RetryClass.NOT_RETRYABLE),
    401: ("authentication_error", RetryClass.NOT_RETRYABLE),
    402: ("billing_error", RetryClass.NOT_RETRYABLE),
    403: ("permission_error", RetryClass.NOT_RETRYABLE),
    404: ("not_found_error", RetryClass.NOT_RETRYABLE),
    409: ("conflict_error", RetryClass.CONDITIONAL),
    413: ("request_too_large", RetryClass.NOT_RETRYABLE),
    429: ("rate_limit_error", RetryClass.RETRYABLE),
    500: ("api_error", RetryClass.RETRYABLE),
    504: ("timeout_error", RetryClass.RETRYABLE),
    529: ("overloaded_error", RetryClass.RETRYABLE),
}


@dataclass(frozen=True)
class ClassifiedResponse:
    status: int
    error_type: str
    retry_class: RetryClass
    retry_after_s: Optional[float] = None


def classify_status(status: int, retry_after: Optional[str] = None) -> ClassifiedResponse:
    """Classify an HTTP status against the retry contract."""
    error_type, retry_class = _STATUS_CONTRACT.get(status, ("api_error", RetryClass.RETRYABLE))
    if status not in _STATUS_CONTRACT and 400 <= status < 500:
        error_type, retry_class = ("invalid_request_error", RetryClass.NOT_RETRYABLE)
    delay: Optional[float] = None
    if retry_after:
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            delay = None
        else:
            # `retry-after` is a value an upstream (or anything that can answer
            # as one) chooses. Honouring it unbounded turns a rate-limit reply
            # into an arbitrarily long daemon stall — `retry-after: 86400` used
            # to sleep the agent loop for a day. Clamp into [0, _RETRY_MAX_DELAY];
            # the retry budget is what bounds total wait, not the server.
            if delay != delay or delay < 0:  # NaN or negative
                delay = None
            else:
                delay = min(delay, _RETRY_MAX_DELAY)
    return ClassifiedResponse(status, error_type, retry_class, delay)


def is_retryable_exception(exc: BaseException) -> bool:
    """Connection-level failures are retryable; everything else is not."""
    import aiohttp

    return isinstance(
        exc,
        (
            aiohttp.ClientConnectionError,
            aiohttp.ClientOSError,
            aiohttp.ServerDisconnectedError,
            asyncio.TimeoutError,
            ConnectionError,
            TimeoutError,
        ),
    )


class AnthropicAPIError(Exception):
    """Non-retryable or retry-exhausted Anthropic API failure."""

    def __init__(self, classified: ClassifiedResponse, body: str = "") -> None:
        super().__init__(
            f"anthropic {classified.status} {classified.error_type}: {body[:300]}"
        )
        self.classified = classified
        self.body = body


class ConflictRequiresResolution(AnthropicAPIError):
    """409 conflict_error — resolve the conflict before retrying."""


@dataclass
class CallResult:
    """Outcome of one completed model call."""

    model_id: str
    message: dict[str, Any]
    stop_reason: Optional[str]
    usage: dict[str, Any] = field(default_factory=dict)
    actual_cost_usd: float = 0.0
    attempts: int = 1
    http_status: int = 200

    def _content_blocks(self) -> list[Any]:
        """Content blocks, tolerating a truncated or malformed 200 body.

        ``.get("content", [])`` returns None when the key is present and null,
        which a partial/streaming-aborted response can produce — and iterating
        None raised TypeError out of a property, i.e. a partial model response
        crashed the caller instead of reading as an empty answer.
        """
        blocks = self.message.get("content") if isinstance(self.message, dict) else None
        return blocks if isinstance(blocks, list) else []

    @property
    def text(self) -> str:
        parts = [
            b.get("text", "")
            for b in self._content_blocks()
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "".join(parts)

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [
            b for b in self._content_blocks()
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]


#: A transport takes (url, payload, headers) and returns (status, body_json,
#: response_headers).  Injectable so tests never make a live API call.
Transport = Callable[
    [str, dict, dict],
    Awaitable[tuple[int, dict, dict]],
]


class AnthropicDirectClient:
    """Executes a :class:`RoutingDecision` against the Anthropic API."""

    def __init__(
        self,
        vault: Any = None,
        transport: Optional[Transport] = None,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> None:
        self._vault = vault
        self._transport = transport
        self._sleep = sleep or asyncio.sleep
        self._session: Any = None

    # -- credentials ----------------------------------------------------
    def _api_key(self) -> str:
        """Resolve ANTHROPIC_API_KEY from the encrypted vault only.

        ``vault`` is also the explicit injection seam for tests.  A missing or
        locked vault fails closed; process-environment credentials are ignored.
        """
        try:
            value = self._vault.get("ANTHROPIC_API_KEY") if self._vault else None
        except Exception:
            value = None
        return str(value or "").strip()

    def has_credentials(self) -> bool:
        return bool(self._api_key())

    # -- transport ------------------------------------------------------
    async def _default_transport(
        self, url: str, payload: dict, headers: dict
    ) -> tuple[int, dict, dict]:
        import aiohttp

        from .http_session import make_outbound_session

        if self._session is None or self._session.closed:
            # ThreadedResolver + AF_INET: aiohttp's default aiodns resolver
            # times out on Windows DNS even when OS resolve + TCP/443 work.
            self._session = make_outbound_session(
                timeout=aiohttp.ClientTimeout(total=600)
            )
        async with self._session.post(url, json=payload, headers=headers) as resp:
            try:
                body = await resp.json()
            except Exception:
                body = {"error": {"message": (await resp.text())[:500]}}
            return resp.status, body, dict(resp.headers)

    async def close(self) -> None:
        if self._session is not None and not getattr(self._session, "closed", True):
            await self._session.close()
        self._session = None

    # -- main entry point -----------------------------------------------
    async def call(
        self,
        decision: RoutingDecision,
        messages: list[dict],
        *,
        system: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        idempotency_key: Optional[str] = None,
    ) -> CallResult:
        """Execute one model call.  Applies the retry contract; never loops.

        ``idempotency_key`` is recorded for the caller's own de-duplication —
        Anthropic has no idempotency mechanism, so a retried 5xx can double-bill
        and de-duplication must live above this call.
        """
        payload = build_request_payload(
            decision, messages, system=system, tools=tools, stream=False
        )
        api_key = self._api_key()
        if not api_key:
            raise AnthropicAPIError(
                ClassifiedResponse(401, "authentication_error", RetryClass.NOT_RETRYABLE),
                "ANTHROPIC_API_KEY is not configured",
            )
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        transport = self._transport or self._default_transport

        logger.info("%s", decision.log_line())
        if idempotency_key:
            logger.info(
                "[model-route] decision=%s idempotency_key=%s (dedup is caller-owned; "
                "Anthropic has no idempotency mechanism)",
                decision.decision_id, idempotency_key,
            )

        delay = _RETRY_BASE_DELAY
        last: Optional[BaseException] = None
        for attempt in range(1, MAX_TRANSPORT_RETRIES + 1):
            try:
                status, body, resp_headers = await transport(
                    ANTHROPIC_MESSAGES_URL, payload, headers
                )
            except BaseException as exc:  # noqa: BLE001 - classified below
                if not is_retryable_exception(exc) or attempt == MAX_TRANSPORT_RETRIES:
                    raise
                last = exc
                logger.warning(
                    "[model-route] decision=%s connection error attempt %d/%d: %s",
                    decision.decision_id, attempt, MAX_TRANSPORT_RETRIES, exc,
                )
                await self._sleep(delay)
                delay = min(delay * 2, _RETRY_MAX_DELAY)
                continue

            if status == 200:
                return self._build_result(decision, body, attempt, status)

            classified = classify_status(status, (resp_headers or {}).get("retry-after"))
            body_text = str(body)[:500]
            if classified.retry_class is RetryClass.CONDITIONAL:
                # 409 — resolve, then retry.  Never a blind retry.
                raise ConflictRequiresResolution(classified, body_text)
            if classified.retry_class is RetryClass.NOT_RETRYABLE:
                raise AnthropicAPIError(classified, body_text)
            if attempt == MAX_TRANSPORT_RETRIES:
                raise AnthropicAPIError(classified, body_text)
            wait = classified.retry_after_s if classified.retry_after_s is not None else delay
            logger.warning(
                "[model-route] decision=%s retryable %d %s attempt %d/%d, sleeping %.1fs",
                decision.decision_id, status, classified.error_type,
                attempt, MAX_TRANSPORT_RETRIES, wait,
            )
            await self._sleep(wait)
            delay = min(delay * 2, _RETRY_MAX_DELAY)

        raise AnthropicAPIError(  # pragma: no cover - loop always returns/raises
            ClassifiedResponse(500, "api_error", RetryClass.RETRYABLE), str(last)
        )

    def _build_result(
        self, decision: RoutingDecision, body: dict, attempt: int, status: int
    ) -> CallResult:
        usage = body.get("usage") or {}
        cost = actual_cost_from_usage(decision.model_id, usage, decision.priced_on)
        result = CallResult(
            model_id=body.get("model") or decision.model_id,
            message=body,
            # A streaming response can fail after a 200 — inspect stop_reason,
            # not just the HTTP status.
            stop_reason=body.get("stop_reason"),
            usage=dict(usage),
            actual_cost_usd=cost,
            attempts=attempt,
            http_status=status,
        )
        logger.info(
            "[model-route] decision=%s model=%s stop_reason=%s attempts=%d "
            "input_tokens=%s output_tokens=%s actual_cost=$%.6f projected_ceiling=$%.6f",
            decision.decision_id, result.model_id, result.stop_reason, attempt,
            usage.get("input_tokens"), usage.get("output_tokens"),
            cost, decision.projected_cost_usd,
        )
        return result
