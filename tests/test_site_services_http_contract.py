"""HTTP contract tests: Cato bridge against a mock site-services API."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

from cato.tools.site_services_bridge import (
    draft_outreach,
    fetch_audit_summary,
    fetch_inbox,
    fetch_stuck,
    match_apply,
    match_preview,
    review_job,
    send_outreach,
)

SECRET = "test-internal-secret"
QUOTE_ID = "11111111-1111-4111-8111-111111111111"
JOB_ID = "22222222-2222-4222-8222-222222222222"
SUPPLIER_ID = "33333333-3333-4333-8333-333333333333"


def _auth_ok(request: web.Request) -> bool:
    return request.headers.get("Authorization") == f"Bearer {SECRET}"


async def _inbox(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response({
        "items": [{
            "quoteId": QUOTE_ID,
            "jobId": JOB_ID,
            "projectAddress": "1 Test St",
            "sku": "permit",
            "totalPriceUsd": 100,
            "applicantName": "Pat",
            "quoteUrl": f"https://example.com/quote/{QUOTE_ID}",
        }],
    })


async def _stuck(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response({
        "stuck": [{"jobId": JOB_ID, "reason": "stuck", "status": "OPEN", "vcapState": "HELD"}],
        "review": [{"jobId": SUPPLIER_ID, "reason": "manual_review", "status": "MANUAL_REVIEW"}],
        "counts": {"stuck": 1, "review": 1, "total": 2},
    })


async def _audit(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    since = request.query.get("since", "24h")
    return web.json_response({"since": since, "countByEventType": {"inbox_poll": 3}})


async def _draft(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    quote_id = request.match_info["quoteId"]
    if quote_id != QUOTE_ID:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({
        "subject": "Your quote",
        "html": "<p>Hi</p>",
        "recipient": "pat@example.com",
        "checkoutUrl": f"https://example.com/quote/{quote_id}",
    })


async def _send(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    body = await request.json()
    quote_id = request.match_info["quoteId"]
    if quote_id == "00000000-0000-4000-8000-000000000099":
        return web.json_response({"error": "Quote already sent"}, status=409)
    return web.json_response({"ok": True, "quoteId": quote_id, "approvedBy": body.get("approvedBy")})


async def _match_preview(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    body = await request.json()
    if body.get("jobId") != JOB_ID:
        return web.json_response({"matches": []})
    return web.json_response({
        "matches": [{"supplierId": SUPPLIER_ID, "supplierName": "Acme", "matchScore": 0.9}],
    })


async def _match_apply(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response({"ok": True})


async def _review(request: web.Request) -> web.Response:
    if not _auth_ok(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    action = request.match_info["action"]
    job_id = request.match_info["jobId"]
    if job_id == "00000000-0000-4000-8000-000000000088":
        return web.json_response({"error": "not reviewable"}, status=409)
    return web.json_response({"ok": True, "action": action, "jobId": job_id})


def _make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/cato/inbox", _inbox)
    app.router.add_get("/api/cato/jobs/stuck", _stuck)
    app.router.add_get("/api/cato/audit/summary", _audit)
    app.router.add_post("/api/cato/opportunities/{quoteId}/draft-outreach", _draft)
    app.router.add_post("/api/cato/opportunities/{quoteId}/send-outreach", _send)
    app.router.add_post("/api/match/preview", _match_preview)
    app.router.add_post("/api/match/apply", _match_apply)
    app.router.add_post("/api/cato/review/{jobId}/{action}", _review)
    return app


def _vault(base_url: str) -> MagicMock:
    vault = MagicMock()

    def _get(key: str) -> str:
        return {
            "SITE_SERVICES_INTERNAL_SECRET": SECRET,
            "SITE_SERVICES_BASE_URL": base_url,
        }.get(key, "")

    vault.get.side_effect = _get
    return vault


@pytest.fixture
async def mock_api():
    app = _make_app()
    server = TestServer(app)
    await server.start_server()
    client = TestClient(server)
    base = str(client.make_url(""))
    base = base.rstrip("/")
    yield base, _vault(base)
    await client.close()
    await server.close()


@pytest.mark.asyncio
async def test_fetch_inbox_contract(mock_api) -> None:
    _, vault = mock_api
    result = await fetch_inbox(vault)
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["items"][0]["quoteId"] == QUOTE_ID


@pytest.mark.asyncio
async def test_fetch_stuck_merges_arrays(mock_api) -> None:
    _, vault = mock_api
    result = await fetch_stuck(vault)
    assert result["ok"] is True
    assert result["count"] == 2
    ids = {j["jobId"] for j in result["jobs"]}
    assert JOB_ID in ids
    assert SUPPLIER_ID in ids


@pytest.mark.asyncio
async def test_fetch_audit_summary(mock_api) -> None:
    _, vault = mock_api
    result = await fetch_audit_summary(vault, since="24h")
    assert result["ok"] is True
    assert result["summary"]["countByEventType"]["inbox_poll"] == 3


@pytest.mark.asyncio
async def test_draft_outreach_success(mock_api) -> None:
    _, vault = mock_api
    result = await draft_outreach(vault, QUOTE_ID)
    assert result["ok"] is True
    assert result["draft"]["recipient"] == "pat@example.com"


@pytest.mark.asyncio
async def test_draft_outreach_rejects_bad_uuid(mock_api) -> None:
    _, vault = mock_api
    result = await draft_outreach(vault, "not-a-uuid")
    assert result["ok"] is False
    assert "UUID" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_send_outreach_409_double_send(mock_api) -> None:
    _, vault = mock_api
    result = await send_outreach(
        vault,
        "00000000-0000-4000-8000-000000000099",
        approved_by="test",
    )
    assert result["ok"] is False
    assert "409" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_match_preview_and_apply(mock_api) -> None:
    _, vault = mock_api
    preview = await match_preview(vault, JOB_ID)
    assert preview["ok"] is True
    assert preview["matches"][0]["supplierId"] == SUPPLIER_ID

    applied = await match_apply(vault, JOB_ID, SUPPLIER_ID, approved_by="test")
    assert applied["ok"] is True


@pytest.mark.asyncio
async def test_review_job_approve_and_reject(mock_api) -> None:
    _, vault = mock_api
    ok = await review_job(vault, JOB_ID, action="approve")
    assert ok["ok"] is True

    bad = await review_job(vault, "00000000-0000-4000-8000-000000000088", action="reject")
    assert bad["ok"] is False
    assert "409" in (bad.get("error") or "")


@pytest.mark.asyncio
async def test_unauthorized_when_secret_wrong(mock_api) -> None:
    base, _ = mock_api
    vault = MagicMock()
    vault.get.side_effect = lambda k: {
        "SITE_SERVICES_INTERNAL_SECRET": "wrong",
        "SITE_SERVICES_BASE_URL": base,
    }.get(k, "")
    result = await fetch_inbox(vault)
    assert result["ok"] is False
    assert "401" in (result.get("error") or "")
