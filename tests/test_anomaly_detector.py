"""
tests/test_anomaly_detector.py — Tests for Anticipatory Signal Monitor (Skill 4).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from cato.monitoring.anomaly_detector import AnomalyDetector, Domain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ad(tmp_path: Path) -> AnomalyDetector:
    detector = AnomalyDetector(db_path=tmp_path / "test_anomaly.db")
    yield detector
    detector.close()


# ---------------------------------------------------------------------------
# Domain management
# ---------------------------------------------------------------------------

def test_add_domain_returns_uuid(ad: AnomalyDetector) -> None:
    domain_id = ad.add_domain("AI Research", "Track AI papers")
    assert isinstance(domain_id, str)
    parsed = uuid.UUID(domain_id)
    assert str(parsed) == domain_id


def test_list_domains_returns_created_domain(ad: AnomalyDetector) -> None:
    domain_id = ad.add_domain("Crypto Market", "Monitor crypto signals")
    domains = ad.list_domains()
    assert len(domains) == 1
    assert domains[0].domain_id == domain_id
    assert domains[0].name == "Crypto Market"


def test_deactivate_domain_returns_true_for_existing(ad: AnomalyDetector) -> None:
    domain_id = ad.add_domain("To Deactivate", "Will be deactivated")
    result = ad.deactivate_domain(domain_id)
    assert result is True


def test_deactivate_domain_returns_false_for_missing(ad: AnomalyDetector) -> None:
    result = ad.deactivate_domain("nonexistent-domain-id")
    assert result is False


def test_deactivated_domain_not_in_active_list(ad: AnomalyDetector) -> None:
    domain_id = ad.add_domain("Inactive", "Inactive domain")
    ad.deactivate_domain(domain_id)
    active = ad.list_domains(active_only=True)
    active_ids = {d.domain_id for d in active}
    assert domain_id not in active_ids


def test_get_domain_returns_none_for_missing(ad: AnomalyDetector) -> None:
    result = ad.get_domain("nonexistent-id")
    assert result is None


def test_get_domain_returns_domain_with_correct_fields(ad: AnomalyDetector) -> None:
    sources = [{"url": "https://example.com/feed", "type": "rss"}]
    domain_id = ad.add_domain("Test Domain", "For testing", signal_sources=sources)
    domain = ad.get_domain(domain_id)
    assert domain is not None
    assert domain.domain_id == domain_id
    assert domain.name == "Test Domain"
    assert domain.description == "For testing"
    assert domain.signal_sources == sources
    assert domain.active is True


# ---------------------------------------------------------------------------
# compute_disagreement_score
# ---------------------------------------------------------------------------

def test_disagreement_score_zero_current_volume(ad: AnomalyDetector) -> None:
    score = ad.compute_disagreement_score(0, 100)
    assert score == 0.0


def test_disagreement_score_3x_volume_anomaly(ad: AnomalyDetector) -> None:
    score = ad.compute_disagreement_score(300, 100, 0.0)
    assert score > 0.0


def test_disagreement_score_semantic_drift_only(ad: AnomalyDetector) -> None:
    # Same volume as baseline (ratio=1.0) but high semantic distance
    score = ad.compute_disagreement_score(100, 100, 0.5)
    # volume_score = (1.0 - 1.0) / 3.0 = 0.0; semantic_score = 0.5; combined = 0.4*0.5 = 0.2
    assert score > 0.0
    assert score == pytest.approx(0.2, abs=1e-4)


def test_disagreement_score_zero_baseline_volume(ad: AnomalyDetector) -> None:
    score = ad.compute_disagreement_score(100, 0)
    assert score == 0.0


def test_disagreement_score_normalized_max_one(ad: AnomalyDetector) -> None:
    # Extreme values should cap at 1.0
    score = ad.compute_disagreement_score(10000, 1, 1.0)
    assert score <= 1.0


# ---------------------------------------------------------------------------
# is_anomaly
# ---------------------------------------------------------------------------

def test_is_anomaly_true_above_threshold_with_cross_source(ad: AnomalyDetector) -> None:
    # threshold for "code" is 0.30; score=0.5 > 0.30 AND cross_source_count=2 >= 2
    assert ad.is_anomaly(0.5, task_type="code", cross_source_count=2) is True


def test_is_anomaly_false_not_cross_corroborated(ad: AnomalyDetector) -> None:
    # Even with high score, cross_source_count=1 is not enough
    assert ad.is_anomaly(0.5, task_type="code", cross_source_count=1) is False


def test_is_anomaly_false_below_threshold(ad: AnomalyDetector) -> None:
    # score=0.1 < 0.35 default threshold
    assert ad.is_anomaly(0.1, task_type="default", cross_source_count=3) is False


def test_is_anomaly_decision_threshold(ad: AnomalyDetector) -> None:
    # decision threshold is 0.25; score=0.3 > 0.25 AND cross_source >= 2
    assert ad.is_anomaly(0.3, task_type="decision", cross_source_count=2) is True


# ---------------------------------------------------------------------------
# classify_disagreement
# ---------------------------------------------------------------------------

def test_classify_risk_assessment(ad: AnomalyDetector) -> None:
    result = ad.classify_disagreement("This approach is dangerous", "It could pose a threat")
    assert result == "RISK_ASSESSMENT"


def test_classify_approach(ad: AnomalyDetector) -> None:
    result = ad.classify_disagreement("Instead use the new API", "Alternatively consider...")
    assert result == "APPROACH"


def test_classify_value_judgment(ad: AnomalyDetector) -> None:
    result = ad.classify_disagreement("I prefer the first option", "You should consider...")
    assert result == "VALUE_JUDGMENT"


def test_classify_factual(ad: AnomalyDetector) -> None:
    result = ad.classify_disagreement("plain fact text about data", "another factual statement")
    assert result == "FACTUAL"


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------

def test_record_prediction_returns_uuid(ad: AnomalyDetector) -> None:
    domain_id = ad.add_domain("Pred Domain", "")
    pred_id = ad.record_prediction(domain_id, "Signal summary", "Predicted outcome", 0.7)
    assert isinstance(pred_id, str)
    parsed = uuid.UUID(pred_id)
    assert str(parsed) == pred_id


def test_verify_prediction_returns_true_for_existing(ad: AnomalyDetector) -> None:
    domain_id = ad.add_domain("Verify Domain", "")
    pred_id = ad.record_prediction(domain_id, "Summary", "Development", 0.6)
    result = ad.verify_prediction(pred_id, lead_time_actual=86400.0)
    assert result is True


def test_verify_prediction_returns_false_for_missing(ad: AnomalyDetector) -> None:
    result = ad.verify_prediction("nonexistent-pred-id")
    assert result is False


def test_get_calibration_score_none_when_less_than_20(ad: AnomalyDetector) -> None:
    domain_id = ad.add_domain("Calib Domain", "")
    for _ in range(5):
        ad.record_prediction(domain_id, "sig", "dev", 0.5)
    score = ad.get_calibration_score(domain_id)
    assert score is None


def test_get_calibration_score_float_when_ge_20(ad: AnomalyDetector) -> None:
    domain_id = ad.add_domain("Big Calib Domain", "")
    pred_ids = []
    for _ in range(20):
        pid = ad.record_prediction(domain_id, "sig", "dev", 0.5)
        pred_ids.append(pid)
    # Verify 10 of them
    for pid in pred_ids[:10]:
        ad.verify_prediction(pid)
    score = ad.get_calibration_score(domain_id)
    assert score is not None
    assert isinstance(score, float)
    assert abs(score - 0.5) < 1e-9
