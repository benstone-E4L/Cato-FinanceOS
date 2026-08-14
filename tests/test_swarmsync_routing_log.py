from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from cato.router import ModelRouter
from cato.routing_log import get_persistent_routing_history, record_routing_event
from cato.swarmsync import get_swarmsync_api_key, swarmsync_key_status


def test_swarmsync_key_prefers_canonical_vault_key(monkeypatch):
    vault = SimpleNamespace(get=lambda key: {"SWARMSYNC_API_KEY": "canonical", "SWARM_SYNC_API_KEY": "legacy"}.get(key))

    key, source = get_swarmsync_api_key(vault)
    status = swarmsync_key_status(vault)

    assert key == "canonical"
    assert source == "SWARMSYNC_API_KEY"
    assert status["present"] is True
    assert status["needs_normalization"] is False


def test_routing_log_persists_metadata_fields(tmp_path, monkeypatch):
    import cato.routing_log as routing_log

    monkeypatch.setattr(routing_log, "_DB_PATH", tmp_path / "routing.sqlite3")

    record_routing_event({
        "ts": 123.0,
        "provider": "swarmsync",
        "status": "ok",
        "routed_model": "openrouter/example/model",
        "raw_model": "example/model",
        "complexity": 0.25,
        "has_tools": False,
        "msg_count": 2,
        "http_status": 200,
        "content_chars": 42,
        "tool_call_count": 0,
        "metadata": {
            "request_id": "req-123",
            "timestamp": "2026-05-18T00:00:00+00:00",
            "routing_reason": "cost-efficient for simple prompt",
            "considered_models": ["a", "b"],
            "estimated_cost": 0.001,
            "actual_cost": 0.0008,
            "fallback_routing": False,
            "success": True,
        },
    })

    history = get_persistent_routing_history()

    assert len(history) == 1
    event = history[0]
    assert event["request_id"] == "req-123"
    assert event["routing_reason"] == "cost-efficient for simple prompt"
    assert event["considered_models"] == ["a", "b"]
    assert event["actual_cost"] == 0.0008
    assert event["success"] is True


# REWRITTEN (t10): the removed test drove ModelRouter._swarmsync_complete_message
# and asserted that a SwarmSync-routed model landed in the routing log — i.e. it
# encoded SwarmSync routing as required model-execution behaviour.  SwarmSync is
# no longer in the model-execution path, so the same guarantee (every routing
# decision is persisted with its model, rule, and reasoning) is now asserted
# against the direct-Anthropic policy path.  No live API call is made.


@pytest.mark.asyncio
async def test_direct_anthropic_completion_records_persistent_route(tmp_path, monkeypatch):
    import cato.routing_log as routing_log
    from cato.anthropic_client import AnthropicDirectClient
    from cato.model_policy import TaskDescriptor, TaskType

    monkeypatch.setattr(routing_log, "_DB_PATH", tmp_path / "routing.sqlite3")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")

    async def fake_transport(url, payload, headers):
        return 200, {
            "model": payload["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 120, "output_tokens": 8},
        }, {}

    router = ModelRouter(
        vault=None,
        anthropic_client=AnthropicDirectClient(
            vault=SimpleNamespace(get=lambda _key: uuid4().hex),
            transport=fake_transport,
        ),
    )
    model, message, decision = await router.complete_message(
        [{"role": "user", "content": "hello"}],
        TaskDescriptor(
            task_type=TaskType.RECONCILIATION_ANALYSIS,
            input_tokens=120,
            max_output_tokens=1024,
            cost_ceiling_usd=10.0,
            task_key="routing-log-test",
        ),
    )

    history = get_persistent_routing_history()
    assert model == "claude-sonnet-5"
    assert message["content"] == "ok"
    latest = history[-1]
    assert latest["provider"] == "anthropic"
    assert latest["routed_model"] == "claude-sonnet-5"
    assert latest["request_id"] == decision.decision_id
    assert "TASK-RECONCILIATION_ANALYSIS" in latest["routing_reason"]
    assert latest["estimated_cost"] == pytest.approx(decision.projected_cost_usd)
    assert latest["actual_cost"] is not None and latest["actual_cost"] > 0
    assert latest["success"] is True
