"""
DisagreementSurfacer — Skill 9 (Epistemic Layer)

Detects and characterises disagreement across multi-model outputs.
Uses word-level Jaccard similarity by default; optional text_similarity_fn
(e.g. embedding-based) can be supplied for paraphrase-sensitive scoring.
Jaccard is kept as fallback for code-heavy prompts where lexical overlap is informative.
"""

from __future__ import annotations

import math
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a and not tokens_b:
        return 1.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


def _stdev(values: list[float]) -> float:
    """Population standard deviation (no numpy required)."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

# Task types for which we always use Jaccard (code-heavy prompts benefit from lexical overlap)
_JACCARD_ONLY_TASK_TYPES = frozenset(["code"])


class DisagreementSurfacer:
    """Detect, classify, and surface disagreements across model outputs."""

    THRESHOLDS: dict[str, float] = {
        "code": 0.30,
        "research": 0.40,
        "decision": 0.25,
        "default": 0.35,
    }

    def __init__(
        self,
        text_similarity_fn: Optional[Callable[[str, str], float]] = None,
    ) -> None:
        """
        text_similarity_fn: optional (a, b) -> similarity in [0, 1].
        When set and task_type is not "code", used for pairwise similarity
        instead of Jaccard (e.g. embedding similarity for paraphrase robustness).
        """
        self._text_similarity_fn = text_similarity_fn

    # ------------------------------------------------------------------
    # Score computation
    # ------------------------------------------------------------------

    def _pairwise_similarity(self, a: str, b: str, task_type: str) -> float:
        """Use Jaccard for code; otherwise optional fn or Jaccard."""
        if task_type in _JACCARD_ONLY_TASK_TYPES or self._text_similarity_fn is None:
            return _jaccard(a, b)
        return self._text_similarity_fn(a, b)

    def compute_disagreement_score(
        self,
        outputs: dict[str, str],
        confidences: dict[str, float],
        task_type: str = "default",
    ) -> float:
        """
        Compute a combined disagreement score in [0.0, 1.0].

        Semantic distance: max pairwise (1 - similarity). Similarity is
        Jaccard by default; if text_similarity_fn is set and task_type is not
        "code", that fn is used (e.g. embedding similarity for paraphrases).
        Confidence divergence: population stdev of confidence values.
        Combined: 0.6 * max_semantic_distance + 0.4 * confidence_stdev.
        """
        output_values = list(outputs.values())

        max_distance = 0.0
        for i in range(len(output_values)):
            for j in range(i + 1, len(output_values)):
                sim = self._pairwise_similarity(output_values[i], output_values[j], task_type)
                dist = 1.0 - sim
                if dist > max_distance:
                    max_distance = dist

        conf_stdev = _stdev(list(confidences.values()))

        combined = 0.6 * max_distance + 0.4 * conf_stdev
        combined = max(0.0, min(1.0, combined))
        return round(combined, 4)

    # ------------------------------------------------------------------
    # Threshold check
    # ------------------------------------------------------------------

    def is_disagreement(self, score: float, task_type: str = "default") -> bool:
        """Return ``True`` if *score* exceeds the threshold for *task_type*."""
        threshold = self.THRESHOLDS.get(task_type, self.THRESHOLDS["default"])
        return score > threshold

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify_disagreement(self, outputs: dict[str, str]) -> str:
        """
        Classify the nature of the disagreement from the combined output text.

        Priority order: RISK_ASSESSMENT > VALUE_JUDGMENT > APPROACH > FACTUAL.
        """
        combined = " ".join(outputs.values()).lower()

        risk_keywords = ["dangerous", "safe", "risk", "unlikely", "threat"]
        value_keywords = ["more important", "prefer", "recommend", "should"]
        approach_keywords = ["instead", "alternatively", "better to", "approach"]

        for kw in risk_keywords:
            if kw in combined:
                return "RISK_ASSESSMENT"

        for kw in value_keywords:
            if kw in combined:
                return "VALUE_JUDGMENT"

        for kw in approach_keywords:
            if kw in combined:
                return "APPROACH"

        return "FACTUAL"

    # ------------------------------------------------------------------
    # Action recommendation
    # ------------------------------------------------------------------

    def recommend_action(self, disagreement_type: str) -> str:
        """Map a disagreement type to a recommended action."""
        mapping = {
            "FACTUAL": "run_additional_queries",
            "APPROACH": "proceed_with_consensus",
            "RISK_ASSESSMENT": "request_user_judgment",
            "VALUE_JUDGMENT": "request_user_judgment",
        }
        return mapping.get(disagreement_type, "run_additional_queries")

    # ------------------------------------------------------------------
    # Surface
    # ------------------------------------------------------------------

    def surface(
        self,
        outputs: dict[str, str],
        confidences: dict[str, float],
        task_type: str = "default",
    ) -> dict | None:
        """
        Return a structured disagreement report if disagreement is detected,
        otherwise return ``None``.
        """
        score = self.compute_disagreement_score(outputs, confidences, task_type)
        if not self.is_disagreement(score, task_type):
            return None

        # Consensus view: output from the model with highest confidence
        consensus_model = max(confidences, key=lambda m: confidences[m])
        minority_model = min(confidences, key=lambda m: confidences[m])

        disagreement_type = self.classify_disagreement(outputs)

        return {
            "consensus_view": outputs[consensus_model],
            "minority_view": outputs[minority_model],
            "minority_model": minority_model,
            "disagreement_type": disagreement_type,
            "disagreement_score": score,
            "recommended_action": self.recommend_action(disagreement_type),
        }
