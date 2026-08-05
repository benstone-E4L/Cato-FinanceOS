"""
cato/core/context_gate.py — Confidence-gated context expansion for CATO.

Phase G — Step 6: Start every turn with minimal context (Tier 0 only).
If confidence of first response is below threshold, identify the specific gap
and retrieve targeted additional context.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from .memory import MemorySystem

logger = logging.getLogger(__name__)

# Hedging phrases that indicate a factual gap
_HEDGING_PHRASES = [
    "i'm not sure",
    "i am not sure",
    "i don't know",
    "i do not know",
    "unclear",
    "uncertain",
    "might be",
]


class ContextGate:
    """
    Confidence-gated context expansion.

    Starts turns with minimal context. If the model's confidence on the first
    response is below threshold, classify the gap type and expand context
    targeted to that gap.

    Usage::

        gate = ContextGate(confidence_extractor, memory, config={
            "confidence_gate_enabled": True,
            "confidence_gate_threshold": 0.85,
            "confidence_gate_max_expansions": 2,
        })
        gap = gate.classify_gap(response_text, confidence=0.72)
        if gap != "none":
            extra_context = await gate.expand(query, gap, existing_context)
    """

    def __init__(
        self,
        confidence_extractor,
        memory: "MemorySystem",
        config: dict | None = None,
    ) -> None:
        self._confidence_extractor = confidence_extractor
        self._memory = memory
        cfg = config or {}
        self._enabled: bool = cfg.get("confidence_gate_enabled", True)
        self._threshold: float = cfg.get("confidence_gate_threshold", 0.85)
        self._max_expansions: int = cfg.get("confidence_gate_max_expansions", 2)

    # ------------------------------------------------------------------
    # Gap classification
    # ------------------------------------------------------------------

    def classify_gap(
        self,
        response_text: str,
        confidence: float,
    ) -> Literal["factual", "code", "intent", "none"]:
        """
        Classify the type of context gap based on response text and confidence.

        Returns:
            "none"    — confidence >= threshold (no gap)
            "factual" — response contains hedging phrases
            "code"    — response contains code blocks but confidence is low
            "intent"  — ambiguity about what user wants (default low-confidence case)
        """
        if confidence >= self._threshold:
            return "none"

        lower = response_text.lower()

        # Check hedging phrases first (factual gap)
        for phrase in _HEDGING_PHRASES:
            if phrase in lower:
                return "factual"

        # Check for code blocks with low confidence (code gap)
        if "```" in response_text:
            return "code"

        # Default: ambiguity about user intent
        return "intent"

    # ------------------------------------------------------------------
    # Context expansion
    # ------------------------------------------------------------------

    async def expand(
        self,
        query: str,
        gap_type: str,
        existing_context: str,
    ) -> str:
        """
        Retrieve targeted additional context for the identified gap type.

        Args:
            query:            The original user query.
            gap_type:         One of "factual", "code", "intent".
            existing_context: Already-injected context string (unused for routing,
                              passed through to avoid duplicates in callers).

        Returns:
            Additional context string to append to the prompt, or a clarifying
            question string for "intent" gaps.
        """
        if gap_type == "factual":
            chunks = await self._memory.asearch(query, top_k=3)
            if not chunks:
                return ""
            lines = ["[Additional context retrieved for factual gap]"]
            for i, chunk in enumerate(chunks, 1):
                lines.append(f"\n--- Retrieved chunk {i} ---\n{chunk}")
            return "\n".join(lines)

        if gap_type == "code":
            # Load COLD sections from skill files found near the query
            cold_text = self._load_cold_sections_from_memory(query)
            if cold_text:
                return f"[COLD skill documentation retrieved]\n\n{cold_text}"
            return ""

        if gap_type == "intent":
            return (
                "Could you clarify what you mean? "
                "I want to make sure I understand your intent before proceeding."
            )

        return ""

    # ------------------------------------------------------------------
    # Gate check
    # ------------------------------------------------------------------

    def should_gate(self, turn_number: int) -> bool:
        """
        Return True if gating is enabled for this turn.

        Args:
            turn_number: Current conversation turn (0-indexed or 1-indexed).
        """
        return self._enabled

    # ------------------------------------------------------------------
    # Properties (for testing / introspection)
    # ------------------------------------------------------------------

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def max_expansions(self) -> int:
        return self._max_expansions

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_cold_sections_from_memory(self, query: str) -> str:
        """
        Attempt to load COLD sections from skill files referenced in memory.

        Searches for .md files with COLD sections in common skill directories.
        Returns empty string if none found.
        """
        from .context_builder import retrieve_cold_section

        # Try to find skill files in standard locations
        skill_dirs = [
            Path.home() / ".cato" / "workspace",
            Path.cwd() / "cato" / "skills",
        ]

        cold_parts: list[str] = []
        for skill_dir in skill_dirs:
            if not skill_dir.exists():
                continue
            for skill_path in skill_dir.glob("**/*.md"):
                cold = retrieve_cold_section(skill_path)
                if cold.strip():
                    cold_parts.append(cold.strip())
                    if len(cold_parts) >= 2:  # Limit to 2 cold sections
                        break
            if cold_parts:
                break

        return "\n\n---\n\n".join(cold_parts)
