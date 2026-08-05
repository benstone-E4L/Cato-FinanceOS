from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from cato.gateway import Gateway


class _Budget:
    pass


class _Vault:
    pass


@pytest.mark.asyncio
async def test_request_response_returns_clean_reply():
    config = SimpleNamespace(agent_name="cato", context_budget_tokens=1024)
    gateway = Gateway(config, _Budget(), _Vault())
    gateway._start_time = 0.0

    async def _ensure_agent_loop() -> None:
        gateway._agent_loop = SimpleNamespace(
            run=lambda **_: asyncio.sleep(0, result=("Hello<tool_call>ignore</tool_call>", "", "model-x"))
        )

    gateway._ensure_agent_loop = _ensure_agent_loop  # type: ignore[assignment]

    result = await gateway.request_response("mcp:test", "hi", channel="mcp")

    assert result["reply"] == "Hello"
    assert result["model"] == "model-x"
    assert result["session_id"] == "mcp:test"
