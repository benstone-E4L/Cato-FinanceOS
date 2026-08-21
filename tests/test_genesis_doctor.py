"""tests/test_genesis_doctor.py — Task 1: live deploy probe + doctor.

Covers:
  - probe_live_agents(): success shapes (bare list, list-of-dicts,
    {"agents": [...]}), upstream non-200, invalid JSON, unrecognized shape,
    timeout, transport exception.
  - build_doctor_report(): allowlist-empty -> unhealthy; gateway-unreachable
    -> unhealthy; all 14 allowlisted+live -> healthy; partial live listing
    -> unhealthy with the correct missing_from_gateway set; "allowlisted"
    and "live_on_gateway" are reported as genuinely separate axes (a slug
    can be one without the other).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from cato.tools.genesis import (
    FAIL_CLOSED_ACCOUNTING_ALLOWLIST,
    build_doctor_report,
    probe_live_agents,
)


class MockConfig:
    def __init__(self, allowlist=None):
        self.genesis_agent_allowlist = list(allowlist or [])


class FakeResp:
    def __init__(self, status=200, body="[]"):
        self.status = status
        self._body = body

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, get_resp=None, get_exc=None):
        self._get_resp = get_resp
        self._get_exc = get_exc
        self.closed = False

    def get(self, *a, **kw):
        if self._get_exc is not None:
            raise self._get_exc
        return self._get_resp

    async def close(self):
        self.closed = True


ALL_14 = sorted(FAIL_CLOSED_ACCOUNTING_ALLOWLIST)


class TestProbeLiveAgents:
    def test_bare_list_of_strings(self):
        session = FakeSession(get_resp=FakeResp(200, json.dumps(ALL_14)))
        result = asyncio.run(probe_live_agents("http://test.local", session=session))
        assert result["ok"] is True
        assert set(result["slugs"]) == set(ALL_14)

    def test_list_of_dicts_with_slug_key(self):
        body = json.dumps([{"slug": s, "status": "deployed"} for s in ALL_14])
        session = FakeSession(get_resp=FakeResp(200, body))
        result = asyncio.run(probe_live_agents("http://test.local", session=session))
        assert result["ok"] is True
        assert set(result["slugs"]) == set(ALL_14)

    def test_agents_wrapped_object(self):
        body = json.dumps({"agents": ALL_14})
        session = FakeSession(get_resp=FakeResp(200, body))
        result = asyncio.run(probe_live_agents("http://test.local", session=session))
        assert result["ok"] is True
        assert set(result["slugs"]) == set(ALL_14)

    def test_upstream_non_200(self):
        session = FakeSession(get_resp=FakeResp(503, "down"))
        result = asyncio.run(probe_live_agents("http://test.local", session=session))
        assert result["ok"] is False
        assert result["error"] == "upstream_error"

    def test_invalid_json(self):
        session = FakeSession(get_resp=FakeResp(200, "not json"))
        result = asyncio.run(probe_live_agents("http://test.local", session=session))
        assert result["ok"] is False
        assert result["error"] == "invalid_response"

    def test_unrecognized_shape(self):
        session = FakeSession(get_resp=FakeResp(200, json.dumps(42)))
        result = asyncio.run(probe_live_agents("http://test.local", session=session))
        assert result["ok"] is False
        assert result["error"] == "unrecognized_response_shape"

    def test_timeout(self):
        session = FakeSession(get_exc=asyncio.TimeoutError())
        result = asyncio.run(probe_live_agents("http://test.local", session=session))
        assert result["ok"] is False
        assert result["error"] == "timeout"
        assert result["outcome_unknown"] is True

    def test_transport_exception(self):
        session = FakeSession(get_exc=ConnectionError("boom"))
        result = asyncio.run(probe_live_agents("http://test.local", session=session))
        assert result["ok"] is False
        assert result["error"] == "exception"


class TestBuildDoctorReport:
    def test_empty_allowlist_is_unhealthy_even_if_gateway_has_everything(self):
        live = {"ok": True, "slugs": ALL_14}
        report = build_doctor_report(MockConfig(allowlist=[]), live)
        assert report["allowlist_empty"] is True
        assert report["healthy"] is False
        # every row should show live_on_gateway True but allowlisted False
        assert all(r["live_on_gateway"] for r in report["rows"])
        assert all(not r["allowlisted"] for r in report["rows"])
        assert report["callable_count"] == 0

    def test_gateway_unreachable_is_unhealthy_even_with_full_allowlist(self):
        live = {"ok": False, "error": "timeout", "outcome_unknown": True}
        report = build_doctor_report(MockConfig(allowlist=ALL_14), live)
        assert report["gateway_reachable"] is False
        assert report["healthy"] is False
        assert report["missing_from_gateway"] == ALL_14
        assert report["callable_count"] == 0

    def test_all_14_allowlisted_and_live_is_healthy(self):
        live = {"ok": True, "slugs": ALL_14}
        report = build_doctor_report(MockConfig(allowlist=ALL_14), live)
        assert report["healthy"] is True
        assert report["callable_count"] == 14
        assert report["missing_from_gateway"] == []

    def test_partial_gateway_listing_reports_exact_missing_set(self):
        present = ALL_14[:10]
        live = {"ok": True, "slugs": present}
        report = build_doctor_report(MockConfig(allowlist=ALL_14), live)
        assert report["healthy"] is False
        assert set(report["missing_from_gateway"]) == set(ALL_14) - set(present)
        assert report["callable_count"] == 10

    def test_allowlisted_but_not_live_is_not_callable(self):
        live = {"ok": True, "slugs": []}
        report = build_doctor_report(MockConfig(allowlist=ALL_14), live)
        for row in report["rows"]:
            assert row["allowlisted"] is True
            assert row["live_on_gateway"] is False
            assert row["callable"] is False

    def test_live_but_not_allowlisted_is_not_callable(self):
        live = {"ok": True, "slugs": ALL_14}
        report = build_doctor_report(MockConfig(allowlist=[]), live)
        for row in report["rows"]:
            assert row["allowlisted"] is False
            assert row["live_on_gateway"] is True
            assert row["callable"] is False

    def test_underscored_alias_in_allowlist_still_matches(self):
        """Allowlist entries can use the underscored/_x402 wire form -- the
        canonicalization in genesis.py must still match it against the
        hyphenated FAIL_CLOSED_ACCOUNTING_ALLOWLIST slug."""
        aliased = [s.replace("-", "_") for s in ALL_14]
        live = {"ok": True, "slugs": ALL_14}
        report = build_doctor_report(MockConfig(allowlist=aliased), live)
        assert report["healthy"] is True
        assert report["callable_count"] == 14
