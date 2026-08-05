"""
tests/test_decision_memory.py — Tests for Outcome-Linked Decision Memory (Skill 2).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import pytest

from cato.memory.decision_memory import DecisionMemory, DecisionRecord
from cato.memory.outcome_observer import OutcomeObserver, _get_observation_window


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dm(tmp_path: Path) -> DecisionMemory:
    mem = DecisionMemory(db_path=tmp_path / "test_decisions.db")
    yield mem
    mem.close()


# ---------------------------------------------------------------------------
# write_decision
# ---------------------------------------------------------------------------

def test_write_decision_returns_uuid(dm: DecisionMemory) -> None:
    decision_id = dm.write_decision("deploy_service", ["premise1"], 0.85)
    assert isinstance(decision_id, str)
    # Should be a valid UUID
    parsed = uuid.UUID(decision_id)
    assert str(parsed) == decision_id


def test_written_record_is_retrievable(dm: DecisionMemory) -> None:
    decision_id = dm.write_decision("send_email", ["fact A", "fact B"], 0.7)
    record = dm.get(decision_id)
    assert record is not None
    assert record.decision_id == decision_id
    assert record.action_taken == "send_email"


def test_premises_round_trip_as_list(dm: DecisionMemory) -> None:
    premises = ["premise one", "premise two", "premise three"]
    decision_id = dm.write_decision("analyze_data", premises, 0.6)
    record = dm.get(decision_id)
    assert record.premises_relied_on == premises


def test_ledger_record_id_nullable_none(dm: DecisionMemory) -> None:
    decision_id = dm.write_decision("action_no_ledger", [], 0.5, ledger_record_id=None)
    record = dm.get(decision_id)
    assert record.ledger_record_id is None


def test_ledger_record_id_stored_when_provided(dm: DecisionMemory) -> None:
    ledger_id = str(uuid.uuid4())
    decision_id = dm.write_decision("action_with_ledger", [], 0.5, ledger_record_id=ledger_id)
    record = dm.get(decision_id)
    assert record.ledger_record_id == ledger_id


def test_confidence_stored_correctly(dm: DecisionMemory) -> None:
    decision_id = dm.write_decision("action_high_conf", [], 0.92)
    record = dm.get(decision_id)
    assert abs(record.confidence_at_decision_time - 0.92) < 1e-9


# ---------------------------------------------------------------------------
# record_outcome
# ---------------------------------------------------------------------------

def test_record_outcome_returns_true_for_existing(dm: DecisionMemory) -> None:
    decision_id = dm.write_decision("deploy", [], 0.8)
    result = dm.record_outcome(decision_id, "Deployed successfully", 0.9, source="monitor")
    assert result is True


def test_record_outcome_returns_false_for_missing(dm: DecisionMemory) -> None:
    result = dm.record_outcome("nonexistent-id", "obs", 0.5)
    assert result is False


def test_outcome_fields_stored_correctly(dm: DecisionMemory) -> None:
    decision_id = dm.write_decision("api_call", [], 0.75)
    dm.record_outcome(decision_id, "API responded with 200", 0.95, source="integration_test")
    record = dm.get(decision_id)
    assert record.outcome_observation == "API responded with 200"
    assert abs(record.outcome_quality_score - 0.95) < 1e-9
    assert record.outcome_source == "integration_test"
    assert record.outcome_timestamp is not None


def test_outcome_quality_score_negative(dm: DecisionMemory) -> None:
    decision_id = dm.write_decision("risky_action", [], 0.9)
    dm.record_outcome(decision_id, "Failed badly", -0.8)
    record = dm.get(decision_id)
    assert abs(record.outcome_quality_score - (-0.8)) < 1e-9


def test_quality_score_stored_as_float(dm: DecisionMemory) -> None:
    decision_id = dm.write_decision("test_action", [], 0.5)
    dm.record_outcome(decision_id, "partial success", 0.5)
    record = dm.get(decision_id)
    assert isinstance(record.outcome_quality_score, float)


# ---------------------------------------------------------------------------
# list_open
# ---------------------------------------------------------------------------

def test_list_open_returns_records_without_outcomes(dm: DecisionMemory) -> None:
    id1 = dm.write_decision("action_a", [], 0.5)
    id2 = dm.write_decision("action_b", [], 0.6)
    open_records = dm.list_open()
    open_ids = {r.decision_id for r in open_records}
    assert id1 in open_ids
    assert id2 in open_ids


def test_list_open_excludes_records_with_outcomes(dm: DecisionMemory) -> None:
    id1 = dm.write_decision("closed_action", [], 0.5)
    id2 = dm.write_decision("open_action", [], 0.6)
    dm.record_outcome(id1, "done", 0.8)
    open_records = dm.list_open()
    open_ids = {r.decision_id for r in open_records}
    assert id1 not in open_ids
    assert id2 in open_ids


# ---------------------------------------------------------------------------
# get_overconfidence_profile
# ---------------------------------------------------------------------------

def test_overconfidence_profile_returns_high_conf_bad_outcome(dm: DecisionMemory) -> None:
    for _ in range(3):
        did = dm.write_decision("overconfident_action", [], 0.9)
        dm.record_outcome(did, "failed", -0.5)
    profile = dm.get_overconfidence_profile()
    assert "overconfident_action" in profile
    stats = profile["overconfident_action"]
    assert stats["avg_conf"] > 0.8
    assert stats["avg_outcome"] < 0.0


def test_overconfidence_excludes_good_outcomes(dm: DecisionMemory) -> None:
    for _ in range(3):
        did = dm.write_decision("good_action", [], 0.9)
        dm.record_outcome(did, "succeeded", 0.9)
    profile = dm.get_overconfidence_profile()
    assert "good_action" not in profile


def test_overconfidence_excludes_records_without_outcomes(dm: DecisionMemory) -> None:
    dm.write_decision("no_outcome_action", [], 0.95)
    profile = dm.get_overconfidence_profile()
    assert "no_outcome_action" not in profile


# ---------------------------------------------------------------------------
# get_reliable_patterns / get_systematic_failures
# ---------------------------------------------------------------------------

def test_reliable_patterns_requires_10_decisions(dm: DecisionMemory) -> None:
    # Only 5 — should not appear
    for _ in range(5):
        did = dm.write_decision("reliable_action", [], 0.8)
        dm.record_outcome(did, "great", 0.95)
    patterns = dm.get_reliable_patterns()
    action_names = [p["action_taken"] for p in patterns]
    assert "reliable_action" not in action_names


def test_reliable_patterns_with_10_decisions(dm: DecisionMemory) -> None:
    for _ in range(10):
        did = dm.write_decision("very_reliable_action", [], 0.8)
        dm.record_outcome(did, "great", 0.95)
    patterns = dm.get_reliable_patterns()
    action_names = [p["action_taken"] for p in patterns]
    assert "very_reliable_action" in action_names


def test_systematic_failures_requires_5_decisions(dm: DecisionMemory) -> None:
    # Only 3 — should not appear
    for _ in range(3):
        did = dm.write_decision("failing_action", [], 0.5)
        dm.record_outcome(did, "failed", -0.5)
    failures = dm.get_systematic_failures()
    action_names = [f["action_taken"] for f in failures]
    assert "failing_action" not in action_names


def test_systematic_failures_with_5_decisions(dm: DecisionMemory) -> None:
    for _ in range(5):
        did = dm.write_decision("consistently_failing_action", [], 0.5)
        dm.record_outcome(did, "failed", -0.5)
    failures = dm.get_systematic_failures()
    action_names = [f["action_taken"] for f in failures]
    assert "consistently_failing_action" in action_names


def test_get_returns_none_for_missing(dm: DecisionMemory) -> None:
    assert dm.get("nonexistent-uuid") is None


# ---------------------------------------------------------------------------
# OutcomeObserver
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outcome_observer_start_and_stop(tmp_path: Path) -> None:
    mem = DecisionMemory(db_path=tmp_path / "obs_test.db")
    observer = OutcomeObserver(mem, poll_interval_sec=1000.0)
    await observer.start()
    assert observer._running is True
    assert observer._task is not None
    await observer.stop()
    assert observer._running is False
    mem.close()


@pytest.mark.asyncio
async def test_outcome_observer_sets_neutral_for_timed_out_records(tmp_path: Path) -> None:
    mem = DecisionMemory(db_path=tmp_path / "timeout_test.db")
    # Write a decision with a very old timestamp (simulate expired window)
    decision_id = mem.write_decision("file_write_old", [], 0.7)
    # Manually backdate the timestamp to simulate 2 days ago (beyond 60s window for file)
    mem._conn.execute(
        "UPDATE decision_records SET timestamp = ? WHERE decision_id = ?",
        (time.time() - 200, decision_id),  # 200s ago, beyond 60s file window
    )
    mem._conn.commit()

    observer = OutcomeObserver(mem, poll_interval_sec=1000.0)
    # Directly call check without starting the full loop
    await observer._check_open_records()

    record = mem.get(decision_id)
    assert record.outcome_quality_score == 0.0
    assert record.outcome_source == "timeout"
    mem.close()


# ---------------------------------------------------------------------------
# _get_observation_window
# ---------------------------------------------------------------------------

def test_observation_window_email() -> None:
    assert _get_observation_window("email_send") == 48 * 3600


def test_observation_window_commit() -> None:
    assert _get_observation_window("git_commit") == 2 * 3600


def test_observation_window_default() -> None:
    assert _get_observation_window("unknown_action_type") == 24 * 3600
