"""Phoenix/OpenInference tracing contract for Cato.

The governing property is **fail-open**: Cato must run normally when Phoenix is
unconfigured, unreachable, or broken. An observability outage must never block
an agent run, a tool dispatch, or a money path. That is asserted here against a
real OTLP exporter pointed at a dead port, not a stub, because the failure that
matters in production is a live TCP failure inside the exporter.
"""

from __future__ import annotations

import asyncio

import pytest

from cato.core import phoenix_tracing as pt


@pytest.fixture(autouse=True)
def _reset_tracing():
    pt.reset_for_tests()
    yield
    pt.reset_for_tests()


@pytest.fixture
def memory_spans(monkeypatch):
    """Route spans to an in-memory exporter instead of a real collector."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    monkeypatch.setattr(pt, "_build_tracer", lambda: provider.get_tracer("test"))
    pt.reset_for_tests()
    return exporter


# ---------------------------------------------------------------------------
# Fail-open.
# ---------------------------------------------------------------------------

def test_unconfigured_phoenix_is_silent_and_non_fatal(monkeypatch):
    for var in ("PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_ENDPOINT",
                "OTEL_EXPORTER_OTLP_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    pt.reset_for_tests()

    assert pt.tracing_enabled() is False
    assert pt.get_tracer() is None

    ran = []
    with pt.span("anything", kind="TOOL") as sp:
        ran.append(sp)
    assert ran == [None]
    assert pt.flush(100) is False


def test_span_body_runs_when_collector_is_unreachable(monkeypatch):
    """A dead collector must not fail, hang, or skip the wrapped work."""
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:9")
    pt.reset_for_tests()

    executed = []
    with pt.span("tool.send_email", kind="TOOL", attributes={"tool.name": "x"}) as sp:
        executed.append(True)
        pt.set_attributes(sp, {"cato.tool.refused": False})
    assert executed == [True]
    assert pt.flush(2000) in (True, False)


def test_span_body_runs_when_tracer_construction_explodes(monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")

    def boom():
        raise RuntimeError("otel exploded")

    monkeypatch.setattr(pt, "_build_tracer", boom)
    pt.reset_for_tests()

    assert pt.get_tracer() is None
    assert "otel exploded" in (pt.disabled_reason() or "")
    executed = []
    with pt.span("tool.x", kind="TOOL"):
        executed.append(True)
    assert executed == [True]


def test_span_body_runs_when_tracer_raises_at_span_start(monkeypatch):
    class _BadTracer:
        def start_as_current_span(self, *_a, **_k):
            raise RuntimeError("cannot start span")

    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    monkeypatch.setattr(pt, "_build_tracer", lambda: _BadTracer())
    pt.reset_for_tests()

    executed = []
    with pt.span("tool.x", kind="TOOL") as sp:
        executed.append(sp)
    assert executed == [None]


def test_set_attributes_never_raises_on_hostile_span():
    class _Hostile:
        def set_attribute(self, *_a):
            raise RuntimeError("nope")

    pt.set_attributes(_Hostile(), {"a": 1, "b": object()})  # must not raise


def test_exception_in_body_is_recorded_and_reraised(memory_spans):
    with pytest.raises(ValueError, match="boom"):
        with pt.span("tool.explodes", kind="TOOL"):
            raise ValueError("boom")
    spans = memory_spans.get_finished_spans()
    assert [s.name for s in spans] == ["tool.explodes"]
    assert spans[0].attributes["exception.type"] == "ValueError"


# ---------------------------------------------------------------------------
# Confidentiality: Cato reads a private vault.
# ---------------------------------------------------------------------------

def test_no_content_on_spans_by_default(monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    monkeypatch.delenv("PHOENIX_TRACE_CONTENT", raising=False)
    pt.reset_for_tests()
    assert pt.safe_content("confidential vault text") is None


def test_offbox_collector_requires_second_explicit_optin(monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT",
                       "https://app.phoenix.arize.com/s/e4l")
    monkeypatch.setenv("PHOENIX_TRACE_CONTENT", "1")
    monkeypatch.delenv("PHOENIX_ALLOW_CONTENT_OFFBOX", raising=False)
    pt.reset_for_tests()

    assert pt.endpoint_is_offbox() is True
    assert pt.content_tracing_enabled() is False
    assert pt.safe_content("confidential vault text") is None

    monkeypatch.setenv("PHOENIX_ALLOW_CONTENT_OFFBOX", "1")
    assert pt.content_tracing_enabled() is True


def test_local_collector_needs_only_one_optin(monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    monkeypatch.setenv("PHOENIX_TRACE_CONTENT", "1")
    monkeypatch.delenv("PHOENIX_ALLOW_CONTENT_OFFBOX", raising=False)
    pt.reset_for_tests()
    assert pt.endpoint_is_offbox() is False
    assert pt.content_tracing_enabled() is True


def test_enabled_content_is_still_redacted(monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    monkeypatch.setenv("PHOENIX_TRACE_CONTENT", "1")
    pt.reset_for_tests()
    out = pt.safe_content("key sk-abcdefghijklmnopqrstuvwxyz012345")
    assert out is not None
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in out


def test_endpoint_aliases_are_honoured(monkeypatch):
    for var in ("PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_ENDPOINT",
                "OTEL_EXPORTER_OTLP_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    # The legacy name phoenix_eval.py already documented must keep working.
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://localhost:6006/")
    assert pt.collector_endpoint() == "http://localhost:6006"
    assert pt.tracing_enabled() is True

    monkeypatch.setenv("PHOENIX_TRACING", "0")
    assert pt.tracing_enabled() is False


# ---------------------------------------------------------------------------
# The eval gate emits real OTLP spans, not the old bespoke JSON POST.
# ---------------------------------------------------------------------------

def test_eval_emits_openinference_spans(memory_spans):
    from cato.core.phoenix_eval import EvalReport, EvalResult, _try_log_to_phoenix

    report = EvalReport(results=[
        EvalResult(question="q1", expects_refusal=False, refused=False, correct=True,
                   confidently_wrong=False, citations=["a.md"], answer_text="ans"),
        EvalResult(question="q2", expects_refusal=True, refused=True, correct=True,
                   confidently_wrong=False, citations=[], answer_text="declined"),
    ])
    assert _try_log_to_phoenix(report) is True

    spans = {s.name: s for s in memory_spans.get_finished_spans()}
    assert "eval.ask_e4l_10q" in spans
    run = spans["eval.ask_e4l_10q"]
    assert run.attributes["eval.total"] == 2
    assert run.attributes["eval.correct"] == 2
    assert run.attributes["eval.confidently_wrong"] == 0
    assert run.attributes[pt.SPAN_KIND] == "CHAIN"

    questions = [s for s in memory_spans.get_finished_spans()
                 if s.name == "eval.question"]
    assert len(questions) == 2
    # Answer text is gated; the fixed question text is not.
    assert all(pt.OUTPUT_VALUE not in q.attributes for q in questions)


def test_eval_logging_returns_false_when_phoenix_unconfigured(monkeypatch):
    """Unconfigured must report honestly rather than claiming a successful log."""
    from cato.core.phoenix_eval import EvalReport, _try_log_to_phoenix

    for var in ("PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_ENDPOINT",
                "OTEL_EXPORTER_OTLP_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    pt.reset_for_tests()
    assert _try_log_to_phoenix(EvalReport(results=[])) is False


def test_eval_logging_survives_unreachable_collector(monkeypatch):
    from cato.core.phoenix_eval import EvalReport, EvalResult, _try_log_to_phoenix

    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:9")
    pt.reset_for_tests()
    report = EvalReport(results=[
        EvalResult(question="q", expects_refusal=False, refused=False, correct=True,
                   confidently_wrong=False, citations=["a.md"], answer_text="ans"),
    ])
    # Spans are handed to the exporter; the dead collector is the exporter's
    # problem, on its own thread, and never the caller's.
    assert _try_log_to_phoenix(report) is True


# ---------------------------------------------------------------------------
# Tool dispatch spans.
# ---------------------------------------------------------------------------

def test_guarded_dispatch_emits_a_tool_span(memory_spans):
    """Every tool call must be visible in Phoenix with its refusal verdict."""
    from cato.agent_loop import AgentLoop, ToolCall

    loop = AgentLoop.__new__(AgentLoop)

    async def fake_inner(tc, session_id, **kwargs):
        return "Refused: risk gate"

    loop._guarded_dispatch_inner = fake_inner  # type: ignore[method-assign]
    out = asyncio.run(
        AgentLoop._guarded_dispatch(loop, ToolCall(name="send_email", args={}, call_id="1"),
                                    "sess-1")
    )
    assert out == "Refused: risk gate"

    spans = memory_spans.get_finished_spans()
    tool = next(s for s in spans if s.name == "tool.send_email")
    assert tool.attributes[pt.SPAN_KIND] == "TOOL"
    assert tool.attributes[pt.TOOL_NAME] == "send_email"
    assert tool.attributes["cato.session.id"] == "sess-1"
    assert tool.attributes["cato.tool.refused"] is True
    assert pt.INPUT_VALUE not in tool.attributes


def test_guarded_dispatch_still_runs_with_phoenix_down(monkeypatch):
    """The gates and the ledger must not depend on Phoenix being up."""
    from cato.agent_loop import AgentLoop, ToolCall

    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:9")
    pt.reset_for_tests()

    loop = AgentLoop.__new__(AgentLoop)
    calls = []

    async def fake_inner(tc, session_id, **kwargs):
        calls.append(tc.name)
        return "ok: dispatched"

    loop._guarded_dispatch_inner = fake_inner  # type: ignore[method-assign]
    out = asyncio.run(
        AgentLoop._guarded_dispatch(loop, ToolCall(name="run_python", args={}, call_id="1"),
                                    "sess-2")
    )
    assert out == "ok: dispatched"
    assert calls == ["run_python"]


# ---------------------------------------------------------------------------
# Router spans.
# ---------------------------------------------------------------------------

def test_router_complete_emits_llm_span_with_routed_model(memory_spans):
    from cato.router import ModelRouter

    router = ModelRouter.__new__(ModelRouter)

    async def fake_inner(messages, model, tools=None, stream=True):
        yield "hello "
        yield {"model": "claude-sonnet-4-5-20250929",
               "usage": {"prompt_tokens": 11, "completion_tokens": 5,
                         "total_tokens": 16}}

    router._complete_inner = fake_inner  # type: ignore[method-assign]

    async def drain():
        return [c async for c in ModelRouter.complete(
            router, [{"role": "user", "content": "hi"}], "claude-sonnet-4-5")]

    chunks = asyncio.run(drain())
    assert chunks[0] == "hello "

    llm = next(s for s in memory_spans.get_finished_spans()
               if s.name == "llm.completion")
    assert llm.attributes[pt.SPAN_KIND] == "LLM"
    assert llm.attributes[pt.LLM_MODEL_NAME] == "claude-sonnet-4-5"
    assert llm.attributes["llm.model_name.routed"] == "claude-sonnet-4-5-20250929"
    assert llm.attributes[pt.LLM_TOKEN_TOTAL] == 16
    assert llm.attributes["llm.stream.chunks"] == 2


def test_router_complete_streams_normally_with_phoenix_down(monkeypatch):
    from cato.router import ModelRouter

    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:9")
    pt.reset_for_tests()

    router = ModelRouter.__new__(ModelRouter)

    async def fake_inner(messages, model, tools=None, stream=True):
        for part in ("a", "b", "c"):
            yield part

    router._complete_inner = fake_inner  # type: ignore[method-assign]

    async def drain():
        return [c async for c in ModelRouter.complete(router, [], "m")]

    assert asyncio.run(drain()) == ["a", "b", "c"]
