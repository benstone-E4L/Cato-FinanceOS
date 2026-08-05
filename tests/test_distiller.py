"""
tests/test_distiller.py — Unit tests for Step 5 memory distillation pipeline.

Covers:
  - Distiller.distill() produces valid DistillationResult from sample conversation
  - key_facts extraction
  - decisions extraction (will/should/decided patterns)
  - open_questions extraction (lines ending with ?)
  - should_distill() triggers at every 20 turns
  - should_distill() triggers when token_count > 85% context limit
  - store_distillation() writes to SQLite
  - search_distilled() returns correct results
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cato.core.distiller import (
    Distiller,
    DistillationResult,
    should_distill,
)


# ---------------------------------------------------------------------------
# Sample conversation fixtures
# ---------------------------------------------------------------------------

SAMPLE_TURNS = [
    {"role": "user", "content": "What is the best way to implement rate limiting?"},
    {
        "role": "assistant",
        "content": (
            "The key point is that rate limiting can be implemented at the API gateway level. "
            "The result is reduced server load. "
            "We should use a token bucket algorithm for this use case. "
            "Will you need burst support as well?"
        ),
    },
    {
        "role": "user",
        "content": "Yes, burst support is important. How does the token bucket work?",
    },
    {
        "role": "assistant",
        "content": (
            "The token bucket algorithm works as follows: it is a counter that refills at a "
            "fixed rate. The value replenishes over time. "
            "We decided to use Redis for the counter store. "
            "Should we add a sliding window as well?"
        ),
    },
]

MINIMAL_TURNS = [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi there! How can I help?"},
]

CODE_TURNS = [
    {"role": "user", "content": "Write a function that sorts a list."},
    {
        "role": "assistant",
        "content": (
            "The answer is to use Python's built-in sorted() function. "
            "It is the most efficient approach for most cases. "
            "I will provide an example implementation."
        ),
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def distiller():
    return Distiller()


@pytest.fixture()
def memory_system(tmp_path):
    from cato.core.memory import MemorySystem

    mem = MemorySystem(agent_id="test-distill", memory_dir=tmp_path)
    yield mem
    mem.close()


# ---------------------------------------------------------------------------
# Distiller.distill() basic tests
# ---------------------------------------------------------------------------


def test_distill_returns_result(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    assert result is not None
    assert isinstance(result, DistillationResult)


def test_distill_empty_turns_returns_none(distiller):
    result = distiller.distill("sess-1", [])
    assert result is None


def test_distill_session_id(distiller):
    result = distiller.distill("my-session", SAMPLE_TURNS)
    assert result.session_id == "my-session"


def test_distill_turn_start_end(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS, turn_start=10)
    assert result.turn_start == 10
    assert result.turn_end == 10 + len(SAMPLE_TURNS) - 1


def test_distill_summary_not_empty(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    assert result.summary
    assert len(result.summary) > 0


def test_distill_summary_max_length(distiller):
    """Summary should not exceed ~200 words (approx token limit)."""
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    word_count = len(result.summary.split())
    assert word_count <= 250  # allow slight overhead for edge cases


def test_distill_created_at_set(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    assert result.created_at
    # Should be ISO format
    assert "T" in result.created_at


def test_distill_confidence_default(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    assert result.confidence == 0.75


def test_distill_embedding_bytes(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    assert result.embedding is not None
    assert isinstance(result.embedding, bytes)
    assert len(result.embedding) > 0


def test_distill_minimal_turns(distiller):
    result = distiller.distill("sess-min", MINIMAL_TURNS)
    assert result is not None
    assert result.summary


# ---------------------------------------------------------------------------
# key_facts extraction
# ---------------------------------------------------------------------------


def test_key_facts_is_list(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    assert isinstance(result.key_facts, list)


def test_key_facts_extracts_fact_patterns(distiller):
    """Turns containing 'the X is', 'it is', 'the result' etc should yield facts."""
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    # At least one fact extracted from "the key point is...", "the result is…"
    assert len(result.key_facts) >= 1


def test_key_facts_from_code_turns(distiller):
    result = distiller.distill("sess-code", CODE_TURNS)
    # "The answer is to use…" and "It is the most efficient…" match fact patterns
    assert len(result.key_facts) >= 1


# ---------------------------------------------------------------------------
# decisions extraction
# ---------------------------------------------------------------------------


def test_decisions_is_list(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    assert isinstance(result.decisions, list)


def test_decisions_extracts_will_pattern(distiller):
    """Sentences with 'will' should appear in decisions."""
    turns = [
        {"role": "assistant", "content": "I will implement the caching layer tomorrow."}
    ]
    result = distiller.distill("sess-dec", turns)
    assert any("will" in d.lower() for d in result.decisions)


def test_decisions_extracts_should_pattern(distiller):
    """Sentences with 'should' should appear in decisions."""
    turns = [
        {"role": "assistant", "content": "We should use a token bucket algorithm."}
    ]
    result = distiller.distill("sess-dec2", turns)
    assert any("should" in d.lower() for d in result.decisions)


def test_decisions_extracts_decided_pattern(distiller):
    """Sentences with 'decided' should appear in decisions."""
    turns = [
        {"role": "assistant", "content": "We decided to use Redis for the counter store."}
    ]
    result = distiller.distill("sess-dec3", turns)
    assert any("decided" in d.lower() for d in result.decisions)


def test_decisions_extracts_chose_pattern(distiller):
    """Sentences with 'chose' should appear in decisions."""
    turns = [
        {"role": "assistant", "content": "The team chose PostgreSQL over MySQL."}
    ]
    result = distiller.distill("sess-dec4", turns)
    assert any("chose" in d.lower() for d in result.decisions)


# ---------------------------------------------------------------------------
# open_questions extraction
# ---------------------------------------------------------------------------


def test_open_questions_is_list(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    assert isinstance(result.open_questions, list)


def test_open_questions_ends_with_question_mark(distiller):
    result = distiller.distill("sess-1", SAMPLE_TURNS)
    # SAMPLE_TURNS contains "Will you need burst support as well?" and
    # "Should we add a sliding window as well?"
    assert len(result.open_questions) >= 1
    for q in result.open_questions:
        assert q.endswith("?")


def test_open_questions_from_user_turn(distiller):
    turns = [
        {"role": "user", "content": "How does the token bucket work?"},
        {"role": "assistant", "content": "It is a counter that refills at a fixed rate."},
    ]
    result = distiller.distill("sess-q", turns)
    assert len(result.open_questions) >= 1


# ---------------------------------------------------------------------------
# should_distill()
# ---------------------------------------------------------------------------


def test_should_distill_at_20_turns():
    assert should_distill(20, 0, 10000) is True


def test_should_distill_at_40_turns():
    assert should_distill(40, 0, 10000) is True


def test_should_distill_at_60_turns():
    assert should_distill(60, 0, 10000) is True


def test_should_distill_not_at_10_turns():
    assert should_distill(10, 0, 10000) is False


def test_should_distill_not_at_1_turn():
    assert should_distill(1, 0, 10000) is False


def test_should_distill_not_at_zero_turns():
    assert should_distill(0, 0, 10000) is False


def test_should_distill_token_threshold_triggers():
    context_limit = 10000
    token_count = int(context_limit * 0.86)  # 86% > 85%
    assert should_distill(5, token_count, context_limit) is True


def test_should_distill_token_below_threshold_no_trigger():
    context_limit = 10000
    token_count = int(context_limit * 0.84)  # 84% < 85%
    assert should_distill(5, token_count, context_limit) is False


def test_should_distill_token_exactly_at_threshold():
    """Exactly at 85% — should NOT trigger (must be strictly greater)."""
    context_limit = 10000
    token_count = int(context_limit * 0.85)
    # Implementation uses >, so exactly 8500 out of 10000 should not trigger
    result = should_distill(5, token_count, context_limit)
    # 8500 > 8500 is False, so we expect False
    assert result is False


# ---------------------------------------------------------------------------
# store_distillation() and search_distilled()
# ---------------------------------------------------------------------------


def test_store_distillation_returns_row_id(distiller, memory_system):
    result = distiller.distill("sess-store", SAMPLE_TURNS)
    row_id = memory_system.store_distillation(result)
    assert isinstance(row_id, int)
    assert row_id > 0


def test_store_distillation_persists_to_db(distiller, memory_system):
    result = distiller.distill("sess-persist", SAMPLE_TURNS)
    memory_system.store_distillation(result)

    rows = memory_system._conn.execute(
        "SELECT * FROM distilled_summaries WHERE session_id = ?", ("sess-persist",)
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "sess-persist"
    assert row["summary"] == result.summary
    assert row["confidence"] == result.confidence


def test_store_distillation_key_facts_json(distiller, memory_system):
    result = distiller.distill("sess-json", SAMPLE_TURNS)
    memory_system.store_distillation(result)

    row = memory_system._conn.execute(
        "SELECT key_facts FROM distilled_summaries WHERE session_id = ?", ("sess-json",)
    ).fetchone()
    assert row is not None
    parsed = json.loads(row["key_facts"])
    assert isinstance(parsed, list)


def test_search_distilled_returns_results(distiller, memory_system):
    result = distiller.distill("sess-search", SAMPLE_TURNS)
    memory_system.store_distillation(result)

    hits = memory_system.search_distilled("rate limiting token bucket", session_id="sess-search")
    assert len(hits) >= 1


def test_search_distilled_source_file_format(distiller, memory_system):
    result = distiller.distill("sess-fmt", SAMPLE_TURNS, turn_start=0)
    memory_system.store_distillation(result)

    hits = memory_system.search_distilled("rate limiting", session_id="sess-fmt")
    assert hits
    source = hits[0]["source_file"]
    assert source.startswith("distill:sess-fmt:")


def test_search_distilled_empty_when_no_data(memory_system):
    hits = memory_system.search_distilled("anything", session_id="nonexistent-session")
    assert hits == []


def test_search_distilled_top_k_limit(distiller, memory_system):
    for i in range(5):
        r = distiller.distill(f"sess-topk-{i}", SAMPLE_TURNS, turn_start=i * 20)
        memory_system.store_distillation(r)

    hits = memory_system.search_distilled("token bucket rate limit", top_k=2)
    assert len(hits) <= 2
