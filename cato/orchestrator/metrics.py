"""
Logging and metrics tracking for coding-agent skill.
Tracks performance, early termination rate, model agreement, and token usage.

Note: logging.basicConfig() is intentionally NOT called here.  Library code
must not configure the root logger; that responsibility belongs to the
application entry point.  Callers that want console output should add a
handler to the root logger or to 'cato' before calling these functions.
"""

import json
import logging
import time
from collections import deque
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# In-memory store for recent invocations (last 100)
_invocation_history: deque = deque(maxlen=100)

# Rolling window of token counts for avg_tokens_in/out_last_100 aggregates
_token_in_history:  deque = deque(maxlen=100)
_token_out_history: deque = deque(maxlen=100)


class MetricsTracker:
    """Track metrics for coding-agent invocations."""

    def __init__(self) -> None:
        self.invocations: List[Dict] = []
        self.early_terminations: int = 0
        self.total_invocations: int = 0
        # Token tracking accumulators
        self.total_tokens_in: int = 0
        self.total_tokens_out: int = 0
        self._token_in_window: deque = deque(maxlen=100)
        self._token_out_window: deque = deque(maxlen=100)
        self._tier_counts: Dict[str, int] = {}

    def add_invocation(
        self,
        invocation: Dict,
        tokens_in: int = 0,
        tokens_out: int = 0,
        query_tier: str = "",
        context_slots_used: Optional[Dict[str, int]] = None,
        ab_test_result: str = "",
    ) -> None:
        """
        Add an invocation record.

        Args:
            invocation: Invocation metrics dict.
            tokens_in: Number of input tokens consumed by this invocation.
            tokens_out: Number of output tokens produced by this invocation.
            query_tier: Routing tier label (e.g. "tier0", "tier1", "tier2").
            context_slots_used: Breakdown of token budget by slot:
                {tier0, tier1_memory, tier1_skill, tier1_tools, history}.
            ab_test_result: A/B test outcome: "champion", "challenger_win",
                "challenger_loss", or "" (not an A/B turn).
        """
        # Attach token metadata to the invocation record before storing
        invocation = dict(invocation)
        invocation["tokens_in"] = tokens_in
        invocation["tokens_out"] = tokens_out
        invocation["query_tier"] = query_tier
        invocation["context_slots_used"] = context_slots_used or {}
        invocation["ab_test_result"] = ab_test_result

        self.invocations.append(invocation)
        self.total_invocations += 1

        if invocation.get("terminated_early"):
            self.early_terminations += 1

        # Accumulate token totals
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self._token_in_window.append(tokens_in)
        self._token_out_window.append(tokens_out)

        # Track tier distribution
        if query_tier:
            self._tier_counts[query_tier] = self._tier_counts.get(query_tier, 0) + 1

        # Also update module-level rolling windows used by token report
        _token_in_history.append(tokens_in)
        _token_out_history.append(tokens_out)

    def reset(self) -> None:
        """
        Reset all tracked state.

        Useful in tests to prevent cross-test state contamination when the
        module-level singleton is used.
        """
        self.invocations.clear()
        self.early_terminations = 0
        self.total_invocations = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self._token_in_window.clear()
        self._token_out_window.clear()
        self._tier_counts.clear()

    def get_summary(self) -> Dict:
        """
        Return summary statistics over all tracked invocations.

        Returns:
            Dict with keys: total_invocations, early_terminations,
            early_termination_rate, avg_latency_ms, model_win_counts,
            recent_invocations, avg_tokens_in_last_100,
            avg_tokens_out_last_100, input_output_ratio, tier_distribution.
        """
        if not self.invocations:
            return {
                "total_invocations": 0,
                "early_terminations": 0,
                "early_termination_rate": 0.0,
                "avg_latency_ms": 0.0,
                "model_win_counts": {},
                "avg_tokens_in_last_100": 0.0,
                "avg_tokens_out_last_100": 0.0,
                "input_output_ratio": 0.0,
                "tier_distribution": {},
            }

        latencies = [inv.get("total_latency_ms", 0.0) for inv in self.invocations]
        avg_latency = sum(latencies) / len(latencies)

        model_wins: Dict[str, int] = {}
        for inv in self.invocations:
            winner = inv.get("winner_model", "unknown")
            model_wins[winner] = model_wins.get(winner, 0) + 1

        early_term_rate = (
            self.early_terminations / self.total_invocations * 100
            if self.total_invocations > 0
            else 0.0
        )

        avg_in = (
            sum(self._token_in_window) / len(self._token_in_window)
            if self._token_in_window
            else 0.0
        )
        avg_out = (
            sum(self._token_out_window) / len(self._token_out_window)
            if self._token_out_window
            else 0.0
        )
        ratio = avg_in / avg_out if avg_out > 0 else 0.0

        return {
            "total_invocations": self.total_invocations,
            "early_terminations": self.early_terminations,
            "early_termination_rate": early_term_rate,
            "avg_latency_ms": avg_latency,
            "model_win_counts": model_wins,
            "recent_invocations": list(self.invocations[-10:]),
            "avg_tokens_in_last_100": round(avg_in, 2),
            "avg_tokens_out_last_100": round(avg_out, 2),
            "input_output_ratio": round(ratio, 3),
            "tier_distribution": dict(self._tier_counts),
        }

    def tier_distribution(self) -> dict[str, int]:
        """
        Return count of invocations per query tier.

        Returns:
            Dict mapping tier label (e.g. "TIER_A", "TIER_B", "TIER_C") to count.
        """
        return dict(self._tier_counts)

    def get_token_report(self, cost_per_million_input: float = 3.0,
                         cost_per_million_output: float = 15.0) -> Dict:
        """
        Return a detailed token usage report.

        Args:
            cost_per_million_input: USD cost per 1M input tokens (default $3).
            cost_per_million_output: USD cost per 1M output tokens (default $15).

        Returns:
            Dict with total_tokens_in, total_tokens_out, ratio,
            per_slot_averages, tier_distribution, estimated_cost_usd.
        """
        avg_in = (
            sum(self._token_in_window) / len(self._token_in_window)
            if self._token_in_window
            else 0.0
        )
        avg_out = (
            sum(self._token_out_window) / len(self._token_out_window)
            if self._token_out_window
            else 0.0
        )
        ratio = self.total_tokens_in / self.total_tokens_out if self.total_tokens_out > 0 else 0.0

        # Compute per-slot averages from stored invocations
        slot_sums: Dict[str, int] = {}
        slot_counts: Dict[str, int] = {}
        for inv in self.invocations:
            for slot, val in (inv.get("context_slots_used") or {}).items():
                slot_sums[slot] = slot_sums.get(slot, 0) + val
                slot_counts[slot] = slot_counts.get(slot, 0) + 1
        per_slot_avg = {
            slot: round(slot_sums[slot] / slot_counts[slot], 1)
            for slot in slot_sums
        }

        cost_in = self.total_tokens_in / 1_000_000 * cost_per_million_input
        cost_out = self.total_tokens_out / 1_000_000 * cost_per_million_output
        estimated_cost = cost_in + cost_out

        return {
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "ratio_in_to_out": round(ratio, 3),
            "avg_tokens_in_last_100": round(avg_in, 2),
            "avg_tokens_out_last_100": round(avg_out, 2),
            "per_slot_averages": per_slot_avg,
            "tier_distribution": dict(self._tier_counts),
            "estimated_cost_usd": round(estimated_cost, 6),
            "total_invocations": self.total_invocations,
        }


# Module-level singleton
_tracker = MetricsTracker()


def track_invocation(
    task: str,
    total_latency_ms: float,
    winner_model: str,
    winner_confidence: float,
    terminated_early: bool,
    models_responded: int = 3,
    individual_latencies: Optional[Dict[str, float]] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    query_tier: str = "",
    context_slots_used: Optional[Dict[str, int]] = None,
    ab_test_result: str = "",
) -> None:
    """
    Record a single invocation in the in-memory history.

    Args:
        task: Task description (truncated to 200 chars in the log line).
        total_latency_ms: Wall-clock time from request start to synthesis.
        winner_model: Which model was selected (claude/codex/gemini).
        winner_confidence: Confidence score of the selected model.
        terminated_early: Whether early termination fired.
        models_responded: Number of models that returned before termination.
        individual_latencies: Mapping of model name to latency_ms.
        tokens_in: Input token count for this invocation.
        tokens_out: Output token count for this invocation.
        query_tier: Routing tier label (e.g. "tier0", "tier1").
        context_slots_used: Token budget breakdown by context slot.
        ab_test_result: A/B test outcome: "champion", "challenger_win",
            "challenger_loss", or "" (not an A/B turn).
    """
    individual_latencies = individual_latencies or {}

    invocation: Dict = {
        "timestamp": time.time(),
        "task": task,
        "total_latency_ms": total_latency_ms,
        "winner_model": winner_model,
        "winner_confidence": winner_confidence,
        "terminated_early": terminated_early,
        "models_responded": models_responded,
        "individual_latencies": individual_latencies,
    }

    _invocation_history.append(invocation)
    _tracker.add_invocation(
        invocation,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        query_tier=query_tier,
        context_slots_used=context_slots_used,
        ab_test_result=ab_test_result,
    )

    logger.info(
        "Task: %s | Latency: %.1fms | Winner: %s (%.2f) | Early: %s | Models: %d/3"
        " | Tokens in=%d out=%d tier=%s",
        task[:50],
        total_latency_ms,
        winner_model,
        winner_confidence,
        terminated_early,
        models_responded,
        tokens_in,
        tokens_out,
        query_tier or "n/a",
    )


def get_metrics_summary() -> Dict:
    """
    Return current metrics summary from the module-level tracker.

    Returns:
        Summary dict (see MetricsTracker.get_summary).
    """
    return _tracker.get_summary()


def get_token_report(
    cost_per_million_input: float = 3.0,
    cost_per_million_output: float = 15.0,
) -> Dict:
    """
    Return a detailed token usage report from the module-level tracker.

    Args:
        cost_per_million_input: USD cost per 1M input tokens (default $3).
        cost_per_million_output: USD cost per 1M output tokens (default $15).

    Returns:
        Token report dict (see MetricsTracker.get_token_report).
    """
    return _tracker.get_token_report(
        cost_per_million_input=cost_per_million_input,
        cost_per_million_output=cost_per_million_output,
    )


def get_recent_invocations(limit: int = 10) -> List[Dict]:
    """
    Return the most recent invocations from the rolling history.

    Args:
        limit: Maximum number of invocations to return (default 10).

    Returns:
        List of invocation dicts, newest last.
    """
    return list(_invocation_history)[-limit:]


def format_metrics_json() -> str:
    """
    Serialise the current metrics summary as a JSON string.

    Returns:
        Indented JSON string.
    """
    return json.dumps(get_metrics_summary(), indent=2, default=str)


def log_early_termination(model: str, confidence: float, elapsed_ms: float) -> None:
    """
    Emit an INFO log for an early termination event.

    Args:
        model: Model that triggered early termination.
        confidence: Confidence score that exceeded the threshold.
        elapsed_ms: Wall-clock time elapsed before termination fired.
    """
    logger.info(
        "Early termination at %.1fms with %.2f confidence (model: %s)",
        elapsed_ms,
        confidence,
        model,
    )


def log_synthesis_result(
    primary: Dict,
    runner_up_count: int,
    synthesis_note: str,
) -> None:
    """
    Emit an INFO log summarising the synthesis result.

    Args:
        primary: Primary result dict (must contain "model" and "confidence").
        runner_up_count: Number of runner-up alternatives.
        synthesis_note: Human-readable explanation of the selection.
    """
    logger.info(
        "Synthesis complete: %s | Runner-ups: %d",
        synthesis_note,
        runner_up_count,
    )


def reset_metrics() -> None:
    """
    Reset the module-level tracker and history.

    Intended for use in tests to prevent cross-test state contamination.
    """
    global _invocation_history
    _invocation_history.clear()
    _token_in_history.clear()
    _token_out_history.clear()
    _tracker.reset()
