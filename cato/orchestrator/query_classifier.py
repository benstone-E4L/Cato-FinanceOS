"""
cato/orchestrator/query_classifier.py — Query tier classifier for single-model routing.

Classifies each query before context assembly:
  TIER_A → single cheapest model (Gemini): short, simple queries
  TIER_B → single mid model (Claude): single clear task, non-code
  TIER_C → fan-out all three: code, multi-step, low confidence

Estimated 40% reduction in multi-model token cost.
"""

from __future__ import annotations

import re
from typing import Literal

import tiktoken

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIER_A_KEYWORDS: frozenset[str] = frozenset(
    {
        "what is",
        "what are",
        "did you",
        "can you",
        "yes",
        "no",
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "sure",
        "got it",
        "sounds good",
        "great",
        "status",
        "ping",
        "how are you",
        "who are you",
    }
)

TIER_B_KEYWORDS: frozenset[str] = frozenset(
    {
        "summarize",
        "summarise",
        "explain",
        "describe",
        "what does",
        "draft",
        "write a",
        "outline",
        "research",
        "plan",
        "list",
        "tell me about",
        "give me an overview",
        "overview of",
        "what is the difference",
        "compare",
        "pros and cons",
        "pros/cons",
        "analyze",
        "analyse",
        "review",
    }
)

TIER_C_KEYWORDS: frozenset[str] = frozenset(
    {
        "implement",
        "write code",
        "create a function",
        "create a class",
        "generate code",
        "refactor",
        "fix bug",
        "debug",
        "build",
        "deploy",
        "migrate",
        "run tests",
        "run the tests",
        "update the database",
        "create endpoint",
        "add endpoint",
    }
)

ESCALATION_KEYWORDS: frozenset[str] = frozenset(
    {
        "best answer",
        "make sure",
        "double-check",
        "double check",
        "important",
        "critical",
        "urgent",
        "must not",
        "do not miss",
        "ensure",
        "verify",
    }
)

# ---------------------------------------------------------------------------
# Internal state (in-memory, reset on process restart)
# ---------------------------------------------------------------------------

_session_confidence: dict[str, float] = {}
_session_escalation: dict[str, bool] = {}

# ---------------------------------------------------------------------------
# Tokenizer (lazy)
# ---------------------------------------------------------------------------

_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = tiktoken.get_encoding("cl100k_base")
    return _tokenizer


def _token_count(text: str) -> int:
    """Return approximate tiktoken cl100k_base token count for *text*."""
    return len(_get_tokenizer().encode(text))


# ---------------------------------------------------------------------------
# Helper predicates
# ---------------------------------------------------------------------------

_CODE_BLOCK_RE = re.compile(r"```|~~~", re.MULTILINE)
_FILE_PATH_RE = re.compile(
    r"""
    (?:
        [a-zA-Z]:[/\\]   # Windows drive letter path
        | /[a-zA-Z]      # Unix absolute path
        | \./            # relative ./
        | \.\./          # relative ../
        | (?:[\w\-]+/){2,}  # two or more path segments
        | \.(?:py|js|ts|tsx|jsx|json|yaml|yml|toml|md|txt|sh|sql|csv)\b  # file extension
    )
    """,
    re.VERBOSE,
)
_MULTI_STEP_RE = re.compile(
    r"""
    (?:
        \bstep\s+\d+\b       # step 1, step 2 …
        | \bfirst[,\s]+then\b
        | \bthen\s+also\b
        | \band\s+also\b
        | \bafter\s+that\b
        | \bfinally\b
        | \d+\.\s+\w          # numbered list item
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _has_code_block(message: str) -> bool:
    return bool(_CODE_BLOCK_RE.search(message))


def _has_file_path(message: str) -> bool:
    return bool(_FILE_PATH_RE.search(message))


def _has_escalation_keyword(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in ESCALATION_KEYWORDS)


def _has_tier_c_keyword(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in TIER_C_KEYWORDS)


def _has_tier_b_keyword(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in TIER_B_KEYWORDS)


def _has_tier_a_keyword(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in TIER_A_KEYWORDS)


def _is_multi_step(message: str) -> bool:
    return bool(_MULTI_STEP_RE.search(message))


# ---------------------------------------------------------------------------
# Public classifier
# ---------------------------------------------------------------------------


def classify_query(
    message: str,
    prev_confidence: float = 1.0,
    session_id: str = "",
) -> Literal["TIER_A", "TIER_B", "TIER_C"]:
    """
    Classify a query into a routing tier.

    Args:
        message: The user message to classify.
        prev_confidence: Confidence score of the previous turn (default 1.0).
        session_id: Optional session identifier for escalation state lookup.

    Returns:
        "TIER_A", "TIER_B", or "TIER_C".
    """
    # Check session-level escalation flag first
    if session_id and _session_escalation.get(session_id, False):
        return "TIER_C"

    # Hard TIER_C conditions — escalation keywords
    if _has_escalation_keyword(message):
        return "TIER_C"

    # Hard TIER_C — code block or file path present
    if _has_code_block(message) or _has_file_path(message):
        return "TIER_C"

    # Hard TIER_C — low previous confidence
    if prev_confidence < 0.70:
        return "TIER_C"

    # Hard TIER_C — multi-step task
    if _is_multi_step(message):
        return "TIER_C"

    # Hard TIER_C — explicit tier-C keywords
    if _has_tier_c_keyword(message):
        return "TIER_C"

    token_count = _token_count(message)

    # TIER_A — short, simple, no code/path, high confidence
    if (
        token_count < 50
        and not _has_code_block(message)
        and not _has_file_path(message)
        and _has_tier_a_keyword(message)
        and prev_confidence >= 0.90
    ):
        return "TIER_A"

    # TIER_A — very short messages that match greeting/simple intent even
    # without explicit keyword, as long as there is no code/multi-step
    if (
        token_count < 20
        and not _has_code_block(message)
        and not _has_file_path(message)
        and not _has_tier_b_keyword(message)
        and not _has_tier_c_keyword(message)
        and prev_confidence >= 0.90
    ):
        return "TIER_A"

    # TIER_B — single clear task, non-code
    if _has_tier_b_keyword(message):
        return "TIER_B"

    # TIER_B — medium length, not code, not escalation
    if (
        50 <= token_count <= 300
        and not _has_code_block(message)
        and not _has_file_path(message)
        and not _is_multi_step(message)
    ):
        return "TIER_B"

    # Default: fan-out
    return "TIER_C"


# ---------------------------------------------------------------------------
# Session confidence management
# ---------------------------------------------------------------------------


def get_session_confidence(session_id: str) -> float:
    """Return the stored confidence for *session_id*, defaulting to 1.0."""
    return _session_confidence.get(session_id, 1.0)


def set_session_confidence(session_id: str, confidence: float) -> None:
    """
    Store *confidence* for *session_id*.

    When confidence < 0.70, automatically marks the session for escalation
    on the next turn.
    """
    _session_confidence[session_id] = confidence
    if confidence < 0.70:
        _session_escalation[session_id] = True


def should_escalate(session_id: str) -> bool:
    """Return True if the next turn for *session_id* should be escalated."""
    return _session_escalation.get(session_id, False)


def clear_escalation(session_id: str) -> None:
    """Clear the escalation flag for *session_id*."""
    _session_escalation.pop(session_id, None)


def clear_session(session_id: str) -> None:
    """Remove all stored state for *session_id*."""
    _session_confidence.pop(session_id, None)
    _session_escalation.pop(session_id, None)
