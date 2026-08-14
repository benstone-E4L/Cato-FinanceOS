"""Arize Phoenix (OpenInference/OTLP) tracing for Cato.

Answers "what did this agent do, with which tools, at what cost" by emitting
three span kinds:

* ``LLM``   — one per :meth:`cato.router.ModelRouter.complete` call, carrying the
  requested and actually-routed model, provider, and streaming outcome.
* ``TOOL``  — one per :meth:`cato.agent_loop.AgentLoop._guarded_dispatch`,
  carrying the tool name, whether it was allowed through the safety gates, and
  which gate refused it when it was not.
* ``CHAIN`` — the ask-e4l eval gate in :mod:`cato.core.phoenix_eval`.

Two hard guarantees, identical to the Genesis runtime tracer:

1. **Observability never blocks Cato.** Every entry point swallows every
   exception. Unconfigured, unreachable, or broken Phoenix all degrade to "no
   trace" while the agent, the tool gates and the ledger proceed untouched.
   Export is on a background thread; nothing in a user-facing path waits on it.
2. **No secret and no vault content leaves the machine by accident.** Prompt,
   tool-argument and answer text are omitted unless ``PHOENIX_TRACE_CONTENT`` is
   set, and when the collector is off-box a second explicit
   ``PHOENIX_ALLOW_CONTENT_OFFBOX`` is also required — Cato reads a private
   vault, so shipping its content to third-party SaaS is an operator decision,
   not a default.

Configuration (all optional; absence disables tracing silently):

* ``PHOENIX_COLLECTOR_ENDPOINT`` — Phoenix base URL, e.g. ``http://localhost:6006``.
  ``PHOENIX_ENDPOINT`` and ``OTEL_EXPORTER_OTLP_ENDPOINT`` are accepted aliases.
* ``PHOENIX_API_KEY`` — sent as ``Authorization: Bearer <key>``.
* ``PHOENIX_PROJECT_NAME`` — defaults to ``cato``.
* ``PHOENIX_TRACING`` — falsey disables while the endpoint stays configured.
* ``PHOENIX_TRACE_CONTENT`` / ``PHOENIX_ALLOW_CONTENT_OFFBOX`` — content opt-in.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Optional

log = logging.getLogger(__name__)

DEFAULT_PROJECT = "cato"
_FALSEY = {"0", "false", "no", "off", ""}
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")

# OpenInference semantic conventions, hard-coded so a missing helper package
# cannot break tracing. These strings are a stable part of the spec.
SPAN_KIND = "openinference.span.kind"
INPUT_VALUE = "input.value"
OUTPUT_VALUE = "output.value"
LLM_MODEL_NAME = "llm.model_name"
LLM_PROVIDER = "llm.provider"
LLM_TOKEN_PROMPT = "llm.token_count.prompt"
LLM_TOKEN_COMPLETION = "llm.token_count.completion"
LLM_TOKEN_TOTAL = "llm.token_count.total"
TOOL_NAME = "tool.name"

_lock = threading.Lock()
_tracer: Any = None
_provider: Any = None
_init_attempted = False
_disabled_reason: Optional[str] = None


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _vault_secret(name: str) -> str:
    """Resolve an observability credential from the encrypted vault only."""
    try:
        from cato.vault import get_vault

        value = get_vault().get(name)
    except Exception:
        value = None
    return str(value or "").strip()


def collector_endpoint() -> str:
    """Phoenix base URL from the first configured alias, or ""."""
    for name in ("PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_ENDPOINT",
                 "OTEL_EXPORTER_OTLP_ENDPOINT"):
        value = _env(name)
        if value:
            return value.rstrip("/")
    return ""


def tracing_enabled() -> bool:
    if not collector_endpoint():
        return False
    flag = os.getenv("PHOENIX_TRACING")
    if flag is not None and flag.strip().lower() in _FALSEY:
        return False
    return True


def endpoint_is_offbox() -> bool:
    """True when the collector is not loopback on this machine."""
    endpoint = collector_endpoint()
    if not endpoint:
        return False
    try:
        from urllib.parse import urlparse
        return (urlparse(endpoint).hostname or "").lower() not in _LOCAL_HOSTS
    except Exception:
        return True


def content_tracing_enabled() -> bool:
    """Whether vault/prompt/tool content may be attached to spans."""
    flag = _env("PHOENIX_TRACE_CONTENT").lower()
    if not flag or flag in _FALSEY:
        return False
    if endpoint_is_offbox():
        allow = _env("PHOENIX_ALLOW_CONTENT_OFFBOX").lower()
        if not allow or allow in _FALSEY:
            return False
    return True


def safe_content(value: Any, limit: int = 4000) -> Optional[str]:
    """Redacted, truncated content for a span, or None if it must not be sent."""
    if not content_tracing_enabled():
        return None
    try:
        from .approval_policy import redact_text

        text = value if isinstance(value, str) else repr(value)
        return redact_text(text)[:limit]
    except Exception:
        # Redaction unavailable => send nothing. Fail open on tracing, closed on secrets.
        return None


def _build_tracer() -> Any:
    global _provider
    endpoint = collector_endpoint()
    if not endpoint:
        return None

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    headers = {}
    api_key = _vault_secret("PHOENIX_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    project = _env("PHOENIX_PROJECT_NAME") or DEFAULT_PROJECT
    provider = TracerProvider(
        resource=Resource.create({"openinference.project.name": project,
                                  "service.name": project})
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces",
                             headers=headers or None, timeout=5),
            schedule_delay_millis=1000,
            export_timeout_millis=5000,
        )
    )
    _provider = provider
    return provider.get_tracer("cato")


def get_tracer() -> Any:
    """Cached tracer, or None when disabled/unavailable. Never raises."""
    global _tracer, _init_attempted, _disabled_reason
    if _tracer is not None:
        return _tracer
    with _lock:
        if _tracer is not None:
            return _tracer
        if _init_attempted:
            return None
        _init_attempted = True
        if not tracing_enabled():
            _disabled_reason = "no PHOENIX_COLLECTOR_ENDPOINT configured"
            return None
        try:
            _tracer = _build_tracer()
            if _tracer is None:
                _disabled_reason = "tracer construction returned None"
            return _tracer
        except Exception as exc:
            _disabled_reason = f"{type(exc).__name__}: {exc}"
            log.warning("Phoenix tracing disabled (%s); Cato continues normally",
                        _disabled_reason)
            return None


def disabled_reason() -> Optional[str]:
    return _disabled_reason


def reset_for_tests() -> None:
    global _tracer, _provider, _init_attempted, _disabled_reason
    with _lock:
        _tracer = None
        _provider = None
        _init_attempted = False
        _disabled_reason = None


def _coerce(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)) and all(
        isinstance(v, (bool, int, float, str)) for v in value
    ):
        return list(value)
    return str(value)


def set_attributes(span_obj: Any, attributes: Mapping[str, Any]) -> None:
    """Best-effort attribute write. Never raises; skips None."""
    if span_obj is None:
        return
    for key, value in attributes.items():
        if value is None:
            continue
        try:
            span_obj.set_attribute(key, _coerce(value))
        except Exception:
            continue


def record_error(span_obj: Any, exc: BaseException) -> None:
    """Mark a span errored without leaking secret-bearing exception text."""
    if span_obj is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        try:
            from .approval_policy import redact_text
            message = redact_text(str(exc))
        except Exception:
            message = type(exc).__name__
        span_obj.set_status(Status(StatusCode.ERROR, message[:500]))
        span_obj.set_attribute("exception.type", type(exc).__name__)
    except Exception:
        pass


@contextmanager
def span(
    name: str,
    *,
    kind: str = "CHAIN",
    attributes: Optional[Mapping[str, Any]] = None,
) -> Iterator[Any]:
    """Start a span, yielding it (or ``None`` when tracing is off).

    Any tracing failure degrades to ``None`` while the caller's body still runs.
    An exception from the body is recorded and re-raised unchanged.
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    ctx = None
    current = None
    try:
        ctx = tracer.start_as_current_span(name)
        current = ctx.__enter__()
        set_attributes(current, {SPAN_KIND: kind, **(attributes or {})})
    except Exception:
        if ctx is not None:
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                pass
        yield None
        return

    try:
        yield current
    except BaseException as exc:
        try:
            record_error(current, exc)
            ctx.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            pass
        raise
    else:
        try:
            ctx.__exit__(None, None, None)
        except Exception:
            pass


def current_trace_id() -> Optional[str]:
    """Hex trace id of the active span, for correlating the ledger to Phoenix."""
    try:
        from opentelemetry import trace as _trace

        ctx = _trace.get_current_span().get_span_context()
        if not ctx or not ctx.trace_id:
            return None
        return format(ctx.trace_id, "032x")
    except Exception:
        return None


def flush(timeout_millis: int = 5000) -> bool:
    """Force-export pending spans. Bounded, best effort, never raises.

    For process shutdown and tests only — never call this on a user-facing path.
    """
    try:
        if _provider is None:
            return False
        return bool(_provider.force_flush(timeout_millis))
    except Exception:
        return False
