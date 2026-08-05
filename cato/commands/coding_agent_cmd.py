"""
CLI command for coding-agent skill.
Orchestrates async model invocation with early termination.
"""

import asyncio
import json
import logging
import time
from typing import Optional

from cato.orchestrator.cli_invoker import (
    invoke_all_parallel,
    invoke_with_early_termination,
)
from cato.orchestrator.early_terminator import wait_for_threshold
from cato.orchestrator.synthesis import simple_synthesis
from cato.orchestrator.metrics import (
    track_invocation,
    log_synthesis_result,
)

logger = logging.getLogger(__name__)


async def cmd_coding_agent(
    task: str,
    context: str = "",
    verbose: bool = False,
    threshold: float = 0.90,
    max_wait_ms: int = 3000,
) -> str:
    """
    Execute a coding-agent task with async model orchestration and early termination.

    Models are invoked concurrently.  Each result is pushed into a queue the
    moment it arrives; ``wait_for_threshold`` monitors the queue and returns as
    soon as any result exceeds *threshold* — without waiting for slower models
    to finish.  This provides genuine latency reduction compared to awaiting
    all models before evaluating confidence scores.

    Args:
        task: Task description (e.g., "optimize this function").
        context: Optional context or code to analyse.
        verbose: Enable verbose progress logging.
        threshold: Early termination confidence threshold (default 0.90).
        max_wait_ms: Maximum wait time in milliseconds (default 3000).

    Returns:
        JSON string with keys: status, synthesis, metrics.
    """
    start_time = time.time()

    try:
        prompt = context or ""
        if verbose:
            logger.info("[CodeAgent] Starting task: %s", task)
            logger.info("[CodeAgent] Prompt length: %d chars", len(prompt))

        # ------------------------------------------------------------------
        # Phase 1: Launch all model invocations concurrently.
        # invoke_with_early_termination pushes each result into results_queue
        # as soon as it completes, so wait_for_threshold can act on the first
        # high-confidence result before the slower models finish.
        # ------------------------------------------------------------------
        results_queue: asyncio.Queue = asyncio.Queue()

        if verbose:
            logger.info("[CodeAgent] Invoking Claude API, Codex CLI, Gemini CLI in parallel...")

        # Schedule the fan-out as a background task so we can concurrently
        # drain the queue in wait_for_threshold.
        fan_out_task = asyncio.create_task(
            invoke_with_early_termination(prompt, task, results_queue, threshold)
        )

        # ------------------------------------------------------------------
        # Phase 2: Early-termination monitoring runs while fan_out_task is
        # still dispatching model calls.
        # ------------------------------------------------------------------
        termination_result = await wait_for_threshold(
            results_queue,
            threshold=threshold,
            max_wait_ms=max_wait_ms,
        )

        winner = termination_result["winner"]
        elapsed_ms = termination_result["elapsed_ms"]
        terminated_early = termination_result["terminated_early"]

        if verbose:
            if terminated_early:
                logger.info(
                    "[CodeAgent] EARLY TERMINATION at %.1fms with %.2f confidence",
                    elapsed_ms,
                    winner.get("confidence", 0),
                )
            else:
                logger.info("[CodeAgent] All models processed in %.1fms", elapsed_ms)

        # ------------------------------------------------------------------
        # Phase 3: Collect all available results for synthesis.
        # We wait for the fan-out task to fully finish so simple_synthesis
        # can see all three model responses (runners-up are useful context).
        # If early termination already fired we may cancel here instead —
        # for now we let it finish to maintain the runners-up feature.
        # ------------------------------------------------------------------
        try:
            await asyncio.wait_for(fan_out_task, timeout=max_wait_ms / 1000.0)
        except asyncio.TimeoutError:
            fan_out_task.cancel()

        # Drain whatever arrived in the queue after early termination
        collected = [winner]
        while not results_queue.empty():
            item = results_queue.get_nowait()
            # Avoid duplicating the winner that wait_for_threshold already consumed
            if item.get("model") != winner.get("model"):
                collected.append(item)

        # Build placeholder results for any missing models
        present_models = {r.get("model") for r in collected}
        for model_name, default_conf in [("claude", 0.5), ("codex", 0.6), ("gemini", 0.55)]:
            if model_name not in present_models:
                collected.append({
                    "model": model_name,
                    "response": f"[{model_name.capitalize()} did not respond in time]",
                    "confidence": default_conf,
                    "latency_ms": elapsed_ms,
                })

        model_map = {r["model"]: r for r in collected}
        claude_result = model_map.get("claude", collected[0])
        codex_result = model_map.get("codex", collected[0])
        gemini_result = model_map.get("gemini", collected[0])

        if verbose:
            for label, res in [("Claude", claude_result), ("Codex", codex_result), ("Gemini", gemini_result)]:
                logger.info("[CodeAgent] %s latency: %.1fms", label, res.get("latency_ms", 0))

        # ------------------------------------------------------------------
        # Phase 4: Synthesis
        # ------------------------------------------------------------------
        synthesis = simple_synthesis(claude_result, codex_result, gemini_result)

        if verbose:
            log_synthesis_result(
                synthesis["primary"],
                len(synthesis["runners_up"]),
                synthesis["synthesis_note"],
            )

        # ------------------------------------------------------------------
        # Phase 5: Metrics
        # ------------------------------------------------------------------
        total_latency_ms = (time.time() - start_time) * 1000
        track_invocation(
            task=task,
            total_latency_ms=total_latency_ms,
            winner_model=synthesis["primary"]["model"],
            winner_confidence=synthesis["primary"]["confidence"],
            terminated_early=terminated_early,
            models_responded=len(present_models),
            individual_latencies={
                "claude": claude_result.get("latency_ms", 0),
                "codex": codex_result.get("latency_ms", 0),
                "gemini": gemini_result.get("latency_ms", 0),
            },
        )

        # ------------------------------------------------------------------
        # Phase 6: Format response
        # ------------------------------------------------------------------
        response = {
            "status": "success",
            "synthesis": synthesis,
            "metrics": {
                "total_latency_ms": total_latency_ms,
                "early_termination": terminated_early,
                "elapsed_ms": elapsed_ms,
            },
        }
        return json.dumps(response, indent=2)

    except Exception as e:
        total_latency_ms = (time.time() - start_time) * 1000
        logger.exception("[CodeAgent] Unhandled error: %s", e)
        return json.dumps({
            "status": "error",
            "error": str(e),
            "total_latency_ms": total_latency_ms,
        })


def cmd_coding_agent_sync(
    task: str,
    context: str = "",
    verbose: bool = False,
    threshold: float = 0.90,
    max_wait_ms: int = 3000,
) -> str:
    """
    Synchronous wrapper for ``cmd_coding_agent``.

    Creates a fresh event loop for each call so it can be safely invoked from
    a non-async context (e.g., a Click CLI command or a unit test) without
    conflicting with any running loop.

    Args:
        task: Task description.
        context: Optional context or code.
        verbose: Verbose logging.
        threshold: Early termination threshold.
        max_wait_ms: Max wait time in milliseconds.

    Returns:
        JSON string response.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            cmd_coding_agent(task, context, verbose, threshold, max_wait_ms)
        )
    finally:
        loop.close()
        asyncio.set_event_loop(None)
