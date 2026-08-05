"""
cato/memory/outcome_observer.py — Outcome Observer background task (part of Skill 2).

Polls open Decision Records and attempts to observe downstream outcomes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .decision_memory import DecisionMemory

logger = logging.getLogger(__name__)

# Default observation windows (seconds) by action type keyword
_OBSERVATION_WINDOWS: dict[str, float] = {
    "email": 48 * 3600,
    "commit": 2 * 3600,
    "push": 2 * 3600,
    "api": 60,
    "file": 60,
    "write": 60,
}
_DEFAULT_WINDOW = 24 * 3600


def _get_observation_window(action: str) -> float:
    for key, window in _OBSERVATION_WINDOWS.items():
        if key in action.lower():
            return window
    return _DEFAULT_WINDOW


class OutcomeObserver:
    """
    Background asyncio task that polls open Decision Records.

    Checks observable downstream states and updates outcome_quality_score.
    This is a best-effort observer — failures are logged but not raised.
    """

    def __init__(
        self,
        decision_memory: DecisionMemory,
        poll_interval_sec: float = 300.0,
        observation_windows: Optional[dict[str, float]] = None,
    ) -> None:
        self._memory = decision_memory
        self._poll_interval = poll_interval_sec
        self._observation_windows = observation_windows or _OBSERVATION_WINDOWS
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="outcome-observer")
        logger.info("OutcomeObserver started (poll_interval=%.0fs)", self._poll_interval)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("OutcomeObserver stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._check_open_records()
            except Exception as exc:
                logger.warning("OutcomeObserver poll error: %s", exc)
            await asyncio.sleep(self._poll_interval)

    async def _check_open_records(self) -> None:
        open_records = self._memory.list_open()
        now = time.time()
        for record in open_records:
            window = next(
                (v for k, v in self._observation_windows.items() if k in record.action_taken.lower()),
                _DEFAULT_WINDOW,
            )
            age = now - record.timestamp

            if age < 60:  # Too fresh to observe
                continue

            if age > window:
                # Window expired without observation — neutral outcome
                self._memory.record_outcome(
                    record.decision_id,
                    observation="Observation window expired without result",
                    quality_score=0.0,
                    source="timeout",
                )
                logger.debug("Timed-out outcome for %s", record.decision_id)
