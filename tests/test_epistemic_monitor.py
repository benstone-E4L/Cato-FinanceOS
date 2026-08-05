"""
Tests for EpistemicMonitor (Skill 3 — Epistemic Layer).
Premise extraction, confidence management, interrupt budget,
session reset, unresolved gap tracking, and persistence.
"""

import time
from pathlib import Path

import pytest

from cato.orchestrator.epistemic_monitor import EpistemicMonitor


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def monitor():
    return EpistemicMonitor(threshold=0.70, max_interrupts=3)


# ---------------------------------------------------------------------------
# Premise extraction
# ---------------------------------------------------------------------------

def test_extract_premises_because(monitor):
    text = "X is valid because Y is always true"
    premises = monitor.extract_premises(text)
    assert len(premises) == 1
    assert "because" in premises[0].lower()


def test_extract_premises_since(monitor):
    text = "Since Z is true, we can proceed"
    premises = monitor.extract_premises(text)
    assert len(premises) == 1
    assert "since" in premises[0].lower()


def test_extract_premises_assuming(monitor):
    text = "Assuming X is valid, the model will converge"
    premises = monitor.extract_premises(text)
    assert len(premises) == 1
    assert "assuming" in premises[0].lower()


def test_extract_premises_given_that(monitor):
    text = "Given that the dataset is large, accuracy improves"
    premises = monitor.extract_premises(text)
    assert len(premises) == 1
    assert "given that" in premises[0].lower()


def test_extract_premises_the_fact_that(monitor):
    text = "The fact that water boils at 100C is well known"
    premises = monitor.extract_premises(text)
    assert len(premises) == 1
    assert "the fact that" in premises[0].lower()


def test_extract_premises_no_markers(monitor):
    text = "The sky is blue. Water is wet. Grass is green."
    premises = monitor.extract_premises(text)
    assert premises == []


def test_extract_premises_multiple_sentences(monitor):
    text = (
        "We proceed because the data is clean. "
        "Assuming the server is up, requests will succeed. "
        "The answer is 42."
    )
    premises = monitor.extract_premises(text)
    assert len(premises) == 2


def test_extract_premises_splits_on_exclamation(monitor):
    text = "This is true! Given that we have proof, we can proceed."
    premises = monitor.extract_premises(text)
    assert len(premises) == 1
    assert "given that" in premises[0].lower()


def test_extract_premises_splits_on_question(monitor):
    text = "Is it safe? Since the API is stable, we can deploy."
    premises = monitor.extract_premises(text)
    assert len(premises) == 1
    assert "since" in premises[0].lower()


def test_extract_premises_mixed_punctuation(monitor):
    text = "Because A holds. B is false! What about C? Assuming D, we continue."
    premises = monitor.extract_premises(text)
    assert len(premises) == 2  # "Because A holds" and "Assuming D, we continue"


# ---------------------------------------------------------------------------
# Confidence management
# ---------------------------------------------------------------------------

def test_update_confidence_stores_value(monitor):
    monitor.update_confidence("Python is fast", 0.85)
    gaps = monitor.get_gaps()
    assert "python is fast" not in gaps


def test_update_confidence_lowercase_key(monitor):
    monitor.update_confidence("Python", 0.80)
    monitor.update_confidence("python", 0.60)  # overwrites
    gaps = monitor.get_gaps()
    assert "python" in gaps


def test_get_gaps_returns_low_confidence_premises(monitor):
    monitor.update_confidence("earth is flat", 0.30)
    gaps = monitor.get_gaps()
    assert "earth is flat" in gaps


def test_get_gaps_empty_when_all_above_threshold(monitor):
    monitor.update_confidence("sky is blue", 0.90)
    monitor.update_confidence("water is wet", 0.80)
    assert monitor.get_gaps() == []


# ---------------------------------------------------------------------------
# Sub-query generation
# ---------------------------------------------------------------------------

def test_generate_sub_query_format(monitor):
    result = monitor.generate_sub_query("the earth is round")
    assert result == "I need to verify: the earth is round"


# ---------------------------------------------------------------------------
# Unresolved gap tracking
# ---------------------------------------------------------------------------

def test_record_unresolved_appends(monitor):
    monitor.record_unresolved("some premise", 0.50)
    summary = monitor.get_unresolved_summary()
    assert summary["total"] == 1


def test_unresolved_has_timestamp(monitor):
    before = time.time()
    monitor.record_unresolved("a premise", 0.40)
    after = time.time()
    gap = monitor.get_unresolved_summary()["gaps"][0]
    assert "timestamp" in gap
    assert before <= gap["timestamp"] <= after


def test_unresolved_has_confidence(monitor):
    monitor.record_unresolved("a premise", 0.55)
    gap = monitor.get_unresolved_summary()["gaps"][0]
    assert "confidence" in gap
    assert gap["confidence"] == 0.55


def test_multiple_unresolved_tracked(monitor):
    monitor.record_unresolved("p1", 0.10)
    monitor.record_unresolved("p2", 0.20)
    monitor.record_unresolved("p3", 0.30)
    assert monitor.get_unresolved_summary()["total"] == 3


# ---------------------------------------------------------------------------
# Interrupt budget
# ---------------------------------------------------------------------------

def test_can_interrupt_true_initially(monitor):
    assert monitor.can_interrupt() is True


def test_can_interrupt_false_at_max(monitor):
    for _ in range(3):
        monitor.consume_interrupt()
    assert monitor.can_interrupt() is False


def test_consume_interrupt_increments(monitor):
    monitor.consume_interrupt()
    assert monitor._interrupt_count == 1


# ---------------------------------------------------------------------------
# Session reset
# ---------------------------------------------------------------------------

def test_reset_session_clears_map(monitor):
    monitor.update_confidence("some premise", 0.10)
    monitor.reset_session()
    assert monitor.get_gaps() == []


def test_reset_session_resets_count(monitor):
    monitor.consume_interrupt()
    monitor.consume_interrupt()
    monitor.consume_interrupt()
    monitor.reset_session()
    assert monitor.can_interrupt() is True


# ---------------------------------------------------------------------------
# Summary structure
# ---------------------------------------------------------------------------

def test_get_unresolved_summary_structure(monitor):
    summary = monitor.get_unresolved_summary()
    assert "total" in summary
    assert "gaps" in summary


def test_get_unresolved_summary_correct_total(monitor):
    monitor.record_unresolved("x", 0.1)
    monitor.record_unresolved("y", 0.2)
    assert monitor.get_unresolved_summary()["total"] == 2


# ---------------------------------------------------------------------------
# Custom threshold / max_interrupts
# ---------------------------------------------------------------------------

def test_custom_threshold():
    m = EpistemicMonitor(threshold=0.50)
    m.update_confidence("fast premise", 0.60)
    assert "fast premise" not in m.get_gaps()


def test_custom_max_interrupts():
    m = EpistemicMonitor(max_interrupts=1)
    m.consume_interrupt()
    assert m.can_interrupt() is False


# ---------------------------------------------------------------------------
# Persistence: unresolved gaps persist to SQLite and reload on restart
# ---------------------------------------------------------------------------

def test_unresolved_gaps_persist_and_reload(tmp_path: Path):
    db = tmp_path / "epistemic.db"
    m1 = EpistemicMonitor(db_path=db)
    m1.record_unresolved("premise one", 0.40)
    m1.record_unresolved("premise two", 0.55)
    summary1 = m1.get_unresolved_summary()
    assert summary1["total"] == 2
    # New monitor instance loading from same DB
    m2 = EpistemicMonitor(db_path=db)
    summary2 = m2.get_unresolved_summary()
    assert summary2["total"] == 2
    premises = {g["premise"] for g in summary2["gaps"]}
    assert "premise one" in premises
    assert "premise two" in premises


def test_unresolved_gaps_reload_empty_db(tmp_path: Path):
    db = tmp_path / "empty_epistemic.db"
    m = EpistemicMonitor(db_path=db)
    assert m.get_unresolved_summary()["total"] == 0
