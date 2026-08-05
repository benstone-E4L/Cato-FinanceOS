from __future__ import annotations

from cato.router import ModelRouter


class DummyVault:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, key: str) -> str:
        return self._values.get(key, "")


def test_human_minimax_label_maps_to_openrouter_slug() -> None:
    vault = DummyVault({"OPENROUTER_API_KEY": "test-openrouter"})
    router = ModelRouter(vault=vault, preferred_model="Minimax:MiniMax M2.5")
    assert router.select_model(0.0) == "openrouter/minimax/minimax-m2.5"


def test_low_complexity_fallback_skips_claude_without_anthropic_key(monkeypatch) -> None:
    # Without ANTHROPIC_API_KEY, low-complexity routing must not select Claude.
    # _ECONOMY is now all openrouter/ slugs — expects OPENROUTER_API_KEY.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    vault = DummyVault({"OPENROUTER_API_KEY": "test-openrouter"})
    router = ModelRouter(vault=vault, preferred_model="")
    result = router.select_model(0.0)
    assert "claude" not in result.lower(), f"Expected non-Claude model, got {result!r}"
    assert result.startswith("openrouter/"), f"Expected OpenRouter model, got {result!r}"


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
    import cato.agent_loop as al_mod
    import inspect

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
