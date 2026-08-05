"""Telegram callback routing for site-services buttons."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.core.outbound_approval import OutboundApprovalStore
from cato.tools.site_services_bridge import (
    CB_DRAFT,
    CB_DENY,
    CB_MATCH,
    CB_REVIEW_NO,
    CB_REVIEW_OK,
    CB_SKIP,
    handle_site_services_callback,
)


def _query(callback_data: str) -> MagicMock:
    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message.reply_text = AsyncMock()
    return query


def _context(gateway: MagicMock | None = None) -> MagicMock:
    ctx = MagicMock()
    app = MagicMock()
    app.bot_data = {"cato_gateway": gateway or MagicMock(_vault=MagicMock())}
    ctx.application = app
    return ctx


@pytest.mark.asyncio
async def test_skip_callback_clears_keyboard() -> None:
    update = MagicMock()
    update.callback_query = _query(f"{CB_SKIP}quote-1")
    await handle_site_services_callback(update, _context())
    update.callback_query.edit_message_reply_markup.assert_awaited()
    assert "Skipped" in update.callback_query.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_review_approve_calls_api() -> None:
    from cato.tools import site_services_bridge as bridge

    update = MagicMock()
    job_id = "11111111-1111-4111-8111-111111111111"
    update.callback_query = _query(f"{CB_REVIEW_OK}{job_id}")
    vault = MagicMock()

    with patch.object(
        bridge,
        "review_job",
        AsyncMock(return_value={"ok": True}),
    ) as review:
        await handle_site_services_callback(update, _context(MagicMock(_vault=vault)))

    review.assert_awaited_once_with(vault, job_id, action="approve")


@pytest.mark.asyncio
async def test_review_reject_calls_api() -> None:
    from cato.tools import site_services_bridge as bridge

    update = MagicMock()
    job_id = "22222222-2222-4222-8222-222222222222"
    update.callback_query = _query(f"{CB_REVIEW_NO}{job_id}")
    vault = MagicMock()

    with patch.object(
        bridge,
        "review_job",
        AsyncMock(return_value={"ok": True}),
    ) as review:
        await handle_site_services_callback(update, _context(MagicMock(_vault=vault)))

    review.assert_awaited_once_with(vault, job_id, action="reject")


@pytest.mark.asyncio
async def test_approve_send_executes_send_outreach(tmp_path) -> None:
    from cato.tools import site_services_bridge as bridge

    store = OutboundApprovalStore(db_path=tmp_path / "cato.db")
    approval = store.create(
        session_id="site-services",
        tool_name="site_services.send_outreach",
        args={"quoteId": "11111111-1111-4111-8111-111111111111"},
        preview="send me",
    )

    update = MagicMock()
    update.callback_query = _query(f"ss_ok_{approval.id}")
    vault = MagicMock()

    with patch("cato.core.outbound_approval.get_approval_store", return_value=store), patch.object(
        bridge,
        "send_outreach",
        AsyncMock(return_value={"ok": True}),
    ) as send:
        await handle_site_services_callback(update, _context(MagicMock(_vault=vault)))

    send.assert_awaited_once()
    assert store.get(approval.id).status == "approved"


@pytest.mark.asyncio
async def test_deny_send_does_not_call_api(tmp_path) -> None:
    from cato.tools import site_services_bridge as bridge

    store = OutboundApprovalStore(db_path=tmp_path / "cato.db")
    approval = store.create(
        session_id="site-services",
        tool_name="site_services.send_outreach",
        args={"quoteId": "11111111-1111-4111-8111-111111111111"},
        preview="send me",
    )

    update = MagicMock()
    update.callback_query = _query(f"{CB_DENY}{approval.id}")

    with patch("cato.core.outbound_approval.get_approval_store", return_value=store), patch.object(
        bridge,
        "send_outreach",
        AsyncMock(),
    ) as send:
        await handle_site_services_callback(update, _context())

    send.assert_not_awaited()
    assert store.get(approval.id).status == "denied"


@pytest.mark.asyncio
async def test_match_preview_no_candidates() -> None:
    from cato.tools import site_services_bridge as bridge

    job_id = "33333333-3333-4333-8333-333333333333"
    update = MagicMock()
    update.callback_query = _query(f"{CB_MATCH}{job_id}")
    query = update.callback_query

    with patch.object(
        bridge,
        "match_preview",
        AsyncMock(return_value={"ok": True, "matches": []}),
    ):
        await handle_site_services_callback(update, _context())

    assert "No supplier matches" in query.message.reply_text.await_args.args[0]
