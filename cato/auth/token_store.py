"""
cato/auth/token_store.py — Delegation Token storage (part of Unbuilt Skill 5).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS delegation_tokens (
    token_id                     TEXT PRIMARY KEY,
    created_at                   TEXT NOT NULL,
    expires_at                   TEXT NOT NULL,
    allowed_action_categories    TEXT NOT NULL DEFAULT '[]',
    parameter_constraints        TEXT NOT NULL DEFAULT '{}',
    spending_ceiling             REAL NOT NULL DEFAULT 0.0,
    spending_used                REAL NOT NULL DEFAULT 0.0,
    revocation_key               TEXT NOT NULL DEFAULT '',
    issuer_public_key_fingerprint TEXT NOT NULL DEFAULT '',
    token_hash                   TEXT NOT NULL DEFAULT '',
    token_signature              TEXT NOT NULL DEFAULT '',
    active                       INTEGER NOT NULL DEFAULT 1,
    revoked_at                   REAL,
    revocation_reason            TEXT,
    parent_token_id              TEXT
);
CREATE INDEX IF NOT EXISTS idx_dt_active ON delegation_tokens(active);
CREATE INDEX IF NOT EXISTS idx_dt_expires ON delegation_tokens(expires_at);
"""

# Action category taxonomy
ACTION_CATEGORIES = frozenset([
    "web.navigate", "web.extract",
    "git.read", "git.write",
    "email.send",
    "file.read", "file.write", "file.delete",
    "api.call", "payment.*",
    "shell.execute",
])


@dataclass
class DelegationToken:
    token_id: str
    created_at: str
    expires_at: str
    allowed_action_categories: list
    parameter_constraints: dict
    spending_ceiling: float
    spending_used: float
    revocation_key: str
    issuer_public_key_fingerprint: str
    token_hash: str
    token_signature: str
    active: bool
    revoked_at: Optional[float] = None
    revocation_reason: Optional[str] = None
    parent_token_id: Optional[str] = None


class TokenStore:
    """SQLite-backed delegation token store."""

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

    def create(
        self,
        allowed_action_categories: list,
        spending_ceiling: float,
        expires_in_seconds: float,
        parameter_constraints: Optional[dict] = None,
        parent_token_id: Optional[str] = None,
        signing_key: Any = None,
    ) -> DelegationToken:
        token_id = str(uuid.uuid4())
        now = time.time()
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        expires_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + expires_in_seconds)
        )
        revocation_key = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        constraints = parameter_constraints or {}

        # Compute token hash
        token_data = json.dumps(
            {
                "token_id": token_id,
                "created_at": created_at,
                "expires_at": expires_at,
                "categories": sorted(allowed_action_categories),
                "constraints": constraints,
                "ceiling": spending_ceiling,
            },
            sort_keys=True,
        )
        token_hash = hashlib.sha256(token_data.encode()).hexdigest()

        # Sign if key available
        token_signature = ""
        issuer_fp = ""
        if signing_key is not None:
            try:
                sig = signing_key.sign(token_hash.encode())
                token_signature = (
                    sig.signature.hex() if hasattr(sig, "signature") else sig.hex()
                )
                issuer_fp = "cato-vault-ed25519"
            except Exception:
                pass

        token = DelegationToken(
            token_id=token_id,
            created_at=created_at,
            expires_at=expires_at,
            allowed_action_categories=allowed_action_categories,
            parameter_constraints=constraints,
            spending_ceiling=spending_ceiling,
            spending_used=0.0,
            revocation_key=revocation_key,
            issuer_public_key_fingerprint=issuer_fp,
            token_hash=token_hash,
            token_signature=token_signature,
            active=True,
            parent_token_id=parent_token_id,
        )
        self._conn.execute(
            """INSERT INTO delegation_tokens
               (token_id, created_at, expires_at, allowed_action_categories,
                parameter_constraints, spending_ceiling, spending_used, revocation_key,
                issuer_public_key_fingerprint, token_hash, token_signature, active,
                revoked_at, revocation_reason, parent_token_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                token_id, created_at, expires_at,
                json.dumps(allowed_action_categories),
                json.dumps(constraints),
                spending_ceiling, 0.0, revocation_key,
                issuer_fp, token_hash, token_signature,
                1, None, None, parent_token_id,
            ),
        )
        self._conn.commit()
        return token

    def get(self, token_id: str) -> Optional[DelegationToken]:
        row = self._conn.execute(
            "SELECT * FROM delegation_tokens WHERE token_id = ?", (token_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_token(row)

    def list_active(self) -> list[DelegationToken]:
        rows = self._conn.execute(
            "SELECT * FROM delegation_tokens WHERE active = 1 ORDER BY created_at"
        ).fetchall()
        return [self._row_to_token(r) for r in rows]

    def revoke(self, token_id: str, reason: str = "") -> bool:
        cur = self._conn.execute(
            "UPDATE delegation_tokens SET active = 0, revoked_at = ?, revocation_reason = ? WHERE token_id = ?",
            (time.time(), reason, token_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def deduct_spending(self, token_id: str, amount: float) -> bool:
        cur = self._conn.execute(
            "UPDATE delegation_tokens SET spending_used = spending_used + ? WHERE token_id = ? AND active = 1",
            (amount, token_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def deactivate_expired(self) -> int:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cur = self._conn.execute(
            "UPDATE delegation_tokens SET active = 0 WHERE expires_at < ? AND active = 1",
            (now,),
        )
        self._conn.commit()
        return cur.rowcount

    def _row_to_token(self, row: sqlite3.Row) -> DelegationToken:
        d = dict(row)
        d["allowed_action_categories"] = json.loads(d["allowed_action_categories"])
        d["parameter_constraints"] = json.loads(d["parameter_constraints"])
        d["active"] = bool(d["active"])
        return DelegationToken(**d)

    def close(self) -> None:
        self._conn.close()
