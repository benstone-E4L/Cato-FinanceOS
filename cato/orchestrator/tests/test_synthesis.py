"""
Unit tests for synthesis module.
"""

import pytest

from cato.orchestrator.synthesis import (
    simple_synthesis,
    weighted_synthesis
)


class TestSimpleSynthesis:
    """Tests for simple_synthesis function."""

    def test_simple_synthesis_basic(self):
        """Test basic synthesis with all 3 models."""
        claude = {"model": "claude", "response": "Claude solution", "confidence": 0.85, "latency_ms": 100}
        codex = {"model": "codex", "response": "Codex solution", "confidence": 0.82, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Gemini solution", "confidence": 0.78, "latency_ms": 120}

        result = simple_synthesis(claude, codex, gemini)

        # Should select claude (highest confidence)
        assert result["primary"]["model"] == "claude"
        assert result["primary"]["confidence"] == 0.85
        assert len(result["runners_up"]) == 2
        assert "synthesis_note" in result

    def test_simple_synthesis_runner_ups_ordered(self):
        """Test that runners-up are ordered by confidence."""
        claude = {"model": "claude", "response": "Claude", "confidence": 0.90, "latency_ms": 100}
        codex = {"model": "codex", "response": "Codex", "confidence": 0.75, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Gemini", "confidence": 0.85, "latency_ms": 120}

        result = simple_synthesis(claude, codex, gemini)

        # Primary should be claude (0.90)
        assert result["primary"]["model"] == "claude"

        # Runners-up should be ordered: gemini (0.85), then codex (0.75)
        assert result["runners_up"][0]["model"] == "gemini"
        assert result["runners_up"][0]["confidence"] == 0.85
        assert result["runners_up"][1]["model"] == "codex"
        assert result["runners_up"][1]["confidence"] == 0.75

    def test_simple_synthesis_all_low_confidence(self):
        """Test synthesis when all confidences are low."""
        claude = {"model": "claude", "response": "Claude", "confidence": 0.30, "latency_ms": 100}
        codex = {"model": "codex", "response": "Codex", "confidence": 0.25, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Gemini", "confidence": 0.20, "latency_ms": 120}

        result = simple_synthesis(claude, codex, gemini)

        # Should still select best (claude with 0.30)
        assert result["primary"]["model"] == "claude"
        assert result["primary"]["confidence"] == 0.30

    def test_simple_synthesis_includes_response(self):
        """Test that responses are included in synthesis."""
        claude = {"model": "claude", "response": "Solution A", "confidence": 0.92, "latency_ms": 100}
        codex = {"model": "codex", "response": "Solution B", "confidence": 0.88, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Solution C", "confidence": 0.85, "latency_ms": 120}

        result = simple_synthesis(claude, codex, gemini)

        assert result["primary"]["response"] == "Solution A"
        assert result["runners_up"][0]["response"] == "Solution B"
        assert result["runners_up"][1]["response"] == "Solution C"

    def test_simple_synthesis_includes_latency(self):
        """Test that latency is preserved in synthesis."""
        claude = {"model": "claude", "response": "Claude", "confidence": 0.95, "latency_ms": 150}
        codex = {"model": "codex", "response": "Codex", "confidence": 0.80, "latency_ms": 200}
        gemini = {"model": "gemini", "response": "Gemini", "confidence": 0.75, "latency_ms": 250}

        result = simple_synthesis(claude, codex, gemini)

        assert result["primary"]["latency_ms"] == 150
        assert result["runners_up"][0]["latency_ms"] == 200

    def test_simple_synthesis_note_format(self):
        """Test synthesis note contains expected information."""
        claude = {"model": "claude", "response": "Claude", "confidence": 0.88, "latency_ms": 100}
        codex = {"model": "codex", "response": "Codex", "confidence": 0.75, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Gemini", "confidence": 0.70, "latency_ms": 120}

        result = simple_synthesis(claude, codex, gemini)

        note = result["synthesis_note"]
        assert "claude" in note.lower()
        assert "0.88" in note
        assert "selected" in note.lower() or "confidence" in note.lower()

    def test_simple_synthesis_missing_fields(self):
        """Test handling of missing fields in results."""
        claude = {"model": "claude", "response": "Claude"}  # Missing confidence and latency_ms
        codex = {"model": "codex", "confidence": 0.80, "latency_ms": 110}
        gemini = {"model": "gemini", "confidence": 0.75, "latency_ms": 120}

        result = simple_synthesis(claude, codex, gemini)

        # Should handle gracefully - codex should be selected as it has higher confidence than claude's default
        assert result["primary"]["model"] in ["claude", "codex"]


class TestWeightedSynthesis:
    """Tests for weighted_synthesis function."""

    def test_weighted_synthesis_default_weights(self):
        """Test weighted synthesis with default weights."""
        claude = {"model": "claude", "response": "Claude", "confidence": 0.80, "latency_ms": 100}
        codex = {"model": "codex", "response": "Codex", "confidence": 0.90, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Gemini", "confidence": 0.95, "latency_ms": 120}

        result = weighted_synthesis(claude, codex, gemini)

        # Default: claude=0.5, codex=0.3, gemini=0.2
        # Weighted scores: claude=0.40, codex=0.27, gemini=0.19
        # Claude should still win despite lower raw confidence due to weight
        assert result["primary"]["model"] == "claude"
        assert "weighted_confidence" in result["primary"]

    def test_weighted_synthesis_custom_weights(self):
        """Test weighted synthesis with custom weights."""
        claude = {"model": "claude", "response": "Claude", "confidence": 0.70, "latency_ms": 100}
        codex = {"model": "codex", "response": "Codex", "confidence": 0.95, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Gemini", "confidence": 0.80, "latency_ms": 120}

        weights = {"claude": 0.2, "codex": 0.6, "gemini": 0.2}
        result = weighted_synthesis(claude, codex, gemini, weights=weights)

        # Weighted scores: claude=0.14, codex=0.57, gemini=0.16
        # Codex should win with higher weight
        assert result["primary"]["model"] == "codex"
        assert result["weights_applied"] == weights

    def test_weighted_synthesis_includes_metadata(self):
        """Test that weighted synthesis includes all required metadata."""
        claude = {"model": "claude", "response": "Claude", "confidence": 0.85, "latency_ms": 100}
        codex = {"model": "codex", "response": "Codex", "confidence": 0.80, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Gemini", "confidence": 0.75, "latency_ms": 120}

        result = weighted_synthesis(claude, codex, gemini)

        # Check structure
        assert "primary" in result
        assert "runners_up" in result
        assert "synthesis_note" in result
        assert "weights_applied" in result

        # Check primary has weighted_confidence
        assert "weighted_confidence" in result["primary"]

    def test_weighted_synthesis_zero_weight(self):
        """Test weighted synthesis with zero weight for a model."""
        claude = {"model": "claude", "response": "Claude", "confidence": 0.99, "latency_ms": 100}
        codex = {"model": "codex", "response": "Codex", "confidence": 0.95, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Gemini", "confidence": 0.90, "latency_ms": 120}

        weights = {"claude": 0.0, "codex": 1.0, "gemini": 0.0}
        result = weighted_synthesis(claude, codex, gemini, weights=weights)

        # Codex should win despite claude's higher confidence
        assert result["primary"]["model"] == "codex"

    def test_weighted_synthesis_equal_weights(self):
        """Test weighted synthesis with equal weights."""
        claude = {"model": "claude", "response": "Claude", "confidence": 0.85, "latency_ms": 100}
        codex = {"model": "codex", "response": "Codex", "confidence": 0.90, "latency_ms": 110}
        gemini = {"model": "gemini", "response": "Gemini", "confidence": 0.95, "latency_ms": 120}

        weights = {"claude": 1.0/3, "codex": 1.0/3, "gemini": 1.0/3}
        result = weighted_synthesis(claude, codex, gemini, weights=weights)

        # With equal weights, gemini (0.95) should still win
        assert result["primary"]["model"] == "gemini"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
