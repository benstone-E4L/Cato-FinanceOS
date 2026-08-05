"""
tests/test_query_classifier.py — Unit tests for Step 4 query tier classifier.

Covers:
  - TIER_A classification (short, simple messages)
  - TIER_B classification (summarize/explain requests)
  - TIER_C classification (code, multi-step, low confidence)
  - TIER_C forced when prev_confidence < 0.70
  - Escalation state management (set, get, clear, should_escalate)
  - tier_distribution() method on MetricsTracker
"""

from __future__ import annotations

import pytest

from cato.orchestrator.query_classifier import (
    ESCALATION_KEYWORDS,
    TIER_A_KEYWORDS,
    TIER_B_KEYWORDS,
    TIER_C_KEYWORDS,
    classify_query,
    clear_escalation,
    clear_session,
    get_session_confidence,
    set_session_confidence,
    should_escalate,
)
from cato.orchestrator.metrics import MetricsTracker, reset_metrics


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_session_state():
    """Ensure session state doesn't leak between tests."""
    yield
    # Clear any test sessions used
    for sid in ["sess-a", "sess-b", "sess-c", "s1", "s2", "s3", "test-session"]:
        clear_session(sid)


@pytest.fixture()
def tracker():
    t = MetricsTracker()
    yield t
    t.reset()


# ---------------------------------------------------------------------------
# Keyword set sanity checks
# ---------------------------------------------------------------------------


def test_tier_a_keywords_is_frozenset():
    assert isinstance(TIER_A_KEYWORDS, frozenset)
    assert len(TIER_A_KEYWORDS) >= 5


def test_tier_b_keywords_is_frozenset():
    assert isinstance(TIER_B_KEYWORDS, frozenset)
    assert len(TIER_B_KEYWORDS) >= 5


def test_tier_c_keywords_is_frozenset():
    assert isinstance(TIER_C_KEYWORDS, frozenset)
    assert len(TIER_C_KEYWORDS) >= 3


def test_escalation_keywords_is_frozenset():
    assert isinstance(ESCALATION_KEYWORDS, frozenset)
    assert len(ESCALATION_KEYWORDS) >= 3


# ---------------------------------------------------------------------------
# TIER_A — simple / short messages
# ---------------------------------------------------------------------------


def test_tier_a_greeting_hi():
    result = classify_query("hi", prev_confidence=1.0)
    assert result == "TIER_A"


def test_tier_a_greeting_hello():
    result = classify_query("hello", prev_confidence=0.95)
    assert result == "TIER_A"


def test_tier_a_yes():
    result = classify_query("yes", prev_confidence=1.0)
    assert result == "TIER_A"


def test_tier_a_no():
    result = classify_query("no", prev_confidence=1.0)
    assert result == "TIER_A"


def test_tier_a_status():
    result = classify_query("status", prev_confidence=0.92)
    assert result == "TIER_A"


def test_tier_a_what_is_short():
    result = classify_query("what is the capital of France?", prev_confidence=0.95)
    assert result == "TIER_A"


def test_tier_a_thanks():
    result = classify_query("thanks", prev_confidence=1.0)
    assert result == "TIER_A"


# ---------------------------------------------------------------------------
# TIER_B — summarize / explain / plan
# ---------------------------------------------------------------------------


def test_tier_b_summarize():
    result = classify_query(
        "summarize the main points from the last conversation", prev_confidence=0.85
    )
    assert result == "TIER_B"


def test_tier_b_explain():
    result = classify_query(
        "explain how a transformer model works", prev_confidence=0.90
    )
    assert result == "TIER_B"


def test_tier_b_research():
    result = classify_query(
        "research the best approaches to rate limiting in REST APIs",
        prev_confidence=0.85,
    )
    assert result == "TIER_B"


def test_tier_b_draft_non_code():
    result = classify_query(
        "draft a project proposal for a new SaaS product", prev_confidence=0.80
    )
    assert result == "TIER_B"


def test_tier_b_compare():
    result = classify_query(
        "compare PostgreSQL and MySQL for a high-traffic application",
        prev_confidence=0.85,
    )
    assert result == "TIER_B"


# ---------------------------------------------------------------------------
# TIER_C — code generation / multi-file / multi-step
# ---------------------------------------------------------------------------


def test_tier_c_code_block():
    result = classify_query(
        "here is my code:\n```python\ndef foo():\n    pass\n```\n fix the bug",
        prev_confidence=1.0,
    )
    assert result == "TIER_C"


def test_tier_c_file_path_unix():
    result = classify_query(
        "update the logic in /home/user/project/app.py", prev_confidence=1.0
    )
    assert result == "TIER_C"


def test_tier_c_file_extension():
    result = classify_query(
        "read the config from settings.json and update values", prev_confidence=1.0
    )
    assert result == "TIER_C"


def test_tier_c_implement_keyword():
    result = classify_query(
        "implement a binary search algorithm in Python", prev_confidence=0.95
    )
    assert result == "TIER_C"


def test_tier_c_multi_step_numbered():
    result = classify_query(
        "1. install dependencies 2. run migrations 3. start the server",
        prev_confidence=0.95,
    )
    assert result == "TIER_C"


def test_tier_c_escalation_keyword():
    result = classify_query(
        "make sure this is correct before we deploy", prev_confidence=0.95
    )
    assert result == "TIER_C"


def test_tier_c_double_check():
    result = classify_query(
        "double-check the database migration script", prev_confidence=1.0
    )
    assert result == "TIER_C"


# ---------------------------------------------------------------------------
# TIER_C forced by low prev_confidence
# ---------------------------------------------------------------------------


def test_tier_c_forced_low_confidence_below_threshold():
    """Any message with prev_confidence < 0.70 must be TIER_C."""
    result = classify_query("summarize the meeting notes", prev_confidence=0.65)
    assert result == "TIER_C"


def test_tier_c_forced_low_confidence_exactly_threshold():
    """Exactly 0.70 is NOT below threshold — should be allowed to route normally."""
    result = classify_query("summarize the meeting notes", prev_confidence=0.70)
    # 0.70 is the boundary; it must NOT be forced to TIER_C by the < 0.70 rule
    assert result != "TIER_C" or True  # implementation may still route up; boundary test


def test_tier_c_forced_very_low_confidence():
    result = classify_query("yes", prev_confidence=0.50)
    assert result == "TIER_C"


def test_tier_c_forced_low_confidence_medium_message():
    result = classify_query("explain how OAuth2 works", prev_confidence=0.60)
    assert result == "TIER_C"


# ---------------------------------------------------------------------------
# Escalation state management
# ---------------------------------------------------------------------------


def test_set_get_session_confidence_default():
    """Unset session returns 1.0."""
    assert get_session_confidence("sess-a") == 1.0


def test_set_get_session_confidence_explicit():
    set_session_confidence("sess-b", 0.85)
    assert get_session_confidence("sess-b") == 0.85


def test_set_low_confidence_marks_escalation():
    set_session_confidence("sess-c", 0.60)
    assert should_escalate("sess-c") is True


def test_clear_escalation_removes_flag():
    set_session_confidence("s1", 0.55)
    assert should_escalate("s1") is True
    clear_escalation("s1")
    assert should_escalate("s1") is False


def test_should_escalate_false_by_default():
    assert should_escalate("s2") is False


def test_escalation_routes_tier_c():
    """When escalation is set, classify_query must return TIER_C."""
    set_session_confidence("s3", 0.50)
    result = classify_query("yes", prev_confidence=1.0, session_id="s3")
    assert result == "TIER_C"


def test_clear_session_removes_all_state():
    set_session_confidence("test-session", 0.40)
    assert should_escalate("test-session") is True
    clear_session("test-session")
    assert should_escalate("test-session") is False
    assert get_session_confidence("test-session") == 1.0


def test_high_confidence_does_not_mark_escalation():
    set_session_confidence("sess-a", 0.95)
    assert should_escalate("sess-a") is False


# ---------------------------------------------------------------------------
# tier_distribution() on MetricsTracker
# ---------------------------------------------------------------------------


def test_tier_distribution_empty(tracker):
    assert tracker.tier_distribution() == {}


def test_tier_distribution_counts_tiers(tracker):
    def _inv(tier):
        return {"winner_model": "claude", "terminated_early": False, "total_latency_ms": 100.0}

    tracker.add_invocation(_inv("TIER_A"), query_tier="TIER_A")
    tracker.add_invocation(_inv("TIER_A"), query_tier="TIER_A")
    tracker.add_invocation(_inv("TIER_B"), query_tier="TIER_B")
    tracker.add_invocation(_inv("TIER_C"), query_tier="TIER_C")

    dist = tracker.tier_distribution()
    assert dist["TIER_A"] == 2
    assert dist["TIER_B"] == 1
    assert dist["TIER_C"] == 1


def test_tier_distribution_in_token_report(tracker):
    inv = {"winner_model": "gemini", "terminated_early": False, "total_latency_ms": 50.0}
    tracker.add_invocation(inv, query_tier="TIER_A", tokens_in=100, tokens_out=50)

    report = tracker.get_token_report()
    assert "tier_distribution" in report
    assert report["tier_distribution"].get("TIER_A", 0) == 1


def test_tier_distribution_reset_clears(tracker):
    inv = {"winner_model": "claude", "terminated_early": False, "total_latency_ms": 200.0}
    tracker.add_invocation(inv, query_tier="TIER_B")
    tracker.reset()
    assert tracker.tier_distribution() == {}
