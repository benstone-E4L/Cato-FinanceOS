"""
Simple synthesis module using majority vote / highest confidence selection.
"""

from typing import Dict, List


def simple_synthesis(
    claude_result: Dict,
    codex_result: Dict,
    gemini_result: Dict
) -> Dict:
    """
    Synthesize results from all 3 models.
    Returns highest-confidence result with runners-up for reference.

    Args:
        claude_result: Result from Claude API
        codex_result: Result from Codex CLI
        gemini_result: Result from Gemini CLI

    Returns:
        {
            "primary": {"model": "...", "response": "...", "confidence": float},
            "runners_up": [
                {"model": "...", "response": "...", "confidence": float},
                ...
            ],
            "synthesis_note": str
        }
    """
    # Collect all results
    all_results = [claude_result, codex_result, gemini_result]

    # Sort by confidence (highest first)
    sorted_results = sorted(
        all_results,
        key=lambda x: x.get("confidence", 0),
        reverse=True
    )

    # Primary: highest confidence
    primary = {
        "model": sorted_results[0].get("model", "unknown"),
        "response": sorted_results[0].get("response", ""),
        "confidence": sorted_results[0].get("confidence", 0),
        "latency_ms": sorted_results[0].get("latency_ms", 0)
    }

    # Runners-up: other results
    runners_up = []
    for result in sorted_results[1:]:
        runners_up.append({
            "model": result.get("model", "unknown"),
            "response": result.get("response", ""),
            "confidence": result.get("confidence", 0),
            "latency_ms": result.get("latency_ms", 0)
        })

    # Synthesis note
    winner_model = primary["model"]
    winner_conf = primary["confidence"]
    synthesis_note = f"{winner_model.capitalize()}'s solution selected (confidence: {winner_conf:.2f})"

    return {
        "primary": primary,
        "runners_up": runners_up,
        "synthesis_note": synthesis_note
    }


def weighted_synthesis(
    claude_result: Dict,
    codex_result: Dict,
    gemini_result: Dict,
    weights: Dict[str, float] = None
) -> Dict:
    """
    Weighted synthesis based on model reliability.

    Args:
        claude_result: Result from Claude API
        codex_result: Result from Codex CLI
        gemini_result: Result from Gemini CLI
        weights: Model weights (default: claude=0.5, codex=0.3, gemini=0.2)

    Returns:
        Synthesis result with weighted scores
    """
    if weights is None:
        weights = {
            "claude": 0.5,
            "codex": 0.3,
            "gemini": 0.2
        }

    # Apply weights to confidence scores
    weighted_results = []

    for result in [claude_result, codex_result, gemini_result]:
        model = result.get("model", "unknown")
        weight = weights.get(model, 0.2)
        weighted_confidence = result.get("confidence", 0) * weight

        weighted_results.append({
            **result,
            "weighted_confidence": weighted_confidence,
            "weight": weight
        })

    # Sort by weighted confidence
    sorted_results = sorted(
        weighted_results,
        key=lambda x: x.get("weighted_confidence", 0),
        reverse=True
    )

    # Primary: highest weighted confidence
    primary = {
        "model": sorted_results[0].get("model", "unknown"),
        "response": sorted_results[0].get("response", ""),
        "confidence": sorted_results[0].get("confidence", 0),
        "weighted_confidence": sorted_results[0].get("weighted_confidence", 0),
        "latency_ms": sorted_results[0].get("latency_ms", 0)
    }

    # Runners-up
    runners_up = []
    for result in sorted_results[1:]:
        runners_up.append({
            "model": result.get("model", "unknown"),
            "response": result.get("response", ""),
            "confidence": result.get("confidence", 0),
            "weighted_confidence": result.get("weighted_confidence", 0),
            "latency_ms": result.get("latency_ms", 0)
        })

    synthesis_note = f"Weighted synthesis: {primary['model'].capitalize()} selected (weighted conf: {primary['weighted_confidence']:.2f})"

    return {
        "primary": primary,
        "runners_up": runners_up,
        "synthesis_note": synthesis_note,
        "weights_applied": weights
    }
