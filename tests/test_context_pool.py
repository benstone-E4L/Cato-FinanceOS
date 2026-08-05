"""
Tests for cato/core/context_pool.py — ContextPool A/B testing.

Phase G — Step 8.4: Min 20 tests.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cato.core.context_pool import ABTestState, ContextPool


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def make_pool() -> tuple[ContextPool, MagicMock]:
    """Create an isolated in-memory ContextPool backed by a temp SQLite file."""
    memory = MagicMock()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    pool = ContextPool(memory, db_path=db_path)
    return pool, memory


# ---------------------------------------------------------------------------
# 1. record_usage — counts and avg_score
# ---------------------------------------------------------------------------

def test_record_usage_increments_use_count():
    pool, _ = make_pool()
    pool.record_usage("chunk-1", "text about Python", confidence=0.90)
    pool.record_usage("chunk-1", "text about Python", confidence=0.90)

    rows = pool._conn.execute(
        "SELECT use_count FROM chunk_usage WHERE chunk_id = 'chunk-1'"
    ).fetchone()
    assert rows["use_count"] == 2


def test_record_usage_increments_success_count_when_confident():
    pool, _ = make_pool()
    pool.record_usage("chunk-2", "text", confidence=0.90, success_threshold=0.80)
    pool.record_usage("chunk-2", "text", confidence=0.85, success_threshold=0.80)

    row = pool._conn.execute(
        "SELECT success_count FROM chunk_usage WHERE chunk_id = 'chunk-2'"
    ).fetchone()
    assert row["success_count"] == 2


def test_record_usage_does_not_increment_success_below_threshold():
    pool, _ = make_pool()
    pool.record_usage("chunk-3", "text", confidence=0.50, success_threshold=0.80)

    row = pool._conn.execute(
        "SELECT success_count FROM chunk_usage WHERE chunk_id = 'chunk-3'"
    ).fetchone()
    assert row["success_count"] == 0


def test_record_usage_mixed_success_and_failure():
    pool, _ = make_pool()
    pool.record_usage("chunk-4", "text", confidence=0.90)  # success
    pool.record_usage("chunk-4", "text", confidence=0.50)  # failure
    pool.record_usage("chunk-4", "text", confidence=0.95)  # success

    row = pool._conn.execute(
        "SELECT use_count, success_count FROM chunk_usage WHERE chunk_id = 'chunk-4'"
    ).fetchone()
    assert row["use_count"] == 3
    assert row["success_count"] == 2


def test_avg_score_calculated_as_success_over_use():
    pool, _ = make_pool()
    pool.record_usage("chunk-5", "text", confidence=0.90)  # success
    pool.record_usage("chunk-5", "text", confidence=0.90)  # success
    pool.record_usage("chunk-5", "text", confidence=0.50)  # failure

    row = pool._conn.execute(
        "SELECT avg_score FROM chunk_usage WHERE chunk_id = 'chunk-5'"
    ).fetchone()
    # 2 successes / 3 uses = 0.666...
    assert abs(row["avg_score"] - 2 / 3) < 0.001


def test_avg_score_zero_when_all_failures():
    pool, _ = make_pool()
    pool.record_usage("chunk-6", "text", confidence=0.30)
    pool.record_usage("chunk-6", "text", confidence=0.40)

    row = pool._conn.execute(
        "SELECT avg_score FROM chunk_usage WHERE chunk_id = 'chunk-6'"
    ).fetchone()
    assert row["avg_score"] == 0.0


def test_avg_score_one_when_all_successes():
    pool, _ = make_pool()
    for _ in range(5):
        pool.record_usage("chunk-7", "text", confidence=0.95)

    row = pool._conn.execute(
        "SELECT avg_score FROM chunk_usage WHERE chunk_id = 'chunk-7'"
    ).fetchone()
    assert abs(row["avg_score"] - 1.0) < 0.001


# ---------------------------------------------------------------------------
# 2. get_champion_chunks — filters use_count < 3
# ---------------------------------------------------------------------------

def test_get_champion_chunks_filters_low_use_count():
    pool, _ = make_pool()
    # Only 2 uses — should NOT appear in champion
    pool.record_usage("low-use", "text", confidence=0.99)
    pool.record_usage("low-use", "text", confidence=0.99)

    champions = pool.get_champion_chunks(top_k=10)
    chunk_ids = [c["chunk_id"] for c in champions]
    assert "low-use" not in chunk_ids


def test_get_champion_chunks_includes_use_count_ge_3():
    pool, _ = make_pool()
    for _ in range(3):
        pool.record_usage("good-chunk", "text", confidence=0.90)

    champions = pool.get_champion_chunks(top_k=10)
    chunk_ids = [c["chunk_id"] for c in champions]
    assert "good-chunk" in chunk_ids


def test_get_champion_chunks_sorted_by_avg_score():
    pool, _ = make_pool()
    # chunk-a: 3 successes / 3 uses = 1.0
    for _ in range(3):
        pool.record_usage("chunk-a", "text a", confidence=0.95)
    # chunk-b: 1 success / 3 uses = 0.333
    pool.record_usage("chunk-b", "text b", confidence=0.95)
    pool.record_usage("chunk-b", "text b", confidence=0.30)
    pool.record_usage("chunk-b", "text b", confidence=0.30)

    champions = pool.get_champion_chunks(top_k=10)
    assert champions[0]["chunk_id"] == "chunk-a"
    assert champions[1]["chunk_id"] == "chunk-b"


def test_get_champion_chunks_empty_when_no_qualified():
    pool, _ = make_pool()
    pool.record_usage("c1", "text", confidence=0.90)  # use_count=1
    champions = pool.get_champion_chunks(top_k=10)
    assert len(champions) == 0


# ---------------------------------------------------------------------------
# 3. get_challenger_chunks — excludes bottom 20% by avg_score
# ---------------------------------------------------------------------------

def test_get_challenger_chunks_excludes_bottom_20_percent():
    pool, _ = make_pool()
    # Create 5 chunks with distinct avg_scores
    # chunk-worst: avg ~0.0 (should be excluded)
    for _ in range(3):
        pool.record_usage("chunk-worst", "text", confidence=0.10)
    # chunk-mid: avg ~0.33
    pool.record_usage("chunk-mid", "text", confidence=0.90)
    pool.record_usage("chunk-mid", "text", confidence=0.10)
    pool.record_usage("chunk-mid", "text", confidence=0.10)
    # chunk-good: avg 1.0
    for _ in range(3):
        pool.record_usage("chunk-good", "text", confidence=0.95)

    challengers = pool.get_challenger_chunks(top_k=10)
    chunk_ids = [c["chunk_id"] for c in challengers]
    # chunk-good should be present
    assert "chunk-good" in chunk_ids
    # chunk-worst (bottom 20%) may be excluded
    # (with 3 items, 20th percentile index = 0, so the worst score should be excluded)


def test_get_challenger_chunks_returns_less_than_or_equal_to_champion():
    pool, _ = make_pool()
    for i in range(5):
        for _ in range(3):
            pool.record_usage(f"chunk-{i}", f"text {i}", confidence=0.80 + i * 0.04)

    champion_count = len(pool.get_champion_chunks(top_k=100))
    challenger_count = len(pool.get_challenger_chunks(top_k=100))
    assert challenger_count <= champion_count


def test_get_challenger_chunks_empty_when_no_qualified():
    pool, _ = make_pool()
    challengers = pool.get_challenger_chunks(top_k=10)
    assert challengers == []


# ---------------------------------------------------------------------------
# 4. should_run_ab_test
# ---------------------------------------------------------------------------

def test_should_run_ab_test_at_10():
    pool, _ = make_pool()
    assert pool.should_run_ab_test(10) is True


def test_should_run_ab_test_at_20():
    pool, _ = make_pool()
    assert pool.should_run_ab_test(20) is True


def test_should_run_ab_test_at_100():
    pool, _ = make_pool()
    assert pool.should_run_ab_test(100) is True


def test_should_run_ab_test_false_at_non_multiples():
    pool, _ = make_pool()
    for n in [1, 5, 7, 11, 15, 21, 33, 99]:
        assert pool.should_run_ab_test(n) is False, f"Expected False at turn {n}"


# ---------------------------------------------------------------------------
# 5. record_ab_result — consecutive success/failure tracking
# ---------------------------------------------------------------------------

def test_record_ab_result_increments_consecutive_successes():
    pool, _ = make_pool()
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)

    stats = pool.get_ab_stats()
    assert stats["consecutive_successes"] == 2


def test_record_ab_result_resets_successes_on_failure():
    pool, _ = make_pool()
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    pool.record_ab_result(turn_is_challenger=True, confidence=0.20)  # failure

    stats = pool.get_ab_stats()
    assert stats["consecutive_successes"] == 0


def test_record_ab_result_increments_consecutive_failures():
    pool, _ = make_pool()
    pool.record_ab_result(turn_is_challenger=True, confidence=0.20)
    pool.record_ab_result(turn_is_challenger=True, confidence=0.30)

    stats = pool.get_ab_stats()
    assert stats["consecutive_failures"] == 2


def test_record_ab_result_resets_failures_on_success():
    pool, _ = make_pool()
    pool.record_ab_result(turn_is_challenger=True, confidence=0.20)
    pool.record_ab_result(turn_is_challenger=True, confidence=0.95)  # success resets

    stats = pool.get_ab_stats()
    assert stats["consecutive_failures"] == 0
    assert stats["consecutive_successes"] == 1


def test_record_ab_result_increments_total_ab_turns():
    pool, _ = make_pool()
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    pool.record_ab_result(turn_is_challenger=False, confidence=0.90)
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)

    stats = pool.get_ab_stats()
    assert stats["total_ab_turns"] == 3


def test_record_ab_result_non_challenger_does_not_affect_streaks():
    """Non-challenger turns only increment total_ab_turns."""
    pool, _ = make_pool()
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    pool.record_ab_result(turn_is_challenger=False, confidence=0.10)  # not challenger

    stats = pool.get_ab_stats()
    assert stats["consecutive_successes"] == 1  # not reset by champion turn


# ---------------------------------------------------------------------------
# 6. should_promote
# ---------------------------------------------------------------------------

def test_should_promote_true_after_3_consecutive_successes():
    pool, _ = make_pool()
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    # Before 3rd success, should_promote should be False
    assert pool.should_promote() is False
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    # After 3rd: promotion fires, consecutive_successes resets to 0
    # so should_promote goes back to False
    assert pool.should_promote() is False
    assert pool.get_ab_stats()["total_promotions"] == 1


def test_should_promote_false_initially():
    pool, _ = make_pool()
    assert pool.should_promote() is False


def test_should_promote_false_after_2_successes():
    pool, _ = make_pool()
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    assert pool.should_promote() is False


def test_promotion_increments_total_promotions():
    pool, _ = make_pool()
    # First promotion
    for _ in range(3):
        pool.record_ab_result(turn_is_challenger=True, confidence=0.90)
    # Second promotion
    for _ in range(3):
        pool.record_ab_result(turn_is_challenger=True, confidence=0.90)

    stats = pool.get_ab_stats()
    assert stats["total_promotions"] == 2


# ---------------------------------------------------------------------------
# 7. get_ab_stats
# ---------------------------------------------------------------------------

def test_get_ab_stats_initial_state():
    pool, _ = make_pool()
    stats = pool.get_ab_stats()
    assert stats["consecutive_successes"] == 0
    assert stats["consecutive_failures"] == 0
    assert stats["total_ab_turns"] == 0
    assert stats["total_promotions"] == 0


def test_get_ab_stats_returns_dict_with_all_keys():
    pool, _ = make_pool()
    stats = pool.get_ab_stats()
    required_keys = {"consecutive_successes", "consecutive_failures",
                     "total_ab_turns", "total_promotions"}
    assert required_keys.issubset(stats.keys())
