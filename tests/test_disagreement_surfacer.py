"""
Tests for DisagreementSurfacer (Skill 9 — Epistemic Layer).
25 tests covering score computation, threshold logic, classification,
action recommendation, and the surface() convenience method.
"""

import pytest

from cato.orchestrator.disagreement_surfacer import DisagreementSurfacer, _jaccard, _stdev


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def surfacer():
    return DisagreementSurfacer()


# ---------------------------------------------------------------------------
# Helpers (internal, tested for correctness)
# ---------------------------------------------------------------------------

def _identical_outputs():
    text = "The answer is forty two and nothing else"
    return {
        "claude": text,
        "codex": text,
        "gemini": text,
    }


def _different_outputs():
    return {
        "claude": "The sky is blue and the grass is green",
        "codex": "Quantum entanglement violates locality principles",
        "gemini": "Photosynthesis converts sunlight into chemical energy",
    }


def _equal_confidences():
    return {"claude": 0.8, "codex": 0.8, "gemini": 0.8}


def _varied_confidences():
    return {"claude": 0.9, "codex": 0.5, "gemini": 0.7}


# ---------------------------------------------------------------------------
# compute_disagreement_score
# ---------------------------------------------------------------------------

def test_compute_score_identical_outputs_zero(surfacer):
    score = surfacer.compute_disagreement_score(
        _identical_outputs(), _equal_confidences()
    )
    assert score == pytest.approx(0.0, abs=0.01)


def test_compute_score_different_outputs_nonzero(surfacer):
    score = surfacer.compute_disagreement_score(
        _different_outputs(), _equal_confidences()
    )
    assert score > 0.0


def test_compute_score_normalized_max_one(surfacer):
    score = surfacer.compute_disagreement_score(
        _different_outputs(), _varied_confidences()
    )
    assert 0.0 <= score <= 1.0


def test_compute_score_rounds_to_4_decimal(surfacer):
    score = surfacer.compute_disagreement_score(
        _different_outputs(), _varied_confidences()
    )
    assert score == round(score, 4)


def test_compute_score_confidence_stdev_contributes(surfacer):
    """Higher confidence variance should yield a higher score than equal confidences."""
    score_equal = surfacer.compute_disagreement_score(
        _different_outputs(), _equal_confidences()
    )
    score_varied = surfacer.compute_disagreement_score(
        _different_outputs(), _varied_confidences()
    )
    assert score_varied >= score_equal


def test_compute_score_default_task_type(surfacer):
    """Passing no task_type should work (uses default threshold 0.35)."""
    score = surfacer.compute_disagreement_score(
        _different_outputs(), _varied_confidences()
    )
    assert isinstance(score, float)


# ---------------------------------------------------------------------------
# is_disagreement
# ---------------------------------------------------------------------------

def test_is_disagreement_above_threshold_true(surfacer):
    assert surfacer.is_disagreement(0.50, "default") is True


def test_is_disagreement_below_threshold_false(surfacer):
    assert surfacer.is_disagreement(0.10, "default") is False


def test_is_disagreement_code_threshold_0_30(surfacer):
    # Score of 0.31 is above code threshold (0.30)
    assert surfacer.is_disagreement(0.31, "code") is True
    # Score of 0.29 is below code threshold
    assert surfacer.is_disagreement(0.29, "code") is False


def test_is_disagreement_decision_threshold_0_25(surfacer):
    assert surfacer.is_disagreement(0.26, "decision") is True
    assert surfacer.is_disagreement(0.24, "decision") is False


# ---------------------------------------------------------------------------
# classify_disagreement
# ---------------------------------------------------------------------------

def test_classify_risk_assessment(surfacer):
    outputs = {"claude": "this action is dangerous", "codex": "it seems safe enough"}
    assert surfacer.classify_disagreement(outputs) == "RISK_ASSESSMENT"


def test_classify_value_judgment(surfacer):
    outputs = {"claude": "I recommend option A", "codex": "option B is better"}
    assert surfacer.classify_disagreement(outputs) == "VALUE_JUDGMENT"


def test_classify_approach(surfacer):
    outputs = {
        "claude": "alternatively you could use a queue",
        "codex": "use a direct call instead",
    }
    assert surfacer.classify_disagreement(outputs) == "APPROACH"


def test_classify_factual_default(surfacer):
    outputs = {"claude": "water boils at 100C", "codex": "water freezes at 0C"}
    assert surfacer.classify_disagreement(outputs) == "FACTUAL"


# ---------------------------------------------------------------------------
# recommend_action
# ---------------------------------------------------------------------------

def test_recommend_factual_run_queries(surfacer):
    assert surfacer.recommend_action("FACTUAL") == "run_additional_queries"


def test_recommend_approach_proceed(surfacer):
    assert surfacer.recommend_action("APPROACH") == "proceed_with_consensus"


def test_recommend_risk_judgment(surfacer):
    assert surfacer.recommend_action("RISK_ASSESSMENT") == "request_user_judgment"


def test_recommend_value_judgment(surfacer):
    assert surfacer.recommend_action("VALUE_JUDGMENT") == "request_user_judgment"


# ---------------------------------------------------------------------------
# surface()
# ---------------------------------------------------------------------------

def test_surface_returns_none_when_no_disagreement(surfacer):
    result = surfacer.surface(_identical_outputs(), _equal_confidences())
    assert result is None


def test_surface_returns_dict_when_disagreement(surfacer):
    result = surfacer.surface(_different_outputs(), _varied_confidences())
    assert result is not None
    assert isinstance(result, dict)


def test_surface_dict_has_all_keys(surfacer):
    result = surfacer.surface(_different_outputs(), _varied_confidences())
    assert result is not None
    required_keys = {
        "consensus_view",
        "minority_view",
        "minority_model",
        "disagreement_type",
        "disagreement_score",
        "recommended_action",
    }
    assert required_keys.issubset(result.keys())


def test_surface_consensus_is_highest_confidence_output(surfacer):
    outputs = {
        "claude": "Recursion leverages the call stack to solve sub-problems elegantly",
        "codex": "Photosynthesis converts sunlight into glucose via chlorophyll absorption",
        "gemini": "Quantum entanglement exhibits non-local correlations between particles",
    }
    confidences = {"claude": 0.95, "codex": 0.50, "gemini": 0.70}
    result = surfacer.surface(outputs, confidences)
    assert result is not None
    assert result["consensus_view"] == outputs["claude"]


def test_surface_minority_is_lowest_confidence(surfacer):
    outputs = {
        "claude": "Recursion leverages the call stack to solve sub-problems elegantly",
        "codex": "Photosynthesis converts sunlight into glucose via chlorophyll absorption",
        "gemini": "Quantum entanglement exhibits non-local correlations between particles",
    }
    confidences = {"claude": 0.95, "codex": 0.50, "gemini": 0.70}
    result = surfacer.surface(outputs, confidences)
    assert result is not None
    assert result["minority_model"] == "codex"
    assert result["minority_view"] == outputs["codex"]


def test_surface_disagreement_score_matches_compute(surfacer):
    outputs = _different_outputs()
    confidences = _varied_confidences()
    expected = surfacer.compute_disagreement_score(outputs, confidences)
    result = surfacer.surface(outputs, confidences)
    assert result is not None
    assert result["disagreement_score"] == expected


def test_surface_two_models_only(surfacer):
    outputs = {
        "claude": "The answer involves recursion and base cases",
        "codex": "Iteration with a stack is more efficient here",
    }
    confidences = {"claude": 0.85, "codex": 0.60}
    # With only 2 models and different enough outputs this may or may not trigger
    # disagreement — we just verify it doesn't raise an exception.
    result = surfacer.surface(outputs, confidences)
    # If it does surface a disagreement, the dict must be valid.
    if result is not None:
        assert "consensus_view" in result
        assert "minority_model" in result


# ---------------------------------------------------------------------------
# Hybrid similarity: paraphrase-friendly fn lowers disagreement score
# ---------------------------------------------------------------------------

def test_paraphrase_high_similarity_fn_lowers_score():
    """When a custom similarity fn treats paraphrases as similar, disagreement score drops."""
    # Lexically different but same meaning -> Jaccard would be low
    outputs = {
        "claude": "We should implement retries with exponential backoff",
        "codex": "Use exponential backoff when retrying requests",
    }
    confidences = {"claude": 0.8, "codex": 0.8}
    jaccard_only = DisagreementSurfacer()
    score_jaccard = jaccard_only.compute_disagreement_score(outputs, confidences, "default")
    # Paraphrase fn: high similarity for any pair (simulate embedding saying "same meaning")
    def paraphrase_fn(a: str, b: str) -> float:
        return 0.9  # high similarity
    hybrid = DisagreementSurfacer(text_similarity_fn=paraphrase_fn)
    score_hybrid = hybrid.compute_disagreement_score(outputs, confidences, "default")
    assert score_hybrid < score_jaccard
    assert score_hybrid == pytest.approx(0.06, abs=0.01)  # 0.6 * (1 - 0.9) + 0.4 * 0


def test_code_task_type_uses_jaccard_even_with_fn():
    """For task_type 'code', Jaccard is used as fallback even when text_similarity_fn is set."""
    outputs = {"a": "def foo(): pass", "b": "def bar(): pass"}
    confidences = {"a": 0.8, "b": 0.8}
    def always_one(_a: str, _b: str) -> float:
        return 1.0
    surfacer = DisagreementSurfacer(text_similarity_fn=always_one)
    score_default = surfacer.compute_disagreement_score(outputs, confidences, "default")
    score_code = surfacer.compute_disagreement_score(outputs, confidences, "code")
    assert score_default == pytest.approx(0.0, abs=0.01)
    assert score_code > 0.0  # Jaccard sees different tokens
