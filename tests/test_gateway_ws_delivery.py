"""Regression proof for browser-chat acknowledgement and idempotency."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from cato.gateway import Gateway
from cato.ui.server import _DAEMON_TOKEN, _load_or_create_daemon_token, create_ui_app


class _Socket:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_str(self, raw: str) -> None:
        self.frames.append(json.loads(raw))


def _gateway() -> Gateway:
    gateway = Gateway.__new__(Gateway)
    gateway._cfg = MagicMock(agent_name="cato")
    gateway._accepted_client_messages = __import__("collections").OrderedDict()
    gateway._accepted_client_messages_max = 4096
    gateway.ingest = AsyncMock()
    return gateway


@pytest.mark.asyncio
async def test_message_is_acknowledged_before_downstream_work() -> None:
    gateway = _gateway()
    socket = _Socket()
    envelope = {
        "type": "message",
        "text": "prepare the close checklist",
        "session_id": "finance-session",
        "client_message_id": "message-0001",
    }

    async def assert_ack_already_sent(*_args, **_kwargs) -> None:
        assert socket.frames == [{
            "type": "accepted",
            "client_message_id": "message-0001",
            "duplicate": False,
        }]

    gateway.ingest.side_effect = assert_ack_already_sent
    await gateway.handle_ws_message(socket, json.dumps(envelope))

    gateway.ingest.assert_awaited_once()
    assert socket.frames == [{
        "type": "accepted",
        "client_message_id": "message-0001",
        "duplicate": False,
    }]


@pytest.mark.asyncio
async def test_duplicate_message_id_does_not_execute_twice() -> None:
    gateway = _gateway()
    first_socket = _Socket()
    replay_socket = _Socket()
    raw = json.dumps({
        "type": "message",
        "text": "prepare the close checklist",
        "session_id": "finance-session",
        "client_message_id": "message-0002",
    })

    await gateway.handle_ws_message(first_socket, raw)
    await gateway.handle_ws_message(replay_socket, raw)

    gateway.ingest.assert_awaited_once()
    assert replay_socket.frames[-1] == {
        "type": "accepted",
        "client_message_id": "message-0002",
        "duplicate": True,
    }


@pytest.mark.asyncio
async def test_invalid_client_message_id_fails_before_ingestion() -> None:
    gateway = _gateway()
    socket = _Socket()

    await gateway.handle_ws_message(socket, json.dumps({
        "type": "message", "text": "unsafe", "client_message_id": "bad id",
    }))

    gateway.ingest.assert_not_awaited()
    assert socket.frames[-1]["code"] == "invalid_client_message_id"


@pytest.mark.asyncio
async def test_browser_subprotocol_authenticates_without_url_credential() -> None:
    app = await create_ui_app(None)
    async with TestClient(TestServer(app)) as client:
        async with client.ws_connect(
            "/ws",
            protocols=[f"cato-auth.{_DAEMON_TOKEN}"],
            headers={"Origin": "http://127.0.0.1:5173"},
        ) as socket:
            assert "token=" not in str(socket._response.url)
            assert socket.protocol == f"cato-auth.{_DAEMON_TOKEN}"
            await socket.send_json({"type": "health"})
            assert (await socket.receive_json())["status"] == "ok"


@pytest.mark.asyncio
async def test_query_only_websocket_authentication_is_rejected() -> None:
    app = await create_ui_app(None)
    async with TestClient(TestServer(app)) as client:
        with pytest.raises(WSServerHandshakeError) as refused:
            await client.ws_connect(f"/ws?token={_DAEMON_TOKEN}")
        assert refused.value.status == 401


@pytest.mark.asyncio
async def test_unapproved_browser_origin_is_rejected_before_upgrade() -> None:
    app = await create_ui_app(None)
    async with TestClient(TestServer(app)) as client:
        with pytest.raises(WSServerHandshakeError) as refused:
            await client.ws_connect(
                "/ws",
                protocols=[f"cato-auth.{_DAEMON_TOKEN}"],
                headers={"Origin": "http://127.0.0.1:9999"},
            )
        assert refused.value.status == 403


def test_daemon_token_rotates_atomically_each_process_start(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("cato.platform.get_data_dir", lambda: tmp_path)

    first = _load_or_create_daemon_token()
    second = _load_or_create_daemon_token()

    assert len(first) == 64
    assert len(second) == 64
    assert first != second
    assert (tmp_path / "daemon.token").read_text(encoding="utf-8") == second
    assert not list(tmp_path.glob(".daemon.token.*.tmp"))
