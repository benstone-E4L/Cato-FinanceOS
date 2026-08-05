"""Pulse + digest orchestration tests (no live Telegram or production API)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.core.site_services_pulse import (
    _item_id,
    _load_state,
    _save_state,
    _stuck_job_id,
    run_site_services_inbox_pulse,
)


def test_item_id_prefers_quote_id() -> None:
    assert _item_id({"quoteId": "q-99", "projectAddress": "x"}) == "q-99"


def test_stuck_job_id() -> None:
    assert _stuck_job_id({"jobId": "j-1"}) == "j-1"


def test_pulse_state_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "cato.core.site_services_pulse.get_data_dir",
        lambda: tmp_path,
    )
    _save_state({"seen_ids": ["a"], "seen_stuck_ids": ["j1"]})
    loaded = _load_state()
    assert loaded["seen_ids"] == ["a"]
    assert loaded["seen_stuck_ids"] == ["j1"]


@pytest.mark.asyncio
async def test_pulse_notifies_only_new_inbox_items(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("cato.core.site_services_pulse.get_data_dir", lambda: tmp_path)

    item = {
        "quoteId": "11111111-1111-4111-8111-111111111111",
        "projectAddress": "1 Main",
        "sku": "permit",
    }
    gateway = MagicMock()
    gateway.send = AsyncMock()
    gateway._vault = MagicMock()

    with patch(
        "cato.core.site_services_pulse.fetch_inbox",
        AsyncMock(return_value={"ok": True, "items": [item], "count": 1}),
    ), patch(
        "cato.core.site_services_pulse.fetch_stuck",
        AsyncMock(return_value={"ok": True, "jobs": [], "count": 0}),
    ), patch(
        "cato.core.site_services_pulse.notify_new_inbox_item",
        AsyncMock(return_value=True),
    ) as notify_inbox, patch(
        "cato.core.site_services_pulse.notify_stuck_job",
        AsyncMock(return_value=True),
    ) as notify_stuck, patch(
        "cato.core.site_services_pulse.send_telegram_message",
        AsyncMock(return_value=True),
    ):
        r1 = await run_site_services_inbox_pulse(gateway, notify=True)
        r2 = await run_site_services_inbox_pulse(gateway, notify=True)

    assert r1["ok"] is True
    assert r1["new_count"] == 1
    assert notify_inbox.await_count == 1
    assert r2["new_count"] == 0
    assert notify_inbox.await_count == 1
    notify_stuck.assert_not_awaited()


@pytest.mark.asyncio
async def test_pulse_notifies_new_stuck_jobs_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("cato.core.site_services_pulse.get_data_dir", lambda: tmp_path)

    stuck_job = {
        "jobId": "22222222-2222-4222-8222-222222222222",
        "projectAddress": "9 Oak",
        "reason": "manual_review",
    }
    gateway = MagicMock()
    gateway.send = AsyncMock()
    gateway._vault = MagicMock()

    with patch(
        "cato.core.site_services_pulse.fetch_inbox",
        AsyncMock(return_value={"ok": True, "items": [], "count": 0}),
    ), patch(
        "cato.core.site_services_pulse.fetch_stuck",
        AsyncMock(return_value={"ok": True, "jobs": [stuck_job], "count": 1}),
    ), patch(
        "cato.core.site_services_pulse.notify_stuck_job",
        AsyncMock(return_value=True),
    ) as notify_stuck, patch(
        "cato.core.site_services_pulse.send_telegram_message",
        AsyncMock(return_value=True),
    ):
        await run_site_services_inbox_pulse(gateway, notify=True)
        await run_site_services_inbox_pulse(gateway, notify=True)

    assert notify_stuck.await_count == 1


@pytest.mark.asyncio
async def test_pulse_skips_when_inbox_fetch_fails() -> None:
    gateway = MagicMock()
    gateway.send = AsyncMock()
    gateway._vault = MagicMock()

    with patch(
        "cato.core.site_services_pulse.fetch_inbox",
        AsyncMock(return_value={"ok": False, "error": "inbox HTTP 401"}),
    ), patch(
        "cato.core.site_services_pulse.send_telegram_message",
        AsyncMock(return_value=True),
    ) as tg:
        result = await run_site_services_inbox_pulse(gateway, notify=True)

    assert result["ok"] is False
    tg.assert_awaited()
    assert "401" in gateway.send.await_args.args[1]


@pytest.mark.asyncio
async def test_digest_includes_pending_approvals(tmp_path, monkeypatch) -> None:
    from cato.core.outbound_approval import OutboundApprovalStore
    from cato.core.site_services_digest import build_site_services_digest

    monkeypatch.setattr("cato.core.site_services_pulse.get_data_dir", lambda: tmp_path)
    store = OutboundApprovalStore(db_path=tmp_path / "cato.db")
    store.create(
        session_id="site-services",
        tool_name="site_services.send_outreach",
        args={"quoteId": "q-1"},
        preview="Draft for q-1",
    )

    vault = MagicMock()
    with patch("cato.core.site_services_digest.get_approval_store", return_value=store), patch(
        "cato.core.site_services_digest.fetch_inbox",
        AsyncMock(return_value={"ok": True, "count": 2}),
    ), patch(
        "cato.core.site_services_digest.fetch_stuck",
        AsyncMock(return_value={"ok": True, "count": 1}),
    ), patch(
        "cato.core.site_services_digest.fetch_audit_summary",
        AsyncMock(return_value={"ok": True, "summary": {"since": "24h", "countByEventType": {}}}),
    ):
        text = await build_site_services_digest(vault)

    assert "Morning Digest" in text
    assert "Inbox: 2" in text
    assert "Stuck jobs: 1" in text
    assert "site-services" in text.lower()
