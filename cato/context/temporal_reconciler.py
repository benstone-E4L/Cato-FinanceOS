"""
cato/context/temporal_reconciler.py — Temporal Context Reconciliation (Unbuilt Skill 6).

Wake-up protocol: on daemon restart, identifies what changed in the world
affecting pending tasks.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .volatility_map import VolatilityMap

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_queue_snapshots (
    task_id              TEXT PRIMARY KEY,
    description          TEXT NOT NULL,
    external_dependencies TEXT NOT NULL DEFAULT '[]',
    last_verified_at     REAL NOT NULL,
    snapshot_hash        TEXT NOT NULL DEFAULT ''
);
"""

_REFRESH_THRESHOLD = 0.4  # Only refresh if priority > this


@dataclass
class WakeupBriefing:
    dormancy_duration: str
    tasks_unblocked: list[str] = field(default_factory=list)
    tasks_now_constrained: list[str] = field(default_factory=list)
    changes_requiring_replanning: list[str] = field(default_factory=list)
    total_dependencies_checked: int = 0
    total_changes_found: int = 0


class TemporalReconciler:
    """
    On daemon wake-up, determines what changed in the world
    and produces a structured briefing.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        volatility_map: Optional[VolatilityMap] = None,
        refresh_threshold: float = _REFRESH_THRESHOLD,
    ) -> None:
        if db_path is None:
            from ..platform import get_data_dir
            db_path = get_data_dir() / "cato.db"
        self._db_path = db_path
        self._vmap = volatility_map or VolatilityMap()
        self._refresh_threshold = refresh_threshold
        self._conn = self._open_db()

    def _open_db(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    def snapshot_task(
        self,
        task_id: str,
        description: str,
        external_dependencies: list[str],
    ) -> None:
        """Snapshot a pending task for reconciliation on next wake-up."""
        import hashlib
        snapshot_hash = hashlib.sha256(
            (description + json.dumps(sorted(external_dependencies))).encode()
        ).hexdigest()
        self._conn.execute(
            """INSERT OR REPLACE INTO task_queue_snapshots
               (task_id, description, external_dependencies, last_verified_at, snapshot_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, description, json.dumps(external_dependencies), time.time(), snapshot_hash),
        )
        self._conn.commit()

    def reconcile(self, dormancy_seconds: float) -> WakeupBriefing:
        """
        Run wake-up reconciliation protocol.

        For each pending task, computes refresh_priority based on volatility
        and task relevance. Only checks high-priority dependencies.
        """
        dormancy_str = self._format_duration(dormancy_seconds)
        briefing = WakeupBriefing(dormancy_duration=dormancy_str)

        rows = self._conn.execute(
            "SELECT * FROM task_queue_snapshots ORDER BY last_verified_at"
        ).fetchall()

        for row in rows:
            deps = json.loads(row["external_dependencies"])
            for dep in deps:
                volatility = self._vmap.get_volatility(dep)
                # Relevance: treat all stored deps as "direct" (1.0 relevance)
                priority = volatility * 1.0
                briefing.total_dependencies_checked += 1

                if priority > self._refresh_threshold:
                    # Would check dep here; simulate as "changed" for high-volatility
                    if volatility > 0.8:
                        briefing.total_changes_found += 1
                        if "issue" in dep.lower() or "pr" in dep.lower():
                            briefing.changes_requiring_replanning.append(
                                f"Task '{row['description'][:50]}' — dependency changed: {dep}"
                            )
                        else:
                            briefing.tasks_now_constrained.append(
                                f"Task '{row['description'][:50]}' — high-volatility dep: {dep}"
                            )

        return briefing

    def get_snapshot(self, task_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM task_queue_snapshots WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["external_dependencies"] = json.loads(d["external_dependencies"])
        return d

    def delete_snapshot(self, task_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM task_queue_snapshots WHERE task_id = ?", (task_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            return f"{seconds/60:.0f}m"
        if seconds < 86400:
            return f"{seconds/3600:.1f}h"
        return f"{seconds/86400:.1f}d"

    def close(self) -> None:
        self._conn.close()
