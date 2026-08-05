"""
tests/test_node.py — Comprehensive unit tests for cato/node.py.

Coverage:
  - NodeInfo: dataclass fields, touch(), is_stale()
  - NodeManager.register: new node, re-register updates fields
  - NodeManager.remove: removes node, cancels pending futures with exception
  - NodeManager.remove_by_ws: finds by ws object and delegates to remove()
  - NodeManager.list_nodes: serialisable output, stale flag
  - NodeManager.nodes_with_capability: filters by cap, excludes stale nodes
  - NodeManager.get_node: present and missing
  - NodeManager.invoke: happy path, no capable node, specific node not found,
    capability not supported, ws.send error, timeout
  - NodeManager.handle_message: node_register, node_unregister, node_ping,
    node_result (pending future resolved), node_list, unknown type, empty node_id
  - NodeManager.register_as_tools: tool names, handler invocation, error wrapping
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from cato.node import NodeInfo, NodeManager, _INVOKE_TIMEOUT


# ===========================================================================
# NodeInfo
# ===========================================================================

class TestNodeInfo:
    """Unit tests for the NodeInfo dataclass."""

    def test_fields_stored_correctly(self):
        ws = MagicMock()
        node = NodeInfo(
            node_id="dev-1",
            name="Dev Box",
            capabilities=["screenshot", "shell"],
            ws=ws,
        )
        assert node.node_id == "dev-1"
        assert node.name == "Dev Box"
        assert node.capabilities == ["screenshot", "shell"]
        assert node.ws is ws

    def test_registered_at_and_last_seen_set_automatically(self):
        before = time.time()
        node = NodeInfo(node_id="x", name="x", capabilities=[], ws=None)
        after = time.time()
        assert before <= node.registered_at <= after
        assert before <= node.last_seen <= after

    def test_touch_updates_last_seen(self):
        node = NodeInfo(node_id="x", name="x", capabilities=[], ws=None)
        node.last_seen = 0.0
        node.touch()
        assert node.last_seen > 0.0

    def test_is_stale_false_when_recently_seen(self):
        node = NodeInfo(node_id="x", name="x", capabilities=[], ws=None)
        # last_seen = now → not stale
        assert node.is_stale(timeout=120.0) is False

    def test_is_stale_true_when_old(self):
        node = NodeInfo(node_id="x", name="x", capabilities=[], ws=None)
        node.last_seen = time.time() - 200.0  # 200s ago
        assert node.is_stale(timeout=120.0) is True

    def test_is_stale_custom_timeout(self):
        node = NodeInfo(node_id="x", name="x", capabilities=[], ws=None)
        node.last_seen = time.time() - 10.0  # 10s ago
        # With 5s timeout it's stale; with 20s timeout it's not
        assert node.is_stale(timeout=5.0) is True
        assert node.is_stale(timeout=20.0) is False


# ===========================================================================
# NodeManager.register / remove / remove_by_ws
# ===========================================================================

class TestNodeManagerRegistration:

    def test_register_new_node(self):
        mgr = NodeManager()
        ws = MagicMock()
        node = mgr.register("node-1", "Box 1", ["screenshot"], ws)
        assert node.node_id == "node-1"
        assert node.name == "Box 1"
        assert mgr.get_node("node-1") is node

    def test_register_updates_existing_node(self):
        mgr = NodeManager()
        ws1, ws2 = MagicMock(), MagicMock()
        mgr.register("node-1", "Old Name", ["screenshot"], ws1)
        original_registered_at = mgr.get_node("node-1").registered_at

        node = mgr.register("node-1", "New Name", ["shell", "camera"], ws2)
        assert node.name == "New Name"
        assert node.capabilities == ["shell", "camera"]
        assert node.ws is ws2
        # registered_at must NOT be reset on re-register
        assert node.registered_at == original_registered_at

    def test_register_returns_node_info(self):
        mgr = NodeManager()
        result = mgr.register("n", "N", [], MagicMock())
        assert isinstance(result, NodeInfo)

    def test_remove_deletes_node(self):
        mgr = NodeManager()
        mgr.register("node-1", "B", [], MagicMock())
        mgr.remove("node-1")
        assert mgr.get_node("node-1") is None

    def test_remove_nonexistent_node_is_noop(self):
        mgr = NodeManager()
        mgr.remove("does-not-exist")  # must not raise

    def test_remove_cancels_pending_futures(self):
        mgr = NodeManager()
        mgr.register("node-1", "B", ["screenshot"], MagicMock())

        # Inject a pending future attributed to this node
        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            mgr._pending["req-abc"] = fut
            mgr._pending_node["req-abc"] = "node-1"
            mgr.remove("node-1")
            # Future must be set to an exception (RuntimeError about disconnect)
            assert fut.done()
            assert isinstance(fut.exception(), RuntimeError)
            assert "node-1" in str(fut.exception())
        finally:
            loop.close()

    def test_remove_by_ws_finds_correct_node(self):
        mgr = NodeManager()
        ws1, ws2 = MagicMock(), MagicMock()
        mgr.register("node-1", "B1", [], ws1)
        mgr.register("node-2", "B2", [], ws2)

        mgr.remove_by_ws(ws1)
        assert mgr.get_node("node-1") is None
        assert mgr.get_node("node-2") is not None

    def test_remove_by_ws_noop_when_no_match(self):
        mgr = NodeManager()
        mgr.register("node-1", "B", [], MagicMock())
        mgr.remove_by_ws(MagicMock())  # different ws → noop
        assert mgr.get_node("node-1") is not None


# ===========================================================================
# NodeManager query methods
# ===========================================================================

class TestNodeManagerQuery:

    def test_list_nodes_empty(self):
        mgr = NodeManager()
        assert mgr.list_nodes() == []

    def test_list_nodes_returns_serialisable_dicts(self):
        mgr = NodeManager()
        mgr.register("node-1", "Box", ["screenshot"], MagicMock())
        nodes = mgr.list_nodes()
        assert len(nodes) == 1
        n = nodes[0]
        assert n["node_id"] == "node-1"
        assert n["name"] == "Box"
        assert n["capabilities"] == ["screenshot"]
        assert "registered_at" in n
        assert "last_seen" in n
        assert "stale" in n
        # Ensure JSON serialisable
        json.dumps(nodes)

    def test_list_nodes_stale_flag_set_correctly(self):
        mgr = NodeManager()
        mgr.register("fresh", "Fresh", [], MagicMock())
        mgr.register("old", "Old", [], MagicMock())
        mgr.get_node("old").last_seen = time.time() - 200.0

        nodes = {n["node_id"]: n for n in mgr.list_nodes()}
        assert nodes["fresh"]["stale"] is False
        assert nodes["old"]["stale"] is True

    def test_nodes_with_capability_returns_matching_live_nodes(self):
        mgr = NodeManager()
        mgr.register("cap-node", "Cap", ["screenshot", "shell"], MagicMock())
        mgr.register("no-cap", "NoCap", ["shell"], MagicMock())

        result = mgr.nodes_with_capability("screenshot")
        assert len(result) == 1
        assert result[0].node_id == "cap-node"

    def test_nodes_with_capability_excludes_stale_nodes(self):
        mgr = NodeManager()
        mgr.register("stale-cap", "S", ["screenshot"], MagicMock())
        mgr.get_node("stale-cap").last_seen = time.time() - 200.0

        result = mgr.nodes_with_capability("screenshot")
        assert result == []

    def test_get_node_returns_none_for_missing(self):
        mgr = NodeManager()
        assert mgr.get_node("missing") is None


# ===========================================================================
# NodeManager.invoke
# ===========================================================================

class TestNodeManagerInvoke:

    @pytest.mark.asyncio
    async def test_invoke_happy_path(self):
        """invoke() sends a JSON payload and resolves the future from node_result."""
        mgr = NodeManager()
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()
        mgr.register("node-1", "B", ["screenshot"], ws)

        # Intercept the Future creation so we can resolve it immediately
        async def fake_wait_for(coro_or_fut, timeout):
            return {"success": True, "result": "base64data", "error": ""}

        with patch("asyncio.wait_for", side_effect=fake_wait_for):
            result = await mgr.invoke("screenshot", {"quality": "high"}, node_id="node-1")

        assert result["success"] is True
        assert result["result"] == "base64data"
        ws.send_str.assert_called_once()
        sent = json.loads(ws.send_str.call_args.args[0])
        assert sent["type"] == "node_invoke"
        assert sent["capability"] == "screenshot"
        assert sent["args"] == {"quality": "high"}

    @pytest.mark.asyncio
    async def test_invoke_raises_when_node_id_not_found(self):
        mgr = NodeManager()
        with pytest.raises(RuntimeError, match="not registered"):
            await mgr.invoke("screenshot", {}, node_id="ghost")

    @pytest.mark.asyncio
    async def test_invoke_raises_when_capability_not_supported(self):
        mgr = NodeManager()
        ws = MagicMock()
        ws.send = AsyncMock()
        mgr.register("node-1", "B", ["shell"], ws)
        with pytest.raises(RuntimeError, match="does not support"):
            await mgr.invoke("screenshot", {}, node_id="node-1")

    @pytest.mark.asyncio
    async def test_invoke_auto_picks_first_capable_node(self):
        """Without node_id, the first live node with the capability is used."""
        mgr = NodeManager()
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()
        mgr.register("cap-node", "B", ["camera"], ws)

        async def fake_wait_for(fut, timeout):
            return {"success": True, "result": "photo", "error": ""}

        with patch("asyncio.wait_for", side_effect=fake_wait_for):
            result = await mgr.invoke("camera", {})

        assert result["success"] is True
        ws.send_str.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_raises_when_no_capable_node(self):
        mgr = NodeManager()
        with pytest.raises(RuntimeError, match="No live node"):
            await mgr.invoke("camera", {})

    @pytest.mark.asyncio
    async def test_invoke_raises_on_ws_send_error(self):
        mgr = NodeManager()
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock(side_effect=ConnectionError("broken pipe"))
        mgr.register("node-1", "B", ["shell"], ws)

        with pytest.raises(RuntimeError, match="Could not send"):
            await mgr.invoke("shell", {}, node_id="node-1")

        # Pending entry must be cleaned up after send error
        assert len(mgr._pending) == 0

    @pytest.mark.asyncio
    async def test_invoke_raises_on_timeout(self):
        mgr = NodeManager()
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()
        mgr.register("node-1", "B", ["screenshot"], ws)

        async def fake_wait_for(fut, timeout):
            raise asyncio.TimeoutError

        with patch("asyncio.wait_for", side_effect=fake_wait_for):
            with pytest.raises(RuntimeError, match="timed out"):
                await mgr.invoke("screenshot", {}, node_id="node-1")

        # Pending entry cleaned up after timeout
        assert len(mgr._pending) == 0

    @pytest.mark.asyncio
    async def test_invoke_cleans_up_pending_on_success(self):
        """The pending entry is removed after a successful invoke."""
        mgr = NodeManager()
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()
        mgr.register("node-1", "B", ["shell"], ws)

        async def fake_wait_for(fut, timeout):
            return {"success": True, "result": "ok", "error": ""}

        with patch("asyncio.wait_for", side_effect=fake_wait_for):
            await mgr.invoke("shell", {}, node_id="node-1")

        assert len(mgr._pending) == 0


# ===========================================================================
# NodeManager.handle_message
# ===========================================================================

class TestNodeManagerHandleMessage:

    @pytest.mark.asyncio
    async def test_handle_node_register(self):
        mgr = NodeManager()
        ws = MagicMock()
        reply = await mgr.handle_message(ws, {
            "type": "node_register",
            "node_id": "pi-1",
            "name": "Raspberry Pi",
            "capabilities": ["camera", "shell"],
        })
        assert reply == {"type": "node_registered", "node_id": "pi-1"}
        assert mgr.get_node("pi-1") is not None
        assert mgr.get_node("pi-1").name == "Raspberry Pi"

    @pytest.mark.asyncio
    async def test_handle_node_register_empty_node_id_returns_error(self):
        mgr = NodeManager()
        ws = MagicMock()
        reply = await mgr.handle_message(ws, {
            "type": "node_register",
            "node_id": "",
            "capabilities": [],
        })
        assert reply is not None
        assert reply["type"] == "error"
        assert "node_id" in reply["text"].lower()

    @pytest.mark.asyncio
    async def test_handle_node_unregister(self):
        mgr = NodeManager()
        ws = MagicMock()
        mgr.register("pi-1", "Pi", ["camera"], ws)
        reply = await mgr.handle_message(ws, {
            "type": "node_unregister",
            "node_id": "pi-1",
        })
        assert reply == {"type": "node_unregistered", "node_id": "pi-1"}
        assert mgr.get_node("pi-1") is None

    @pytest.mark.asyncio
    async def test_handle_node_ping_updates_last_seen(self):
        mgr = NodeManager()
        ws = MagicMock()
        mgr.register("pi-1", "Pi", ["camera"], ws)
        node = mgr.get_node("pi-1")
        node.last_seen = 0.0

        reply = await mgr.handle_message(ws, {
            "type": "node_ping",
            "node_id": "pi-1",
        })
        assert reply == {"type": "node_pong"}
        assert node.last_seen > 0.0

    @pytest.mark.asyncio
    async def test_handle_node_ping_for_unknown_node_returns_pong(self):
        """Ping from an unregistered node still returns pong (no crash)."""
        mgr = NodeManager()
        ws = MagicMock()
        reply = await mgr.handle_message(ws, {
            "type": "node_ping",
            "node_id": "ghost",
        })
        assert reply == {"type": "node_pong"}

    @pytest.mark.asyncio
    async def test_handle_node_result_resolves_pending_future(self):
        """node_result message with a known request_id resolves the Future."""
        mgr = NodeManager()
        ws = MagicMock()

        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        req_id = "req-xyz"
        mgr._pending[req_id] = fut

        reply = await mgr.handle_message(ws, {
            "type": "node_result",
            "request_id": req_id,
            "success": True,
            "result": "screenshot-data",
        })
        assert reply is None   # no reply for node_result
        assert fut.done()
        result = fut.result()
        assert result["success"] is True
        assert result["result"] == "screenshot-data"

    @pytest.mark.asyncio
    async def test_handle_node_result_unknown_request_id_is_noop(self):
        """node_result for an unknown request_id does not crash."""
        mgr = NodeManager()
        ws = MagicMock()
        # No pending entries
        reply = await mgr.handle_message(ws, {
            "type": "node_result",
            "request_id": "unknown-req",
            "success": True,
            "result": "data",
        })
        assert reply is None

    @pytest.mark.asyncio
    async def test_handle_node_list(self):
        mgr = NodeManager()
        ws = MagicMock()
        mgr.register("pi-1", "Pi", ["camera"], ws)
        reply = await mgr.handle_message(ws, {"type": "node_list"})
        assert reply["type"] == "node_list_result"
        assert len(reply["nodes"]) == 1
        assert reply["nodes"][0]["node_id"] == "pi-1"

    @pytest.mark.asyncio
    async def test_handle_unknown_message_type_returns_none(self):
        mgr = NodeManager()
        ws = MagicMock()
        reply = await mgr.handle_message(ws, {"type": "node_custom_unknown"})
        assert reply is None

    @pytest.mark.asyncio
    async def test_handle_node_result_updates_node_last_seen(self):
        """node_result also touches the responding node's last_seen."""
        mgr = NodeManager()
        ws = MagicMock()
        mgr.register("pi-1", "Pi", ["camera"], ws)
        node = mgr.get_node("pi-1")
        node.last_seen = 0.0

        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        mgr._pending["r1"] = fut

        await mgr.handle_message(ws, {
            "type": "node_result",
            "request_id": "r1",
            "node_id": "pi-1",
            "success": True,
            "result": "data",
        })
        assert node.last_seen > 0.0

    @pytest.mark.asyncio
    async def test_handle_node_result_already_done_future_not_set_again(self):
        """If a Future is already done, node_result must not crash trying to set it."""
        mgr = NodeManager()
        ws = MagicMock()

        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        fut.set_result({"success": True, "result": "early"})  # already done
        mgr._pending["r-done"] = fut

        # Must not raise InvalidStateError
        reply = await mgr.handle_message(ws, {
            "type": "node_result",
            "request_id": "r-done",
            "success": True,
            "result": "late",
        })
        assert reply is None


# ===========================================================================
# NodeManager.register_as_tools
# ===========================================================================

class TestNodeManagerRegisterAsTools:

    def test_register_as_tools_calls_register_fn_for_each_capability(self):
        """register_as_tools() calls register_fn once per (node, cap) pair."""
        mgr = NodeManager()
        mgr.register("pi-1", "Pi", ["screenshot", "shell"], MagicMock())

        registered_tools: list[str] = []
        def fake_register(name, handler):
            registered_tools.append(name)

        mgr.register_as_tools(fake_register)

        assert "node.pi-1.screenshot" in registered_tools
        assert "node.pi-1.shell" in registered_tools
        assert len(registered_tools) == 2

    def test_register_as_tools_tool_name_format(self):
        """Tool names follow the pattern node.<node_id>.<capability>."""
        mgr = NodeManager()
        mgr.register("macbook-alice", "Alice", ["camera"], MagicMock())

        captured = {}
        def fake_register(name, handler):
            captured[name] = handler

        mgr.register_as_tools(fake_register)

        assert "node.macbook-alice.camera" in captured

    @pytest.mark.asyncio
    async def test_register_as_tools_handler_calls_invoke(self):
        """The registered handler delegates to NodeManager.invoke."""
        mgr = NodeManager()
        ws = MagicMock()
        ws.send = AsyncMock()
        mgr.register("pi-1", "Pi", ["shell"], ws)

        captured_handlers: dict = {}
        def fake_register(name, handler):
            captured_handlers[name] = handler

        mgr.register_as_tools(fake_register)

        # Patch invoke to return a controlled result
        async def mock_invoke(capability, args, node_id=None):
            return {"success": True, "result": "output"}

        mgr.invoke = mock_invoke

        handler = captured_handlers["node.pi-1.shell"]
        result_json = await handler({"command": "echo hello"})
        result = json.loads(result_json)
        assert result["success"] is True
        assert result["result"] == "output"

    @pytest.mark.asyncio
    async def test_register_as_tools_handler_wraps_invoke_errors(self):
        """If invoke raises, the handler returns a JSON error dict."""
        mgr = NodeManager()
        ws = MagicMock()
        ws.send = AsyncMock()
        mgr.register("pi-1", "Pi", ["shell"], ws)

        captured_handlers: dict = {}
        def fake_register(name, handler):
            captured_handlers[name] = handler

        mgr.register_as_tools(fake_register)

        async def failing_invoke(capability, args, node_id=None):
            raise RuntimeError("node offline")

        mgr.invoke = failing_invoke

        handler = captured_handlers["node.pi-1.shell"]
        result_json = await handler({"command": "echo hello"})
        result = json.loads(result_json)
        assert result["success"] is False
        assert "node offline" in result["error"]

    def test_register_as_tools_multiple_nodes(self):
        """All tools across multiple nodes are registered."""
        mgr = NodeManager()
        mgr.register("pi-1", "Pi", ["camera", "shell"], MagicMock())
        mgr.register("mac-1", "Mac", ["screenshot"], MagicMock())

        registered: list[str] = []
        mgr.register_as_tools(lambda name, h: registered.append(name))

        assert "node.pi-1.camera" in registered
        assert "node.pi-1.shell" in registered
        assert "node.mac-1.screenshot" in registered
        assert len(registered) == 3

    def test_register_as_tools_no_nodes_is_noop(self):
        """register_as_tools() with zero nodes does not call register_fn."""
        mgr = NodeManager()
        calls: list = []
        mgr.register_as_tools(lambda name, h: calls.append(name))
        assert calls == []


# ===========================================================================
# NodeManager.remove — pending future cancellation detail
# ===========================================================================

class TestNodeManagerRemovePendingCancellation:
    """Edge cases around pending future cancellation on node disconnect."""

    def test_remove_only_cancels_undone_futures(self):
        """remove() skips futures that are already done."""
        mgr = NodeManager()
        mgr.register("node-1", "B", ["screenshot"], MagicMock())

        loop = asyncio.new_event_loop()
        try:
            # Already-resolved future attributed to this node
            done_fut = loop.create_future()
            done_fut.set_result({"success": True, "result": "x"})
            # Pending future attributed to this node
            pending_fut = loop.create_future()
            mgr._pending["done-req"] = done_fut
            mgr._pending_node["done-req"] = "node-1"
            mgr._pending["pending-req"] = pending_fut
            mgr._pending_node["pending-req"] = "node-1"

            mgr.remove("node-1")

            # done_fut unchanged, pending_fut has exception
            assert done_fut.result() == {"success": True, "result": "x"}
            assert pending_fut.done()
            assert isinstance(pending_fut.exception(), RuntimeError)
        finally:
            loop.close()

    def test_remove_only_cancels_futures_for_disconnecting_node(self):
        """remove() must NOT cancel futures belonging to a different node."""
        mgr = NodeManager()
        mgr.register("node-1", "B", ["screenshot"], MagicMock())
        mgr.register("node-2", "C", ["camera"], MagicMock())

        loop = asyncio.new_event_loop()
        try:
            # fut1 belongs to node-1 (the one disconnecting)
            fut1 = loop.create_future()
            mgr._pending["r1"] = fut1
            mgr._pending_node["r1"] = "node-1"
            # fut2 belongs to node-2 (still alive)
            fut2 = loop.create_future()
            mgr._pending["r2"] = fut2
            mgr._pending_node["r2"] = "node-2"

            mgr.remove("node-1")

            # fut1 (node-1's request) should be cancelled
            assert fut1.done()
            assert isinstance(fut1.exception(), RuntimeError)
            assert "node-1" in str(fut1.exception())
            # fut2 (node-2's request) must NOT be touched
            assert not fut2.done()
        finally:
            loop.close()


# ===========================================================================
# R5 bug-fix: send_str vs send dispatch in invoke() and run_ping_loop()
# ===========================================================================

class TestR5SendStrDispatch:
    """
    Verify that invoke() and run_ping_loop() dispatch to ws.send_str on
    aiohttp-style websockets (which expose send_str) and fall back to
    ws.send on raw-websockets-style connections (which only expose send).
    """

    @pytest.mark.asyncio
    async def test_invoke_uses_send_str_for_aiohttp_node(self):
        """invoke() calls ws.send_str (not ws.send) when the ws has send_str."""
        mgr = NodeManager()
        # aiohttp WebSocketResponse exposes send_str, not send
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()
        mgr.register("aio-node", "AioHTTP Node", ["screenshot"], ws)

        async def fake_wait_for(coro_or_fut, timeout):
            return {"success": True, "result": "img", "error": ""}

        with patch("asyncio.wait_for", side_effect=fake_wait_for):
            result = await mgr.invoke("screenshot", {}, node_id="aio-node")

        assert result["success"] is True
        ws.send_str.assert_called_once()
        # send must NOT have been called (spec restricts the mock to send_str only)
        assert not hasattr(ws, "send") or not ws.send.called

    @pytest.mark.asyncio
    async def test_invoke_uses_send_for_raw_ws_node(self):
        """invoke() calls ws.send (not ws.send_str) when the ws has no send_str."""
        mgr = NodeManager()
        # websockets library exposes send, not send_str
        ws = MagicMock(spec=["send"])
        ws.send = AsyncMock()
        mgr.register("raw-node", "Raw WS Node", ["shell"], ws)

        async def fake_wait_for(coro_or_fut, timeout):
            return {"success": True, "result": "output", "error": ""}

        with patch("asyncio.wait_for", side_effect=fake_wait_for):
            result = await mgr.invoke("shell", {}, node_id="raw-node")

        assert result["success"] is True
        ws.send.assert_called_once()
        # send_str must NOT have been called (spec restricts mock to send only)
        assert not hasattr(ws, "send_str") or not ws.send_str.called

    @pytest.mark.asyncio
    async def test_ping_loop_uses_send_str_for_aiohttp_node(self):
        """run_ping_loop() sends the ping via ws.send_str for aiohttp-style nodes."""
        mgr = NodeManager()
        # aiohttp-style ws: has send_str, not send
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()
        mgr.register("aio-ping", "AioHTTP Ping Node", ["screenshot"], ws)

        sleep_call_count = 0

        async def fake_sleep(delay):
            nonlocal sleep_call_count
            sleep_call_count += 1
            # First call: return normally so the loop body (ping) executes.
            # Second call: cancel so the loop exits cleanly.
            if sleep_call_count >= 2:
                raise asyncio.CancelledError

        async def fake_wait_for(coro_or_fut, timeout):
            # Execute the coroutine so send_str is actually awaited
            await coro_or_fut
            return None

        with patch("asyncio.sleep", side_effect=fake_sleep), \
             patch("asyncio.wait_for", side_effect=fake_wait_for):
            await mgr.run_ping_loop()

        ws.send_str.assert_called_once()
        sent_payload = json.loads(ws.send_str.call_args.args[0])
        assert sent_payload["type"] == "node_ping"
        assert sent_payload["node_id"] == "aio-ping"
