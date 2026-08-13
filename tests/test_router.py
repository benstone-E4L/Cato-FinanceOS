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


async def test_legacy_model_id_is_translated_at_native_provider_wire_boundary(monkeypatch) -> None:
    vault = DummyVault({"OPENAI_API_KEY": "test-openai"})
    router = ModelRouter(vault=vault, preferred_model="openai/gpt-4o-mini")
    captured: dict[str, str] = {}

    async def fake_openai(messages, model, tools, api_key, base_url):
        captured.update(model=model, api_key=api_key, base_url=base_url)
        yield "ok"

    monkeypatch.setattr(router, "_openai_compat", fake_openai)

    chunks = [chunk async for chunk in router._complete_single(
        "openai/gpt-4o-mini", [{"role": "user", "content": "hello"}],
    )]

    assert chunks == ["ok"]
    assert captured["model"] == "gpt-4o-mini"
    assert captured["base_url"] == "https://api.openai.com/v1/chat/completions"


async def test_openrouter_model_id_is_not_translated_to_native_provider(monkeypatch) -> None:
    vault = DummyVault({"OPENROUTER_API_KEY": "test-openrouter"})
    router = ModelRouter(vault=vault, preferred_model="openrouter/openai/gpt-4o-mini")
    captured: dict[str, str] = {}

    async def fake_openai(messages, model, tools, api_key, base_url):
        captured.update(model=model, base_url=base_url)
        yield "ok"

    monkeypatch.setattr(router, "_openai_compat", fake_openai)
    _ = [chunk async for chunk in router._complete_single(
        "openrouter/openai/gpt-4o-mini", [{"role": "user", "content": "hello"}],
    )]

    assert captured["model"] == "openrouter/openai/gpt-4o-mini"
    assert captured["base_url"] == "https://openrouter.ai/api/v1/chat/completions"


async def test_availability_check_and_wire_dispatch_agree_on_translation(monkeypatch) -> None:
    """_is_available and _complete_single must resolve a model identically.

    The live HTTP 400 came from exactly this disagreement: _is_available
    translated "openai/gpt-4o-mini" to "gpt-4o-mini" to find a key, declared the
    model available, and then _complete_single put the UNTRANSLATED id on the
    wire to api.openai.com, which rejected it. Every legacy id must agree, and
    openrouter/ ids must stay untranslated on both sides.
    """
    from cato.router import MODEL_TRANSLATIONS, _FALLBACK_CHAIN

    vault = DummyVault({
        "OPENAI_API_KEY": "test-openai",
        "ANTHROPIC_API_KEY": "test-anthropic",
        "OPENROUTER_API_KEY": "test-openrouter",
        "DEEPSEEK_API_KEY": "test-deepseek",
        "GROQ_API_KEY": "test-groq",
        "MISTRAL_API_KEY": "test-mistral",
        "GOOGLE_API_KEY": "test-google",
    })
    router = ModelRouter(vault=vault, preferred_model="openai/gpt-4o-mini")

    captured: dict[str, str] = {}

    async def capture(messages, model, *args, **kwargs):
        captured["model"] = model
        yield "ok"

    monkeypatch.setattr(router, "_openai_compat", capture)
    monkeypatch.setattr(router, "_anthropic", capture)
    monkeypatch.setattr(router, "_google", capture)

    candidates = list(MODEL_TRANSLATIONS) + list(_FALLBACK_CHAIN)
    checked = 0
    for model in candidates:
        if not router._is_available(model):
            continue
        captured.clear()
        _ = [c async for c in router._complete_single(
            model, [{"role": "user", "content": "hi"}],
        )]
        expected = (
            model if model.startswith("openrouter/")
            else MODEL_TRANSLATIONS.get(model, model)
        )
        assert captured["model"] == expected, (
            f"{model!r} passed _is_available but went on the wire as "
            f"{captured['model']!r}; the provider expects {expected!r}"
        )
        checked += 1

    assert checked >= 5, f"only {checked} models exercised — the sweep is not meaningful"
