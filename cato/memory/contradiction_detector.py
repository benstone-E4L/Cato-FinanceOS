"""
cato/memory/contradiction_detector.py — ContradictionDetector (Skill 7).

Hooks into the memory write path to detect semantic contradictions between
new facts and existing memory, logging them for resolution.

Contradiction types: TEMPORAL, SOURCE, PREFERENCE, FACTUAL
Similarity: word-level Jaccard (no external deps)
Storage: SQLite with WAL mode
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_contradictions (
    contradiction_id   TEXT PRIMARY KEY,
    fact_a_text        TEXT NOT NULL,
    fact_b_text        TEXT NOT NULL,
    entity             TEXT NOT NULL DEFAULT '',
    contradiction_type TEXT NOT NULL,
    explanation        TEXT NOT NULL DEFAULT '',
    detected_at        REAL NOT NULL,
    resolved           INTEGER NOT NULL DEFAULT 0,
    resolution         TEXT
);
CREATE INDEX IF NOT EXISTS idx_mc_resolved ON memory_contradictions(resolved);
CREATE INDEX IF NOT EXISTS idx_mc_entity   ON memory_contradictions(entity);
CREATE INDEX IF NOT EXISTS idx_mc_type     ON memory_contradictions(contradiction_type);
"""

# ---------------------------------------------------------------------------
# Keyword sets for classify_contradiction
# ---------------------------------------------------------------------------

_TEMPORAL_KEYWORDS = {
    "2020", "2021", "2022", "2023", "2024",
    "yesterday", "last year", "this year",
    "previously", "now", "currently", "before", "after",
}

_SOURCE_KEYWORDS = {
    "according to", "study shows", "research says",
    "report states", "source:", "citation", "per ", "as of",
}

_PREFERENCE_KEYWORDS = {
    "prefer", "want", "like", "don't like", "dislike",
    "love", "hate", "enjoy", "avoid",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jaccard_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a and not tokens_b:
        return 1.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


def _contains_keyword(text: str, keywords: set) -> bool:
    """Return True if any keyword is found in the lowercased text."""
    lower = text.lower()
    return any(kw in lower for kw in keywords)


# ---------------------------------------------------------------------------
# ContradictionDetector
# ---------------------------------------------------------------------------

class ContradictionDetector:
    """Detects and logs semantic contradictions between memory facts."""

    SAME_TOPIC_THRESHOLD = 0.35  # Jaccard similarity above this → same topic

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".cato" / "contradictions.db"
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Core detection
    # ------------------------------------------------------------------

    def check_and_log(
        self,
        new_fact: str,
        existing_facts: list[str],
        entity: str = "",
    ) -> list[str]:
        """
        Compare new_fact against each existing_fact.
        For pairs with Jaccard >= SAME_TOPIC_THRESHOLD, classify contradiction.
        If contradicted (type != "NONE") and not already detected, log to DB.
        Returns list of contradiction_ids for newly logged contradictions.
        """
        ids: list[str] = []
        for existing in existing_facts:
            sim = _jaccard_similarity(new_fact, existing)
            if sim < self.SAME_TOPIC_THRESHOLD:
                continue
            c_type = self.classify_contradiction(new_fact, existing)
            if c_type == "NONE":
                continue
            if self.already_detected(new_fact, existing):
                continue
            explanation = self.generate_explanation(new_fact, existing, c_type)
            cid = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO memory_contradictions
                    (contradiction_id, fact_a_text, fact_b_text, entity,
                     contradiction_type, explanation, detected_at, resolved, resolution)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL)
                """,
                (cid, new_fact, existing, entity, c_type, explanation, time.time()),
            )
            self._conn.commit()
            ids.append(cid)
        return ids

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify_contradiction(self, fact_a: str, fact_b: str) -> str:
        """
        Keyword-based classification returning one of:
        TEMPORAL, SOURCE, PREFERENCE, FACTUAL, NONE
        """
        sim = _jaccard_similarity(fact_a, fact_b)
        if sim < self.SAME_TOPIC_THRESHOLD:
            return "NONE"

        combined = fact_a + " " + fact_b

        # TEMPORAL: temporal keywords present in the combined text
        if _contains_keyword(combined, _TEMPORAL_KEYWORDS):
            return "TEMPORAL"

        # SOURCE: source-attribution keywords
        if _contains_keyword(combined, _SOURCE_KEYWORDS):
            return "SOURCE"

        # PREFERENCE: preference keywords
        if _contains_keyword(combined, _PREFERENCE_KEYWORDS):
            return "PREFERENCE"

        # FACTUAL: same topic, no special keywords
        return "FACTUAL"

    # ------------------------------------------------------------------
    # Explanation
    # ------------------------------------------------------------------

    def generate_explanation(self, fact_a: str, fact_b: str, contradiction_type: str) -> str:
        """Return a human-readable explanation string."""
        return f"{contradiction_type} contradiction: '{fact_a[:80]}' vs '{fact_b[:80]}'"

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_unresolved(self, entity: str = "") -> list[dict]:
        """Return unresolved contradictions, optionally filtered by entity."""
        if entity:
            rows = self._conn.execute(
                "SELECT * FROM memory_contradictions WHERE resolved=0 AND entity=?",
                (entity,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memory_contradictions WHERE resolved=0"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_by_type(self, contradiction_type: str) -> list[dict]:
        """Return all contradictions of a given type."""
        rows = self._conn.execute(
            "SELECT * FROM memory_contradictions WHERE contradiction_type=?",
            (contradiction_type,),
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve(self, contradiction_id: str, resolution: str) -> bool:
        """Mark a contradiction as resolved. Return True if a row was updated."""
        cur = self._conn.execute(
            "UPDATE memory_contradictions SET resolved=1, resolution=? WHERE contradiction_id=?",
            (resolution, contradiction_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_unresolved_count(self) -> int:
        """Return count of unresolved contradictions."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM memory_contradictions WHERE resolved=0"
        ).fetchone()
        return row[0]

    def get_health_summary(self) -> dict:
        """
        Return a health summary dict with keys:
            total, unresolved, by_type, most_contradicted_entities
        """
        total = self._conn.execute(
            "SELECT COUNT(*) FROM memory_contradictions"
        ).fetchone()[0]

        unresolved = self.get_unresolved_count()

        by_type: dict[str, int] = {"TEMPORAL": 0, "SOURCE": 0, "PREFERENCE": 0, "FACTUAL": 0}
        for row in self._conn.execute(
            "SELECT contradiction_type, COUNT(*) as cnt FROM memory_contradictions GROUP BY contradiction_type"
        ).fetchall():
            t = row[0]
            if t in by_type:
                by_type[t] = row[1]

        entity_rows = self._conn.execute(
            """
            SELECT entity, COUNT(*) as cnt
            FROM memory_contradictions
            WHERE entity != ''
            GROUP BY entity
            ORDER BY cnt DESC
            LIMIT 3
            """
        ).fetchall()
        most_contradicted_entities = [r[0] for r in entity_rows]

        return {
            "total": total,
            "unresolved": unresolved,
            "by_type": by_type,
            "most_contradicted_entities": most_contradicted_entities,
        }

    def already_detected(self, fact_a: str, fact_b: str) -> bool:
        """
        Return True if this pair (in either order) already exists in the DB.
        """
        row = self._conn.execute(
            """
            SELECT 1 FROM memory_contradictions
            WHERE (fact_a_text=? AND fact_b_text=?)
               OR (fact_a_text=? AND fact_b_text=?)
            LIMIT 1
            """,
            (fact_a, fact_b, fact_b, fact_a),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()


# ---------------------------------------------------------------------------
# HOT section ends here — COLD marker below
# ---------------------------------------------------------------------------

# <!-- COLD -->
# ContradictionDetector — extended notes
#
# Contradiction types and detection logic
# ----------------------------------------
# TEMPORAL  — triggered when either fact contains year literals (2020-2024) or
#             temporal adverbs: yesterday, last year, this year, previously, now,
#             currently, before, after.
#
# SOURCE    — triggered by attribution phrases: "according to", "study shows",
#             "research says", "report states", "source:", "citation", "per ",
#             "as of".
#
# PREFERENCE — triggered by hedonic/volitional words: prefer, want, like,
#              don't like, dislike, love, hate, enjoy, avoid.
#
# FACTUAL   — catch-all when Jaccard >= SAME_TOPIC_THRESHOLD but no above
#             keywords match. Indicates a direct factual discrepancy.
#
# NONE      — returned by classify_contradiction when Jaccard < threshold;
#             check_and_log guards against this before calling classify.
#
# Duplicate prevention
# --------------------
# already_detected() checks both (A,B) and (B,A) orderings so that the same
# logical pair is never double-counted regardless of which fact is "new".
#
# WAL mode
# --------
# PRAGMA journal_mode=WAL is set on every connection open. WAL gives
# concurrent read access and reduces write contention.
#
# No external dependencies
# ------------------------
# Only stdlib: sqlite3, uuid, time, pathlib, typing.
