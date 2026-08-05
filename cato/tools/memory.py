"""
cato/tools/memory.py — Memory search/store tool for agent use.

Wraps MemorySystem (core/memory.py) so the agent loop can call it as a tool.
Actions: search, store, flush
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MemoryTool:
    """Search and store facts in long-term memory.

    Wraps MemorySystem for use as an agent tool.
    """

    async def execute(self, args: dict[str, Any]) -> str:
        """Dispatch from agent_loop tool registry (receives raw args dict)."""
        action = args.get("action", "")
        query = args.get("query")
        content = args.get("content")
        agent_id = args.get("agent_id", "main")
        top_k = int(args.get("top_k", 5))

        result = await self._run(
            action=action,
            query=query,
            content=content,
            agent_id=agent_id,
            top_k=top_k,
        )
        return json.dumps(result)

    async def _run(
        self,
        action: str,
        query: Optional[str] = None,
        content: Optional[str] = None,
        agent_id: str = "main",
        top_k: int = 5,
    ) -> dict:
        """
        Memory operations.

        Actions:
          search: Find relevant memories by semantic similarity
          store:  Add new fact/note to memory
          flush:  Force-flush recent conversation to memory (call before compaction)

        Returns:
            search: {"results": [{"text": str}], "count": int}
            store:  {"success": bool, "chunks_stored": int}
            flush:  {"success": bool, "chunks_stored": int, "note": str}
        """
        from ..core.memory import MemorySystem

        mem = MemorySystem(agent_id)
        try:
            if hasattr(mem, "initialize"):
                await mem.initialize()

            if action == "search":
                if not query:
                    return {"error": "query required for search action"}
                raw_results = await mem.asearch(query, top_k=top_k)
                # asearch returns list[str] — wrap each for consistent structure
                results = [{"text": chunk} for chunk in raw_results]
                return {"results": results, "count": len(results)}

            elif action == "store":
                if not content:
                    return {"error": "content required for store action"}
                chunks_stored = await mem.astore(content, source_file="tool_call")
                return {"success": True, "chunks_stored": chunks_stored}

            elif action == "flush":
                # Full flush is handled by agent_loop before context compaction.
                # This stub acknowledges the call and documents that behaviour.
                return {
                    "success": True,
                    "chunks_stored": 0,
                    "note": "Call from agent_loop for full flush",
                }

            return {"error": f"Unknown action: {action!r}. Valid: search, store, flush"}
        finally:
            if hasattr(mem, "close"):
                mem.close()
