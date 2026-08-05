"""Site-services bridge helpers and approval flow."""



from __future__ import annotations



import asyncio
from unittest.mock import AsyncMock, MagicMock, patch



import aiohttp
import pytest



from cato.core.outbound_approval import OutboundApprovalStore

from cato.tools.site_services_bridge import (
    CB_DRAFT,
    CB_REVIEW_OK,
    _normalize_stuck_jobs,
    fetch_inbox,
    fetch_stuck,
    format_inbox_item_text,
    format_stuck_job_text,
    inbox_item_keyboard,
    resolve_site_services_config,
    stuck_job_keyboard,
)





def test_resolve_config_missing_secret() -> None:

    vault = MagicMock()

    vault.get.return_value = ""

    base, secret, err = resolve_site_services_config(vault)

    assert base is None

    assert secret is None

    assert err is not None





def test_resolve_config_ok() -> None:

    vault = MagicMock()



    def _get(key: str) -> str:

        return {

            "SITE_SERVICES_INTERNAL_SECRET": "sekret",

            "SITE_SERVICES_BASE_URL": "https://example.com",

        }.get(key, "")



    vault.get.side_effect = _get

    base, secret, err = resolve_site_services_config(vault)

    assert err is None

    assert secret == "sekret"

    assert base == "https://example.com"


def _configured_vault() -> MagicMock:
    vault = MagicMock()

    def _get(key: str) -> str:
        return {
            "SITE_SERVICES_INTERNAL_SECRET": "sekret",
            "SITE_SERVICES_BASE_URL": "https://example.com",
        }.get(key, "")

    vault.get.side_effect = _get
    return vault


@pytest.mark.asyncio
async def test_fetch_inbox_network_failure_returns_error() -> None:
    from cato.tools import site_services_bridge as bridge

    with patch.object(
        bridge,
        "_fetch_json",
        AsyncMock(side_effect=aiohttp.ClientConnectionError("connection failed")),
    ):
        result = await fetch_inbox(_configured_vault())

    assert result["ok"] is False
    assert result["items"] == []
    assert "network error" in result["error"]


@pytest.mark.asyncio
async def test_fetch_stuck_timeout_returns_error() -> None:
    from cato.tools import site_services_bridge as bridge

    with patch.object(
        bridge,
        "_fetch_json",
        AsyncMock(side_effect=asyncio.TimeoutError()),
    ):
        result = await fetch_stuck(_configured_vault())

    assert result["ok"] is False
    assert result["jobs"] == []
    assert result["error"].startswith("network error:")


def test_format_inbox_item() -> None:

    text = format_inbox_item_text({

        "quoteId": "q-1",

        "projectAddress": "123 Main",

        "sku": "permit-fee",

        "totalPriceUsd": 499,

        "applicantName": "Jane",

    })

    assert "123 Main" in text

    assert "permit-fee" in text

    assert "q-1" in text





def test_inbox_keyboard_has_draft_and_skip() -> None:

    kb = inbox_item_keyboard({"quoteId": "abc-123", "jobId": "job-9"})

    flat = [btn.callback_data for row in kb.inline_keyboard for btn in row]

    assert f"{CB_DRAFT}abc-123" in flat

    assert any(d.startswith("ss_skp_") for d in flat)

    assert any(d.startswith("ss_mtc_") for d in flat)





@pytest.mark.asyncio

async def test_draft_outreach_queues_approval(tmp_path) -> None:

    from cato.tools import site_services_bridge as bridge



    store = OutboundApprovalStore(db_path=tmp_path / "cato.db")

    query = MagicMock()

    query.message.reply_text = AsyncMock()

    query.edit_message_reply_markup = AsyncMock()



    vault = MagicMock()

    draft_body = {

        "subject": "Your permit quote",

        "html": "<p>Hello</p>",

        "recipient": "jane@example.com",

        "checkoutUrl": "https://pay.example/q",

    }



    with patch("cato.core.outbound_approval.get_approval_store", return_value=store):
        with patch.object(bridge, "draft_outreach", AsyncMock(return_value={"ok": True, "draft": draft_body})):
            await bridge._handle_draft_outreach(query, vault, "quote-42")



    pending = store.list_pending()

    assert len(pending) == 1

    assert pending[0].tool_name == "site_services.send_outreach"

    assert pending[0].args["quoteId"] == "quote-42"

    query.message.reply_text.assert_awaited()


def test_normalize_stuck_jobs_merges_stuck_and_review() -> None:
    payload = {
        "stuck": [{"jobId": "a", "reason": "stuck"}],
        "review": [{"jobId": "b", "reason": "manual_review"}],
    }
    jobs = _normalize_stuck_jobs(payload)
    ids = {j["jobId"] for j in jobs}
    assert ids == {"a", "b"}


def test_stuck_job_keyboard_has_review_buttons() -> None:
    kb = stuck_job_keyboard({"jobId": "job-123"})
    flat = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert f"{CB_REVIEW_OK}job-123" in flat
    assert any(d.startswith("ss_rno_") for d in flat)


def test_stuck_job_keyboard_accepts_generic_id() -> None:
    kb = stuck_job_keyboard({"id": "job-456"})
    flat = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert f"{CB_REVIEW_OK}job-456" in flat
    assert "ss_rno_job-456" in flat


def test_format_stuck_job() -> None:
    text = format_stuck_job_text({
        "jobId": "j-1",
        "projectAddress": "9 Oak St",
        "sku": "permit",
        "status": "MANUAL_REVIEW",
        "vcapState": "HELD",
        "reason": "manual_review",
    })
    assert "9 Oak St" in text
    assert "j-1" in text

