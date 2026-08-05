"""
Tests for cato/core/context_gate.py — ContextGate confidence-gated context expansion.

Phase G — Step 6.2: Min 20 tests.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.core.context_gate import ContextGate, _HEDGING_PHRASES


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def make_gate(
    threshold: float = 0.85,
    enabled: bool = True,
    max_expansions: int = 2,
    memory_results: Optional[list[str]] = None,
) -> ContextGate:
    """Create a ContextGate with mocked confidence extractor and memory."""
    confidence_extractor = MagicMock()
    memory = AsyncMock()
    memory.asearch = AsyncMock(return_value=memory_results or [])
    config = {
        "confidence_gate_enabled": enabled,
        "confidence_gate_threshold": threshold,
        "confidence_gate_max_expansions": max_expansions,
    }
    return ContextGate(confidence_extractor, memory, config=config)


# ---------------------------------------------------------------------------
# 1. classify_gap — "none" when confidence >= threshold
# ---------------------------------------------------------------------------

def test_classify_gap_none_at_threshold():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("I know the answer clearly.", confidence=0.85)
    assert result == "none"


def test_classify_gap_none_above_threshold():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("I'm not sure actually.", confidence=0.95)
    # confidence >= threshold means "none" regardless of content
    assert result == "none"


def test_classify_gap_none_high_confidence():
    gate = make_gate(threshold=0.70)
    result = gate.classify_gap("Python is great.", confidence=0.99)
    assert result == "none"


# ---------------------------------------------------------------------------
# 2. classify_gap — "factual" for hedging phrases
# ---------------------------------------------------------------------------

def test_classify_gap_factual_im_not_sure():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("I'm not sure about this topic.", confidence=0.50)
    assert result == "factual"


def test_classify_gap_factual_i_dont_know():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("I don't know the exact answer.", confidence=0.60)
    assert result == "factual"


def test_classify_gap_factual_unclear():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("The situation is unclear to me.", confidence=0.40)
    assert result == "factual"


def test_classify_gap_factual_uncertain():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("I am uncertain about this.", confidence=0.55)
    assert result == "factual"


def test_classify_gap_factual_might_be():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("It might be correct, I think.", confidence=0.60)
    assert result == "factual"


def test_classify_gap_factual_i_am_not_sure():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("I am not sure about the implementation.", confidence=0.50)
    assert result == "factual"


# ---------------------------------------------------------------------------
# 3. classify_gap — "code" for code blocks with low confidence
# ---------------------------------------------------------------------------

def test_classify_gap_code_with_code_block():
    gate = make_gate(threshold=0.85)
    response = "Here is some code:\n```python\nprint('hello')\n```"
    result = gate.classify_gap(response, confidence=0.60)
    assert result == "code"


def test_classify_gap_code_multiple_blocks():
    gate = make_gate(threshold=0.85)
    response = "Try this:\n```js\nconsole.log(x);\n```\nor this:\n```js\nconsole.log(y);\n```"
    result = gate.classify_gap(response, confidence=0.70)
    assert result == "code"


def test_classify_gap_code_not_triggered_without_backticks():
    """Without code blocks, low confidence falls to intent gap."""
    gate = make_gate(threshold=0.85)
    response = "Try using x = 5 and then calling the function."
    result = gate.classify_gap(response, confidence=0.60)
    assert result == "intent"


# ---------------------------------------------------------------------------
# 4. classify_gap — "intent" as default for low confidence
# ---------------------------------------------------------------------------

def test_classify_gap_intent_default():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("Let me help you with that task.", confidence=0.50)
    assert result == "intent"


def test_classify_gap_intent_no_hedging_no_code():
    gate = make_gate(threshold=0.85)
    result = gate.classify_gap("The function needs to be called correctly.", confidence=0.40)
    assert result == "intent"


# ---------------------------------------------------------------------------
# 5. expand() — factual gap calls memory.asearch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expand_factual_calls_memory_asearch():
    memory = AsyncMock()
    memory.asearch = AsyncMock(return_value=["chunk A", "chunk B", "chunk C"])
    gate = ContextGate(MagicMock(), memory, config={"confidence_gate_threshold": 0.85})

    result = await gate.expand("What is Python?", "factual", "existing context")

    memory.asearch.assert_called_once_with("What is Python?", top_k=3)
    assert "chunk A" in result
    assert "chunk B" in result
    assert "chunk C" in result


@pytest.mark.asyncio
async def test_expand_factual_empty_memory_returns_empty():
    memory = AsyncMock()
    memory.asearch = AsyncMock(return_value=[])
    gate = ContextGate(MagicMock(), memory)

    result = await gate.expand("Unknown topic", "factual", "")
    assert result == ""


@pytest.mark.asyncio
async def test_expand_factual_includes_header():
    memory = AsyncMock()
    memory.asearch = AsyncMock(return_value=["fact one"])
    gate = ContextGate(MagicMock(), memory)

    result = await gate.expand("query", "factual", "")
    assert "factual gap" in result.lower()


# ---------------------------------------------------------------------------
# 6. expand() — intent gap returns clarifying question
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expand_intent_returns_clarifying_question():
    gate = make_gate()
    result = await gate.expand("do the thing", "intent", "")
    assert "clarify" in result.lower() or "intent" in result.lower() or "mean" in result.lower()


@pytest.mark.asyncio
async def test_expand_unknown_gap_type_returns_empty():
    gate = make_gate()
    result = await gate.expand("query", "unknown_type", "")
    assert result == ""


# ---------------------------------------------------------------------------
# 7. should_gate() — respects config flag
# ---------------------------------------------------------------------------

def test_should_gate_enabled_returns_true():
    gate = make_gate(enabled=True)
    assert gate.should_gate(1) is True
    assert gate.should_gate(100) is True


def test_should_gate_disabled_returns_false():
    gate = make_gate(enabled=False)
    assert gate.should_gate(1) is False
    assert gate.should_gate(50) is False


# ---------------------------------------------------------------------------
# 8. Config overrides
# ---------------------------------------------------------------------------

def test_config_threshold_override():
    gate = make_gate(threshold=0.70)
    assert gate.threshold == 0.70
    # Below threshold
    result = gate.classify_gap("I might be wrong.", confidence=0.65)
    assert result == "factual"
    # At threshold
    result2 = gate.classify_gap("I might be wrong.", confidence=0.70)
    assert result2 == "none"


def test_config_max_expansions_override():
    gate = make_gate(max_expansions=5)
    assert gate.max_expansions == 5


def test_config_enabled_override():
    gate = make_gate(enabled=False)
    assert gate.enabled is False


def test_default_config_values():
    """Default config should have sensible defaults."""
    confidence_extractor = MagicMock()
    memory = AsyncMock()
    gate = ContextGate(confidence_extractor, memory)
    assert gate.threshold == 0.85
    assert gate.max_expansions == 2
    assert gate.enabled is True


def test_config_none_uses_defaults():
    """Passing config=None should use defaults."""
    confidence_extractor = MagicMock()
    memory = AsyncMock()
    gate = ContextGate(confidence_extractor, memory, config=None)
    assert gate.threshold == 0.85
    assert gate.enabled is True
