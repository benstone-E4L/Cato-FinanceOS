"""
cato/core/session_checkpoint.py — Context-Anchor Session Checkpoint (Skill 8).

Monitors cumulative token usage across agent turns.  When the running total
crosses a configurable threshold (default 80% of the model context window)
a compressed checkpoint is written atomically to SQLite and injected as a
system message on the next turn so the agent can continue without context loss.

SQLite table ``session_checkpoints`` lives in the shared cato.db database.
Checkpoint writes use asyncio.shield so they never block the WebSocket stream.

Usage::

    ckpt = SessionCheckpoint()
    ckpt.connect()

    # After each agent turn:
    await ckpt.maybe_checkpoint(
        session_id="sess-abc",
        task_description="refactor gateway.py",
        decisions_made=["use asyncio.shield", "flatten LaneQueue"],
        files_modified=["cato/gateway.py"],
        current_plan="Step 3 of 5 — write tests",
        key_facts={"model": "claude-sonnet-4-6", "turns": 4},
        new_tokens=1200,
        context_limit=8192,
        threshold=0.80,
    )

    # On session resume:
    summary = ckpt.get_summary(session_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_checkpoints (
    session_id        TEXT    PRIMARY KEY,
    task_description  TEXT    NOT NULL DEFAULT '',
    decisions_made    TEXT    NOT NULL DEFAULT '[]',
    files_modified    TEXT    NOT NULL DEFAULT '[]',
    current_plan      TEXT    NOT NULL DEFAULT '',
    key_facts         TEXT    NOT NULL DEFAULT '{}',
    checkpoint_at     TEXT    NOT NULL,
    token_count       INTEGER NOT NULL DEFAULT 0
);
"""

# Approximate tokens in the compressed summary injected on resume
_SUMMARY_MAX_TOKENS = 1000

# Characters-per-token approximation (matches agent_loop.py)
_CHARS_PER_TOKEN = 4


# ---------------------------------------------------------------------------
# SessionCheckpoint
# ---------------------------------------------------------------------------

class SessionCheckpoint:
    """
    Atomic, token-aware session checkpointing backed by SQLite.

    Thread-safe for single-writer use (one asyncio event loop).
    All writes happen inside a single SQLite transaction via REPLACE INTO.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            from ..platform import get_data_dir
            db_path = get_data_dir() / "cato.db"
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # Per-session cumulative token counter (in-memory, reset on new session)
        self._token_totals: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        """Open (or create) the database and apply the checkpoint schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.debug("SessionCheckpoint connected to %s", self._db_path)

    def _ensure_connected(self) -> None:
        if self._conn is None:
            self.connect()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "SessionCheckpoint":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Token tracking                                                     #
    # ------------------------------------------------------------------ #

    def add_tokens(self, session_id: str, token_count: int) -> int:
        """
        Accumulate *token_count* for *session_id*.

        Returns the new cumulative total.
        """
        total = self._token_totals.get(session_id, 0) + token_count
        self._token_totals[session_id] = total
        return total

    def reset_tokens(self, session_id: str) -> None:
        """Reset the in-memory token counter for *session_id* (e.g. after checkpoint)."""
        self._token_totals[session_id] = 0

    def current_tokens(self, session_id: str) -> int:
        """Return the current cumulative token total for *session_id*."""
        return self._token_totals.get(session_id, 0)

    # ------------------------------------------------------------------ #
    # Core checkpoint logic                                               #
    # ------------------------------------------------------------------ #

    def _should_checkpoint(
        self, session_id: str, context_limit: int, threshold: float
    ) -> bool:
        """Return True when cumulative tokens exceed threshold * context_limit."""
        total = self._token_totals.get(session_id, 0)
        limit_tokens = int(context_limit * threshold)
        return total >= limit_tokens

    def write(
        self,
        session_id: str,
        task_description: str,
        decisions_made: list[str],
        files_modified: list[str],
        current_plan: str,
        key_facts: dict[str, Any],
        token_count: int,
    ) -> None:
        """
        Write or overwrite the checkpoint row for *session_id*.

        Uses REPLACE INTO (upsert) inside a single transaction — atomic.
        """
        self._ensure_connected()
        assert self._conn is not None

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        with self._conn:
            self._conn.execute(
                """
                REPLACE INTO session_checkpoints
                  (session_id, task_description, decisions_made,
                   files_modified, current_plan, key_facts,
                   checkpoint_at, token_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_description,
                    json.dumps(decisions_made, ensure_ascii=True),
                    json.dumps(files_modified, ensure_ascii=True),
                    current_plan,
                    json.dumps(key_facts, ensure_ascii=True),
                    now,
                    token_count,
                ),
            )
        logger.info(
            "Checkpoint written: session=%s tokens=%d plan=%r",
            session_id, token_count, current_plan[:60],
        )

    async def async_write(
        self,
        session_id: str,
        task_description: str,
        decisions_made: list[str],
        files_modified: list[str],
        current_plan: str,
        key_facts: dict[str, Any],
        token_count: int,
    ) -> None:
        """
        Async wrapper for write().

        Uses asyncio.shield so the write is protected from cancellation
        and never blocks the WebSocket stream.
        """
        loop = asyncio.get_running_loop()
        await asyncio.shield(
            loop.run_in_executor(
                None,
                self.write,
                session_id,
                task_description,
                decisions_made,
                files_modified,
                current_plan,
                key_facts,
                token_count,
            )
        )

    async def maybe_checkpoint(
        self,
        session_id: str,
        task_description: str,
        decisions_made: list[str],
        files_modified: list[str],
        current_plan: str,
        key_facts: dict[str, Any],
        new_tokens: int,
        context_limit: int = 8192,
        threshold: float = 0.80,
        audit_log: Any = None,
    ) -> bool:
        """
        Accumulate *new_tokens* and checkpoint if the threshold is crossed.

        Called BETWEEN turns only — never mid-stream.
        Returns True if a checkpoint was written.
        """
        self.add_tokens(session_id, new_tokens)

        if not self._should_checkpoint(session_id, context_limit, threshold):
            return False

        total = self._token_totals.get(session_id, 0)
        logger.info(
            "Context threshold reached (%d/%d tokens) — checkpointing session %s",
            total, context_limit, session_id,
        )

        await self.async_write(
            session_id=session_id,
            task_description=task_description,
            decisions_made=decisions_made,
            files_modified=files_modified,
            current_plan=current_plan,
            key_facts=key_facts,
            token_count=total,
        )

        # Audit
        if audit_log is not None:
            try:
                audit_log.log(
                    session_id=session_id,
                    action_type="context_anchor",
                    tool_name="session_checkpoint",
                    inputs={"threshold": threshold, "context_limit": context_limit},
                    outputs={"token_count": total, "checkpoint_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                )
            except Exception as exc:
                logger.warning("Audit log failed for checkpoint %s: %s", session_id, exc)

        # Reset counter after checkpoint
        self.reset_tokens(session_id)
        return True

    # ------------------------------------------------------------------ #
    # Resume / query                                                      #
    # ------------------------------------------------------------------ #

    def get(self, session_id: str) -> Optional[dict]:
        """Return the checkpoint dict for *session_id*, or None if not found."""
        self._ensure_connected()
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM session_checkpoints WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["decisions_made"] = json.loads(d.get("decisions_made", "[]"))
        d["files_modified"] = json.loads(d.get("files_modified", "[]"))
        d["key_facts"] = json.loads(d.get("key_facts", "{}"))
        return d

    def get_summary(self, session_id: str) -> str:
        """
        Return a compressed ≤1000-token text summary for injection on session resume.

        Truncates decisions/files lists and key_facts to stay within budget.
        """
        data = self.get(session_id)
        if data is None:
            return ""

        decisions = data.get("decisions_made", [])[:10]
        files = data.get("files_modified", [])[:20]
        facts = data.get("key_facts", {})

        lines = [
            f"=== SESSION CHECKPOINT (resumed at {data['checkpoint_at']}) ===",
            f"Task: {data['task_description']}",
            f"Plan: {data['current_plan']}",
        ]
        if decisions:
            lines.append("Decisions made:")
            lines.extend(f"  - {d}" for d in decisions)
        if files:
            lines.append(f"Files modified: {', '.join(files)}")
        if facts:
            lines.append(f"Key facts: {json.dumps(facts, ensure_ascii=True)}")
        lines.append("=== END CHECKPOINT ===")

        summary = "\n".join(lines)
        # Truncate to _SUMMARY_MAX_TOKENS characters-equivalent
        max_chars = _SUMMARY_MAX_TOKENS * _CHARS_PER_TOKEN
        if len(summary) > max_chars:
            summary = summary[:max_chars] + "\n... [truncated]"
        return summary

    def list_all(self) -> list[dict]:
        """Return all checkpoint rows as plain dicts, ordered by checkpoint_at DESC."""
        self._ensure_connected()
        assert self._conn is not None
        rows = self._conn.execute(
            """
            SELECT session_id, task_description, checkpoint_at, token_count
            FROM session_checkpoints
            ORDER BY checkpoint_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, session_id: str) -> bool:
        """Delete the checkpoint for *session_id*.  Returns True if deleted."""
        self._ensure_connected()
        assert self._conn is not None
        cur = self._conn.execute(
            "DELETE FROM session_checkpoints WHERE session_id = ?",
            (session_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0
