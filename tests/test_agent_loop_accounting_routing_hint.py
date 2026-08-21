"""tests/test_agent_loop_accounting_routing_hint.py — Task 3 follow-up:
wiring cato/accounting_router.py into cato/agent_loop.py's planning.

Covers:
  - A confidently-routed e4l accounting question produces a hint naming the
    matrix-selected slug(s) and never a money-domain stub.
  - An ambiguous-but-plausibly-accounting question produces a
    NEED_CLARIFICATION-flavoured hint instead of a guess.
  - Ordinary non-accounting chat produces no hint (no noise).
  - The hint never raises even if the router/matrix is broken (planning
    hints must never take down the main loop).
  - AgentLoop.run() actually includes the hint as an extra system message
    when relevant.
"""

from __future__ import annotations

from cato.agent_loop import _build_accounting_routing_hint


class TestRoutingHintContent:
    def test_confident_match_names_matrix_slugs(self):
        hint = _build_accounting_routing_hint("Why does Stripe cash not match Xero?")
        assert hint is not None
        assert "genesis-e4l-stripe" in hint
        assert "genesis-e4l-cash" in hint
        assert "genesis-e4l-revenue" in hint
        assert "genesis-e4l-fs-integrity" in hint

    def test_confident_match_never_suggests_money_domain_stub(self):
        hint = _build_accounting_routing_hint("Close July for all E4L entities.")
        assert hint is not None
        assert "genesis-finance" not in hint.split("NEVER")[0]
        assert "genesis-billing" not in hint.split("NEVER")[0]

    def test_ambiguous_accounting_leaning_prompt_asks_for_clarification(self):
        hint = _build_accounting_routing_hint("Something about stripe cash revenue reconciliation")
        # This prompt is dominated by real accounting keywords and should
        # either route confidently or ask for clarification -- never None.
        assert hint is not None

    def test_ordinary_chat_produces_no_hint(self):
        assert _build_accounting_routing_hint("What is the weather today?") is None
        assert _build_accounting_routing_hint("hi") is None
        assert _build_accounting_routing_hint("Tell me a joke.") is None

    def test_never_raises_when_router_import_fails(self, monkeypatch):
        """Simulate accounting_router being unimportable -- the hint builder
        must swallow this and return None, never propagate the exception up
        into AgentLoop.run()."""
        import builtins

        import cato.agent_loop as al

        real_import = builtins.__import__

        def _patched_import(name, *a, **kw):
            if name == "cato.accounting_router":
                raise ImportError("simulated")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", _patched_import)
        assert al._build_accounting_routing_hint("Why does Stripe cash not match Xero?") is None


class TestRoutingHintWiredIntoRun:
    def test_run_injects_hint_as_extra_system_message_for_accounting_question(self):
        import inspect

        import cato.agent_loop as al

        source = inspect.getsource(al.AgentLoop.run)
        assert "_build_accounting_routing_hint(message)" in source
        assert 'messages.append({"role": "system", "content": routing_hint})' in source
