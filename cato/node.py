"""
cato/node.py — Remote node capability registration for CATO.

Nodes are remote physical devices (a Mac, phone, Raspberry Pi, etc.) that
connect to the Gateway's WebSocket API and advertise capabilities.  The
Gateway can then route tool calls to the appropriate node.

Protocol (WebSocket messages, JSON):

  Node → Gateway  (register):
    {
      "type": "node_register",
      "node_id": "macbook-alice",       # unique stable ID per device
      "name": "Alice's MacBook",        # human label
      "capabilities": ["screenshot", "camera", "geolocation", "shell"]
    }

  Gateway → Node  (registered):
    {"type": "node_registered", "node_id": "macbook-alice"}

  Gateway → Node  (invoke capability):
    {
      "type": "node_invoke",
      "request_id": "<uuid>",
      "capability": "screenshot",
      "args": {}
    }

  Node → Gateway  (result):
    {
      "type": "node_result",
      "request_id": "<uuid>",
      "success": true,
      "result": "<base64 or text>"
    }

  Node → Gateway  (heartbeat / keep-alive):
    {"type": "node_ping", "node_id": "macbook-alice"}

  Gateway → Node  (keep-alive response):
    {"type": "node_pong"}

  Node → Gateway  (disconnect):
    {"type": "node_unregister", "node_id": "macbook-alice"}

Registered nodes are stored in memory only (no persistence across Gateway
restarts).  Nodes must re-register when they reconnect.

Node capabilities are also exposed as tools in the agent loop under the
namespace ``node.<node_id>.<capability>``, e.g.
``node.macbook-alice.screenshot``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

_INVOKE_TIMEOUT  = 30.0   # seconds to wait for a node capability response
_PING_INTERVAL   = 60.0   # seconds between gateway→node pings
_PING_TIMEOUT    = 10.0   # seconds to wait for pong before marking stale


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class NodeInfo:
    """Represents one registered remote node."""
    node_id:      str
    name:         str
    capabilities: list[str]
    ws:           Any                        # websocket connection object
    registered_at: float = field(default_factory=time.time)
    last_seen:    float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_seen = time.time()

    def is_stale(self, timeout: float = 120.0) -> bool:
        return time.time() - self.last_seen > timeout


# ---------------------------------------------------------------------------
# NodeManager
# ---------------------------------------------------------------------------

class NodeManager:
    """
    Manages all registered remote nodes.

    Instantiated once by the Gateway.  The Gateway WebSocket handler calls
    :meth:`handle_message` for every message whose ``type`` starts with
    ``node_``.  The Gateway also calls :meth:`remove_node` when a connection
    drops.
    """

    def __init__(self) -> None:
        # node_id → NodeInfo
        self._nodes: dict[str, NodeInfo] = {}
        # pending invoke: request_id → asyncio.Future
        self._pending: dict[str, asyncio.Future] = {}
        # pending invoke: request_id → node_id (to cancel only that node's futures)
        self._pending_node: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, node_id: str, name: str,
                 capabilities: list[str], ws: Any) -> NodeInfo:
        """Register or update a node.  Returns the NodeInfo."""
        if node_id in self._nodes:
            # Update existing — re-use registration time
            node = self._nodes[node_id]
            node.name = name
            node.capabilities = capabilities
            node.ws = ws
            node.touch()
            logger.info("Node re-registered: %s (%s) caps=%s", node_id, name, capabilities)
        else:
            node = NodeInfo(
                node_id=node_id,
                name=name,
                capabilities=capabilities,
                ws=ws,
            )
            self._nodes[node_id] = node
            logger.info("Node registered: %s (%s) caps=%s", node_id, name, capabilities)
        return node

    def remove(self, node_id: str) -> None:
        """Remove a node (called on WebSocket disconnect)."""
        if node_id in self._nodes:
            del self._nodes[node_id]
            logger.info("Node removed: %s", node_id)
            # Cancel only pending invocations that were sent to this specific node
            for req_id, fut in list(self._pending.items()):
                if self._pending_node.get(req_id) == node_id and not fut.done():
                    fut.set_exception(RuntimeError(f"Node {node_id!r} disconnected"))
                    self._pending_node.pop(req_id, None)

    def remove_by_ws(self, ws: Any) -> None:
        """Remove the node whose WebSocket matches *ws* (on disconnect)."""
        for node_id, node in list(self._nodes.items()):
            if node.ws is ws:
                self.remove(node_id)
                return

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_nodes(self) -> list[dict]:
        """Return a JSON-serialisable list of all registered nodes."""
        return [
            {
                "node_id":      n.node_id,
                "name":         n.name,
                "capabilities": n.capabilities,
                "registered_at": n.registered_at,
                "last_seen":    n.last_seen,
                "stale":        n.is_stale(),
            }
            for n in self._nodes.values()
        ]

    def nodes_with_capability(self, capability: str) -> list[NodeInfo]:
        """Return all live nodes that advertise *capability*."""
        return [
            n for n in self._nodes.values()
            if capability in n.capabilities and not n.is_stale()
        ]

    def get_node(self, node_id: str) -> Optional[NodeInfo]:
        return self._nodes.get(node_id)

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    async def invoke(self, capability: str, args: dict,
                     node_id: Optional[str] = None) -> dict:
        """
        Invoke *capability* on a node.

        If *node_id* is None the first live node advertising the capability
        is used.  Raises RuntimeError if no capable node is found or the
        call times out.
        """
        if node_id:
            node = self.get_node(node_id)
            if node is None:
                raise RuntimeError(f"Node {node_id!r} not registered")
            if capability not in node.capabilities:
                raise RuntimeError(f"Node {node_id!r} does not support {capability!r}")
        else:
            candidates = self.nodes_with_capability(capability)
            if not candidates:
                raise RuntimeError(f"No live node supports capability {capability!r}")
            node = candidates[0]

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[request_id] = fut
        self._pending_node[request_id] = node.node_id

        import json
        payload = json.dumps({
            "type":       "node_invoke",
            "request_id": request_id,
            "capability": capability,
            "args":       args,
        })
        try:
            if hasattr(node.ws, "send_str"):
                await node.ws.send_str(payload)
            else:
                await node.ws.send(payload)
        except Exception as exc:
            self._pending.pop(request_id, None)
            self._pending_node.pop(request_id, None)
            raise RuntimeError(f"Could not send to node {node.node_id!r}: {exc}") from exc

        try:
            result = await asyncio.wait_for(fut, timeout=_INVOKE_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            self._pending_node.pop(request_id, None)
            raise RuntimeError(
                f"Node {node.node_id!r} timed out after {_INVOKE_TIMEOUT}s "
                f"for capability {capability!r}"
            )
        finally:
            self._pending.pop(request_id, None)
            self._pending_node.pop(request_id, None)

        return result

    # ------------------------------------------------------------------
    # Message handling (called by Gateway WS handler)
    # ------------------------------------------------------------------

    async def handle_message(self, ws: Any, data: dict) -> Optional[dict]:
        """
        Process an incoming node-protocol message.

        Returns a dict to send back to the caller, or None.
        """
        msg_type = data.get("type", "")
        import json

        if msg_type == "node_register":
            node_id      = data.get("node_id", "").strip()
            name         = data.get("name", node_id)
            capabilities = data.get("capabilities") or []
            if not node_id:
                return {"type": "error", "text": "node_id required"}
            self.register(node_id, name, capabilities, ws)
            return {"type": "node_registered", "node_id": node_id}

        elif msg_type == "node_unregister":
            node_id = data.get("node_id", "").strip()
            self.remove(node_id)
            return {"type": "node_unregistered", "node_id": node_id}

        elif msg_type == "node_ping":
            node_id = data.get("node_id", "").strip()
            node = self.get_node(node_id)
            if node:
                node.touch()
            return {"type": "node_pong"}

        elif msg_type == "node_result":
            request_id = data.get("request_id", "")
            fut = self._pending.get(request_id)
            if fut and not fut.done():
                fut.set_result({
                    "success": data.get("success", True),
                    "result":  data.get("result"),
                    "error":   data.get("error", ""),
                })
            # Update last_seen for the responding node
            node_id = data.get("node_id", "")
            node = self.get_node(node_id)
            if node:
                node.touch()
            return None  # no reply needed

        elif msg_type == "node_list":
            return {"type": "node_list_result", "nodes": self.list_nodes()}

        return None   # unknown node message — let caller handle

    # ------------------------------------------------------------------
    # Tool adapter (registers node capabilities into the agent tool registry)
    # ------------------------------------------------------------------

    def register_as_tools(self, register_fn: Any) -> None:
        """
        Register all currently-connected node capabilities as agent tools.

        *register_fn* is a callable with signature ``(tool_name: str, handler: Coroutine)``,
        e.g. ``agent_loop.register_tool``.

        Tools are named ``node.<node_id>.<capability>``.

        The caller is responsible for invoking this after each new node registration
        so that freshly-connected capabilities become available to the agent loop.
        Call it from the node_register handler in Gateway if you want live wiring:

            nodes.register_as_tools(agent_loop.register_tool)
        """
        for node in self._nodes.values():
            for cap in node.capabilities:
                tool_name = f"node.{node.node_id}.{cap}"

                # Capture variables for closure
                def _make_handler(_node_id: str, _cap: str):
                    async def handler(args: dict) -> str:
                        import json
                        try:
                            result = await self.invoke(_cap, args, node_id=_node_id)
                            return json.dumps(result)
                        except Exception as exc:
                            return json.dumps({"error": str(exc), "success": False})
                    return handler

                register_fn(tool_name, _make_handler(node.node_id, cap))
                logger.debug("Registered node tool: %s", tool_name)

    # ------------------------------------------------------------------
    # Keepalive ping (run as a Gateway background task)
    # ------------------------------------------------------------------

    async def run_ping_loop(self) -> None:
        """
        Background task: ping all registered nodes every *_PING_INTERVAL* seconds.

        Nodes that do not respond within *_PING_TIMEOUT* seconds are removed
        (their WebSocket is presumed dead).  This ensures ``is_stale()`` reflects
        reality rather than waiting passively for the node to send a message.
        """
        import json
        while True:
            try:
                await asyncio.sleep(_PING_INTERVAL)
                for node_id, node in list(self._nodes.items()):
                    ping = json.dumps({"type": "node_ping", "node_id": node_id})
                    try:
                        _send = node.ws.send_str if hasattr(node.ws, "send_str") else node.ws.send
                        await asyncio.wait_for(_send(ping), timeout=_PING_TIMEOUT)
                        logger.debug("Pinged node %s", node_id)
                    except Exception as exc:
                        logger.warning("Ping failed for node %s — removing: %s", node_id, exc)
                        self.remove(node_id)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Node ping loop error: %s", exc)
