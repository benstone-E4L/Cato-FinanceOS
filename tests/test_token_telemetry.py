"""
tests/test_token_telemetry.py — Unit tests for Step 7 token usage telemetry.

Covers:
  - MetricsTracker.add_invocation() with token fields
  - MetricsTracker.get_summary() token aggregates
  - MetricsTracker.get_token_report() full report
  - MetricsTracker.reset() clears token state
  - track_invocation() module function with token kwargs
  - get_token_report() module function
  - reset_metrics() clears module-level token windows
  - WebSocket handler emits token_telemetry event (via AioHTTPTestCase)
  - CLI token-report command output
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from cato.orchestrator.metrics import (
    MetricsTracker,
    get_token_report,
    reset_metrics,
    track_invocation,
)

# Import CLI main at module load time so it is cached before any test
# in the full suite can corrupt the cato.platform import path.
from cato.cli import main as _cli_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_invocation(
    *,
    winner_model: str = "claude",
    terminated_early: bool = False,
    total_latency_ms: float = 500.0,
) -> dict:
    return {
        "timestamp": time.time(),
        "task": "test task",
        "total_latency_ms": total_latency_ms,
        "winner_model": winner_model,
        "winner_confidence": 0.90,
        "terminated_early": terminated_early,
        "models_responded": 3,
        "individual_latencies": {},
    }


# ---------------------------------------------------------------------------
# MetricsTracker — token field storage
# ---------------------------------------------------------------------------

class TestMetricsTrackerTokenFields:
    def setup_method(self):
        self.tracker = MetricsTracker()

    def test_add_invocation_stores_tokens_in(self):
        inv = _make_invocation()
        self.tracker.add_invocation(inv, tokens_in=1200, tokens_out=300)
        assert self.tracker.total_tokens_in == 1200

    def test_add_invocation_stores_tokens_out(self):
        inv = _make_invocation()
        self.tracker.add_invocation(inv, tokens_in=1200, tokens_out=300)
        assert self.tracker.total_tokens_out == 300

    def test_add_invocation_accumulates_multiple(self):
        for _ in range(3):
            self.tracker.add_invocation(_make_invocation(), tokens_in=100, tokens_out=50)
        assert self.tracker.total_tokens_in == 300
        assert self.tracker.total_tokens_out == 150

    def test_add_invocation_stores_query_tier(self):
        inv = _make_invocation()
        self.tracker.add_invocation(inv, tokens_in=100, tokens_out=50, query_tier="tier0")
        assert self.tracker._tier_counts.get("tier0") == 1

    def test_add_invocation_tracks_tier_distribution(self):
        for _ in range(3):
            self.tracker.add_invocation(_make_invocation(), query_tier="tier0")
        for _ in range(2):
            self.tracker.add_invocation(_make_invocation(), query_tier="tier1")
        assert self.tracker._tier_counts["tier0"] == 3
        assert self.tracker._tier_counts["tier1"] == 2

    def test_add_invocation_stores_context_slots(self):
        slots = {"tier0": 500, "tier1_memory": 200, "history": 300}
        inv = _make_invocation()
        self.tracker.add_invocation(inv, tokens_in=1000, tokens_out=200,
                                     context_slots_used=slots)
        stored = self.tracker.invocations[-1].get("context_slots_used", {})
        assert stored["tier0"] == 500
        assert stored["tier1_memory"] == 200
        assert stored["history"] == 300

    def test_add_invocation_no_mutation_of_original_dict(self):
        """add_invocation should not modify the caller's dict."""
        inv = _make_invocation()
        original_keys = set(inv.keys())
        self.tracker.add_invocation(inv, tokens_in=100, tokens_out=50, query_tier="t0")
        assert set(inv.keys()) == original_keys

    def test_reset_clears_token_state(self):
        self.tracker.add_invocation(_make_invocation(), tokens_in=500, tokens_out=100)
        self.tracker.reset()
        assert self.tracker.total_tokens_in == 0
        assert self.tracker.total_tokens_out == 0
        assert self.tracker._tier_counts == {}
        assert len(self.tracker._token_in_window) == 0
        assert len(self.tracker._token_out_window) == 0


# ---------------------------------------------------------------------------
# MetricsTracker — get_summary() token aggregates
# ---------------------------------------------------------------------------

class TestMetricsTrackerSummaryTokens:
    def setup_method(self):
        self.tracker = MetricsTracker()

    def test_empty_summary_has_token_fields(self):
        s = self.tracker.get_summary()
        assert "avg_tokens_in_last_100" in s
        assert "avg_tokens_out_last_100" in s
        assert "input_output_ratio" in s
        assert "tier_distribution" in s

    def test_summary_avg_tokens_in(self):
        for tokens in [100, 200, 300]:
            self.tracker.add_invocation(_make_invocation(), tokens_in=tokens, tokens_out=10)
        s = self.tracker.get_summary()
        assert s["avg_tokens_in_last_100"] == pytest.approx(200.0, rel=1e-3)

    def test_summary_avg_tokens_out(self):
        for tokens in [50, 100, 150]:
            self.tracker.add_invocation(_make_invocation(), tokens_in=10, tokens_out=tokens)
        s = self.tracker.get_summary()
        assert s["avg_tokens_out_last_100"] == pytest.approx(100.0, rel=1e-3)

    def test_summary_input_output_ratio(self):
        self.tracker.add_invocation(_make_invocation(), tokens_in=300, tokens_out=100)
        s = self.tracker.get_summary()
        assert s["input_output_ratio"] == pytest.approx(3.0, rel=1e-3)

    def test_summary_ratio_zero_when_no_output(self):
        self.tracker.add_invocation(_make_invocation(), tokens_in=100, tokens_out=0)
        s = self.tracker.get_summary()
        assert s["input_output_ratio"] == 0.0

    def test_summary_tier_distribution(self):
        self.tracker.add_invocation(_make_invocation(), query_tier="tier0")
        self.tracker.add_invocation(_make_invocation(), query_tier="tier0")
        self.tracker.add_invocation(_make_invocation(), query_tier="tier1")
        s = self.tracker.get_summary()
        assert s["tier_distribution"]["tier0"] == 2
        assert s["tier_distribution"]["tier1"] == 1


# ---------------------------------------------------------------------------
# MetricsTracker — get_token_report()
# ---------------------------------------------------------------------------

class TestMetricsTrackerTokenReport:
    def setup_method(self):
        self.tracker = MetricsTracker()

    def test_token_report_structure(self):
        self.tracker.add_invocation(_make_invocation(), tokens_in=1000, tokens_out=200)
        r = self.tracker.get_token_report()
        required_keys = {
            "total_tokens_in", "total_tokens_out", "ratio_in_to_out",
            "avg_tokens_in_last_100", "avg_tokens_out_last_100",
            "per_slot_averages", "tier_distribution",
            "estimated_cost_usd", "total_invocations",
        }
        assert required_keys.issubset(r.keys())

    def test_token_report_totals(self):
        self.tracker.add_invocation(_make_invocation(), tokens_in=2000, tokens_out=500)
        self.tracker.add_invocation(_make_invocation(), tokens_in=1000, tokens_out=250)
        r = self.tracker.get_token_report()
        assert r["total_tokens_in"] == 3000
        assert r["total_tokens_out"] == 750

    def test_token_report_ratio(self):
        self.tracker.add_invocation(_make_invocation(), tokens_in=4000, tokens_out=1000)
        r = self.tracker.get_token_report()
        assert r["ratio_in_to_out"] == pytest.approx(4.0, rel=1e-3)

    def test_token_report_estimated_cost(self):
        # At $3/M input, $15/M output: 1M in = $3.00, 1M out = $15.00
        self.tracker.add_invocation(_make_invocation(), tokens_in=1_000_000, tokens_out=1_000_000)
        r = self.tracker.get_token_report(cost_per_million_input=3.0, cost_per_million_output=15.0)
        assert r["estimated_cost_usd"] == pytest.approx(18.0, rel=1e-3)

    def test_token_report_per_slot_averages(self):
        slots1 = {"tier0": 500, "history": 300}
        slots2 = {"tier0": 700, "history": 100}
        self.tracker.add_invocation(_make_invocation(), tokens_in=800, tokens_out=100,
                                     context_slots_used=slots1)
        self.tracker.add_invocation(_make_invocation(), tokens_in=800, tokens_out=100,
                                     context_slots_used=slots2)
        r = self.tracker.get_token_report()
        assert r["per_slot_averages"]["tier0"] == pytest.approx(600.0, rel=1e-3)
        assert r["per_slot_averages"]["history"] == pytest.approx(200.0, rel=1e-3)

    def test_token_report_empty_tracker(self):
        r = self.tracker.get_token_report()
        assert r["total_tokens_in"] == 0
        assert r["total_tokens_out"] == 0
        assert r["estimated_cost_usd"] == 0.0
        assert r["per_slot_averages"] == {}

    def test_token_report_custom_costs(self):
        self.tracker.add_invocation(_make_invocation(), tokens_in=1_000_000, tokens_out=0)
        r = self.tracker.get_token_report(cost_per_million_input=5.0, cost_per_million_output=20.0)
        assert r["estimated_cost_usd"] == pytest.approx(5.0, rel=1e-3)

    def test_token_report_total_invocations(self):
        for _ in range(7):
            self.tracker.add_invocation(_make_invocation(), tokens_in=100, tokens_out=50)
        r = self.tracker.get_token_report()
        assert r["total_invocations"] == 7


# ---------------------------------------------------------------------------
# Module-level track_invocation() and get_token_report()
# ---------------------------------------------------------------------------

class TestModuleLevelTokenFunctions:
    def setup_method(self):
        reset_metrics()

    def teardown_method(self):
        reset_metrics()

    def test_track_invocation_accepts_token_kwargs(self):
        track_invocation(
            task="test",
            total_latency_ms=100.0,
            winner_model="claude",
            winner_confidence=0.92,
            terminated_early=False,
            tokens_in=800,
            tokens_out=200,
            query_tier="tier0",
            context_slots_used={"tier0": 400, "history": 400},
        )
        r = get_token_report()
        assert r["total_tokens_in"] == 800
        assert r["total_tokens_out"] == 200

    def test_track_invocation_defaults_tokens_to_zero(self):
        track_invocation(
            task="test",
            total_latency_ms=100.0,
            winner_model="claude",
            winner_confidence=0.92,
            terminated_early=False,
        )
        r = get_token_report()
        assert r["total_tokens_in"] == 0
        assert r["total_tokens_out"] == 0

    def test_get_token_report_accumulates_across_calls(self):
        for _ in range(5):
            track_invocation(
                task="t",
                total_latency_ms=100.0,
                winner_model="claude",
                winner_confidence=0.9,
                terminated_early=False,
                tokens_in=100,
                tokens_out=50,
            )
        r = get_token_report()
        assert r["total_tokens_in"] == 500
        assert r["total_tokens_out"] == 250

    def test_reset_metrics_clears_token_totals(self):
        track_invocation(
            task="t",
            total_latency_ms=100.0,
            winner_model="claude",
            winner_confidence=0.9,
            terminated_early=False,
            tokens_in=999,
            tokens_out=333,
        )
        reset_metrics()
        r = get_token_report()
        assert r["total_tokens_in"] == 0
        assert r["total_tokens_out"] == 0
        assert r["total_invocations"] == 0

    def test_get_token_report_cost_calculation(self):
        track_invocation(
            task="t",
            total_latency_ms=100.0,
            winner_model="claude",
            winner_confidence=0.9,
            terminated_early=False,
            tokens_in=500_000,
            tokens_out=100_000,
        )
        r = get_token_report(cost_per_million_input=3.0, cost_per_million_output=15.0)
        # 0.5M * $3 = $1.50 + 0.1M * $15 = $1.50 => $3.00
        assert r["estimated_cost_usd"] == pytest.approx(3.0, rel=1e-3)

    def test_tier_distribution_in_module_report(self):
        track_invocation(
            task="t", total_latency_ms=100.0, winner_model="claude",
            winner_confidence=0.9, terminated_early=False, query_tier="tier0",
        )
        track_invocation(
            task="t", total_latency_ms=100.0, winner_model="codex",
            winner_confidence=0.85, terminated_early=False, query_tier="tier1",
        )
        r = get_token_report()
        assert r["tier_distribution"]["tier0"] == 1
        assert r["tier_distribution"]["tier1"] == 1


# ---------------------------------------------------------------------------
# WebSocket handler — token_telemetry event emission
# ---------------------------------------------------------------------------

# The coding-agent WebSocket now FAILS CLOSED (see cato/api/ws_auth.py): an app
# with no daemon_token refuses every connection. These tests previously relied
# on the unauthenticated path, which encoded fail-open-on-empty as correct.
TEST_DAEMON_TOKEN = "t21" + "0" * 61


def ws_url(path: str) -> str:
    return f"{path}?token={TEST_DAEMON_TOKEN}"


def _make_ws_app() -> web.Application:
    from cato.api.websocket_handler import register_routes
    app = web.Application()
    app["daemon_token"] = TEST_DAEMON_TOKEN
    register_routes(app)
    return app


class TestWebSocketTokenTelemetryEvent(AioHTTPTestCase):
    """Tests that coding_agent_ws_handler emits token_telemetry after synthesis."""

    async def get_application(self) -> web.Application:
        return _make_ws_app()

    async def test_token_telemetry_event_emitted(self):
        from cato.api.websocket_handler import _task_store
        import uuid

        task_id = str(uuid.uuid4())
        _task_store[task_id] = {
            "task": "Write a hello world function in Python.",
            "prompt": "Write a hello world function in Python.",
            "language": "python",
            "context": "",
            "created_at": int(time.time() * 1000),
            "status": "queued",
        }

        fake_result = {
            "model": "claude",
            "response": "def hello(): print('Hello, World!')",
            "confidence": 0.92,
            "latency_ms": 150.0,
            "source": "mock",
        }

        event_names: list[str] = []

        with patch("cato.api.websocket_handler.invoke_claude_api",
                   return_value=fake_result), \
             patch("cato.api.websocket_handler.invoke_codex_cli",
                   return_value={**fake_result, "model": "codex", "confidence": 0.80}), \
             patch("cato.api.websocket_handler.invoke_gemini_cli",
                   return_value={**fake_result, "model": "gemini", "confidence": 0.75}):
            async with self.client.ws_connect(
                ws_url(f"/ws/coding-agent/{task_id}")
            ) as ws:
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.receive_str(), timeout=10.0)
                        parsed = json.loads(raw.strip())
                        event_names.append(parsed.get("event", ""))
                        if parsed.get("event") == "synthesis_complete":
                            # One more message should follow (token_telemetry)
                            try:
                                raw2 = await asyncio.wait_for(ws.receive_str(), timeout=3.0)
                                parsed2 = json.loads(raw2.strip())
                                event_names.append(parsed2.get("event", ""))
                            except (asyncio.TimeoutError, Exception):
                                pass
                            break
                except (asyncio.TimeoutError, Exception):
                    pass

        assert "token_telemetry" in event_names, (
            f"Expected 'token_telemetry' event but got: {event_names}"
        )

    async def test_token_telemetry_event_structure(self):
        from cato.api.websocket_handler import _task_store
        import uuid

        task_id = str(uuid.uuid4())
        _task_store[task_id] = {
            "task": "Explain async generators in Python carefully.",
            "prompt": "Explain async generators in Python carefully.",
            "language": "python",
            "context": "",
            "created_at": int(time.time() * 1000),
            "status": "queued",
        }

        fake_result = {
            "model": "claude",
            "response": "Async generators yield values lazily.",
            "confidence": 0.91,
            "latency_ms": 120.0,
            "source": "mock",
        }

        telemetry_data: list[dict] = []

        with patch("cato.api.websocket_handler.invoke_claude_api",
                   return_value=fake_result), \
             patch("cato.api.websocket_handler.invoke_codex_cli",
                   return_value={**fake_result, "model": "codex", "confidence": 0.78}), \
             patch("cato.api.websocket_handler.invoke_gemini_cli",
                   return_value={**fake_result, "model": "gemini", "confidence": 0.72}):
            async with self.client.ws_connect(
                ws_url(f"/ws/coding-agent/{task_id}")
            ) as ws:
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.receive_str(), timeout=10.0)
                        parsed = json.loads(raw.strip())
                        if parsed.get("event") == "token_telemetry":
                            telemetry_data.append(parsed["data"])
                        if parsed.get("event") == "synthesis_complete":
                            # Collect any trailing events
                            try:
                                raw2 = await asyncio.wait_for(ws.receive_str(), timeout=3.0)
                                parsed2 = json.loads(raw2.strip())
                                if parsed2.get("event") == "token_telemetry":
                                    telemetry_data.append(parsed2["data"])
                            except (asyncio.TimeoutError, Exception):
                                pass
                            break
                except (asyncio.TimeoutError, Exception):
                    pass

        assert len(telemetry_data) >= 1, "Expected at least one token_telemetry event"
        t = telemetry_data[0]
        required_fields = {
            "turn_tokens_in", "turn_tokens_out",
            "session_total_in", "session_total_out",
            "avg_tokens_in_last_100", "input_output_ratio",
            "estimated_cost_usd", "timestamp",
        }
        assert required_fields.issubset(t.keys()), (
            f"Missing fields in token_telemetry: {required_fields - t.keys()}"
        )
        assert t["turn_tokens_in"] >= 0
        assert t["turn_tokens_out"] >= 0
        assert t["timestamp"] > 0


# ---------------------------------------------------------------------------
# CLI — cato metrics token-report
# ---------------------------------------------------------------------------

class TestCLITokenReport:
    def setup_method(self):
        reset_metrics()

    def teardown_method(self):
        reset_metrics()

    def test_token_report_command_runs(self):
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(_cli_main, ["metrics", "token-report"])
        assert result.exit_code == 0, f"CLI failed: {result.output}"

    def test_token_report_command_shows_headers(self):
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(_cli_main, ["metrics", "token-report"])
        assert "Token Usage Report" in result.output
        assert "Total input tokens" in result.output
        assert "Total output tokens" in result.output
        assert "Estimated cost" in result.output

    def test_token_report_json_flag(self):
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(_cli_main, ["metrics", "token-report", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output.strip())
        assert "total_tokens_in" in parsed
        assert "total_tokens_out" in parsed
        assert "estimated_cost_usd" in parsed

    def test_token_report_reflects_tracked_data(self):
        from click.testing import CliRunner

        # Populate tracker via module function
        track_invocation(
            task="sample task",
            total_latency_ms=200.0,
            winner_model="claude",
            winner_confidence=0.95,
            terminated_early=False,
            tokens_in=42000,
            tokens_out=8000,
            query_tier="tier0",
        )

        runner = CliRunner()
        result = runner.invoke(_cli_main, ["metrics", "token-report", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert data["total_tokens_in"] == 42000
        assert data["total_tokens_out"] == 8000
        assert data["tier_distribution"]["tier0"] == 1

    def test_token_report_custom_cost_rates(self):
        from click.testing import CliRunner

        track_invocation(
            task="t", total_latency_ms=100.0, winner_model="claude",
            winner_confidence=0.9, terminated_early=False,
            tokens_in=1_000_000, tokens_out=0,
        )

        runner = CliRunner()
        result = runner.invoke(_cli_main, ["metrics", "token-report",
                                           "--cost-in", "5.0", "--cost-out", "20.0", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        # 1M tokens * $5/M = $5.00
        assert data["estimated_cost_usd"] == pytest.approx(5.0, rel=1e-3)
