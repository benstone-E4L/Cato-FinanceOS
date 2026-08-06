"""Fail-closed Cato → E4L FinanceOS HTTP client.

Encodes the traps documented in ``docs/ops/LIMITATIONS.md`` §8:

* Capability token required for mutating calls (no mint endpoint exists).
* HTTP 503 with body ``That request is already queued.`` is SUCCESS (dedupe).
* HTTP 202 means queued/deferred — **not** applied; poll ``GET /api/intents/:id``.
* Money is ``Decimal`` / wire strings — never ``float``.
* E4L owns approvals; Cato never approves.

No Xero code lives here. Token values are never logged.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# Exact body string from LIMITATIONS.md §8 — match before any retry logic.
ALREADY_QUEUED_BODY = "That request is already queued."

# Intent states treated as terminal when polling (conservative; expand when
# FinanceOS source is re-verified).
_DEFAULT_TERMINAL_STATES = frozenset(
    {
        "applied",
        "confirmed",
        "failed",
        "rejected",
        "cancelled",
        "canceled",
        "deferred",  # modules index missing → jobs end deferred (§8)
        "error",
    }
)

Transport = Callable[
    [str, str, dict[str, str], dict[str, Any] | None, float],
    "FinanceOSHttpResponse",
]


class FinanceOSError(Exception):
    """Base error for FinanceOS client failures."""


class FinanceOSCapabilityRequired(FinanceOSError):
    """Mutating call refused: no capability token supplied (fail-closed)."""


class FinanceOSMintForbidden(FinanceOSError):
    """Capability-token mint is not available and must not be attempted."""


class FinanceOSApproveForbidden(FinanceOSError):
    """Cato must never approve E4L decisions (LIMITATIONS.md §8)."""


class FinanceOSMoneyError(FinanceOSError, TypeError, ValueError):
    """Money value is not a safe Decimal/string representation."""


@dataclass(frozen=True)
class FinanceOSHttpResponse:
    """Raw HTTP layer response (status + text body)."""

    status: int
    body: str
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FinanceOSResult:
    """Normalized client result with §8 semantics applied."""

    status: int
    body: str
    parsed: Any
    ok: bool
    applied: bool
    outcome: str
    intent_id: str | None = None
    deduplicated: bool = False
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        """Safe summary for tool/API surfaces (no secrets)."""
        return {
            "status": self.status,
            "ok": self.ok,
            "applied": self.applied,
            "outcome": self.outcome,
            "intent_id": self.intent_id,
            "deduplicated": self.deduplicated,
            "detail": self.detail,
            "body": self.parsed if self.parsed is not None else self.body,
        }


def parse_money(value: Any) -> Decimal:
    """Parse wire money into ``Decimal``.

    FinanceOS returns ``numeric(14,2)`` as **strings**. Floats are rejected —
    binary floating point must never touch ledger amounts.
    """
    if isinstance(value, bool):
        raise FinanceOSMoneyError("Money must not be a boolean")
    if isinstance(value, float):
        raise FinanceOSMoneyError(
            "Money must not be float; use Decimal or a decimal string"
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise FinanceOSMoneyError("Money string is empty")
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise FinanceOSMoneyError(f"Invalid money string: {text!r}") from exc
    raise FinanceOSMoneyError(f"Unsupported money type: {type(value).__name__}")


def money_to_wire(amount: Decimal | str | int) -> str:
    """Serialize money for FinanceOS request bodies (string, never float)."""
    if isinstance(amount, float):
        raise FinanceOSMoneyError(
            "Money must not be float; use Decimal or a decimal string"
        )
    dec = parse_money(amount)
    # Match numeric(14,2) wire shape without scientific notation.
    quantized = dec.quantize(Decimal("0.01"))
    return format(quantized, "f")


def is_already_queued_success(status: int, body: str) -> bool:
    """True when FinanceOS signals duplicate-suppression success (§8)."""
    if status != 503:
        return False
    return body.strip() == ALREADY_QUEUED_BODY


def _default_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None,
    timeout: float,
) -> FinanceOSHttpResponse:
    """stdlib urllib transport. Scheme must be http(s).

    Unlike ``integrations.http_client.request_json``, this allows private hosts
    so operators can reach an internal FinanceOS deployment. Callers still must
    supply a capability token for mutating verbs.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FinanceOSError(f"Disallowed URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise FinanceOSError("URL missing host")

    payload: bytes | None = None
    request_headers = dict(headers)
    if body is not None:
        payload = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
        request_headers.setdefault("Content-Type", "application/json")

    req = Request(url=url, data=payload, headers=request_headers, method=method.upper())
    try:
        with urlopen(req, timeout=timeout) as resp:
            return FinanceOSHttpResponse(
                status=int(resp.status),
                body=resp.read().decode("utf-8", errors="replace"),
                headers=dict(resp.headers.items()),
            )
    except HTTPError as exc:
        return FinanceOSHttpResponse(
            status=int(exc.code),
            body=exc.read().decode("utf-8", errors="replace"),
            headers=dict(exc.headers.items()) if exc.headers else {},
        )
    except URLError as exc:
        return FinanceOSHttpResponse(
            status=0,
            body=json.dumps({"error": str(exc.reason)}),
            headers={},
        )


def _parse_body(body: str) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def _extract_intent_id(parsed: Any, fallback: str | None = None) -> str | None:
    if fallback:
        return fallback
    if isinstance(parsed, dict):
        for key in ("intent_id", "id", "intentId"):
            value = parsed.get(key)
            if value is not None and str(value).strip():
                return str(value)
    return None


def _intent_state(parsed: Any) -> str | None:
    if not isinstance(parsed, dict):
        return None
    for key in ("state", "status", "decision_state", "lifecycle"):
        value = parsed.get(key)
        if value is not None and str(value).strip():
            return str(value).strip().lower()
    return None


class FinanceOSClient:
    """HTTP client for FinanceOS with fail-closed auth and §8 response rules.

    Parameters
    ----------
    base_url:
        FinanceOS origin, e.g. ``https://financeos.example``.
    capability_token:
        Intent-bound capability token. Required for every mutating call.
        There is **no mint** — the token must be supplied by an out-of-band
        operator process. Empty/None → mutating calls raise
        ``FinanceOSCapabilityRequired``.
    intent_id:
        Optional default intent this capability is bound to (informational;
        used when building Authorization context and poll defaults).
    transport:
        Injectable ``(method, url, headers, body, timeout) -> FinanceOSHttpResponse``
        for unit tests. Defaults to stdlib urllib.
    """

    def __init__(
        self,
        base_url: str,
        *,
        capability_token: str | None = None,
        intent_id: str | None = None,
        transport: Transport | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not base_url or not str(base_url).strip():
            raise FinanceOSError("base_url is required")
        self._base_url = str(base_url).rstrip("/") + "/"
        self._capability_token = (capability_token or "").strip() or None
        self._intent_id = (intent_id or "").strip() or None
        self._transport = transport or _default_transport
        self._timeout = float(timeout)

    @property
    def has_capability_token(self) -> bool:
        return self._capability_token is not None

    @property
    def base_url(self) -> str:
        return self._base_url.rstrip("/")

    # ------------------------------------------------------------------ #
    # Hard refusals (LIMITATIONS §8)
    # ------------------------------------------------------------------ #

    def mint_capability_token(self, *_args: Any, **_kwargs: Any) -> None:
        """Refuse mint attempts — no mint endpoint exists (§8)."""
        raise FinanceOSMintForbidden(
            "FinanceOS has no capability-token mint endpoint. "
            "Cato must not invent or request a mint. Supply an "
            "operator-issued intent-bound capability token."
        )

    def approve(self, *_args: Any, **_kwargs: Any) -> None:
        """Refuse approvals — E4L owns them; Cato never approves (§8)."""
        raise FinanceOSApproveForbidden(
            "E4L owns FinanceOS approvals. Cato relays only and must never approve."
        )

    def approve_intent(self, *_args: Any, **_kwargs: Any) -> None:
        """Alias refusal for approve-shaped call sites."""
        self.approve()

    # ------------------------------------------------------------------ #
    # Auth gate
    # ------------------------------------------------------------------ #

    def require_capability_token(self) -> str:
        """Fail-closed gate for mutating calls."""
        if not self._capability_token:
            raise FinanceOSCapabilityRequired(
                "Capability token required for FinanceOS mutating calls. "
                "No mint endpoint exists; refuse rather than guess."
            )
        return self._capability_token

    def _auth_headers(self, *, mutating: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Cato-FinanceOSClient/0.1",
        }
        if mutating:
            token = self.require_capability_token()
            headers["Authorization"] = f"Bearer {token}"
            if self._intent_id:
                headers["X-FinanceOS-Intent-Id"] = self._intent_id
        elif self._capability_token:
            # Reads may carry the token when present; never invent one.
            headers["Authorization"] = f"Bearer {self._capability_token}"
            if self._intent_id:
                headers["X-FinanceOS-Intent-Id"] = self._intent_id
        return headers

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return urljoin(self._base_url, path.lstrip("/"))

    # ------------------------------------------------------------------ #
    # Core request + §8 interpretation
    # ------------------------------------------------------------------ #

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        mutating: bool | None = None,
        intent_id: str | None = None,
        timeout: float | None = None,
    ) -> FinanceOSResult:
        """Issue one HTTP call and apply §8 outcome semantics."""
        verb = method.upper()
        if mutating is None:
            mutating = verb not in ("GET", "HEAD", "OPTIONS")
        if mutating and body:
            body = self._sanitize_money_fields(body)

        headers = self._auth_headers(mutating=mutating)
        url = self._url(path)
        # Never log Authorization / token material.
        logger.info(
            "financeos_request method=%s path=%s mutating=%s has_token=%s",
            verb,
            path,
            mutating,
            bool(self._capability_token),
        )
        raw = self._transport(
            verb,
            url,
            headers,
            body if verb not in ("GET", "HEAD") else None,
            timeout if timeout is not None else self._timeout,
        )
        return self._interpret(raw, intent_id=intent_id or self._intent_id)

    def _sanitize_money_fields(self, body: dict[str, Any]) -> dict[str, Any]:
        """Ensure known money keys are wire strings, never floats."""
        money_keys = {
            "amount",
            "total",
            "subtotal",
            "tax",
            "net",
            "gross",
            "balance",
            "money",
            "value",
        }
        out: dict[str, Any] = {}
        for key, value in body.items():
            if key.lower() in money_keys or key.lower().endswith("_amount"):
                if isinstance(value, float):
                    raise FinanceOSMoneyError(
                        f"Field {key!r} must not be float; use Decimal or string"
                    )
                if isinstance(value, (Decimal, int, str)):
                    out[key] = money_to_wire(value)
                else:
                    out[key] = value
            elif isinstance(value, dict):
                out[key] = self._sanitize_money_fields(value)
            else:
                if isinstance(value, float) and key.lower() in money_keys:
                    raise FinanceOSMoneyError(f"Field {key!r} must not be float")
                out[key] = value
        return out

    def _interpret(
        self,
        raw: FinanceOSHttpResponse,
        *,
        intent_id: str | None = None,
    ) -> FinanceOSResult:
        parsed = _parse_body(raw.body)
        resolved_id = _extract_intent_id(parsed, intent_id)

        if is_already_queued_success(raw.status, raw.body):
            return FinanceOSResult(
                status=raw.status,
                body=raw.body,
                parsed=parsed,
                ok=True,
                applied=False,
                outcome="queued_deduplicated",
                intent_id=resolved_id,
                deduplicated=True,
                detail=(
                    "HTTP 503 with exact already-queued body is SUCCESS "
                    "(duplicate suppression). Do not retry."
                ),
            )

        if raw.status == 202:
            return FinanceOSResult(
                status=raw.status,
                body=raw.body,
                parsed=parsed,
                ok=True,
                applied=False,
                outcome="accepted_not_applied",
                intent_id=resolved_id,
                detail=(
                    "HTTP 202 means queued/deferred — not applied. "
                    "Poll GET /api/intents/:id for terminal state."
                ),
            )

        if 200 <= raw.status < 300:
            state = _intent_state(parsed)
            applied = state in ("applied", "confirmed") if state else False
            return FinanceOSResult(
                status=raw.status,
                body=raw.body,
                parsed=parsed,
                ok=True,
                applied=applied,
                outcome="applied" if applied else "success",
                intent_id=resolved_id,
                detail="" if applied else "HTTP success; applied not inferred without state.",
            )

        return FinanceOSResult(
            status=raw.status,
            body=raw.body,
            parsed=parsed,
            ok=False,
            applied=False,
            outcome="error",
            intent_id=resolved_id,
            detail=f"HTTP {raw.status}",
        )

    # ------------------------------------------------------------------ #
    # Intent helpers
    # ------------------------------------------------------------------ #

    def submit_intent(
        self,
        payload: dict[str, Any],
        *,
        path: str = "/api/intents",
    ) -> FinanceOSResult:
        """POST an intent. Requires capability token. 202 ≠ applied."""
        return self.request("POST", path, body=payload, mutating=True)

    def get_intent(self, intent_id: str) -> FinanceOSResult:
        """GET ``/api/intents/:id`` — source of truth for applied state."""
        if not intent_id or not str(intent_id).strip():
            raise FinanceOSError("intent_id is required")
        iid = str(intent_id).strip()
        return self.request(
            "GET",
            f"/api/intents/{iid}",
            mutating=False,
            intent_id=iid,
        )

    def poll_intent(
        self,
        intent_id: str,
        *,
        interval_seconds: float = 0.05,
        timeout_seconds: float = 5.0,
        terminal_states: frozenset[str] | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> FinanceOSResult:
        """Poll ``GET /api/intents/:id`` until terminal state or timeout.

        Never treat a prior 202 as applied — only the polled intent document
        decides. ``sleep`` / ``clock`` are injectable for unit tests.
        """
        if not intent_id or not str(intent_id).strip():
            raise FinanceOSError("intent_id is required")
        terminals = terminal_states or _DEFAULT_TERMINAL_STATES
        sleeper = sleep or time.sleep
        now = clock or time.monotonic
        deadline = now() + float(timeout_seconds)
        last: FinanceOSResult | None = None

        while True:
            last = self.get_intent(intent_id)
            state = _intent_state(last.parsed)
            if state and state in terminals:
                applied = state in ("applied", "confirmed")
                return FinanceOSResult(
                    status=last.status,
                    body=last.body,
                    parsed=last.parsed,
                    ok=last.ok,
                    applied=applied,
                    outcome="applied" if applied else f"terminal:{state}",
                    intent_id=intent_id,
                    detail=f"Reached terminal state {state!r}",
                )
            if now() >= deadline:
                return FinanceOSResult(
                    status=last.status if last else 0,
                    body=last.body if last else "",
                    parsed=last.parsed if last else None,
                    ok=False,
                    applied=False,
                    outcome="poll_timeout",
                    intent_id=intent_id,
                    detail=(
                        f"Timed out after {timeout_seconds}s waiting for "
                        f"terminal intent state (last={state!r})"
                    ),
                )
            sleeper(float(interval_seconds))
