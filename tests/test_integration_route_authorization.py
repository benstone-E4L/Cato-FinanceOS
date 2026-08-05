"""GAP 1 — the HTTP entry point cannot authorize a live write from a body field.

`approved`/`dry_run` in the POST body used to be passed straight into
IntegrationRuntime.action(), where `approved` was the sole gate before a live
third-party write (Stripe create_payment_link/create_checkout_session, GitHub
create_repo, Vercel create_deployment). That is the same defect shape already
removed from cato/tools/integration_tool.py, reached through a different door.

Authorization now comes only from a single-use, payload-bound execution grant
minted by OutboundApprovalStore.consume() when a human-approved ticket is
redeemed, or from an ApprovalContext passed by trusted Python.

No network I/O anywhere in this file.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from cato.core.approval_policy import (
    clear_execution_grants,
    compute_args_digest,
    grant_execution,
)

integration_routes = pytest.importorskip("cato.api.integration_routes")


class _RecordingRuntime:
    """Stands in for IntegrationRuntime so the dry_run/approved kwargs the route
    computes are observable without any credential or network I/O."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def action(self, integration_id, action_name, params, *, dry_run, approved, timeout):
        self.calls.append({
            "integration": integration_id,
            "action": action_name,
            "params": params,
            "dry_run": dry_run,
            "approved": approved,
        })
        return {"ok": True, "dry_run": dry_run, "performed": approved}


class TestActionRouteCannotSelfAuthorize(AioHTTPTestCase):
    PARAMS = {"line_items[0][price]": "price_fake_123", "line_items[0][quantity]": 1}

    async def get_application(self) -> web.Application:
        app = web.Application()
        integration_routes.register_routes(app)
        return app

    def setUp(self) -> None:
        super().setUp()
        clear_execution_grants()

    def tearDown(self) -> None:
        clear_execution_grants()
        super().tearDown()

    async def test_body_supplied_approved_flag_never_reaches_the_transport(self) -> None:
        live_calls: list[dict] = []

        def _fake_request_json(*, method, url, headers, body, body_format, timeout):
            # Reaching this at all means a live third-party write was attempted.
            live_calls.append({"method": method, "url": url})
            raise AssertionError("live transport must not be reached")

        with patch("cato.integrations.runtime.request_json", _fake_request_json):
            resp = await self.client.post(
                "/api/integrations/stripe/actions/create_payment_link",
                json={
                    "payload": self.PARAMS,
                    "dry_run": False,   # caller-supplied
                    "approved": True,   # caller-supplied — the exact bypass shape
                },
            )

        assert resp.status == 403, await resp.text()
        data = await resp.json()
        assert data["error"] == "approval_required"
        assert data["approval_required"] is True
        assert data["performed"] is False
        assert data["dry_run"] is True
        assert live_calls == [], "a live third-party write was reached with no approval ticket"

    async def test_string_truthy_approved_is_also_refused(self) -> None:
        resp = await self.client.post(
            "/api/integrations/github/actions/create_repo",
            json={"payload": {"name": "x"}, "approved": "true", "dry_run": "no"},
        )
        assert resp.status == 403, await resp.text()
        assert (await resp.json())["error"] == "approval_required"

    async def test_a_redeemed_grant_is_the_only_thing_that_authorizes_execution(self) -> None:
        runtime = _RecordingRuntime()
        grant_args = {
            "integration": "stripe",
            "action": "create_payment_link",
            "params": self.PARAMS,
        }
        grant_execution(
            "integration_action",
            compute_args_digest("integration.action", grant_args),
        )

        with patch.object(integration_routes, "_runtime", return_value=runtime):
            resp = await self.client.post(
                "/api/integrations/stripe/actions/create_payment_link",
                # No `approved` field anywhere — the grant is the authorization.
                json={"payload": self.PARAMS},
            )
            assert resp.status == 200, await resp.text()
            assert runtime.calls[-1]["dry_run"] is False
            assert runtime.calls[-1]["approved"] is True

            # Single use: the identical request now has no grant behind it.
            replay = await self.client.post(
                "/api/integrations/stripe/actions/create_payment_link",
                json={"payload": self.PARAMS, "approved": True},
            )
        assert replay.status == 403, await replay.text()
        assert len(runtime.calls) == 1

    async def test_a_grant_for_a_different_payload_does_not_authorize_this_one(self) -> None:
        runtime = _RecordingRuntime()
        approved_args = {
            "integration": "stripe",
            "action": "create_payment_link",
            "params": {"line_items[0][price]": "price_cheap"},
        }
        grant_execution(
            "integration_action",
            compute_args_digest("integration.action", approved_args),
        )

        with patch.object(integration_routes, "_runtime", return_value=runtime):
            resp = await self.client.post(
                "/api/integrations/stripe/actions/create_payment_link",
                json={"payload": {"line_items[0][price]": "price_expensive"}, "approved": True},
            )
        assert resp.status == 403, await resp.text()
        assert runtime.calls == []

    async def test_an_unauthorized_plain_request_still_gets_its_plan(self) -> None:
        """No silent downgrade in the other direction either: a caller that did
        not ask for a live write still gets the dry-run plan it asked for."""
        runtime = _RecordingRuntime()
        with patch.object(integration_routes, "_runtime", return_value=runtime):
            resp = await self.client.post(
                "/api/integrations/github/actions/create_issue",
                json={"payload": {"owner": "acme", "repo": "private", "title": "plan"}},
            )
        assert resp.status == 200, await resp.text()
        assert runtime.calls[-1]["dry_run"] is True
        assert runtime.calls[-1]["approved"] is False


class TestActionRouteIsOperatorAuthenticated(AioHTTPTestCase):
    """Evidence for the severity call: this endpoint is behind the daemon token.

    cato/ui/server.py builds the app with `middlewares=[cors_middleware,
    auth_token_middleware]` and registers these routes through
    register_all_routes(); only GET /health, /, /coding-agent and /api/activity
    are token-exempt, so a POST always requires a valid X-Cato-Token.
    """

    async def get_application(self) -> web.Application:
        from cato.ui.server import auth_token_middleware

        app = web.Application(middlewares=[auth_token_middleware])
        integration_routes.register_routes(app)
        return app

    async def test_post_without_the_daemon_token_is_rejected(self) -> None:
        resp = await self.client.post(
            "/api/integrations/stripe/actions/create_payment_link",
            json={"payload": {}, "approved": True},
        )
        assert resp.status == 401

    async def test_post_with_a_wrong_token_is_rejected(self) -> None:
        resp = await self.client.post(
            "/api/integrations/stripe/actions/create_payment_link",
            json={"payload": {}},
            headers={"X-Cato-Token": "not-the-daemon-token"},
        )
        assert resp.status == 401

    async def test_the_token_gets_you_in_but_not_past_the_approval_gate(self) -> None:
        from cato.ui.server import _DAEMON_TOKEN

        clear_execution_grants()
        resp = await self.client.post(
            "/api/integrations/stripe/actions/create_payment_link",
            json={"payload": {}, "approved": True},
            headers={"X-Cato-Token": _DAEMON_TOKEN},
        )
        assert resp.status == 403, await resp.text()
        assert (await resp.json())["error"] == "approval_required"
