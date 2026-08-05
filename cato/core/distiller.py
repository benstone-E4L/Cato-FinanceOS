"""
cato/core/distiller.py — Memory distillation pipeline.

Every 20 turns (or when context nears limit), compresses oldest conversation
history into 400-token SQLite chunks. Prevents truncation information loss
and makes all past context searchable via cosine similarity.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DISTILL_EVERY_N_TURNS: int = 20
_CONTEXT_THRESHOLD_RATIO: float = 0.85
_SUMMARY_MAX_TOKENS: int = 200  # rough word count approximation

_MODEL_NAME = "all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------

_DECISION_WORDS_RE = re.compile(
    r"\b(?:will|should|decided|chose|choose|going to|must|shall|agreed|plan to)\b",
    re.IGNORECASE,
)
_QUESTION_END_RE = re.compile(r"\?\s*$")
_FACT_PATTERNS_RE = re.compile(
    r"""
    (?:
        \bthe\s+\w+\s+is\b         # "the X is …"
        | \bthis\s+is\b            # "this is …"
        | \bit\s+is\b              # "it is …"
        | \bI\s+am\b               # "I am …"
        | \bthere\s+are\b          # "there are …"
        | \bwe\s+have\b            # "we have …"
        | \bthe\s+value\b          # "the value …"
        | \bthe\s+result\b         # "the result …"
        | \bthe\s+answer\b         # "the answer …"
        | \bthe\s+total\b          # "the total …"
        | \bthe\s+key\b            # "the key …"
        | \bkey\s+point\b          # "key point"
        | \bnote\s+that\b          # "note that"
        | \bimportant\b            # "important"
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ---------------------------------------------------------------------------
# DistillationResult dataclass
# ---------------------------------------------------------------------------


@dataclass
class DistillationResult:
    """Result of distilling a batch of conversation turns."""

    session_id: str
    turn_start: int
    turn_end: int
    summary: str
    key_facts: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    confidence: float = 0.75
    created_at: str = ""
    embedding: Optional[bytes] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Distiller
# ---------------------------------------------------------------------------


class Distiller:
    """
    Extracts structured summaries from conversation turn batches.

    Uses heuristic regex extraction — no model call required for MVP.
    Computes sentence-transformer embeddings on the summary for semantic search.
    """

    def __init__(self) -> None:
        self._embed_model = None

    # ------------------------------------------------------------------
    # Lazy embedding model
    # ------------------------------------------------------------------

    def _get_embed_model(self):
        if self._embed_model is None:
            from sentence_transformers import SentenceTransformer  # noqa

            logger.info("Loading embedding model %s …", _MODEL_NAME)
            self._embed_model = SentenceTransformer(_MODEL_NAME)
        return self._embed_model

    # ------------------------------------------------------------------
    # Heuristic extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_sentences(text: str) -> list[str]:
        """Split text into sentences (simple approach)."""
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _truncate_to_tokens(text: str, max_words: int = _SUMMARY_MAX_TOKENS) -> str:
        """Rough word-level truncation to approximate token limit."""
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]) + " …"

    def _build_summary(self, turns: list[dict]) -> str:
        """
        Build a summary (≤200 tokens) from assistant turns.

        Strategy: concatenate first meaningful sentence from each assistant
        turn, then truncate.
        """
        sentences: list[str] = []
        for turn in turns:
            if turn.get("role") != "assistant":
                continue
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            sents = self._extract_sentences(content)
            if sents:
                sentences.append(sents[0])

        if not sentences:
            # Fall back: use any available content
            for turn in turns:
                content = (turn.get("content") or "").strip()
                if content:
                    sents = self._extract_sentences(content)
                    if sents:
                        sentences.append(sents[0])
                        break

        combined = " ".join(sentences)
        return self._truncate_to_tokens(combined, _SUMMARY_MAX_TOKENS)

    def _extract_key_facts(self, turns: list[dict]) -> list[str]:
        """Extract fact-like sentences from all turns."""
        facts: list[str] = []
        for turn in turns:
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            for sentence in self._extract_sentences(content):
                if _FACT_PATTERNS_RE.search(sentence):
                    facts.append(sentence.strip())
        # Deduplicate preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for f in facts:
            key = f.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        return deduped[:10]  # cap at 10

    def _extract_decisions(self, turns: list[dict]) -> list[str]:
        """Extract sentences containing decision language."""
        decisions: list[str] = []
        for turn in turns:
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            for sentence in self._extract_sentences(content):
                if _DECISION_WORDS_RE.search(sentence):
                    decisions.append(sentence.strip())
        seen: set[str] = set()
        deduped: list[str] = []
        for d in decisions:
            key = d.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(d)
        return deduped[:10]

    def _extract_open_questions(self, turns: list[dict]) -> list[str]:
        """Extract sentences that end with a question mark."""
        questions: list[str] = []
        for turn in turns:
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            for sentence in self._extract_sentences(content):
                if _QUESTION_END_RE.search(sentence):
                    questions.append(sentence.strip())
        seen: set[str] = set()
        deduped: list[str] = []
        for q in questions:
            key = q.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(q)
        return deduped[:10]

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _compute_embedding(self, summary: str, key_facts: list[str]) -> bytes:
        """Compute float32 embedding blob for the distillation result."""
        text = summary
        if key_facts:
            text = text + " " + " ".join(key_facts[:3])
        model = self._get_embed_model()
        vec = model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
        return vec.astype(np.float32).tobytes()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def distill(
        self,
        session_id: str,
        turns: list[dict],
        turn_start: int = 0,
    ) -> Optional[DistillationResult]:
        """
        Distil a list of conversation turns into a structured summary.

        Args:
            session_id: The session these turns belong to.
            turns: List of ``{role: str, content: str}`` dicts.
            turn_start: Index of the first turn in the broader conversation.

        Returns:
            A :class:`DistillationResult`, or ``None`` if *turns* is empty.
        """
        if not turns:
            return None

        turn_end = turn_start + len(turns) - 1

        summary = self._build_summary(turns)
        key_facts = self._extract_key_facts(turns)
        decisions = self._extract_decisions(turns)
        open_questions = self._extract_open_questions(turns)

        try:
            embedding = self._compute_embedding(summary, key_facts)
        except Exception as exc:
            logger.warning("Embedding computation failed: %s", exc)
            embedding = None

        return DistillationResult(
            session_id=session_id,
            turn_start=turn_start,
            turn_end=turn_end,
            summary=summary,
            key_facts=key_facts,
            decisions=decisions,
            open_questions=open_questions,
            confidence=0.75,
            created_at=datetime.now(timezone.utc).isoformat(),
            embedding=embedding,
        )


# ---------------------------------------------------------------------------
# Trigger condition
# ---------------------------------------------------------------------------


def should_distill(
    turn_count: int,
    token_count: int,
    context_limit: int,
) -> bool:
    """
    Determine whether distillation should be triggered.

    Args:
        turn_count: Number of turns in the current session.
        token_count: Current token count in the conversation history.
        context_limit: Model context window limit in tokens.

    Returns:
        True when ``turn_count % 20 == 0`` (and turn_count > 0)
        OR when ``token_count > context_limit * 0.85``.
    """
    if turn_count > 0 and turn_count % _DISTILL_EVERY_N_TURNS == 0:
        return True
    if context_limit > 0 and token_count > context_limit * _CONTEXT_THRESHOLD_RATIO:
        return True
    return False
