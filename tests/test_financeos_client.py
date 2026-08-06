"""Unit tests for FinanceOS HTTP client (§8 traps).

Covers:
1. HTTP 503 + exact already-queued body → SUCCESS (dedupe)
2. Missing capability token → fail-closed on mutating calls
3. Money as Decimal/strings — floats rejected
4. poll_intent helper waits for terminal GET /api/intents/:id
Plus: no mint, Cato never approves.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from cato.integrations.financeos_client import (
    ALREADY_QUEUED_BODY,
    FinanceOSApproveForbidden,
    FinanceOSCapabilityRequired,
    FinanceOSClient,
    FinanceOSHttpResponse,
    FinanceOSMintForbidden,
    FinanceOSMoneyError,
    FinanceOSResult,
    is_already_queued_success,
    money_to_wire,
    parse_money,
)


def _transport_sequence(
    responses: list[FinanceOSHttpResponse],
) -> tuple[Any, list[tuple[Any, ...]]]:
    """Return (transport, call_log) that yields responses in order."""
    calls: list[tuple[Any, ...]] = []
    queue = list(responses)

    def transport(
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any] | None,
        timeout: float,
    ) -> FinanceOSHttpResponse:
        # Never assert on raw token values — only presence.
        calls.append((method, url, "Authorization" in headers, body, timeout))
        if not queue:
            raise AssertionError("Unexpected extra HTTP call")
        return queue.pop(0)

    return transport, calls


# ---------------------------------------------------------------------------
# 503-as-success
# ---------------------------------------------------------------------------


class TestAlreadyQueuedSuccess:
    def test_helper_matches_exact_body(self) -> None:
        assert is_already_queued_success(503, ALREADY_QUEUED_BODY) is True
        assert is_already_queued_success(503, f"  {ALREADY_QUEUED_BODY}  ") is True
        assert is_already_queued_success(503, "service unavailable") is False
        assert is_already_queued_success(500, ALREADY_QUEUED_BODY) is False
        assert is_already_queued_success(200, ALREADY_QUEUED_BODY) is False

    def test_submit_treats_503_queued_as_ok(self) -> None:
        transport, calls = _transport_sequence(
            [
                FinanceOSHttpResponse(status=503, body=ALREADY_QUEUED_BODY),
            ]
        )
        client = FinanceOSClient(
            "https://financeos.test",
            capability_token="cap-test-token",
            transport=transport,
        )
        result = client.submit_intent({"kind": "bill.create", "amount": "10.00"})
        assert result.ok is True
        assert result.deduplicated is True
        assert result.applied is False
        assert result.outcome == "queued_deduplicated"
        assert result.status == 503
        assert len(calls) == 1
        assert calls[0][0] == "POST"

    def test_other_503_is_error(self) -> None:
        transport, _ = _transport_sequence(
            [FinanceOSHttpResponse(status=503, body="upstream overloaded")]
        )
        client = FinanceOSClient(
            "https://financeos.test",
            capability_token="cap-test-token",
            transport=transport,
        )
        result = client.submit_intent({"kind": "bill.create"})
        assert result.ok is False
        assert result.deduplicated is False
        assert result.outcome == "error"


# ---------------------------------------------------------------------------
# Missing token fail-closed
# ---------------------------------------------------------------------------


class TestCapabilityTokenFailClosed:
    def test_mutating_without_token_raises(self) -> None:
        transport, calls = _transport_sequence([])
        client = FinanceOSClient("https://financeos.test", transport=transport)
        with pytest.raises(FinanceOSCapabilityRequired):
            client.submit_intent({"kind": "bill.create"})
        assert calls == []

    def test_request_post_without_token_raises(self) -> None:
        client = FinanceOSClient("https://financeos.test", transport=lambda *a: None)  # type: ignore[arg-type, return-value]
        with pytest.raises(FinanceOSCapabilityRequired):
            client.request("POST", "/api/intents", body={"x": 1})

    def test_get_without_token_still_allowed(self) -> None:
        transport, calls = _transport_sequence(
            [
                FinanceOSHttpResponse(
                    status=200,
                    body='{"id":"intent-1","state":"deferred"}',
                )
            ]
        )
        client = FinanceOSClient("https://financeos.test", transport=transport)
        result = client.get_intent("intent-1")
        assert result.ok is True
        assert result.applied is False
        assert len(calls) == 1
        assert calls[0][2] is False  # no Authorization header

    def test_mint_forbidden(self) -> None:
        client = FinanceOSClient("https://financeos.test", capability_token="x")
        with pytest.raises(FinanceOSMintForbidden):
            client.mint_capability_token(intent_id="anything")

    def test_approve_forbidden(self) -> None:
        client = FinanceOSClient("https://financeos.test", capability_token="x")
        with pytest.raises(FinanceOSApproveForbidden):
            client.approve(intent_id="intent-1")
        with pytest.raises(FinanceOSApproveForbidden):
            client.approve_intent("intent-1")


# ---------------------------------------------------------------------------
# Decimal money
# ---------------------------------------------------------------------------


class TestDecimalMoney:
    def test_parse_string_and_decimal(self) -> None:
        assert parse_money("12.34") == Decimal("12.34")
        assert parse_money(Decimal("1.00")) == Decimal("1.00")
        assert parse_money(5) == Decimal(5)

    def test_reject_float(self) -> None:
        with pytest.raises(FinanceOSMoneyError):
            parse_money(1.23)  # type: ignore[arg-type]
        with pytest.raises(FinanceOSMoneyError):
            money_to_wire(1.23)  # type: ignore[arg-type]

    def test_wire_serialization(self) -> None:
        assert money_to_wire(Decimal("10")) == "10.00"
        assert money_to_wire("9.5") == "9.50"

    def test_submit_rejects_float_amount(self) -> None:
        transport, calls = _transport_sequence([])
        client = FinanceOSClient(
            "https://financeos.test",
            capability_token="cap-test-token",
            transport=transport,
        )
        with pytest.raises(FinanceOSMoneyError):
            client.submit_intent({"kind": "bill.create", "amount": 10.5})
        assert calls == []

    def test_submit_stringifies_decimal_amount(self) -> None:
        transport, calls = _transport_sequence(
            [FinanceOSHttpResponse(status=202, body='{"id":"i1","state":"deferred"}')]
        )
        client = FinanceOSClient(
            "https://financeos.test",
            capability_token="cap-test-token",
            transport=transport,
        )
        result = client.submit_intent(
            {"kind": "bill.create", "amount": Decimal("42.5")}
        )
        assert result.ok is True
        assert result.applied is False
        assert result.outcome == "accepted_not_applied"
        assert calls[0][3] is not None
        assert calls[0][3]["amount"] == "42.50"
        assert isinstance(calls[0][3]["amount"], str)


# ---------------------------------------------------------------------------
# Poll helper — 202 ≠ applied
# ---------------------------------------------------------------------------


class TestPollHelper:
    def test_202_is_not_applied(self) -> None:
        transport, _ = _transport_sequence(
            [FinanceOSHttpResponse(status=202, body='{"id":"i9","state":"deferred"}')]
        )
        client = FinanceOSClient(
            "https://financeos.test",
            capability_token="cap-test-token",
            transport=transport,
        )
        result = client.submit_intent({"kind": "x"})
        assert result.status == 202
        assert result.ok is True
        assert result.applied is False
        assert result.outcome == "accepted_not_applied"

    def test_poll_until_terminal_applied(self) -> None:
        # "deferred" is terminal per §8 — use non-terminal "pending" first so
        # the poll helper actually waits for a later applied state.
        transport, calls = _transport_sequence(
            [
                FinanceOSHttpResponse(
                    status=200,
                    body='{"id":"intent-42","state":"pending"}',
                ),
                FinanceOSHttpResponse(
                    status=200,
                    body='{"id":"intent-42","state":"applied","amount":"10.00"}',
                ),
            ]
        )
        sleeps: list[float] = []
        ticks = {"n": 0.0}

        def clock() -> float:
            return ticks["n"]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            ticks["n"] += seconds

        client = FinanceOSClient("https://financeos.test", transport=transport)
        result = client.poll_intent(
            "intent-42",
            interval_seconds=0.01,
            timeout_seconds=1.0,
            sleep=sleep,
            clock=clock,
        )
        assert result.ok is True
        assert result.applied is True
        assert result.outcome == "applied"
        assert result.intent_id == "intent-42"
        assert len(calls) == 2
        assert sleeps == [0.01]
        # Money in response stays string — parse via helper
        assert parse_money(result.parsed["amount"]) == Decimal("10.00")

    def test_poll_stops_on_deferred_terminal(self) -> None:
        """§8: missing modules index → jobs end deferred; treat as terminal."""
        transport, calls = _transport_sequence(
            [
                FinanceOSHttpResponse(
                    status=200,
                    body='{"id":"intent-d","state":"deferred"}',
                ),
            ]
        )
        client = FinanceOSClient("https://financeos.test", transport=transport)
        result = client.poll_intent(
            "intent-d",
            interval_seconds=0.01,
            timeout_seconds=1.0,
            sleep=lambda _s: None,
            clock=lambda: 0.0,
        )
        assert result.ok is True
        assert result.applied is False
        assert result.outcome == "terminal:deferred"
        assert len(calls) == 1

    def test_poll_timeout(self) -> None:
        transport, calls = _transport_sequence(
            [
                FinanceOSHttpResponse(
                    status=200,
                    body='{"id":"intent-7","state":"pending"}',
                ),
                FinanceOSHttpResponse(
                    status=200,
                    body='{"id":"intent-7","state":"pending"}',
                ),
            ]
        )
        ticks = {"n": 0.0}

        def clock() -> float:
            return ticks["n"]

        def sleep(seconds: float) -> None:
            ticks["n"] += 10.0  # jump past deadline after first wait

        client = FinanceOSClient("https://financeos.test", transport=transport)
        result = client.poll_intent(
            "intent-7",
            interval_seconds=0.01,
            timeout_seconds=1.0,
            sleep=sleep,
            clock=clock,
        )
        assert result.ok is False
        assert result.applied is False
        assert result.outcome == "poll_timeout"
        assert len(calls) >= 1


class TestPublicDict:
    def test_result_public_dict_has_no_secrets(self) -> None:
        r = FinanceOSResult(
            status=503,
            body=ALREADY_QUEUED_BODY,
            parsed=ALREADY_QUEUED_BODY,
            ok=True,
            applied=False,
            outcome="queued_deduplicated",
            intent_id="i1",
            deduplicated=True,
        )
        d = r.public_dict()
        assert "Authorization" not in str(d)
        assert d["deduplicated"] is True
        assert d["applied"] is False
