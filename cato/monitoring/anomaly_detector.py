"""
cato/monitoring/anomaly_detector.py — Anticipatory Signal Monitor (Unbuilt Skill 4).

Multi-stream weak-signal monitoring with anomaly detection, cross-source correlation,
and self-calibrating false-positive suppression.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interest_domains (
    domain_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    signal_sources TEXT NOT NULL DEFAULT '[]',
    created_at   REAL NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS signal_baselines (
    domain_id       TEXT NOT NULL,
    snapshot_date   TEXT NOT NULL,
    avg_daily_volume REAL NOT NULL DEFAULT 0.0,
    semantic_centroid TEXT NOT NULL DEFAULT '[]',
    source_diversity  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (domain_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS signal_predictions (
    prediction_id        TEXT PRIMARY KEY,
    domain_id            TEXT NOT NULL,
    signal_summary       TEXT NOT NULL,
    predicted_at         REAL NOT NULL,
    predicted_development TEXT NOT NULL,
    confidence_at_prediction REAL NOT NULL DEFAULT 0.5,
    verified             INTEGER,
    verified_at          REAL,
    lead_time_actual     REAL
);
CREATE INDEX IF NOT EXISTS idx_sp_domain ON signal_predictions(domain_id);
CREATE INDEX IF NOT EXISTS idx_sp_verified ON signal_predictions(verified);
"""

# Default anomaly thresholds by task type
_THRESHOLDS: dict[str, float] = {
    "code":     0.30,
    "research": 0.40,
    "decision": 0.25,
    "default":  0.35,
}


@dataclass
class Alert:
    domain: str
    signals_fired: list[str]
    pattern_match: str
    cross_source_count: int
    estimated_lead_time: str
    calibrated_confidence: float
    suggested_action: str


@dataclass
class Domain:
    domain_id: str
    name: str
    description: str
    signal_sources: list[dict]
    created_at: float
    active: bool


class AnomalyDetector:
    """
    Monitors interest domains for weak signals and anomalies.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            from ..platform import get_data_dir
            db_path = get_data_dir() / "cato.db"
        self._db_path = db_path
        self._conn = self._open_db()

    def _open_db(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    # ------------------------------------------------------------------
    # Domain management
    # ------------------------------------------------------------------

    def add_domain(
        self,
        name: str,
        description: str = "",
        signal_sources: list[dict] | None = None,
    ) -> str:
        domain_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO interest_domains
               (domain_id, name, description, signal_sources, created_at, active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (domain_id, name, description, json.dumps(signal_sources or []), time.time()),
        )
        self._conn.commit()
        return domain_id

    def list_domains(self, active_only: bool = True) -> list[Domain]:
        query = "SELECT * FROM interest_domains"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY created_at"
        rows = self._conn.execute(query).fetchall()
        return [self._row_to_domain(r) for r in rows]

    def deactivate_domain(self, domain_id: str) -> bool:
        cur = self._conn.execute(
            "UPDATE interest_domains SET active = 0 WHERE domain_id = ?", (domain_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_domain(self, domain_id: str) -> Optional[Domain]:
        row = self._conn.execute(
            "SELECT * FROM interest_domains WHERE domain_id = ?", (domain_id,)
        ).fetchone()
        return self._row_to_domain(row) if row else None

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    def compute_disagreement_score(
        self,
        current_volume: float,
        baseline_volume: float,
        current_centroid_distance: float = 0.0,
        task_type: str = "default",
    ) -> float:
        """
        Compute anomaly score comparing current signal batch to baseline.

        volume_ratio: how much above baseline is current volume
        semantic_distance: how far current centroid is from baseline
        Combined score normalized 0.0-1.0.
        """
        if baseline_volume <= 0:
            return 0.0

        volume_ratio = current_volume / baseline_volume
        # Volume anomaly: score based on how much above 2x threshold
        volume_score = min(1.0, max(0.0, (volume_ratio - 1.0) / 3.0))

        # Semantic drift score (already normalized 0-1 as cosine distance)
        semantic_score = min(1.0, current_centroid_distance)

        combined = 0.6 * volume_score + 0.4 * semantic_score
        return round(min(1.0, combined), 4)

    def is_anomaly(
        self,
        score: float,
        task_type: str = "default",
        cross_source_count: int = 1,
    ) -> bool:
        """
        Return True only when score exceeds threshold AND cross-source correlation >= 2.
        """
        threshold = _THRESHOLDS.get(task_type, _THRESHOLDS["default"])
        return score > threshold and cross_source_count >= 2

    def classify_disagreement_heuristic(self, text_a: str, text_b: str) -> str:
        """
        Classify the nature of disagreement between two signal texts using keyword heuristics only.

        This is a lightweight, deterministic classifier: it looks for specific
        keywords (e.g. "risk", "prefer", "instead") and returns a category.
        No embeddings or ML; use for fast filtering. For calibration or
        embedding-backed classification, use a separate pipeline.

        Returns: FACTUAL | APPROACH | RISK_ASSESSMENT | VALUE_JUDGMENT
        """
        combined = (text_a + " " + text_b).lower()
        if any(w in combined for w in ["dangerous", "safe", "risk", "unlikely", "threat"]):
            return "RISK_ASSESSMENT"
        if any(w in combined for w in ["more important", "prefer", "recommend", "should"]):
            return "VALUE_JUDGMENT"
        if any(w in combined for w in ["instead", "alternatively", "better to", "approach"]):
            return "APPROACH"
        return "FACTUAL"

    def classify_disagreement(self, text_a: str, text_b: str) -> str:
        """Alias for classify_disagreement_heuristic for backward compatibility."""
        return self.classify_disagreement_heuristic(text_a, text_b)

    # ------------------------------------------------------------------
    # Predictions
    # ------------------------------------------------------------------

    def record_prediction(
        self,
        domain_id: str,
        signal_summary: str,
        predicted_development: str,
        confidence: float = 0.5,
    ) -> str:
        pred_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO signal_predictions
               (prediction_id, domain_id, signal_summary, predicted_at,
                predicted_development, confidence_at_prediction)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pred_id, domain_id, signal_summary, time.time(), predicted_development, confidence),
        )
        self._conn.commit()
        return pred_id

    def verify_prediction(self, prediction_id: str, lead_time_actual: Optional[float] = None) -> bool:
        cur = self._conn.execute(
            """UPDATE signal_predictions
               SET verified = 1, verified_at = ?, lead_time_actual = ?
               WHERE prediction_id = ?""",
            (time.time(), lead_time_actual, prediction_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_calibration_score(self, domain_id: str) -> Optional[float]:
        """Return verified_count / total_predictions. None if < 20 predictions."""
        row = self._conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN verified = 1 THEN 1 ELSE 0 END) as verified_count
               FROM signal_predictions WHERE domain_id = ?""",
            (domain_id,),
        ).fetchone()
        total = row["total"]
        if total < 20:
            return None
        return row["verified_count"] / total

    def _row_to_domain(self, row: sqlite3.Row) -> Domain:
        d = dict(row)
        d["signal_sources"] = json.loads(d["signal_sources"])
        d["active"] = bool(d["active"])
        return Domain(**d)

    def close(self) -> None:
        self._conn.close()
