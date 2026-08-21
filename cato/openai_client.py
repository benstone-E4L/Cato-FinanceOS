"""
cato/openai_client.py — Direct OpenAI Chat Completions API client.

Legacy compatibility client retained for isolated tooling/tests. It is not in
Cato's sanctioned production model path: model_policy contains Anthropic-only
candidates and ModelRouter.complete_message never dispatches this client.

RETRY CONTRACT (mirrors anthropic_client.py's structure)
---------------------------------------------------------
retryable      429 rate_limit_exceeded, 500/502/503 server_error, connection errors
NOT retryable  400 invalid_request_error, 401 invalid_api_key, 403 permission_error,
               404 model_not_found
OpenAI's Chat Completions API has no idempotency-key mechanism either -- same
caveat as Anthropic: a retried 5xx can double-bill. De-duplication lives above
this module (caller-owned), same as anthropic_client.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from .model_policy import RoutingDecision, actual_cost_from_usage, build_openai_request_payload

logger = logging.getLogger(__name__)

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

#: Hard cap on transport retries per request. Retries must terminate.
MAX_TRANSPORT_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0


class RetryClass(Enum):
    RETRYABLE = "retryable"
    NOT_RETRYABLE = "not_retryable"


#: status -> (error_type, retry class). Verified against OpenAI's error docs.
_STATUS_CONTRACT: dict[int, tuple[str, RetryClass]] = {
    400: ("invalid_request_error", RetryClass.NOT_RETRYABLE),
    401: ("invalid_api_key", RetryClass.NOT_RETRYABLE),
    403: ("permission_error", RetryClass.NOT_RETRYABLE),
    404: ("model_not_found", RetryClass.NOT_RETRYABLE),
    429: ("rate_limit_exceeded", RetryClass.RETRYABLE),
    500: ("server_error", RetryClass.RETRYABLE),
    502: ("server_error", RetryClass.RETRYABLE),
    503: ("server_error", RetryClass.RETRYABLE),
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


class OpenAIAPIError(Exception):
    """Non-retryable or retry-exhausted OpenAI API failure."""

    def __init__(self, classified: ClassifiedResponse, body: str = "") -> None:
        super().__init__(f"openai {classified.status} {classified.error_type}: {body[:300]}")
        self.classified = classified
        self.body = body


@dataclass
class CallResult:
    """Outcome of one completed OpenAI call.

    Public shape matches anthropic_client.CallResult (.text / .tool_uses)
    so router.py can treat either provider's result uniformly.
    """

    model_id: str
    message: dict[str, Any]
    stop_reason: Optional[str]
    usage: dict[str, Any] = field(default_factory=dict)
    actual_cost_usd: float = 0.0
    attempts: int = 1
    http_status: int = 200

    @property
    def text(self) -> str:
        content = self.message.get("content") if isinstance(self.message, dict) else None
        return content if isinstance(content, str) else ""

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        """Normalize OpenAI tool_calls to the same {id, name, input} shape
        anthropic_client.CallResult.tool_uses produces."""
        out: list[dict[str, Any]] = []
        for tc in (self.message.get("tool_calls") or []):
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            try:
                parsed_input = json.loads(fn.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                parsed_input = {}
            out.append({
                "id": tc.get("id", ""),
                "name": fn.get("name", ""),
                "input": parsed_input,
            })
        return out


#: A transport takes (url, payload, headers) and returns (status, body_json,
#: response_headers). Injectable so tests never make a live API call.
Transport = Callable[
    [str, dict, dict],
    Awaitable[tuple[int, dict, dict]],
]


class OpenAIDirectClient:
    """Legacy OpenAI client; not a sanctioned production execution path."""

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
        """Resolve OPENAI_API_KEY from the encrypted vault only.

        The value is never logged, echoed, or included in any record.  A
        missing or locked vault fails closed; process environment is ignored.
        """
        try:
            value = self._vault.get("OPENAI_API_KEY") if self._vault else None
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
            # Same Windows DNS fix as anthropic_client — see http_session.py.
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
        tools: Optional[list[dict]] = None,
        idempotency_key: Optional[str] = None,
    ) -> CallResult:
        """Execute one model call. Applies the retry contract; never loops.

        ``messages`` must already include a ``{"role": "system", ...}`` entry
        if a system prompt is needed -- Chat Completions has no separate
        system parameter (unlike anthropic_client.call's ``system`` kwarg).
        """
        payload = build_openai_request_payload(decision, messages, tools=tools, stream=False)
        api_key = self._api_key()
        if not api_key:
            raise OpenAIAPIError(
                ClassifiedResponse(401, "invalid_api_key", RetryClass.NOT_RETRYABLE),
                "OPENAI_API_KEY is not configured",
            )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        transport = self._transport or self._default_transport

        logger.info("%s", decision.log_line())
        if idempotency_key:
            logger.info(
                "[model-route] decision=%s idempotency_key=%s (dedup is caller-owned; "
                "OpenAI Chat Completions has no idempotency mechanism)",
                decision.decision_id, idempotency_key,
            )

        delay = _RETRY_BASE_DELAY
        last: Optional[BaseException] = None
        for attempt in range(1, MAX_TRANSPORT_RETRIES + 1):
            try:
                status, body, resp_headers = await transport(
                    OPENAI_CHAT_COMPLETIONS_URL, payload, headers
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
            if classified.retry_class is RetryClass.NOT_RETRYABLE:
                raise OpenAIAPIError(classified, body_text)
            if attempt == MAX_TRANSPORT_RETRIES:
                raise OpenAIAPIError(classified, body_text)
            wait = classified.retry_after_s if classified.retry_after_s is not None else delay
            logger.warning(
                "[model-route] decision=%s retryable %d %s attempt %d/%d, sleeping %.1fs",
                decision.decision_id, status, classified.error_type,
                attempt, MAX_TRANSPORT_RETRIES, wait,
            )
            await self._sleep(wait)
            delay = min(delay * 2, _RETRY_MAX_DELAY)

        raise OpenAIAPIError(  # pragma: no cover - loop always returns/raises
            ClassifiedResponse(500, "api_error", RetryClass.RETRYABLE), str(last)
        )

    def _build_result(
        self, decision: RoutingDecision, body: dict, attempt: int, status: int
    ) -> CallResult:
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage_raw = body.get("usage") or {}
        # OpenAI's usage keys differ from Anthropic's -- normalize to the
        # names model_policy.actual_cost_from_usage() expects. Cached-token
        # discounting (prompt_tokens_details.cached_tokens) is not applied
        # here -- this under-counts a cache benefit, never over-counts cost.
        usage = {
            "input_tokens": usage_raw.get("prompt_tokens", 0),
            "output_tokens": usage_raw.get("completion_tokens", 0),
        }
        cost = actual_cost_from_usage(decision.model_id, usage, decision.priced_on)
        result = CallResult(
            model_id=body.get("model") or decision.model_id,
            message=message,
            stop_reason=choice.get("finish_reason"),
            usage=usage,
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
