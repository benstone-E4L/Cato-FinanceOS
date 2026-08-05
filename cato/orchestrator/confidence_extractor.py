"""
Confidence extraction from model responses.
Parses various confidence patterns and scores response quality.
"""

import re


def extract_confidence(response_text: object) -> float:
    """
    Extract confidence score from response text.

    Looks for patterns (case-insensitive):
    - ``confidence: 0.XX``
    - ``confidence is X.XX%``
    - ``[confidence: 0.XX]``

    Values greater than 1.0 are treated as percentages and divided by 100.
    The result is clamped to [0.0, 1.0].

    Args:
        response_text: Model response text.  Non-string values (including
            ``None``) are handled gracefully and return the default score.

    Returns:
        Confidence score in [0.0, 1.0]; defaults to 0.75 when no pattern is
        found or when the input is not a non-empty string.
    """
    if not isinstance(response_text, str) or not response_text:
        return 0.75

    def _parse_and_clamp(raw: str) -> float:
        value = float(raw)
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    # Pattern 1: "confidence: 0.XX"  (also matches negative via [+-]? but we
    # intentionally restrict to digits so -0.5 falls through to the default —
    # a negative confidence string is not a well-formed value)
    match = re.search(r'confidence:\s*([0-9]+(?:\.[0-9]+)?)', response_text, re.IGNORECASE)
    if match:
        try:
            return _parse_and_clamp(match.group(1))
        except ValueError:
            pass

    # Pattern 2: "confidence is X.XX%"
    match = re.search(r'confidence\s+is\s+([0-9]+(?:\.[0-9]+)?)%?', response_text, re.IGNORECASE)
    if match:
        try:
            return _parse_and_clamp(match.group(1))
        except ValueError:
            pass

    # Pattern 3: "[confidence: 0.XX]"
    match = re.search(r'\[confidence:\s*([0-9]+(?:\.[0-9]+)?)\]', response_text, re.IGNORECASE)
    if match:
        try:
            return _parse_and_clamp(match.group(1))
        except ValueError:
            pass

    # Pattern 4: "I am 85% confident" / "85% confident"
    match = re.search(r'([0-9]+(?:\.[0-9]+)?)%?\s+confident', response_text, re.IGNORECASE)
    if match:
        try:
            return _parse_and_clamp(match.group(1))
        except ValueError:
            pass

    return 0.75


def score_response_quality(response: object) -> float:
    """
    Score response quality based on heuristics.

    Heuristics applied in order:
    - Base score: 0.80
    - Length < 20 characters: -0.05
    - Contains "error", "failed", or "exception": -0.10
    - Contains code indicators (triple backticks, ``<code>``, ``def ``,
      ``class ``, ``function ``): +0.05

    The result is clamped to [0.0, 1.0].

    Args:
        response: Model response text.  Non-string values (including ``None``)
            are treated as empty strings, yielding a score of 0.75.

    Returns:
        Quality score in [0.0, 1.0].
    """
    if not isinstance(response, str):
        response = ""

    score = 0.80

    if len(response) < 20:
        score -= 0.05

    if re.search(r'error|failed|exception', response, re.IGNORECASE):
        score -= 0.10

    if re.search(r'```|<code>|def |class |function ', response, re.IGNORECASE):
        score += 0.05

    return max(0.0, min(1.0, score))
