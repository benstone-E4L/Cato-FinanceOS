"""
tests/test_habit_extractor.py — Tests for Habit Pattern Extractor (Skill 10).
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from cato.personalization.habit_extractor import (
    EVENT_ACCEPTED,
    EVENT_REJECTED,
    EVENT_FOLLOWUP,
    HabitExtractor,
    InferredHabit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def he(tmp_path: Path) -> HabitExtractor:
    extractor = HabitExtractor(db_path=tmp_path / "test_habits.db")
    yield extractor
    extractor.close()


def _make_habit(
    habit_id: str | None = None,
    habit_description: str = "Test habit",
    evidence_count: int = 5,
    confidence: float = 0.7,
    skill_affinity: str = "write_file",
    soft_constraint: str = "Be careful with file writes.",
    active: bool = True,
    created_at: float | None = None,
    user_confirmed: bool | None = None,
) -> InferredHabit:
    return InferredHabit(
        habit_id=habit_id or str(uuid.uuid4()),
        habit_description=habit_description,
        evidence_count=evidence_count,
        confidence=confidence,
        skill_affinity=skill_affinity,
        soft_constraint=soft_constraint,
        active=active,
        created_at=created_at or time.time(),
        user_confirmed=user_confirmed,
    )


# ---------------------------------------------------------------------------
# log_event
# ---------------------------------------------------------------------------

def test_log_event_returns_event_id(he: HabitExtractor) -> None:
    event_id = he.log_event(EVENT_ACCEPTED, session_id="sess-1")
    assert isinstance(event_id, str)
    parsed = uuid.UUID(event_id)
    assert str(parsed) == event_id


def test_events_are_stored_in_db(he: HabitExtractor) -> None:
    event_id = he.log_event(EVENT_REJECTED, session_id="sess-2", skill_used="search")
    row = he._conn.execute(
        "SELECT * FROM interaction_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    assert row is not None
    assert row["event_type"] == EVENT_REJECTED
    assert row["skill_used"] == "search"


# ---------------------------------------------------------------------------
# classify_user_message
# ---------------------------------------------------------------------------

def test_classify_rejection_message(he: HabitExtractor) -> None:
    assert he.classify_user_message("wrong, try again") == EVENT_REJECTED


def test_classify_rejection_redo(he: HabitExtractor) -> None:
    assert he.classify_user_message("redo this please") == EVENT_REJECTED


def test_classify_acceptance_message(he: HabitExtractor) -> None:
    assert he.classify_user_message("thanks, that looks good") == EVENT_ACCEPTED


def test_classify_neutral_message(he: HabitExtractor) -> None:
    assert he.classify_user_message("can you help me with something else?") == EVENT_ACCEPTED


# ---------------------------------------------------------------------------
# save_habit / list_habits
# ---------------------------------------------------------------------------

def test_save_and_list_habits_round_trip(he: HabitExtractor) -> None:
    habit = _make_habit(habit_description="User prefers concise answers")
    he.save_habit(habit)
    habits = he.list_habits()
    assert len(habits) == 1
    assert habits[0].habit_description == "User prefers concise answers"


def test_list_habits_active_only_true(he: HabitExtractor) -> None:
    active_habit = _make_habit(active=True)
    inactive_habit = _make_habit(habit_id=str(uuid.uuid4()), active=False)
    he.save_habit(active_habit)
    he.save_habit(inactive_habit)
    active = he.list_habits(active_only=True)
    assert len(active) == 1
    assert active[0].habit_id == active_habit.habit_id


def test_inferred_habit_user_confirmed_none_by_default(he: HabitExtractor) -> None:
    habit = _make_habit()
    he.save_habit(habit)
    stored = he.list_habits()[0]
    assert stored.user_confirmed is None


# ---------------------------------------------------------------------------
# delete_habit
# ---------------------------------------------------------------------------

def test_delete_habit_returns_true_for_existing(he: HabitExtractor) -> None:
    habit = _make_habit()
    he.save_habit(habit)
    result = he.delete_habit(habit.habit_id)
    assert result is True


def test_delete_habit_returns_false_for_missing(he: HabitExtractor) -> None:
    result = he.delete_habit("nonexistent-habit-id")
    assert result is False


def test_delete_habit_removes_from_db(he: HabitExtractor) -> None:
    habit = _make_habit()
    he.save_habit(habit)
    he.delete_habit(habit.habit_id)
    assert len(he.list_habits()) == 0


# ---------------------------------------------------------------------------
# confirm_habit
# ---------------------------------------------------------------------------

def test_confirm_habit_sets_user_confirmed_true(he: HabitExtractor) -> None:
    habit = _make_habit()
    he.save_habit(habit)
    he.confirm_habit(habit.habit_id, confirmed=True)
    stored = he.list_habits()[0]
    assert stored.user_confirmed is True


def test_confirm_habit_sets_user_confirmed_false(he: HabitExtractor) -> None:
    habit = _make_habit()
    he.save_habit(habit)
    he.confirm_habit(habit.habit_id, confirmed=False)
    # Still in DB (not deleted), confirmed=False
    all_habits = he.list_habits(active_only=False)
    match = next(h for h in all_habits if h.habit_id == habit.habit_id)
    assert match.user_confirmed is False


# ---------------------------------------------------------------------------
# clear_unconfirmed
# ---------------------------------------------------------------------------

def test_clear_unconfirmed_removes_only_unconfirmed(he: HabitExtractor) -> None:
    unconfirmed = _make_habit(habit_id=str(uuid.uuid4()))
    confirmed = _make_habit(habit_id=str(uuid.uuid4()), user_confirmed=True)
    he.save_habit(unconfirmed)
    he.save_habit(confirmed)
    removed = he.clear_unconfirmed()
    assert removed == 1
    remaining = he.list_habits(active_only=False)
    remaining_ids = {h.habit_id for h in remaining}
    assert confirmed.habit_id in remaining_ids
    assert unconfirmed.habit_id not in remaining_ids


# ---------------------------------------------------------------------------
# get_habits_for_skill / get_soft_constraints
# ---------------------------------------------------------------------------

def test_get_habits_for_skill_returns_matching_affinity(he: HabitExtractor) -> None:
    habit = _make_habit(skill_affinity="search_web")
    he.save_habit(habit)
    results = he.get_habits_for_skill("search_web")
    assert len(results) == 1
    assert results[0].skill_affinity == "search_web"


def test_get_habits_for_skill_returns_all_affinity(he: HabitExtractor) -> None:
    all_habit = _make_habit(habit_id=str(uuid.uuid4()), skill_affinity="all")
    specific_habit = _make_habit(habit_id=str(uuid.uuid4()), skill_affinity="write_file")
    he.save_habit(all_habit)
    he.save_habit(specific_habit)
    results = he.get_habits_for_skill("write_file")
    habit_ids = {h.habit_id for h in results}
    assert all_habit.habit_id in habit_ids
    assert specific_habit.habit_id in habit_ids


def test_get_soft_constraints_returns_strings(he: HabitExtractor) -> None:
    habit = _make_habit(skill_affinity="api_call", soft_constraint="Always check auth headers.")
    he.save_habit(habit)
    constraints = he.get_soft_constraints("api_call")
    assert isinstance(constraints, list)
    assert "Always check auth headers." in constraints


def test_get_soft_constraints_empty_when_no_habits(he: HabitExtractor) -> None:
    constraints = he.get_soft_constraints("nonexistent_skill")
    assert constraints == []


# ---------------------------------------------------------------------------
# extract_patterns
# ---------------------------------------------------------------------------

def test_extract_patterns_returns_list(he: HabitExtractor) -> None:
    # No events — should return empty list
    patterns = he.extract_patterns()
    assert isinstance(patterns, list)


def test_extract_patterns_detects_high_rejection_rate(he: HabitExtractor) -> None:
    """Log 7 rejections and 1 acceptance for a skill — should infer habit."""
    skill = "code_review"
    for _ in range(7):
        he.log_event(EVENT_REJECTED, session_id="s1", skill_used=skill)
    he.log_event(EVENT_ACCEPTED, session_id="s1", skill_used=skill)
    # 7 rejections out of 8 total = 87.5% rejection rate (> 60% threshold, >= 5 events)
    habits = he.extract_patterns()
    skill_habits = [h for h in habits if h.skill_affinity == skill]
    assert len(skill_habits) == 1
    assert skill_habits[0].confidence > 0.6


def test_extract_patterns_no_habit_below_min_evidence(he: HabitExtractor) -> None:
    """Only 3 events — below _MIN_EVIDENCE of 5, should not create habit."""
    skill = "rarely_used_skill"
    for _ in range(3):
        he.log_event(EVENT_REJECTED, session_id="s2", skill_used=skill)
    habits = he.extract_patterns()
    skill_habits = [h for h in habits if h.skill_affinity == skill]
    assert len(skill_habits) == 0


def test_extract_patterns_old_habits_age_out(he: HabitExtractor) -> None:
    """Recency weighting: many old rejections get low weight and do not yield a habit in default window."""
    import time
    now = time.time()
    # Events 60 days ago: 8 rejections for skill_old — outside 30-day default window
    old_ts = now - 60 * 86400
    for i in range(8):
        he._conn.execute(
            """INSERT INTO interaction_events (event_id, timestamp, event_type, session_id, response_id, event_detail, skill_used)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (f"old-{i}", old_ts, EVENT_REJECTED, "s-old", None, "{}", "skill_old"),
        )
    he._conn.commit()
    habits = he.extract_patterns(window_days=30)
    # skill_old events are outside window (30 days) so they are excluded entirely
    skill_old_habits = [h for h in habits if h.skill_affinity == "skill_old"]
    assert len(skill_old_habits) == 0


def test_extract_patterns_recent_repeated_habits_win(he: HabitExtractor) -> None:
    """Recent repeated rejections for a skill produce a habit; old acceptances don't outweigh them."""
    import time
    now = time.time()
    # 5 old acceptances (40 days ago)
    old_ts = now - 40 * 86400
    for i in range(5):
        he._conn.execute(
            """INSERT INTO interaction_events (event_id, timestamp, event_type, session_id, response_id, event_detail, skill_used)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (f"old-acc-{i}", old_ts, EVENT_ACCEPTED, "s1", None, "{}", "skill_recent"),
        )
    # 6 recent rejections (within last 2 days)
    for _ in range(6):
        he.log_event(EVENT_REJECTED, session_id="s1", skill_used="skill_recent")
    habits = he.extract_patterns(window_days=30)
    skill_habits = [h for h in habits if h.skill_affinity == "skill_recent"]
    assert len(skill_habits) == 1
    # Weighted rejection rate should be high (recent rejections weighted heavily)
    assert skill_habits[0].confidence > 0.6
