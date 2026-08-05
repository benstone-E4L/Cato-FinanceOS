"""
EpistemicMonitor — Skill 3 (Epistemic Layer)

Tracks factual premises extracted from model outputs, monitors confidence
gaps, and manages interrupt budgets for clarification sub-queries.
"""

import re
import sqlite3
import time
from pathlib import Path
from typing import Optional


_GAPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS epistemic_unresolved_gaps (
    gap_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    premise    TEXT NOT NULL,
    confidence REAL NOT NULL,
    timestamp  REAL NOT NULL,
    created_at REAL NOT NULL
);
"""


class EpistemicMonitor:
    """Monitor epistemic state across a multi-model reasoning session."""

    PREMISE_MARKERS = [
        "because",
        "since",
        "assuming",
        "given that",
        "the fact that",
    ]

    def __init__(
        self,
        threshold: float = 0.70,
        max_interrupts: int = 3,
        db_path: Optional[Path] = None,
    ):
        self.threshold = threshold
        self.max_interrupts = max_interrupts
        self._premise_confidence_map: dict[str, float] = {}
        self._interrupt_count: int = 0
        self._unresolved_gaps: list[dict] = []
        self._db_path = db_path
        if db_path is not None:
            self._load_unresolved_gaps()

    # ------------------------------------------------------------------
    # Premise extraction
    # ------------------------------------------------------------------

    def extract_premises(self, text: str) -> list[str]:
        """
        Extract factual premises from *text*.

        Splits on sentence boundaries: ``". "``, ``"! "``, ``"? "``, or newline.
        Then keeps every sentence that contains at least one of the marker
        phrases. Returns the matched sentences (stripped).
        """
        # Split on ". ", "! ", "? ", or newline to get individual sentences
        sentences = re.split(r"[.!?]\s+|\n", text)
        premises: list[str] = []
        for sentence in sentences:
            stripped = sentence.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            for marker in self.PREMISE_MARKERS:
                if marker in lower:
                    premises.append(stripped)
                    break
        return premises

    # ------------------------------------------------------------------
    # Confidence management
    # ------------------------------------------------------------------

    def update_confidence(self, premise: str, score: float) -> None:
        """Store/update confidence for *premise* (key is lowercased + stripped)."""
        key = premise.lower().strip()
        self._premise_confidence_map[key] = score

    def get_gaps(self) -> list[str]:
        """Return premises whose stored confidence is below ``self.threshold``."""
        return [
            premise
            for premise, score in self._premise_confidence_map.items()
            if score < self.threshold
        ]

    # ------------------------------------------------------------------
    # Sub-query generation
    # ------------------------------------------------------------------

    def generate_sub_query(self, premise: str) -> str:
        """Return a verification sub-query for *premise*."""
        return f"I need to verify: {premise}"

    # ------------------------------------------------------------------
    # Unresolved gap tracking
    # ------------------------------------------------------------------

    def record_unresolved(self, premise: str, confidence: float) -> None:
        """Append *premise* and its *confidence* to the unresolved gaps list and persist if db_path set."""
        ts = time.time()
        gap = {"premise": premise, "confidence": confidence, "timestamp": ts}
        self._unresolved_gaps.append(gap)
        if self._db_path is not None:
            self._persist_gap(premise, confidence, ts)

    # ------------------------------------------------------------------
    # Interrupt budget
    # ------------------------------------------------------------------

    def can_interrupt(self) -> bool:
        """Return ``True`` if the interrupt budget has not been exhausted."""
        return self._interrupt_count < self.max_interrupts

    def consume_interrupt(self) -> None:
        """Consume one unit of the interrupt budget."""
        self._interrupt_count += 1

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def reset_session(self) -> None:
        """Clear all per-session state (confidence map and interrupt count). Unresolved gaps are not cleared."""
        self._premise_confidence_map.clear()
        self._interrupt_count = 0

    def _conn(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.executescript(_GAPS_SCHEMA)
        conn.commit()
        return conn

    def _load_unresolved_gaps(self) -> None:
        """Load persisted unresolved gaps from SQLite."""
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT premise, confidence, timestamp FROM epistemic_unresolved_gaps ORDER BY timestamp"
            ).fetchall()
            conn.close()
            self._unresolved_gaps = [
                {"premise": r[0], "confidence": r[1], "timestamp": r[2]} for r in rows
            ]
        except Exception:
            self._unresolved_gaps = []

    def _persist_gap(self, premise: str, confidence: float, timestamp: float) -> None:
        try:
            conn = self._conn()
            conn.execute(
                "INSERT INTO epistemic_unresolved_gaps (premise, confidence, timestamp, created_at) VALUES (?, ?, ?, ?)",
                (premise, confidence, timestamp, time.time()),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_unresolved_summary(self) -> dict:
        """Return a summary dict of all unresolved gaps."""
        return {
            "total": len(self._unresolved_gaps),
            "gaps": self._unresolved_gaps,
        }
