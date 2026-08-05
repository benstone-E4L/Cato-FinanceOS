"""
cato/memory/decision_memory.py — Outcome-Linked Decision Memory (Unbuilt Skill 2).

Binds decisions to observed outcomes over time. Enables bias analysis — identifying
domains where the agent is overconfident or systematically failing.
Requires ledger_records table (from 2A Causal Action Ledger) for ledger_record_id FK.
Falls back gracefully if ledger is not present.
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
CREATE TABLE IF NOT EXISTS decision_records (
    decision_id                TEXT PRIMARY KEY,
    timestamp                  REAL NOT NULL,
    action_taken               TEXT NOT NULL,
    premises_relied_on         TEXT NOT NULL DEFAULT '[]',
    confidence_at_decision_time REAL NOT NULL DEFAULT 0.5,
    ledger_record_id           TEXT,
    outcome_observation        TEXT,
    outcome_timestamp          REAL,
    outcome_quality_score      REAL,
    outcome_source             TEXT
);
CREATE INDEX IF NOT EXISTS idx_dr_confidence  ON decision_records(confidence_at_decision_time);
CREATE INDEX IF NOT EXISTS idx_dr_outcome     ON decision_records(outcome_quality_score);
CREATE INDEX IF NOT EXISTS idx_dr_timestamp   ON decision_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_dr_conf_out    ON decision_records(confidence_at_decision_time, outcome_quality_score);
"""


@dataclass
class DecisionRecord:
    decision_id: str
    timestamp: float
    action_taken: str
    premises_relied_on: list[str]
    confidence_at_decision_time: float
    ledger_record_id: Optional[str]
    outcome_observation: Optional[str]
    outcome_timestamp: Optional[float]
    outcome_quality_score: Optional[float]
    outcome_source: Optional[str]


class DecisionMemory:
    """
    Records agent decisions and links them to observed outcomes.
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

    def write_decision(
        self,
        action: str,
        premises: list[str],
        confidence: float,
        ledger_record_id: Optional[str] = None,
    ) -> str:
        """Write a decision record. Returns decision_id."""
        decision_id = str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            """INSERT INTO decision_records
               (decision_id, timestamp, action_taken, premises_relied_on,
                confidence_at_decision_time, ledger_record_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (decision_id, now, action, json.dumps(premises), confidence, ledger_record_id),
        )
        self._conn.commit()
        logger.debug("Decision recorded: %s (action=%s, conf=%.2f)", decision_id, action, confidence)
        return decision_id

    def record_outcome(
        self,
        decision_id: str,
        observation: str,
        quality_score: float,
        source: str = "agent",
    ) -> bool:
        """
        Update a decision record with an observed outcome.
        quality_score: -1.0 (failed) to 1.0 (fully successful).
        Returns True if updated.
        """
        cur = self._conn.execute(
            """UPDATE decision_records
               SET outcome_observation = ?,
                   outcome_timestamp = ?,
                   outcome_quality_score = ?,
                   outcome_source = ?
               WHERE decision_id = ?""",
            (observation, time.time(), quality_score, source, decision_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get(self, decision_id: str) -> Optional[DecisionRecord]:
        row = self._conn.execute(
            "SELECT * FROM decision_records WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_overconfidence_profile(self) -> dict:
        """Returns domains where confidence > 0.8 AND outcome < 0.0."""
        rows = self._conn.execute(
            """SELECT action_taken, AVG(confidence_at_decision_time) as avg_conf,
                      AVG(outcome_quality_score) as avg_outcome, COUNT(*) as n
               FROM decision_records
               WHERE confidence_at_decision_time > 0.8
                 AND outcome_quality_score < 0.0
                 AND outcome_quality_score IS NOT NULL
               GROUP BY action_taken
               ORDER BY avg_conf DESC"""
        ).fetchall()
        return {
            r["action_taken"]: {"avg_conf": r["avg_conf"], "avg_outcome": r["avg_outcome"], "n": r["n"]}
            for r in rows
        }

    def get_reliable_patterns(self) -> list[dict]:
        """Action types with avg outcome > 0.7 across 10+ decisions."""
        rows = self._conn.execute(
            """SELECT action_taken, AVG(outcome_quality_score) as avg_outcome, COUNT(*) as n
               FROM decision_records
               WHERE outcome_quality_score IS NOT NULL
               GROUP BY action_taken
               HAVING avg_outcome > 0.7 AND n >= 10
               ORDER BY avg_outcome DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_systematic_failures(self) -> list[dict]:
        """Action types with avg outcome < 0.0 across 5+ decisions."""
        rows = self._conn.execute(
            """SELECT action_taken, AVG(outcome_quality_score) as avg_outcome, COUNT(*) as n
               FROM decision_records
               WHERE outcome_quality_score IS NOT NULL
               GROUP BY action_taken
               HAVING avg_outcome < 0.0 AND n >= 5
               ORDER BY avg_outcome ASC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def list_open(self) -> list[DecisionRecord]:
        """Return decisions with no outcome yet."""
        rows = self._conn.execute(
            "SELECT * FROM decision_records WHERE outcome_quality_score IS NULL ORDER BY timestamp"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def _row_to_record(self, row: sqlite3.Row) -> DecisionRecord:
        d = dict(row)
        d["premises_relied_on"] = json.loads(d["premises_relied_on"])
        return DecisionRecord(**d)

    def close(self) -> None:
        self._conn.close()
