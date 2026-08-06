"""Unit tests for cato.http_session — Windows-safe outbound aiohttp factory."""

from __future__ import annotations

import socket

import aiohttp
import pytest

from cato.http_session import make_outbound_connector, make_outbound_session


@pytest.mark.asyncio
async def test_make_outbound_connector_uses_threaded_resolver_and_ipv4():
    connector = make_outbound_connector()
    try:
        assert connector.family == socket.AF_INET
        assert isinstance(connector._resolver, aiohttp.ThreadedResolver)
    finally:
        await connector.close()


@pytest.mark.asyncio
async def test_make_outbound_session_wires_connector_and_timeout():
    timeout = aiohttp.ClientTimeout(total=12)
    session = make_outbound_session(timeout=timeout)
    try:
        assert not session.closed
        assert session.timeout.total == 12
        assert session.connector is not None
        assert session.connector.family == socket.AF_INET
        assert isinstance(session.connector._resolver, aiohttp.ThreadedResolver)
    finally:
        await session.close()
