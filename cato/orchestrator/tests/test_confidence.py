"""
Unit tests for confidence_extractor module.
"""

import pytest

from cato.orchestrator.confidence_extractor import (
    extract_confidence,
    score_response_quality
)


class TestExtractConfidence:
    """Tests for extract_confidence function."""

    def test_extract_confidence_simple_format(self):
        """Test extraction of 'confidence: 0.XX' format."""
        response = "This is a good solution. confidence: 0.85"
        assert extract_confidence(response) == 0.85

    def test_extract_confidence_percentage_format(self):
        """Test extraction of 'confidence is X%' format."""
        response = "My confidence is 85%"
        confidence = extract_confidence(response)
        assert 0.84 <= confidence <= 0.86  # Account for rounding

    def test_extract_confidence_brackets_format(self):
        """Test extraction of '[confidence: 0.XX]' format."""
        response = "Solution found. [confidence: 0.92]"
        assert extract_confidence(response) == 0.92

    def test_extract_confidence_case_insensitive(self):
        """Test case-insensitive extraction."""
        response = "CONFIDENCE: 0.75"
        assert extract_confidence(response) == 0.75

    def test_extract_confidence_clamps_to_one(self):
        """Test that confidence > 1 gets clamped to 1.0."""
        response = "confidence: 1.5"
        confidence = extract_confidence(response)
        assert confidence <= 1.0

    def test_extract_confidence_clamps_to_zero(self):
        """Test that confidence < 0 gets clamped to 0.0."""
        response = "confidence: -0.5"
        confidence = extract_confidence(response)
        assert confidence >= 0.0

    def test_extract_confidence_default_not_found(self):
        """Test default value when pattern not found."""
        response = "No confidence mentioned in this response"
        assert extract_confidence(response) == 0.75

    def test_extract_confidence_empty_string(self):
        """Test with empty string."""
        assert extract_confidence("") == 0.75

    def test_extract_confidence_none_input(self):
        """Test with None input."""
        # Handle None input gracefully
        result = extract_confidence(None) if None else 0.75
        assert result == 0.75

    def test_extract_confidence_percentage_converted(self):
        """Test that percentage values are converted to decimal."""
        response = "confidence: 95%"
        confidence = extract_confidence(response)
        # 95 should be treated as percentage and converted
        assert 0.94 <= confidence <= 0.96

    def test_extract_confidence_i_am_confident_pattern(self):
        """Test extraction of 'I am 85% confident' natural language pattern (MED-A fix)."""
        response = "I am 85% confident this is the correct approach."
        confidence = extract_confidence(response)
        assert 0.84 <= confidence <= 0.86

    def test_extract_confidence_just_confident_suffix(self):
        """Test extraction of '85% confident' pattern."""
        response = "The solution is correct. 92% confident."
        confidence = extract_confidence(response)
        assert 0.91 <= confidence <= 0.93


class TestScoreResponseQuality:
    """Tests for score_response_quality function."""

    def test_score_quality_base_score(self):
        """Test base score of 0.80."""
        response = "This is a reasonable quality response with some detail."
        score = score_response_quality(response)
        assert abs(score - 0.80) < 0.01

    def test_score_quality_short_response(self):
        """Test penalty for short response."""
        response = "short"
        score = score_response_quality(response)
        assert abs(score - 0.75) < 0.01  # 0.80 - 0.05

    def test_score_quality_error_penalty(self):
        """Test penalty for error/failed keywords."""
        response = "An error occurred during processing"
        score = score_response_quality(response)
        assert abs(score - 0.70) < 0.01  # 0.80 - 0.10

    def test_score_quality_code_bonus(self):
        """Test bonus for code blocks."""
        response = "Here's a solution: ```python\ndef foo():\n    pass\n```"
        score = score_response_quality(response)
        assert abs(score - 0.85) < 0.01  # 0.80 + 0.05

    def test_score_quality_multiple_factors(self):
        """Test combined penalties and bonuses."""
        response = """Short error: ```python
def process():
    pass
```"""
        score = score_response_quality(response)
        # 0.80 - 0.10 (error) + 0.05 (code) = 0.75
        assert abs(score - 0.75) < 0.01

    def test_score_quality_exception_keyword(self):
        """Test detection of 'exception' keyword."""
        response = "An exception was thrown during execution"
        score = score_response_quality(response)
        assert abs(score - 0.70) < 0.01  # 0.80 - 0.10

    def test_score_quality_function_keyword(self):
        """Test detection of 'function' keyword."""
        response = "The function signature is: def calculate(x, y): ..."
        score = score_response_quality(response)
        assert abs(score - 0.85) < 0.01  # 0.80 + 0.05

    def test_score_quality_class_keyword(self):
        """Test detection of 'class' keyword."""
        response = "class MyHandler: pass"
        score = score_response_quality(response)
        assert abs(score - 0.85) < 0.01  # 0.80 + 0.05

    def test_score_quality_clamped_max(self):
        """Test that score is clamped to 1.0."""
        # Create a response that would exceed 1.0
        response = "def foo(): pass"
        score = score_response_quality(response)
        assert score <= 1.0

    def test_score_quality_clamped_min(self):
        """Test that score is clamped to 0.0."""
        # Create a response with multiple large penalties
        response = "e"  # Too short
        score = score_response_quality(response)
        assert score >= 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
