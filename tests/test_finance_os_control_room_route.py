"""Tests for GET /api/finance-os/control-room (CHUNK_5_FINANCE_VIEW).

Covers the three spec-required scenarios: live happy path, an auth-failure
("capability-token mint doesn't exist yet", O2O-FOS-1) treated as stale rather
than "no data", and a fully-unreachable failure — none of which may ever
crash the route or write anything back to FinanceOS.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

import cato.integrations.financeos_client as financeos_client_module
from cato.integrations.financeos_client import FinanceOSHttpResponse
from cato.ui import server as server_module
from cato.ui.server import create_ui_app


def _auth_headers() -> dict[str, str]:
    return {"X-Cato-Token": server_module._DAEMON_TOKEN}


@pytest.fixture(autouse=True)
def isolated_memory_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the control-room cache at a throwaway per-test SQLite file."""
    data_dir = tmp_path / "cato-data"
    monkeypatch.setattr("cato.platform.get_data_dir", lambda: data_dir)
    yield


@pytest.fixture(autouse=True)
def set_control_room_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FINANCEOS_CONTROL_ROOM_URL", "http://127.0.0.1:3001")
    monkeypatch.delenv("FINANCEOS_CAPABILITY_TOKEN", raising=False)


def _install_transport(monkeypatch: pytest.MonkeyPatch, responder):
    monkeypatch.setattr(financeos_client_module, "_default_transport", responder)


@pytest.mark.asyncio
async def test_request_timeout_stays_inside_desktop_fallback_budget(monkeypatch):
    observed_timeouts: list[float] = []

    def responder(method, url, headers, body, timeout):
        observed_timeouts.append(timeout)
        return FinanceOSHttpResponse(status=200, body="{}")

    _install_transport(monkeypatch, responder)
    await server_module._fetch_finance_control_room()

    assert observed_timeouts == [2.0, 2.0]
    assert sum(observed_timeouts) < 6.0


@pytest.mark.asyncio
async def test_happy_path_live_data_renders_without_staleness_flag(monkeypatch):
    def responder(method, url, headers, body, timeout):
        if "integrations-health" in url:
            return FinanceOSHttpResponse(status=200, body='{"xero": "ok", "stripe": "ok"}')
        return FinanceOSHttpResponse(
            status=200,
            body='{"close_status": "open", "holds": 2, "write_gate_enabled": false}',
        )

    _install_transport(monkeypatch, responder)
    app = await create_ui_app(gateway=None)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/finance-os/control-room", headers=_auth_headers())
        assert resp.status == 200
        payload = await resp.json()

    assert payload["connected"] is True
    assert payload["stale"] is False
    assert payload["data"]["control_room"]["close_status"] == "open"
    assert payload["data"]["control_room"]["holds"] == 2
    assert payload["data"]["integrations_health"]["xero"] == "ok"


@pytest.mark.asyncio
async def test_auth_failure_falls_back_to_stale_not_treated_as_no_data(monkeypatch):
    """O2O-FOS-1: no capability-token mint endpoint exists yet. A 401/403 from
    FinanceOS must fail closed into the stale-marked state, not render as an
    empty/successful "no data" response."""

    def live_responder(method, url, headers, body, timeout):
        if "integrations-health" in url:
            return FinanceOSHttpResponse(status=200, body='{"xero": "ok"}')
        return FinanceOSHttpResponse(status=200, body='{"close_status": "open", "holds": 1}')

    def auth_failure_responder(method, url, headers, body, timeout):
        return FinanceOSHttpResponse(status=401, body='{"error": "capability token required"}')

    app = await create_ui_app(gateway=None)

    # First call succeeds and seeds the cache.
    _install_transport(monkeypatch, live_responder)
    async with TestClient(TestServer(app)) as client:
        first = await client.get("/api/finance-os/control-room", headers=_auth_headers())
        assert (await first.json())["connected"] is True

        # Second call: FinanceOS now refuses with 401 (capability token gate).
        _install_transport(monkeypatch, auth_failure_responder)
        second = await client.get("/api/finance-os/control-room", headers=_auth_headers())
        assert second.status == 200
        payload = await second.json()

    assert payload["connected"] is False
    assert payload["stale"] is True
    # Must serve the last-known-good value, not an empty "no data" shape.
    assert payload["data"] == {"control_room": {"close_status": "open", "holds": 1}, "integrations_health": {"xero": "ok"}}
    assert payload["cached_at"]


@pytest.mark.asyncio
async def test_fully_unreachable_renders_stale_with_no_cache_and_no_crash(monkeypatch):
    requested_urls: list[str] = []

    def unreachable_responder(method, url, headers, body, timeout):
        requested_urls.append(url)
        return FinanceOSHttpResponse(status=0, body='{"error": "Connection refused"}')

    _install_transport(monkeypatch, unreachable_responder)
    app = await create_ui_app(gateway=None)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/finance-os/control-room", headers=_auth_headers())
        assert resp.status == 200
        payload = await resp.json()

    assert payload["connected"] is False
    assert payload["stale"] is True
    assert payload["data"] is None
    assert payload["cached_at"] is None
    assert len(requested_urls) == 1
    assert requested_urls[0].endswith("/api/v1/control-room")
