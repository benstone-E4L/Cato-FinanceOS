"""
tests/test_coding_agent_integration.py
Integration tests for the full coding agent flow.

Tests:
  1. User submits task → sees loading state (task queued)
  2. Messages arrive via WebSocket in correct order
  3. Early termination stops loading
  4. Synthesis displays best result
  5. Error handling displays error message
  6. WebSocket reconnection (simulated)
  7. History persistence via task store
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from aiohttp import web, ClientWebSocketResponse
from aiohttp.test_utils import AioHTTPTestCase

from cato.api.websocket_handler import (
    _task_store,
    _synthesize_results,
    _confidence_level,
    register_routes,
)


# ── Test App Factory ─────────────────────────────────────────────────────── #

# The coding-agent WebSocket now FAILS CLOSED (see cato/api/ws_auth.py): an app
# with no daemon_token refuses every connection. These tests previously relied
# on the unauthenticated path, which encoded fail-open-on-empty as correct.
TEST_DAEMON_TOKEN = "t21" + "0" * 61


def ws_url(path: str) -> str:
    return f"{path}?token={TEST_DAEMON_TOKEN}"


def make_app() -> web.Application:
    app = web.Application()
    app["daemon_token"] = TEST_DAEMON_TOKEN
    register_routes(app)
    return app


# ── Test 1: User submits task, sees loading state ────────────────────────── #

class TestTaskSubmission(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    async def test_shows_loading_state_for_all_3_models(self):
        """
        When a task is submitted, the backend queues it.
        The WS handler starts invoking all 3 models concurrently.
        Simulate loading state: status event before model responses arrive.
        """
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": "Explain this recursive function"},
        )
        assert resp.status == 200
        data = await resp.json()
        task_id = data["task_id"]

        # Verify task is stored as "queued" (= loading state)
        assert task_id in _task_store
        assert _task_store[task_id]["status"] == "queued"
        assert _task_store[task_id]["task"] == "Explain this recursive function"

    async def test_claude_codex_gemini_all_invoked(self):
        """
        When WS connects, all three models are invoked.
        We verify by patching _run_model_and_stream and checking all 3 calls.
        """
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": "Show loading spinners for all 3 models"},
        )
        data = await resp.json()
        tid = data["task_id"]

        called_models = []

        async def capture_model(ws, model, task, prompt):
            called_models.append(model)
            return {"model": model, "response": f"{model} says hi", "confidence": 0.80}

        with patch("cato.api.websocket_handler._run_model_and_stream", side_effect=capture_model):
            async with self.client.ws_connect(ws_url(f"/ws/coding-agent/{tid}")) as ws:
                events = []
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.receive_str(), timeout=8.0)
                        p = json.loads(msg.strip())
                        events.append(p["event"])
                        if p["event"] == "synthesis_complete":
                            break
                except (asyncio.TimeoutError, Exception):
                    pass

        # All 3 models should have been called
        assert "claude"  in called_models
        assert "codex"   in called_models
        assert "gemini"  in called_models


# ── Test 2: Messages arrive in order ────────────────────────────────────── #

class TestMessageArrival(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    async def test_messages_arrive_via_websocket(self):
        """
        Mock model responses. Verify each model's event arrives via WS.
        The client reads events and checks for claude/codex/gemini_response events.
        """
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": "Displays messages as they arrive via WebSocket"},
        )
        data = await resp.json()
        tid  = data["task_id"]

        # The real _run_model_and_stream sends the WS event itself.
        # We need to mock the lower-level invoke functions instead.
        mock_claude = {"model": "claude", "response": "Analysis: good code.", "confidence": 0.92, "latency_ms": 100}
        mock_codex  = {"model": "codex",  "response": "Codex review complete.", "confidence": 0.85, "latency_ms": 120}
        mock_gemini = {"model": "gemini", "response": "Gemini perspective.",   "confidence": 0.78, "latency_ms": 110}

        with patch("cato.api.websocket_handler.invoke_claude_api", return_value=mock_claude), \
             patch("cato.api.websocket_handler.invoke_codex_cli",  return_value=mock_codex), \
             patch("cato.api.websocket_handler.invoke_gemini_cli", return_value=mock_gemini):

            async with self.client.ws_connect(ws_url(f"/ws/coding-agent/{tid}")) as ws:
                received_events = []
                received_data   = {}
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.receive_str(), timeout=10.0)
                        p = json.loads(msg.strip())
                        received_events.append(p["event"])
                        if p["event"] in ("claude_response", "codex_response", "gemini_response"):
                            received_data[p["event"]] = p["data"]
                        if p["event"] == "synthesis_complete":
                            break
                except (asyncio.TimeoutError, Exception):
                    pass

                # All 3 model events should be received
                assert "claude_response"  in received_events, f"Got: {received_events}"
                assert "codex_response"   in received_events, f"Got: {received_events}"
                assert "gemini_response"  in received_events, f"Got: {received_events}"

                # Verify message content
                assert "Analysis" in received_data.get("claude_response", {}).get("text", "")

    async def test_messages_have_confidence_scores(self):
        """Each message event should include a confidence score."""
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": "Test confidence scores in messages"},
        )
        data = await resp.json()
        tid  = data["task_id"]

        mock_r = {"model": "claude", "response": "Test response.", "confidence": 0.92, "latency_ms": 50}
        with patch("cato.api.websocket_handler.invoke_claude_api", return_value=mock_r), \
             patch("cato.api.websocket_handler.invoke_codex_cli",  return_value={**mock_r,"model":"codex","confidence":0.75}), \
             patch("cato.api.websocket_handler.invoke_gemini_cli", return_value={**mock_r,"model":"gemini","confidence":0.68}):

            async with self.client.ws_connect(ws_url(f"/ws/coding-agent/{tid}")) as ws:
                model_events = {}
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.receive_str(), timeout=10.0)
                        p = json.loads(msg.strip())
                        if p["event"] in ("claude_response","codex_response","gemini_response"):
                            model_events[p["event"]] = p["data"]
                        if p["event"] == "synthesis_complete":
                            break
                except Exception:
                    pass

                for evt, d in model_events.items():
                    assert "confidence" in d, f"Missing confidence in {evt}"
                    assert 0.0 <= d["confidence"] <= 1.0
                    assert "confidence_level" in d
                    assert d["confidence_level"] in ("high", "medium", "low")


# ── Test 3: Early termination ────────────────────────────────────────────── #

class TestEarlyTermination(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    async def test_stops_loading_on_early_termination(self):
        """
        When primary model confidence >= 0.95, early_termination event is sent.
        After synthesis_complete, loading should be done.
        """
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": "Stops loading on early termination event"},
        )
        data = await resp.json()
        tid  = data["task_id"]

        # Return very high confidence from Claude → should trigger early termination
        mock_claude = {"model": "claude", "response": "Definitive answer.", "confidence": 0.96, "latency_ms": 50}
        mock_codex  = {"model": "codex",  "response": "Also good.",         "confidence": 0.80, "latency_ms": 60}
        mock_gemini = {"model": "gemini", "response": "Another view.",       "confidence": 0.72, "latency_ms": 70}

        with patch("cato.api.websocket_handler.invoke_claude_api", return_value=mock_claude), \
             patch("cato.api.websocket_handler.invoke_codex_cli",  return_value=mock_codex), \
             patch("cato.api.websocket_handler.invoke_gemini_cli", return_value=mock_gemini):

            async with self.client.ws_connect(ws_url(f"/ws/coding-agent/{tid}")) as ws:
                events = []
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.receive_str(), timeout=10.0)
                        p   = json.loads(msg.strip())
                        events.append(p["event"])
                        if p["event"] == "synthesis_complete":
                            synthesis_data = p["data"]
                            break
                except Exception:
                    pass

                # early_termination should be in events (before synthesis_complete)
                assert "early_termination" in events, f"Expected early_termination, got: {events}"
                assert "synthesis_complete" in events

                # Verify loading stops: synthesis_complete comes after early_termination
                et_idx = events.index("early_termination")
                sc_idx = events.index("synthesis_complete")
                assert et_idx < sc_idx


# ── Test 4: Synthesis displays best result ───────────────────────────────── #

class TestSynthesisDisplay(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    async def test_shows_synthesis_with_highest_confidence(self):
        """
        synthesis_complete event should contain primary result
        pointing to the model with the highest confidence score.
        """
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": "Shows synthesis result with highest confidence"},
        )
        data = await resp.json()
        tid  = data["task_id"]

        mock_claude = {"model": "claude", "response": "Best solution here.",  "confidence": 0.92, "latency_ms": 80}
        mock_codex  = {"model": "codex",  "response": "Alternate approach.",   "confidence": 0.77, "latency_ms": 90}
        mock_gemini = {"model": "gemini", "response": "Third perspective.",    "confidence": 0.65, "latency_ms": 100}

        with patch("cato.api.websocket_handler.invoke_claude_api", return_value=mock_claude), \
             patch("cato.api.websocket_handler.invoke_codex_cli",  return_value=mock_codex), \
             patch("cato.api.websocket_handler.invoke_gemini_cli", return_value=mock_gemini):

            async with self.client.ws_connect(ws_url(f"/ws/coding-agent/{tid}")) as ws:
                synthesis_data = None
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.receive_str(), timeout=10.0)
                        p = json.loads(msg.strip())
                        if p["event"] == "synthesis_complete":
                            synthesis_data = p["data"]
                            break
                except Exception:
                    pass

                assert synthesis_data is not None, "Did not receive synthesis_complete"
                primary = synthesis_data["primary"]

                # Should select Claude (0.92) as primary
                assert primary["model"] == "claude"
                assert primary["confidence"] == 0.92
                assert "Best solution" in primary["response"]

                # Runners-up should contain the others
                runners = synthesis_data["runners_up"]
                runner_models = [r["model"] for r in runners]
                assert "codex"  in runner_models
                assert "gemini" in runner_models

    async def test_synthesis_result_structure(self):
        """synthesis_complete data should have primary + runners_up."""
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": "Test synthesis result data structure"},
        )
        data = await resp.json()
        tid  = data["task_id"]

        mocks = {
            "claude":  {"model":"claude",  "response":"C","confidence":0.88,"latency_ms":50},
            "codex":   {"model":"codex",   "response":"X","confidence":0.80,"latency_ms":55},
            "gemini":  {"model":"gemini",  "response":"G","confidence":0.72,"latency_ms":60},
        }

        with patch("cato.api.websocket_handler.invoke_claude_api", return_value=mocks["claude"]), \
             patch("cato.api.websocket_handler.invoke_codex_cli",  return_value=mocks["codex"]), \
             patch("cato.api.websocket_handler.invoke_gemini_cli", return_value=mocks["gemini"]):

            async with self.client.ws_connect(ws_url(f"/ws/coding-agent/{tid}")) as ws:
                synthesis_data = None
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.receive_str(), timeout=10.0)
                        p = json.loads(msg.strip())
                        if p["event"] == "synthesis_complete":
                            synthesis_data = p["data"]
                            break
                except Exception:
                    pass

                assert synthesis_data is not None
                assert "primary"    in synthesis_data
                assert "runners_up" in synthesis_data
                assert "early_exit" in synthesis_data

                primary = synthesis_data["primary"]
                for field in ("model", "response", "confidence", "confidence_level", "latency_ms"):
                    assert field in primary, f"Missing field: {field}"


# ── Test 5: Error handling ───────────────────────────────────────────────── #

class TestErrorHandling(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    async def test_displays_error_when_model_api_fails(self):
        """
        When a model raises an exception, an error event is streamed.
        The task should still complete with results from other models.
        """
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": "Displays error message if Claude API fails"},
        )
        data = await resp.json()
        tid  = data["task_id"]

        # Claude fails; others succeed
        async def claude_fail(prompt, task):
            raise RuntimeError("Claude API error: rate limit exceeded")

        mock_codex  = {"model": "codex",  "response": "Codex still works.", "confidence": 0.83, "latency_ms": 80}
        mock_gemini = {"model": "gemini", "response": "Gemini still works.", "confidence": 0.79, "latency_ms": 90}

        with patch("cato.api.websocket_handler.invoke_claude_api", side_effect=claude_fail), \
             patch("cato.api.websocket_handler.invoke_codex_cli",  return_value=mock_codex), \
             patch("cato.api.websocket_handler.invoke_gemini_cli", return_value=mock_gemini):

            async with self.client.ws_connect(ws_url(f"/ws/coding-agent/{tid}")) as ws:
                events = []
                event_data = {}
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.receive_str(), timeout=10.0)
                        p = json.loads(msg.strip())
                        events.append(p["event"])
                        event_data[p["event"]] = p["data"]
                        if p["event"] == "synthesis_complete":
                            break
                except Exception:
                    pass

                # An error event should appear for Claude
                assert "error" in events, f"Expected error event, got: {events}"
                err_data = event_data.get("error", {})
                assert "API Error" in err_data.get("message", "") or \
                       "rate limit" in err_data.get("message", "").lower() or \
                       "Claude" in err_data.get("message", "") or \
                       err_data.get("model") == "claude"

                # But synthesis should still happen from remaining models
                assert "synthesis_complete" in events

    async def test_unknown_task_sends_error(self):
        """WS connection for unknown task_id returns error event."""
        async with self.client.ws_connect(ws_url("/ws/coding-agent/nonexistent-task")) as ws:
            msg = await asyncio.wait_for(ws.receive_str(), timeout=5.0)
            p   = json.loads(msg.strip())
            assert p["event"] == "error"
            assert p["data"]["message"]


# ── Test 6: Synthesis logic unit tests ──────────────────────────────────── #

class TestSynthesisLogic:
    """Unit tests for synthesis business logic — no HTTP needed."""

    def test_synthesis_selects_highest_confidence(self):
        results = [
            {"model": "claude",  "response": "Claude answer",  "confidence": 0.92},
            {"model": "codex",   "response": "Codex answer",   "confidence": 0.75},
            {"model": "gemini",  "response": "Gemini answer",  "confidence": 0.68},
        ]
        s = _synthesize_results(results)
        assert s["primary"]["model"] == "claude"
        assert s["primary"]["confidence"] == 0.92

    def test_synthesis_runners_up_sorted(self):
        results = [
            {"model": "claude",  "response": "A", "confidence": 0.91},
            {"model": "codex",   "response": "B", "confidence": 0.85},
            {"model": "gemini",  "response": "C", "confidence": 0.78},
        ]
        s = _synthesize_results(results)
        runners = s["runners_up"]
        # codex (0.85) before gemini (0.78)
        assert runners[0]["model"] == "codex"
        assert runners[1]["model"] == "gemini"

    def test_synthesis_early_exit_false_by_default(self):
        results = [{"model": "claude", "response": "A", "confidence": 0.90}]
        s = _synthesize_results(results)
        assert s["early_exit"] is False

    def test_confidence_badge_green_at_90(self):
        assert _confidence_level(0.90) == "high"

    def test_confidence_badge_yellow_at_70(self):
        assert _confidence_level(0.70) == "medium"

    def test_confidence_badge_orange_below_70(self):
        assert _confidence_level(0.69) == "low"

    def test_confidence_badge_green_range(self):
        for c in [0.90, 0.91, 0.95, 0.99, 1.00]:
            assert _confidence_level(c) == "high"

    def test_confidence_badge_yellow_range(self):
        for c in [0.70, 0.75, 0.80, 0.85, 0.89]:
            assert _confidence_level(c) == "medium"

    def test_confidence_badge_orange_range(self):
        for c in [0.00, 0.50, 0.65, 0.69]:
            assert _confidence_level(c) == "low"


# ── Test 7: Task store persistence ──────────────────────────────────────── #

class TestTaskPersistence(AioHTTPTestCase):
    async def get_application(self):
        return make_app()

    async def test_task_saved_on_creation(self):
        task_text = "Analyze this factory pattern implementation"
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": task_text},
        )
        data = await resp.json()
        tid = data["task_id"]

        assert tid in _task_store
        assert _task_store[tid]["task"] == task_text

    async def test_task_metadata_accessible_via_api(self):
        task_text = "Review this observer pattern code"
        resp = await self.client.post(
            "/api/coding-agent/invoke",
            json={"task": task_text, "language": "typescript"},
        )
        data = await resp.json()
        tid  = data["task_id"]

        resp2 = await self.client.get(f"/api/coding-agent/{tid}")
        assert resp2.status == 200
        meta = await resp2.json()
        assert meta["task"]     == task_text
        assert meta["language"] == "typescript"

    async def test_multiple_tasks_stored_independently(self):
        task1 = "First task: review algorithm"
        task2 = "Second task: optimize query"

        r1 = await self.client.post("/api/coding-agent/invoke", json={"task": task1})
        r2 = await self.client.post("/api/coding-agent/invoke", json={"task": task2})

        d1 = await r1.json()
        d2 = await r2.json()

        assert d1["task_id"] != d2["task_id"]
        assert _task_store[d1["task_id"]]["task"] == task1
        assert _task_store[d2["task_id"]]["task"] == task2
