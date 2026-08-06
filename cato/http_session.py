"""
cato/http_session.py — Shared aiohttp session factory for outbound HTTPS.

Windows note: aiohttp's default async DNS resolver (aiodns/c-ares) frequently
fails with "Timeout while contacting DNS servers" / "Could not contact DNS
servers" even when PowerShell Resolve-DnsName and TCP/443 succeed.  Threaded
Resolver uses socket.getaddrinfo() via a thread pool (OS DNS), matching what
urllib and PowerShell use.  Prefer IPv4 to avoid broken IPv6 paths.
"""

from __future__ import annotations

import socket
from typing import Any, Optional

import aiohttp


def make_outbound_connector(**kwargs: Any) -> aiohttp.TCPConnector:
    """TCP connector with OS DNS (ThreadedResolver) and IPv4 preference."""
    opts: dict[str, Any] = {
        "family": socket.AF_INET,
        "resolver": aiohttp.ThreadedResolver(),
    }
    opts.update(kwargs)
    return aiohttp.TCPConnector(**opts)


def make_outbound_session(
    *,
    timeout: Optional[aiohttp.ClientTimeout] = None,
    **session_kwargs: Any,
) -> aiohttp.ClientSession:
    """ClientSession suitable for outbound API calls from the daemon."""
    return aiohttp.ClientSession(
        connector=make_outbound_connector(),
        timeout=timeout,
        **session_kwargs,
    )
