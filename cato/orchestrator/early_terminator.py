"""
Early termination logic for async model invocation.
Implements threshold-based termination to reduce latency.
"""

import asyncio
import logging
import time
from typing import Dict, List

logger = logging.getLogger(__name__)


async def wait_for_threshold(
    results_queue: asyncio.Queue,
    threshold: float = 0.90,
    max_wait_ms: int = 3000,
    cancel_event: asyncio.Event | None = None,
) -> Dict:
    """
    Monitor incoming results and terminate when the confidence threshold is met.

    Termination conditions (evaluated in priority order):
    1. Any result has ``confidence >= threshold`` — return that result immediately.
    2. All 3 expected results have arrived — return the highest-confidence one.
    3. ``max_wait_ms`` elapsed — return the best result seen so far.

    The function is designed to be used together with
    ``invoke_with_early_termination``, which pushes each model result into
    *results_queue* as soon as it arrives.  This arrangement means condition 1
    fires before the slower models have finished, achieving real latency savings.

    Args:
        results_queue: Queue fed by concurrent model invocations.
        threshold: Confidence threshold for early termination (default 0.90).
        max_wait_ms: Maximum wall-clock wait time in milliseconds (default 3000).
        cancel_event: Optional asyncio.Event to set when threshold is met,
            signalling ``invoke_with_early_termination`` to cancel slow models.

    Returns:
        {
            "winner": dict,          # Best result selected
            "elapsed_ms": float,     # Wall-clock time until decision
            "terminated_early": bool # True when threshold triggered early exit
        }
    """
    start_time = time.time()
    results: List[Dict] = []
    best_result: Dict = None
    best_confidence: float = -1.0
    max_wait_sec = max_wait_ms / 1000.0

    while True:
        elapsed_sec = time.time() - start_time
        if elapsed_sec >= max_wait_sec:
            break

        remaining_sec = max_wait_sec - elapsed_sec

        try:
            result = await asyncio.wait_for(
                results_queue.get(),
                timeout=remaining_sec,
            )
        except asyncio.TimeoutError:
            break

        results.append(result)
        confidence = result.get("confidence", 0.0)

        if confidence > best_confidence:
            best_confidence = confidence
            best_result = result

        if confidence >= threshold:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                "Early termination at %.1fms with %.2f confidence (model: %s)",
                elapsed_ms,
                confidence,
                result.get("model", "unknown"),
            )
            if cancel_event is not None:
                cancel_event.set()
            return {
                "winner": result,
                "elapsed_ms": elapsed_ms,
                "terminated_early": True,
            }

        if len(results) >= 3:
            break

    elapsed_ms = (time.time() - start_time) * 1000

    if best_result is None:
        best_result = {
            "model": "unknown",
            "response": "No results received",
            "confidence": 0.0,
            "latency_ms": elapsed_ms,
        }

    return {
        "winner": best_result,
        "elapsed_ms": elapsed_ms,
        "terminated_early": False,
    }


async def wait_for_best_of_n(
    results: List[Dict],
    n: int = 3,
) -> Dict:
    """
    Return the highest-confidence result from *results*.

    If fewer than *n* results are present the function still returns the best
    of whatever is available rather than blocking; this makes it safe to call
    after a timeout or partial failure.

    Args:
        results: List of result dicts, each containing at least a
            ``"confidence"`` key.
        n: Expected number of results.  Used only for logging; does not block.

    Returns:
        {
            "winner": dict,      # Highest-confidence result
            "count": int,        # Number of results provided
            "elapsed_ms": float  # Time spent in this function (near-zero)
        }
    """
    start_time = time.time()

    if results:
        best_result = max(results, key=lambda x: x.get("confidence", 0.0))
    else:
        best_result = {
            "model": "unknown",
            "response": "No results",
            "confidence": 0.0,
            "latency_ms": 0.0,
        }

    elapsed_ms = (time.time() - start_time) * 1000

    if len(results) < n:
        logger.warning(
            "wait_for_best_of_n: expected %d results, received %d",
            n,
            len(results),
        )

    return {
        "winner": best_result,
        "count": len(results),
        "elapsed_ms": elapsed_ms,
    }
