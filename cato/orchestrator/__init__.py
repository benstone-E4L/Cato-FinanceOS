"""
Cato Orchestrator: Async model invocation and synthesis.

Implements parallel async invocation of Claude API, Codex CLI, and Gemini CLI
with early termination for latency reduction and confidence-based selection.
"""

from cato.orchestrator.cli_invoker import (
    invoke_claude_api,
    invoke_codex_cli,
    invoke_gemini_cli,
    invoke_all_parallel,
    invoke_with_early_termination,
)
from cato.orchestrator.confidence_extractor import (
    extract_confidence,
    score_response_quality
)
from cato.orchestrator.early_terminator import (
    wait_for_threshold,
    wait_for_best_of_n
)
from cato.orchestrator.synthesis import (
    simple_synthesis,
    weighted_synthesis
)
from cato.orchestrator.cli_process_pool import (
    get_pool,
    CLIProcessPool,
)
from cato.orchestrator.metrics import (
    track_invocation,
    get_metrics_summary,
    get_recent_invocations,
    format_metrics_json,
    log_early_termination,
    log_synthesis_result,
    reset_metrics,
)

__all__ = [
    # CLI Invoker
    "invoke_claude_api",
    "invoke_codex_cli",
    "invoke_gemini_cli",
    "invoke_all_parallel",
    "invoke_with_early_termination",
    # Confidence Extractor
    "extract_confidence",
    "score_response_quality",
    # Early Terminator
    "wait_for_threshold",
    "wait_for_best_of_n",
    # Synthesis
    "simple_synthesis",
    "weighted_synthesis",
    # Process Pool
    "get_pool",
    "CLIProcessPool",
    # Metrics
    "track_invocation",
    "get_metrics_summary",
    "get_recent_invocations",
    "format_metrics_json",
    "log_early_termination",
    "log_synthesis_result",
    "reset_metrics",
]
