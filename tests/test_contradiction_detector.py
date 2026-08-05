"""
tests/test_contradiction_detector.py — Tests for ContradictionDetector (Skill 7).

All DB-backed tests use tmp_path fixture to avoid touching the real filesystem.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from cato.memory.contradiction_detector import ContradictionDetector, _jaccard_similarity


# ===========================================================================
# TestSimilarity (4 tests)
# ===========================================================================

class TestSimilarity:
    def test_identical_facts_high_similarity(self):
        sim = _jaccard_similarity("Python is a great language", "Python is a great language")
        assert sim == 1.0

    def test_completely_different_facts_low_similarity(self):
        sim = _jaccard_similarity("Python is a programming language", "Sushi is delicious Japanese food")
        assert sim < 0.2

    def test_partial_overlap_intermediate(self):
        sim = _jaccard_similarity("Python is great for data science", "Python is also used for web development")
        assert 0.0 < sim < 1.0

    def test_empty_facts_similarity_one(self):
        sim = _jaccard_similarity("", "")
        assert sim == 1.0


# ===========================================================================
# TestClassifyContradiction (6 tests)
# ===========================================================================

class TestClassifyContradiction:
    def setup_method(self, method):
        # Use an in-memory-like detector for classify tests (no DB I/O needed)
        # We still need a DB path; use a temp attribute approach with tmp_path
        # — but classify_contradiction doesn't need DB, so we use a sentinel path
        # that won't be created (no check_and_log called).
        pass

    @pytest.fixture
    def det(self, tmp_path):
        d = ContradictionDetector(db_path=tmp_path / "cls.db")
        yield d
        d.close()

    def test_classify_temporal_with_year(self, det):
        result = det.classify_contradiction(
            "Python 3.9 released in 2020",
            "Python 3.9 released in 2021",
        )
        assert result == "TEMPORAL"

    def test_classify_source_attribution(self, det):
        # Both facts share "according to" keyword and have enough overlap
        result = det.classify_contradiction(
            "according to study the drug is effective",
            "according to research the drug is ineffective",
        )
        assert result == "SOURCE"

    def test_classify_preference(self, det):
        result = det.classify_contradiction(
            "I prefer dark mode for coding",
            "I prefer light mode for coding",
        )
        assert result == "PREFERENCE"

    def test_classify_factual_same_topic_no_keywords(self, det):
        result = det.classify_contradiction(
            "The sky is blue",
            "The sky is green",
        )
        assert result == "FACTUAL"

    def test_classify_none_different_topics(self, det):
        result = det.classify_contradiction(
            "Python is great for programming",
            "Sushi is delicious Japanese cuisine",
        )
        assert result == "NONE"

    def test_classify_temporal_keywords_currently(self, det):
        result = det.classify_contradiction(
            "the service currently costs ten dollars per month",
            "the service previously cost five dollars per month",
        )
        assert result == "TEMPORAL"


# ===========================================================================
# TestCheckAndLog (8 tests)
# ===========================================================================

class TestCheckAndLog:
    @pytest.fixture
    def det(self, tmp_path):
        d = ContradictionDetector(db_path=tmp_path / "cal.db")
        yield d
        d.close()

    def test_check_and_log_returns_empty_when_no_contradictions(self, det):
        ids = det.check_and_log(
            "Python is a programming language",
            ["Sushi is delicious", "Coffee is a beverage"],
        )
        assert ids == []

    def test_check_and_log_returns_id_when_contradiction_found(self, det):
        ids = det.check_and_log(
            "The sky is blue today",
            ["The sky is green today"],
        )
        assert len(ids) == 1
        assert isinstance(ids[0], str)
        assert len(ids[0]) > 0

    def test_check_and_log_logs_to_db(self, det):
        det.check_and_log(
            "The sky is blue today",
            ["The sky is green today"],
        )
        unresolved = det.list_unresolved()
        assert len(unresolved) == 1
        row = unresolved[0]
        assert row["fact_a_text"] == "The sky is blue today"
        assert row["fact_b_text"] == "The sky is green today"

    def test_check_and_log_entity_stored(self, det):
        det.check_and_log(
            "The sky is blue today",
            ["The sky is green today"],
            entity="weather",
        )
        unresolved = det.list_unresolved()
        assert unresolved[0]["entity"] == "weather"

    def test_check_and_log_multiple_existing_facts(self, det):
        existing = [
            "Sushi is Japanese food",        # unrelated
            "Pizza is Italian cuisine",      # unrelated
            "The sky is green today",        # contradicts
        ]
        ids = det.check_and_log("The sky is blue today", existing)
        assert len(ids) == 1

    def test_check_and_log_multiple_contradictions(self, det):
        existing = [
            "The sky is green today",
            "The sky is red today",
            "The sky is yellow today",
        ]
        ids = det.check_and_log("The sky is blue today", existing)
        assert len(ids) == 3

    def test_check_and_log_prevents_duplicate(self, det):
        ids1 = det.check_and_log(
            "The sky is blue today",
            ["The sky is green today"],
        )
        assert len(ids1) == 1
        # Second call with same pair should return empty
        ids2 = det.check_and_log(
            "The sky is blue today",
            ["The sky is green today"],
        )
        assert ids2 == []

    def test_check_and_log_below_threshold_no_log(self, det):
        ids = det.check_and_log(
            "Quantum mechanics governs subatomic particles",
            ["Sushi tastes great with wasabi"],
        )
        assert ids == []
        assert det.get_unresolved_count() == 0


# ===========================================================================
# TestResolve (4 tests)
# ===========================================================================

class TestResolve:
    @pytest.fixture
    def det_with_entry(self, tmp_path):
        d = ContradictionDetector(db_path=tmp_path / "res.db")
        ids = d.check_and_log(
            "The sky is blue today",
            ["The sky is green today"],
        )
        yield d, ids[0]
        d.close()

    def test_resolve_returns_true_for_existing(self, det_with_entry):
        det, cid = det_with_entry
        result = det.resolve(cid, "kept_a")
        assert result is True

    def test_resolve_returns_false_for_missing(self, tmp_path):
        det = ContradictionDetector(db_path=tmp_path / "res2.db")
        result = det.resolve("non-existent-id-000", "kept_a")
        assert result is False
        det.close()

    def test_resolve_marks_as_resolved(self, det_with_entry):
        det, cid = det_with_entry
        det.resolve(cid, "kept_a")
        unresolved = det.list_unresolved()
        assert all(r["contradiction_id"] != cid for r in unresolved)

    def test_resolve_stores_resolution_text(self, det_with_entry):
        det, cid = det_with_entry
        det.resolve(cid, "kept_a")
        row = det._conn.execute(
            "SELECT resolution FROM memory_contradictions WHERE contradiction_id=?",
            (cid,),
        ).fetchone()
        assert row is not None
        assert row[0] == "kept_a"


# ===========================================================================
# TestListAndQuery (4 tests)
# ===========================================================================

class TestListAndQuery:
    @pytest.fixture
    def det(self, tmp_path):
        d = ContradictionDetector(db_path=tmp_path / "lq.db")
        yield d
        d.close()

    def test_list_unresolved_returns_only_unresolved(self, det):
        # Insert two contradictions
        ids1 = det.check_and_log("The sky is blue today", ["The sky is green today"])
        ids2 = det.check_and_log("Water is wet", ["Water is dry"])
        assert len(ids1) == 1
        assert len(ids2) == 1
        # Resolve the first
        det.resolve(ids1[0], "kept_a")
        unresolved = det.list_unresolved()
        assert len(unresolved) == 1
        assert unresolved[0]["contradiction_id"] == ids2[0]

    def test_list_by_type_filters_correctly(self, det):
        # TEMPORAL contradiction
        det.check_and_log(
            "The project started in 2020",
            ["The project started in 2022"],
        )
        # FACTUAL contradiction (no temporal/source/preference keywords)
        det.check_and_log(
            "The sky is blue today",
            ["The sky is green today"],
        )
        temporal = det.list_by_type("TEMPORAL")
        factual = det.list_by_type("FACTUAL")
        assert all(r["contradiction_type"] == "TEMPORAL" for r in temporal)
        assert all(r["contradiction_type"] == "FACTUAL" for r in factual)
        assert len(temporal) >= 1
        assert len(factual) >= 1

    def test_list_unresolved_filtered_by_entity(self, det):
        det.check_and_log("The sky is blue today", ["The sky is green today"], entity="weather")
        det.check_and_log("Water is wet", ["Water is dry"], entity="science")
        weather = det.list_unresolved(entity="weather")
        science = det.list_unresolved(entity="science")
        assert all(r["entity"] == "weather" for r in weather)
        assert all(r["entity"] == "science" for r in science)
        assert len(weather) == 1
        assert len(science) == 1

    def test_get_unresolved_count_accurate(self, det):
        det.check_and_log("The sky is blue today", ["The sky is green today"])
        det.check_and_log("Water is wet", ["Water is dry"])
        count = det.get_unresolved_count()
        assert count == len(det.list_unresolved())


# ===========================================================================
# TestHealthSummary (4 tests)
# ===========================================================================

class TestHealthSummary:
    @pytest.fixture
    def det_populated(self, tmp_path):
        d = ContradictionDetector(db_path=tmp_path / "hs.db")
        # TEMPORAL
        d.check_and_log(
            "The project started in 2020",
            ["The project started in 2022"],
            entity="projectA",
        )
        # FACTUAL
        d.check_and_log(
            "The sky is blue today",
            ["The sky is green today"],
            entity="weather",
        )
        # PREFERENCE
        d.check_and_log(
            "I prefer dark mode for coding sessions",
            ["I prefer light mode for coding sessions"],
            entity="projectA",
        )
        yield d
        d.close()

    def test_health_summary_keys_present(self, det_populated):
        summary = det_populated.get_health_summary()
        assert "total" in summary
        assert "unresolved" in summary
        assert "by_type" in summary
        assert "most_contradicted_entities" in summary

    def test_health_summary_total_correct(self, det_populated):
        summary = det_populated.get_health_summary()
        row = det_populated._conn.execute(
            "SELECT COUNT(*) FROM memory_contradictions"
        ).fetchone()
        assert summary["total"] == row[0]

    def test_health_summary_by_type_counts(self, det_populated):
        summary = det_populated.get_health_summary()
        bt = summary["by_type"]
        assert "TEMPORAL" in bt
        assert "SOURCE" in bt
        assert "PREFERENCE" in bt
        assert "FACTUAL" in bt
        assert bt["TEMPORAL"] >= 1
        assert bt["PREFERENCE"] >= 1

    def test_health_summary_most_contradicted_entities_top3(self, det_populated):
        summary = det_populated.get_health_summary()
        entities = summary["most_contradicted_entities"]
        assert isinstance(entities, list)
        assert len(entities) <= 3
        # projectA appears twice, so it should be in top entities
        assert "projectA" in entities
