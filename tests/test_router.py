from __future__ import annotations

from cato.router import ModelRouter


class DummyVault:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, key: str) -> str:
        return self._values.get(key, "")


async def test_legacy_complete_fails_closed_without_model_selection() -> None:
    router = ModelRouter(vault=DummyVault({"OPENAI_API_KEY": "stored-but-inert"}))
    assert not hasattr(router, "select_model")
    assert not hasattr(router, "_complete_single")
    with __import__("pytest").raises(RuntimeError, match="complete_message"):
        await router.complete([{"role": "user", "content": "hello"}])


async def test_caller_supplied_model_is_rejected_by_signature() -> None:
    router = ModelRouter(vault=DummyVault({"OPENAI_API_KEY": "stored-but-inert"}))
    with __import__("pytest").raises(TypeError):
        await router.complete([], "openai/gpt-4o-mini")


def test_routing_decision_persists_to_sqlite_log(tmp_path, monkeypatch) -> None:
    import cato.router as router_mod
    import cato.routing_log as routing_log

    monkeypatch.setattr(routing_log, "_DB_PATH", tmp_path / "routing_log.sqlite3")
    router_mod._routing_history.clear()

    router_mod._record_routing_decision(
        {
            "provider": "swarmsync",
            "success": True,
            "chosen_model": "openrouter/minimax/minimax-m2.5",
            "raw_model": "minimax/minimax-m2.5",
            "request_id": "req-router-1",
            "routing_reason": "simple request routed to economy model",
            "considered_models": ["minimax/minimax-m2.5", "gemini/flash"],
            "estimated_cost": "0.0012",
            "actual_cost": 0.001,
            "fallback_routing": False,
            "complexity_score": 0.42,
            "history_length": 3,
            "has_tools": True,
            "http_status": 200,
            "content_chars": 12,
            "tool_call_count": 1,
        }
    )

    history = routing_log.get_persistent_routing_history(limit=10)
    assert len(history) == 1
    assert history[0]["provider"] == "swarmsync"
    assert history[0]["status"] == "ok"
    assert history[0]["routed_model"] == "openrouter/minimax/minimax-m2.5"
    assert history[0]["tool_call_count"] == 1
    assert history[0]["request_id"] == "req-router-1"
    assert history[0]["routing_reason"] == "simple request routed to economy model"
    assert history[0]["considered_models"] == ["minimax/minimax-m2.5", "gemini/flash"]
    assert history[0]["estimated_cost"] == 0.0012
    assert history[0]["actual_cost"] == 0.001
    assert history[0]["success"] is True
    assert history[0]["fallback_routing"] is False


def test_missing_anthropic_key_returns_error_message(monkeypatch):
    """REWRITTEN (t10): this test previously asserted that agent_loop still
    contained the SwarmSync no-key error string, which encoded SwarmSync as
    required model-execution behaviour.  SwarmSync has been removed from the
    model-execution path; the credential the LLM path now needs is
    ANTHROPIC_API_KEY, so the assertion tracks that instead."""
    import inspect

    import cato.agent_loop as al_mod

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert al_mod._anthropic_key_present(DummyVault({})) is False
    assert al_mod._anthropic_key_present(DummyVault({"ANTHROPIC_API_KEY": "x"})) is True

    src = inspect.getsource(al_mod)
    assert "ANTHROPIC_API_KEY is not configured" in src, (
        "User-visible error message must remain in agent_loop for no-key scenario"
    )
    assert "SWARMSYNC_API_KEY" not in src, (
        "SwarmSync must not appear in the active model-execution path"
    )
