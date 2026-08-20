"""End-to-end proof that a model-originated tool call is receipted and replayable."""

from __future__ import annotations

import json
from types import SimpleNamespace

import cato.agent_loop as agent_loop_mod
from cato.anthropic_client import AnthropicAPIError, classify_status
from cato.receipt import ReceiptWriter
from cato.replay import ReplayEngine
from tests.scheduler_gate_harness import build_scheduler_gate_env


async def test_retry_exhaustion_never_escapes_direct_anthropic_policy(
    tmp_path, monkeypatch,
) -> None:
    env = build_scheduler_gate_env(tmp_path, monkeypatch)
    env.gateway._vault.set("ANTHROPIC_API_KEY", "test-anthropic-key")

    async def unavailable(*_args, **_kwargs):
        raise AnthropicAPIError(classify_status(529), "test outage")

    legacy_calls = 0

    async def prohibited_legacy(*_args, **_kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        return "unsafe fallback", []

    monkeypatch.setattr(env.loop._router, "complete_message", unavailable)
    monkeypatch.setattr(env.loop, "_stream_collect", prohibited_legacy)

    final_text, _model, _agent = await env.loop.run(
        "retry-fail-closed", "Return a short status", "cato",
    )

    assert "Anthropic API unavailable after bounded retries" in final_text
    assert legacy_calls == 0


async def test_unexpected_direct_failure_never_uses_legacy_transport(
    tmp_path, monkeypatch,
) -> None:
    env = build_scheduler_gate_env(tmp_path, monkeypatch)
    env.gateway._vault.set("ANTHROPIC_API_KEY", "test-anthropic-key")

    async def broken(*_args, **_kwargs):
        raise RuntimeError("unexpected")

    legacy_calls = 0

    async def prohibited_legacy(*_args, **_kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        return "unsafe fallback", []

    monkeypatch.setattr(env.loop._router, "complete_message", broken)
    monkeypatch.setattr(env.loop, "_stream_collect", prohibited_legacy)

    final_text, _model, _agent = await env.loop.run(
        "unexpected-fail-closed", "Return a short status", "cato",
    )

    assert "Direct Anthropic routing failed" in final_text
    assert legacy_calls == 0


async def test_model_tool_call_produces_valid_audit_receipt_and_dry_replay(
    tmp_path, monkeypatch,
) -> None:
    env = build_scheduler_gate_env(tmp_path, monkeypatch)
    calls: list[dict] = []

    async def harmless_search(args: dict) -> str:
        calls.append(dict(args))
        return json.dumps({"ok": True, "results": ["grounded"]})

    monkeypatch.setitem(agent_loop_mod._TOOL_REGISTRY, "web.search", harmless_search)
    monkeypatch.setitem(agent_loop_mod._TOOL_SCHEMAS, "web.search", {
        "type": "function",
        "function": {
            "name": "web.search",
            "description": "Read-only evidence search",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    })
    env.gateway._vault.set("ANTHROPIC_API_KEY", "test-anthropic-key")
    turns = iter([
        {
            "content": "",
            "tool_calls": [{
                "id": "model-call-1",
                "type": "function",
                "function": {
                    "name": "web__search",
                    "arguments": json.dumps({"query": "E4L evidence"}),
                },
            }],
        },
        {"content": "Grounded result delivered.", "tool_calls": []},
    ])

    async def complete_message(*_args, **_kwargs):
        return "test-model", next(turns), SimpleNamespace(log_line=lambda: "test route")

    monkeypatch.setattr(env.loop._router, "complete_message", complete_message)

    final_text, _model, _agent = await env.loop.run(
        "model-audit-session", "Use a tool to find E4L evidence", "cato",
    )

    assert final_text == "Grounded result delivered."
    assert calls == [{"query": "E4L evidence"}]
    audit_log = env.loop._audit_log
    assert audit_log is not None
    assert audit_log.verify_chain("model-audit-session") is True

    receipt = ReceiptWriter().generate("model-audit-session", audit_log)
    assert [line.tool_name for line in receipt.actions] == ["web.search"]
    assert receipt.signed_hash

    replay = ReplayEngine(audit_log=audit_log).replay("model-audit-session", live=False)
    assert replay.total_steps == 1
    assert replay.matched == 1
    assert replay.steps[0].tool_name == "web.search"
