from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from .models import EmpireRun


_SCHEMA = """
CREATE TABLE IF NOT EXISTS empire_runs (
    run_id         TEXT PRIMARY KEY,
    business_slug  TEXT NOT NULL,
    idea           TEXT NOT NULL,
    business_dir   TEXT NOT NULL,
    status         TEXT NOT NULL,
    current_phase  INTEGER NOT NULL DEFAULT 0,
    metadata_json  TEXT NOT NULL DEFAULT '{}',
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_empire_runs_slug ON empire_runs(business_slug);

CREATE TABLE IF NOT EXISTS empire_tasks (
    task_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    business_slug   TEXT NOT NULL,
    phase           INTEGER NOT NULL,
    worker          TEXT NOT NULL,
    status          TEXT NOT NULL,
    prompt_file     TEXT,
    workdir         TEXT,
    note            TEXT NOT NULL DEFAULT '',
    result_json     TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_empire_tasks_run ON empire_tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_empire_tasks_status ON empire_tasks(status);
"""

# Migrations applied once to existing databases (idempotent — ALTER TABLE is
# skipped automatically when the column already exists due to the try/except).
_SCHEMA_MIGRATIONS: list[str] = [
    "ALTER TABLE empire_runs ADD COLUMN checkpoint_json TEXT",
    "ALTER TABLE empire_runs ADD COLUMN genesis_phase_map TEXT",
]


class PipelineStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._apply_migrations()

    def _apply_migrations(self) -> None:
        """Apply _SCHEMA_MIGRATIONS once; ignore OperationalError if column exists."""
        for ddl in _SCHEMA_MIGRATIONS:
            try:
                self._conn.execute(ddl)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists

    def write_phase_checkpoint(
        self,
        run_id: str,
        phase: int,
        payload: dict[str, Any],
        *,
        checkpoint_dir: Optional[Path] = None,
    ) -> None:
        """Persist a phase checkpoint to both the DB column and a JSON file.

        The DB column ``checkpoint_json`` stores a dict keyed by phase number
        (as string) so multiple phases can accumulate without overwriting each
        other.  If *checkpoint_dir* is supplied the checkpoint is also written
        to ``<checkpoint_dir>/phase-<phase>.json``.
        """
        row = self._conn.execute(
            "SELECT checkpoint_json FROM empire_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)

        existing: dict[str, Any] = {}
        raw = row["checkpoint_json"]
        if raw:
            try:
                existing = json.loads(raw)
            except json.JSONDecodeError:
                existing = {}

        existing[str(phase)] = payload
        self._conn.execute(
            "UPDATE empire_runs SET checkpoint_json = ?, updated_at = ? WHERE run_id = ?",
            (json.dumps(existing), time.time(), run_id),
        )
        self._conn.commit()

        if checkpoint_dir is not None:
            checkpoint_dir = Path(checkpoint_dir)
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            (checkpoint_dir / f"phase-{phase}.json").write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )

    def get_phase_checkpoint(self, run_id: str, phase: int) -> Optional[dict[str, Any]]:
        """Return the stored checkpoint for *phase*, or None if absent."""
        row = self._conn.execute(
            "SELECT checkpoint_json FROM empire_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None or not row["checkpoint_json"]:
            return None
        try:
            data = json.loads(row["checkpoint_json"])
            return data.get(str(phase))
        except json.JSONDecodeError:
            return None

    def create_run(
        self,
        run_id: str,
        business_slug: str,
        idea: str,
        business_dir: Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> EmpireRun:
        now = time.time()
        payload = json.dumps(metadata or {})
        self._conn.execute(
            "INSERT OR REPLACE INTO empire_runs "
            "(run_id, business_slug, idea, business_dir, status, current_phase, metadata_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'CREATED', 0, ?, ?, ?)",
            (run_id, business_slug, idea, str(business_dir), payload, now, now),
        )
        self._conn.commit()
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> EmpireRun:
        row = self._conn.execute(
            "SELECT * FROM empire_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return EmpireRun(
            run_id=row["run_id"],
            business_slug=row["business_slug"],
            idea=row["idea"],
            business_dir=Path(row["business_dir"]),
            status=row["status"],
            current_phase=row["current_phase"],
            metadata=json.loads(row["metadata_json"]),
        )

    def get_run_by_slug(self, business_slug: str) -> Optional[EmpireRun]:
        row = self._conn.execute(
            "SELECT * FROM empire_runs WHERE business_slug = ? ORDER BY created_at DESC LIMIT 1",
            (business_slug,),
        ).fetchone()
        if row is None:
            return None
        return EmpireRun(
            run_id=row["run_id"],
            business_slug=row["business_slug"],
            idea=row["idea"],
            business_dir=Path(row["business_dir"]),
            status=row["status"],
            current_phase=row["current_phase"],
            metadata=json.loads(row["metadata_json"]),
        )

    def list_runs(self) -> list[EmpireRun]:
        rows = self._conn.execute(
            "SELECT * FROM empire_runs ORDER BY updated_at DESC"
        ).fetchall()
        return [
            EmpireRun(
                run_id=row["run_id"],
                business_slug=row["business_slug"],
                idea=row["idea"],
                business_dir=Path(row["business_dir"]),
                status=row["status"],
                current_phase=row["current_phase"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def update_run_status(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        current_phase: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        run = self.get_run(run_id)
        self._conn.execute(
            "UPDATE empire_runs SET status = ?, current_phase = ?, metadata_json = ?, updated_at = ? WHERE run_id = ?",
            (
                status or run.status,
                current_phase if current_phase is not None else run.current_phase,
                json.dumps(metadata if metadata is not None else run.metadata),
                time.time(),
                run_id,
            ),
        )
        self._conn.commit()

    def add_task(
        self,
        *,
        task_id: str,
        run_id: str,
        business_slug: str,
        phase: int,
        worker: str,
        prompt_file: Optional[Path],
        workdir: Optional[Path],
        note: str = "",
    ) -> None:
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO empire_tasks "
            "(task_id, run_id, business_slug, phase, worker, status, prompt_file, workdir, note, result_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, '{}', ?, ?)",
            (
                task_id,
                run_id,
                business_slug,
                phase,
                worker,
                str(prompt_file) if prompt_file else None,
                str(workdir) if workdir else None,
                note,
                now,
                now,
            ),
        )
        self._conn.commit()

    def update_task(
        self,
        task_id: str,
        *,
        status: str,
        note: str = "",
        result: Optional[dict[str, Any]] = None,
    ) -> None:
        self._conn.execute(
            "UPDATE empire_tasks SET status = ?, note = ?, result_json = ?, updated_at = ? WHERE task_id = ?",
            (status, note, json.dumps(result or {}), time.time(), task_id),
        )
        self._conn.commit()

    def list_tasks(self, run_id: Optional[str] = None) -> list[dict[str, Any]]:
        if run_id:
            rows = self._conn.execute(
                "SELECT * FROM empire_tasks WHERE run_id = ? ORDER BY created_at DESC",
                (run_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM empire_tasks ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]
