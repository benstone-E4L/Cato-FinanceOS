"""
cato/heartbeat.py — Periodic health-check monitor for CATO.

Reads HEARTBEAT.md from each agent's workspace directory.  HEARTBEAT.md
contains a checklist of items the agent should verify on a schedule.

Format example::

    # Heartbeat Checklist
    <!-- interval: 300 -->   ← seconds between checks (default 300)

    - [ ] Check disk space is above 10%
    - [ ] Verify monitoring script is running
    - [ ] Confirm API endpoints return 200

Lines starting with ``- [ ]`` or ``- [x]`` are checklist items.
An optional HTML comment ``<!-- interval: N -->`` sets the poll interval
in seconds (default 300s / 5 minutes).

When a heartbeat fires the full checklist is sent to the agent as a
system prompt, exactly like a cron-injected message.  The agent responds
and the result is delivered to the ``heartbeat`` channel (broadcast to
all connected WebSocket clients).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .gateway import Gateway

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 300          # 5 minutes
_INTERVAL_RE      = re.compile(r"<!--\s*interval:\s*(\d+)\s*-->", re.IGNORECASE)
_ITEM_RE          = re.compile(r"^\s*-\s*\[[ x]\]\s*(.+)$", re.MULTILINE)


def _parse_heartbeat_md(path: Path) -> tuple[int, list[str]]:
    """
    Parse HEARTBEAT.md.

    Returns (interval_seconds, [checklist_items]).
    Returns (DEFAULT_INTERVAL, []) if the file is missing or empty.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _DEFAULT_INTERVAL, []

    interval = _DEFAULT_INTERVAL
    m = _INTERVAL_RE.search(text)
    if m:
        interval = max(30, int(m.group(1)))  # minimum 30s

    items = [m.group(1).strip() for m in _ITEM_RE.finditer(text)]
    return interval, items


def _build_heartbeat_prompt(agent_name: str, items: list[str]) -> str:
    """Build the prompt string sent to the agent during a heartbeat check."""
    checklist = "\n".join(f"- [ ] {item}" for item in items)
    return (
        f"[HEARTBEAT CHECK for agent: {agent_name}]\n\n"
        "Please go through each item below and confirm its status. "
        "Use your available tools (shell, browser, file) to verify. "
        "Report any failures clearly so they can be acted on.\n\n"
        f"{checklist}\n\n"
        "Respond with: OK items, any FAIL items with reason, and recommended actions."
    )


class HeartbeatMonitor:
    """
    Runs periodic heartbeat checks for all agents that have HEARTBEAT.md.

    Instantiated once by the Gateway and started as a background task.
    """

    def __init__(self, gateway: "Gateway", data_dir: Path) -> None:
        self._gateway   = gateway
        self._data_dir  = data_dir
        # Track last fire time per agent to respect per-agent intervals
        self._last_fire: dict[str, float] = {}

    async def run_forever(self) -> None:
        """Main loop: poll every 30s, fire agents whose interval has elapsed."""
        logger.info("HeartbeatMonitor started")
        while True:
            try:
                await asyncio.sleep(30)
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("HeartbeatMonitor error: %s", exc, exc_info=True)

    async def _tick(self) -> None:
        agents_dir = self._data_dir / "agents"
        if not agents_dir.exists():
            return

        now = time.time()
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            hb_path = agent_dir / "workspace" / "HEARTBEAT.md"
            if not hb_path.exists():
                # Also check directly in agent_dir (flat layout)
                hb_path = agent_dir / "HEARTBEAT.md"
                if not hb_path.exists():
                    continue

            interval, items = _parse_heartbeat_md(hb_path)
            if not items:
                continue

            last = self._last_fire.get(agent_dir.name, 0.0)
            if now - last < interval:
                continue

            self._last_fire[agent_dir.name] = now
            await self._fire(agent_dir.name, items)

    async def _fire(self, agent_name: str, items: list[str]) -> None:
        """Inject a heartbeat check into the agent's lane queue."""
        session_id = f"heartbeat-{agent_name}"
        prompt     = _build_heartbeat_prompt(agent_name, items)
        logger.info("Heartbeat firing for agent=%s (%d items)", agent_name, len(items))
        try:
            await self._gateway.ingest(
                session_id=session_id,
                message=prompt,
                channel="heartbeat",
                agent_id=agent_name,
            )
        except Exception as exc:
            logger.error("Heartbeat inject failed for %s: %s", agent_name, exc)

    # ------------------------------------------------------------------
    # Manual trigger (for tests / cato heartbeat run CLI)
    # ------------------------------------------------------------------

    async def fire_now(self, agent_name: str) -> Optional[list[str]]:
        """
        Immediately fire heartbeat for *agent_name*.

        Returns the checklist items that were sent, or None if no
        HEARTBEAT.md found.
        """
        agent_dir = self._data_dir / "agents" / agent_name
        hb_path = agent_dir / "workspace" / "HEARTBEAT.md"
        if not hb_path.exists():
            hb_path = agent_dir / "HEARTBEAT.md"
            if not hb_path.exists():
                return None

        _, items = _parse_heartbeat_md(hb_path)
        if not items:
            return []

        await self._fire(agent_name, items)
        return items
