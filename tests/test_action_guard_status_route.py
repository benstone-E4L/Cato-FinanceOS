"""GAP 4 — the dashboard may only report controls that are actually enforced.

GET /api/action-guard/status used to return three rows hardcoded `active: True`
plus a hardcoded `autonomy_level: 0.5`, from a handler that consulted nothing.
A control that exists only as a UI panel is worse than no control: it reports
safety it does not provide.

Every row's `active` bit is now the result of exercising the real control, and
only active rows appear in `checks`. These tests prove the bit is computed by
flipping each underlying control and watching the row leave `checks`.
"""

from __future__ import annotations

from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from cato.audit.action_guard import GuardDecision
from cato.config import CatoConfig
from cato.ui.server import _DAEMON_TOKEN, create_ui_app

EXPECTED_RULES = {
    "Irreversibility check",
    "Spending ceiling check",
    "High-risk tool approval",
}


class _AlwaysProceedGuard:
    """An ActionGuard that enforces nothing."""

    def check_before_execute(self, *_a, **_k) -> GuardDecision:
        return GuardDecision(
            proceed=True, requires_confirmation=False,
            reason="stub: enforces nothing", applied_checks=["stub"],
        )


class TestActionGuardStatusReportsOnlyEnforcedControls(AioHTTPTestCase):
    async def get_application(self):
        return await create_ui_app(gateway=None)

    async def _status(self) -> dict:
        resp = await self.client.get(
            "/api/action-guard/status", headers={"X-Cato-Token": _DAEMON_TOKEN},
        )
        assert resp.status == 200, await resp.text()
        return await resp.json()

    async def test_the_endpoint_is_token_protected(self) -> None:
        resp = await self.client.get("/api/action-guard/status")
        assert resp.status == 401

    async def test_every_reported_check_is_active_and_carries_evidence(self) -> None:
        data = await self._status()

        assert data["checks"], "no control reported as enforced"
        for check in data["checks"]:
            assert check["active"] is True, check
            assert check["evidence"], f"{check['rule']} claims active with no evidence"
        assert {c["rule"] for c in data["checks"]} <= EXPECTED_RULES

    async def test_the_three_rows_are_all_backed_by_real_enforcement(self) -> None:
        """Default config: ActionGuard blocks an irreversible probe, budget caps
        are configured, and the approval policy gates integration.action."""
        data = await self._status()
        assert {c["rule"] for c in data["checks"]} == EXPECTED_RULES
        assert data["inactive_checks"] == []

    async def test_autonomy_level_is_read_from_config_not_hardcoded(self) -> None:
        cfg = CatoConfig()
        cfg.autonomy_level = 0.85
        with patch.object(CatoConfig, "load", return_value=cfg):
            data = await self._status()
        assert data["autonomy_level"] == 0.85

    async def test_a_guard_that_enforces_nothing_is_not_reported_as_active(self) -> None:
        """The proof that row 1's `active` is a probe result, not a literal."""
        with patch("cato.audit.action_guard.ActionGuard", _AlwaysProceedGuard):
            data = await self._status()

        assert "Irreversibility check" not in {c["rule"] for c in data["checks"]}
        row = next(c for c in data["inactive_checks"] if c["rule"] == "Irreversibility check")
        assert row["active"] is False
        assert "proceed=True" in row["evidence"]

    async def test_uncapped_spend_is_not_reported_as_a_spending_ceiling(self) -> None:
        """The proof that row 2's `active` reflects real caps."""
        cfg = CatoConfig()
        cfg.daily_cap = 0.0
        cfg.monthly_cap = 0.0
        with patch.object(CatoConfig, "load", return_value=cfg):
            data = await self._status()

        assert "Spending ceiling check" not in {c["rule"] for c in data["checks"]}

    async def test_the_spend_row_does_not_claim_the_unenforced_session_cap(self) -> None:
        """cato/budget.py enforces daily + monthly; session_cap is informational
        only. The old row claimed 'per-session and monthly spend caps'."""
        data = await self._status()
        row = next(c for c in data["checks"] if c["rule"] == "Spending ceiling check")
        assert "daily" in row["description"]
        assert "monthly" in row["description"]
        assert "not enforced" in row["description"]

    async def test_the_live_budget_is_preferred_over_configured_caps(self) -> None:
        class _Budget:
            def get_status(self):
                return {
                    "daily_spend": 1.25, "daily_cap": 3.0,
                    "monthly_spend": 4.5, "monthly_cap": 20.0,
                }

        class _Gateway:
            _budget = _Budget()
            _cfg = None

        app = await create_ui_app(gateway=_Gateway())
        handler = next(
            r.handler for r in app.router.routes()
            if getattr(r.resource, "canonical", "") == "/api/action-guard/status"
        )

        class _Req:
            pass

        resp = await handler(_Req())
        import json as _json
        data = _json.loads(resp.text)
        row = next(c for c in data["checks"] if c["rule"] == "Spending ceiling check")
        assert "live budget" in row["evidence"]
        assert "$1.25/$3.00" in row["evidence"]
