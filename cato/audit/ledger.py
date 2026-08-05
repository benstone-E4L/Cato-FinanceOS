"""
cato/audit/ledger.py — Causal Action Ledger (Unbuilt Skill 1).

Hash-chained, Ed25519-signed tamper-evident record of every agent decision.

WHY THIS MODULE FAILS CLOSED
----------------------------
An audit trail that can be skipped is not an audit trail. Two rules are
enforced *mechanically* here, not by convention:

1. Every write failure raises ``LedgerWriteError``. That class derives from
   ``BaseException``, **not** ``Exception``, so the historical anti-pattern::

       try:
           ledger.append(...)
       except Exception:
           logger.debug("ledger failed")   # action proceeds unrecorded

   CANNOT swallow it. A ledger failure propagates and the action does not
   happen. If you genuinely need to catch it you must name it, which is a
   reviewable act.

2. The execution path is reached only through a handle that is produced by a
   *successful* INTENT append. There is no supported way to run a protected
   action first and record it afterwards.

RECORD VOCABULARY (``EntryKind``)
---------------------------------
    INTENT     — about to attempt; carries redacted inputs + policy decision
    DENIED     — a gate refused; carries the gate name and the reason
    ATTEMPTED  — execution actually began
    FAILED     — execution errored (or the action was abandoned unresolved)
    CONFIRMED  — execution succeeded; carries the outcome
    VERIFIED   — independent read-back agreed with CONFIRMED
    MISMATCH   — independent read-back disagreed
    RECOVERED  — a recovery routine reconciled a crash-orphaned INTENT

Denials and failures are first-class rows in the same hash chain. An auditor
reading this ledger sees refusals and breakages, not only successes.

CALL SHAPE FOR THE DISPATCH PATH
--------------------------------
Async tool dispatch (the agent-loop shape)::

    with ledger.recorded_action(
        tool_name=tool_name,
        tool_input=tool_args,
        agent_session_id=session_id,
        policy_decision="allow",              # what policy said
        policy_gate="safety.check_action",    # which gate said it
        approval_ref=approval_id,             # or None
        idempotency_key=call_id,              # optional; enables replay refusal
    ) as action:
        result = await action.arun(dispatch_tool(tool_name, tool_args))
    # INTENT is durably committed before dispatch_tool runs.
    # CONFIRMED (or FAILED) is committed after it returns (or raises).

Synchronous tool dispatch::

    result = ledger.execute_action(
        tool_name=..., tool_input=..., agent_session_id=...,
        policy_decision="allow", policy_gate="safety.check_action",
        fn=lambda: run_tool(...),
    )

A gate refusal — record it *before* returning the refusal to the model::

    ledger.record_denial(
        tool_name=tool_name, tool_input=tool_args,
        agent_session_id=session_id,
        gate="outbound_approval", reason="no approval token",
    )

Independent read-back after the fact::

    ledger.record_verification(action_id=action.action_id, matched=False,
                               detail="file not present on disk")

Leaving the ``with`` block without calling ``arun``/``execute``/``confirm``/
``fail``/``deny`` writes a FAILED row and raises ``LedgerStateError``: an
unresolved action is a bug, and it is recorded as one.

CRASH RECOVERY
--------------
INTENT is committed (``synchronous=FULL``) and read back before the action is
attempted. If the process dies between INTENT and the terminal row, the chain
retains an INTENT with no terminal entry. ``LedgerQuery.unresolved_intents()``
finds those. Re-running with the same ``idempotency_key`` raises
``DuplicateActionError`` *before* the callable is invoked, so replay after a
restart cannot duplicate a side effect. A recovery routine reconciles with
``record_recovery(action_id=..., outcome=...)``.

REDACTION
---------
Inputs and outputs are redacted **recursively** (nested dicts, lists, tuples)
before they are hashed or persisted. Only the redacted form ever reaches the
chain.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, fields as dataclass_fields
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

logger = logging.getLogger(__name__)

_GENESIS_PREV_HASH = "0" * 64  # Fixed genesis sentinel

# Records written before the fail-closed rewrite hash only the v1 field set.
# Records written after carry schema_version=2 and hash the full field set.
_HASH_SCHEMA_VERSION = 2

_MAX_REDACTED_INPUT_CHARS = 4000
_MAX_OUTCOME_CHARS = 500
_MAX_REDACT_DEPTH = 12
_REDACTED = "[REDACTED]"

# Substring match, lower-cased. Kept identical to
# cato/core/approval_policy.py::_SENSITIVE_KEY_PARTS — the two redactors must
# agree, and that list is the reference. It matches credential-shaped key
# *names* (api_key / apikey / api-key / _key / private_key / session_key) and
# deliberately does NOT match a bare "key", which is an ordinary argument name
# (e.g. the keystroke in {"key": "Enter"}) and was being logged as [REDACTED].
# This narrows key-name matching only; value-shape scrubbing
# (_SENSITIVE_VALUE_PREFIXES, _SECRET_PATTERNS) is unchanged, so a credential
# under an innocent key is still caught.
_SENSITIVE_KEY_PARTS = (
    "api_key", "apikey", "api-key", "_key", "authorization", "auth_token",
    "access_token", "refresh_token", "id_token", "bearer", "token", "secret",
    "password", "passwd", "passphrase", "credential", "private_key",
    "client_secret", "session_key", "cookie", "vault", "signature", "otp",
)
_SENSITIVE_VALUE_PREFIXES = (
    "sk-", "sk_live_", "sk_test_", "Bearer ", "bearer ", "ghp_", "gho_",
    "github_pat_", "xoxb-", "xoxp-", "ya29.", "AKIA", "AIza", "eyJ",
)

# Embedded-credential scrubbing for free text (reasons, error messages,
# outcomes). Same patterns as cato/ui/server.py:_SECRET_PATTERNS — a secret in
# the middle of a sentence is still a secret.
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(['\"\s:=]+)([^,'\"\s}]+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_\-]{30,}\b"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_records (
    seq                   INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id             TEXT NOT NULL UNIQUE,
    prev_hash             TEXT NOT NULL,
    timestamp             TEXT NOT NULL,
    agent_session_id      TEXT NOT NULL,
    tool_name             TEXT NOT NULL,
    tool_input_hash       TEXT NOT NULL,
    tool_output_hash      TEXT NOT NULL,
    reasoning_excerpt     TEXT NOT NULL DEFAULT '',
    confidence_score      REAL NOT NULL DEFAULT 0.0,
    model_source          TEXT NOT NULL DEFAULT 'claude',
    reversibility         REAL NOT NULL DEFAULT 0.5,
    delegation_token_id   TEXT,
    record_hash           TEXT NOT NULL,
    record_signature      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ledger_ts       ON ledger_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_ledger_tool     ON ledger_records(tool_name);
CREATE INDEX IF NOT EXISTS idx_ledger_session  ON ledger_records(agent_session_id);
CREATE INDEX IF NOT EXISTS idx_ledger_token    ON ledger_records(delegation_token_id);
"""

# Columns added by the fail-closed rewrite. Applied to fresh and existing DBs
# via ALTER TABLE so old chains keep verifying under the v1 hash formula.
_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("entry_kind", "TEXT NOT NULL DEFAULT 'CONFIRMED'"),
    ("action_id", "TEXT NOT NULL DEFAULT ''"),
    ("idempotency_key", "TEXT NOT NULL DEFAULT ''"),
    ("policy_decision", "TEXT NOT NULL DEFAULT ''"),
    ("policy_gate", "TEXT NOT NULL DEFAULT ''"),
    ("approval_ref", "TEXT NOT NULL DEFAULT ''"),
    ("actor", "TEXT NOT NULL DEFAULT ''"),
    ("outcome", "TEXT NOT NULL DEFAULT ''"),
    ("tool_input_redacted", "TEXT NOT NULL DEFAULT ''"),
    ("schema_version", "INTEGER NOT NULL DEFAULT 1"),
)

_POST_MIGRATION_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_ledger_action ON ledger_records(action_id)",
    "CREATE INDEX IF NOT EXISTS idx_ledger_kind ON ledger_records(entry_kind)",
    # Partial unique index: only INTENT rows carry an idempotency key, so this
    # makes replay refusal an invariant of the storage layer, not just a check.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_idem "
    "ON ledger_records(idempotency_key) WHERE idempotency_key <> ''",
)


# ---------------------------------------------------------------------------
# Errors — BaseException on purpose (see module docstring)
# ---------------------------------------------------------------------------

class LedgerError(BaseException):
    """Base for ledger faults. Derives from BaseException so that a blanket
    ``except Exception`` around an audit write cannot silently drop it."""


class LedgerWriteError(LedgerError):
    """The entry could not be durably written and chained. The action must not
    proceed."""


class DuplicateActionError(LedgerError):
    """An INTENT with this idempotency key already exists. Replaying it would
    duplicate a side effect."""


class LedgerStateError(LedgerError):
    """The action handle was used out of contract (double execution, or the
    action scope exited without a terminal entry)."""


class EntryKind(str, Enum):
    INTENT = "INTENT"
    DENIED = "DENIED"
    ATTEMPTED = "ATTEMPTED"
    FAILED = "FAILED"
    CONFIRMED = "CONFIRMED"
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    RECOVERED = "RECOVERED"
    #: The action was dispatched and the real-world outcome is UNKNOWN — the
    #: request reached the wire but no answer came back (remote timeout,
    #: connection dropped mid-flight). Recording this as FAILED would assert
    #: "it did not happen", which is a claim we cannot support and which a
    #: retry decision would key off. INDETERMINATE resolves the INTENT (so it
    #: is not confused with a crash) but stays on the reconciliation queue.
    INDETERMINATE = "INDETERMINATE"


TERMINAL_KINDS = frozenset({
    EntryKind.DENIED.value,
    EntryKind.FAILED.value,
    EntryKind.CONFIRMED.value,
    EntryKind.RECOVERED.value,
    EntryKind.INDETERMINATE.value,
})


@dataclass
class LedgerRecord:
    seq: int
    record_id: str
    prev_hash: str
    timestamp: str
    agent_session_id: str
    tool_name: str
    tool_input_hash: str
    tool_output_hash: str
    reasoning_excerpt: str
    confidence_score: float
    model_source: str
    reversibility: float
    delegation_token_id: Optional[str]
    record_hash: str
    record_signature: str
    entry_kind: str = EntryKind.CONFIRMED.value
    action_id: str = ""
    idempotency_key: str = ""
    policy_decision: str = ""
    policy_gate: str = ""
    approval_ref: str = ""
    actor: str = ""
    outcome: str = ""
    tool_input_redacted: str = ""
    schema_version: int = 1


_RECORD_FIELD_NAMES = frozenset(f.name for f in dataclass_fields(LedgerRecord))


# ---------------------------------------------------------------------------
# Hashing / redaction helpers
# ---------------------------------------------------------------------------

def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _hash_json(obj: Any) -> str:
    return _sha256(json.dumps(obj, sort_keys=True, default=str))


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _is_sensitive_value(value: Any) -> bool:
    return isinstance(value, str) and any(
        value.startswith(p) for p in _SENSITIVE_VALUE_PREFIXES
    )


def _scrub_text(text: str) -> str:
    """Mask credentials embedded inside a larger string."""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(r"\1\2" + _REDACTED, text)
        else:
            text = pattern.sub(_REDACTED, text)
    return text


def redact(value: Any, key: str = "", _depth: int = 0) -> Any:
    """Recursively strip credentials from a payload.

    Mirrors ``cato/ui/server.py:_redact_diagnostics_data``: sensitivity is
    decided per key at *every* level, not only at the top level, so
    ``{"headers": {"authorization": "Bearer ..."}}`` is redacted.
    """
    if _depth > _MAX_REDACT_DEPTH:
        return "[TRUNCATED_DEPTH]"

    if key and _is_sensitive_key(key):
        if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
            return value
        return _REDACTED if value else value

    if isinstance(value, dict):
        return {
            str(k): redact(v, str(k), _depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item, "", _depth + 1) for item in value]
    if isinstance(value, str):
        return _REDACTED if _is_sensitive_value(value) else _scrub_text(value)
    return value


def _redacted_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)[:_MAX_REDACTED_INPUT_CHARS]


def _summarize(value: Any) -> str:
    """Redacted, truncated, single-line summary for the ``outcome`` column."""
    red = redact(value)
    if isinstance(red, str):
        text = red
    else:
        text = json.dumps(red, sort_keys=True, default=str)
    return text.replace("\n", " ")[:_MAX_OUTCOME_CHARS]


def _now_timestamp() -> str:
    now_ts = time.time()
    return (
        time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime(now_ts))
        + f"{int(now_ts * 1000) % 1000:03d}Z"
    )


def _compute_record_hash(row: Mapping[str, Any]) -> str:
    """Recompute a record hash from its stored fields.

    v1 rows (written before the fail-closed rewrite) hash the original twelve
    fields. v2 rows additionally hash the vocabulary/policy/redacted-input
    fields, so mutating any of them — or downgrading schema_version to dodge
    the v2 formula — breaks the chain.
    """
    base = [
        str(row["record_id"]), str(row["prev_hash"]), str(row["timestamp"]),
        str(row["agent_session_id"]), str(row["tool_name"]),
        str(row["tool_input_hash"]), str(row["tool_output_hash"]),
        str(row["reasoning_excerpt"]), str(row["confidence_score"]),
        str(row["model_source"]), str(row["reversibility"]),
        str(row["delegation_token_id"] or ""),
    ]
    version = int(row["schema_version"] or 1)
    if version < 2:
        return _sha256("|".join(base))
    base.extend([
        f"v{version}",
        str(row["entry_kind"]), str(row["action_id"]),
        str(row["idempotency_key"]), str(row["policy_decision"]),
        str(row["policy_gate"]), str(row["approval_ref"]),
        str(row["actor"]), str(row["outcome"]),
        str(row["tool_input_redacted"]),
    ])
    return _sha256("|".join(base))


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the table if absent and add any missing v2 columns in place."""
    conn.executescript(_SCHEMA)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(ledger_records)")}
    for name, decl in _ADDED_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE ledger_records ADD COLUMN {name} {decl}")
    for stmt in _POST_MIGRATION_INDEXES:
        conn.execute(stmt)
    conn.commit()


def _row_to_record(row: sqlite3.Row) -> LedgerRecord:
    d = {k: v for k, v in dict(row).items() if k in _RECORD_FIELD_NAMES}
    return LedgerRecord(**d)


# ---------------------------------------------------------------------------
# Action handle — the only route to a recorded execution
# ---------------------------------------------------------------------------

class ActionHandle:
    """Returned only by a successful INTENT append.

    Holds the identity of an in-flight protected action and is the sole way to
    write its terminal entry. Construct it yourself and you get an object with
    no INTENT behind it — which is exactly why ``recorded_action()`` is the
    documented entry point.
    """

    def __init__(
        self,
        ledger: "LedgerMiddleware",
        action_id: str,
        intent_record_id: str,
        tool_name: str,
        agent_session_id: str,
        idempotency_key: str,
        common: dict,
    ) -> None:
        self._ledger = ledger
        self.action_id = action_id
        self.intent_record_id = intent_record_id
        self.tool_name = tool_name
        self.agent_session_id = agent_session_id
        self.idempotency_key = idempotency_key
        self._common = common
        self._resolved = False
        self._attempted = False

    @property
    def resolved(self) -> bool:
        """True once a terminal entry (CONFIRMED/FAILED/DENIED) was written."""
        return self._resolved

    @property
    def attempted(self) -> bool:
        return self._attempted

    # -- internal writes ---------------------------------------------------

    def _write(self, kind: EntryKind, *, outcome: str = "",
               tool_output: Any = None, policy_gate: Optional[str] = None,
               policy_decision: Optional[str] = None) -> str:
        payload = dict(self._common)
        if policy_gate is not None:
            payload["policy_gate"] = policy_gate
        if policy_decision is not None:
            payload["policy_decision"] = policy_decision
        return self._ledger._write_entry(
            entry_kind=kind,
            action_id=self.action_id,
            idempotency_key="",  # only the INTENT row carries the key
            tool_output=tool_output,
            outcome=outcome,
            **payload,
        )

    def _mark_attempt(self) -> str:
        if self._attempted:
            raise LedgerStateError(
                f"action {self.action_id} was already attempted; "
                "re-running it would duplicate the side effect"
            )
        if self._resolved:
            raise LedgerStateError(
                f"action {self.action_id} is already resolved"
            )
        self._attempted = True
        return self._write(EntryKind.ATTEMPTED, outcome="execution started")

    # -- public terminal writes -------------------------------------------

    def confirm(self, tool_output: Any = None, outcome: str = "success") -> str:
        """Record CONFIRMED. Raises if the action is already resolved."""
        if self._resolved:
            raise LedgerStateError(f"action {self.action_id} is already resolved")
        record_id = self._write(
            EntryKind.CONFIRMED, tool_output=tool_output,
            outcome=_summarize(outcome),
        )
        self._resolved = True
        return record_id

    def fail(self, error: Any, outcome: str = "") -> str:
        """Record FAILED. Safe to call from an exception handler."""
        if self._resolved:
            raise LedgerStateError(f"action {self.action_id} is already resolved")
        detail = outcome or f"{type(error).__name__}: {error}"
        record_id = self._write(EntryKind.FAILED, outcome=_summarize(detail))
        self._resolved = True
        return record_id

    def indeterminate(self, reason: Any, tool_output: Any = None) -> str:
        """Record INDETERMINATE — dispatched, real-world outcome UNKNOWN.

        Use this and never :meth:`fail` when the request left the process and
        no answer came back. FAILED means "it did not happen"; asserting that
        about a timed-out remote call is how a duplicate side effect gets
        created by a well-meaning retry.
        """
        if self._resolved:
            raise LedgerStateError(f"action {self.action_id} is already resolved")
        record_id = self._write(
            EntryKind.INDETERMINATE,
            tool_output=tool_output,
            outcome=_summarize(f"INDETERMINATE: {reason}"),
        )
        self._resolved = True
        return record_id

    def deny(self, gate: str, reason: str) -> str:
        """Record DENIED for a gate that refused after INTENT was written."""
        if self._resolved:
            raise LedgerStateError(f"action {self.action_id} is already resolved")
        record_id = self._write(
            EntryKind.DENIED, outcome=_summarize(reason),
            policy_gate=gate, policy_decision="deny",
        )
        self._resolved = True
        return record_id

    # -- execution wrappers ------------------------------------------------

    def _resolve_exception(self, exc: BaseException) -> str:
        """Write the terminal entry that matches what the exception proves.

        An exception carrying a truthy ``ledger_indeterminate`` attribute means
        the caller reached an external system and lost the answer, so FAILED
        ("it did not happen") would be unsupported. Everything else is FAILED.
        This attribute is the ledger's only coupling to callers — it deliberately
        does not import them.
        """
        if getattr(exc, "ledger_indeterminate", False):
            return self.indeterminate(exc)
        return self.fail(exc)

    def execute(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous action: ATTEMPTED → fn() → CONFIRMED / FAILED."""
        self._mark_attempt()
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — recorded then re-raised
            self._resolve_exception(exc)
            raise
        self.confirm(result)
        return result

    async def arun(self, awaitable: Any) -> Any:
        """Await an action: ATTEMPTED → await → CONFIRMED / FAILED.

        This is the shape the async agent loop uses::

            result = await action.arun(dispatch_tool(name, args))
        """
        self._mark_attempt()
        try:
            result = await awaitable
        except BaseException as exc:  # noqa: BLE001 — recorded then re-raised
            self._resolve_exception(exc)
            raise
        self.confirm(result)
        return result


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class LedgerMiddleware:
    """
    Appends signed records to the hash chain.

    Thread-safe via a write lock. Every write is committed with
    ``synchronous=FULL`` and read back before the call returns; if the row is
    not there, ``LedgerWriteError`` is raised and the caller must abort.
    """

    def __init__(self, db_path: Optional[Path] = None, signing_key: Any = None) -> None:
        if db_path is None:
            from ..platform import get_data_dir
            db_path = get_data_dir() / "cato.db"
        self._db_path = db_path
        self._signing_key = signing_key  # Ed25519 SigningKey or None
        self._write_lock = threading.RLock()
        self._conn = self._open_db()

    def _open_db(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        # FULL, not NORMAL: an INTENT must survive a crash that happens
        # microseconds after it is written, because the action runs next.
        conn.execute("PRAGMA synchronous=FULL")
        _ensure_schema(conn)
        return conn

    def _last_record_hash(self) -> str:
        row = self._conn.execute(
            "SELECT record_hash FROM ledger_records ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return row["record_hash"] if row else _GENESIS_PREV_HASH

    def _sign(self, record_hash: str) -> str:
        if self._signing_key is None:
            return ""
        try:
            sig = self._signing_key.sign(record_hash.encode("utf-8"))
            return sig.signature.hex() if hasattr(sig, "signature") else sig.hex()
        except Exception as exc:
            logger.warning("Ledger signing failed: %s", exc)
            return ""

    # -- core write --------------------------------------------------------

    def _write_entry(
        self,
        *,
        entry_kind: EntryKind,
        tool_name: str,
        tool_input: Any = None,
        tool_output: Any = None,
        agent_session_id: str,
        action_id: str = "",
        idempotency_key: str = "",
        policy_decision: str = "",
        policy_gate: str = "",
        approval_ref: str = "",
        actor: str = "",
        outcome: str = "",
        reasoning_excerpt: str = "",
        confidence_score: float = 0.0,
        model_source: str = "claude",
        reversibility: float = 0.5,
        delegation_token_id: Optional[str] = None,
    ) -> str:
        """Write one chained, signed, redacted entry. Raises on any failure."""
        record_id = str(uuid.uuid4())
        timestamp = _now_timestamp()
        kind_value = entry_kind.value if isinstance(entry_kind, EntryKind) else str(entry_kind)

        # Redact BEFORE hashing and BEFORE persisting. The raw payload never
        # reaches the chain in any form.
        redacted_input = redact(tool_input)
        redacted_output = redact(tool_output)
        tool_input_hash = _hash_json(redacted_input)
        tool_output_hash = _hash_json(redacted_output)
        tool_input_redacted = _redacted_json(redacted_input)

        row = {
            "record_id": record_id,
            "prev_hash": "",  # set under the lock
            "timestamp": timestamp,
            "agent_session_id": agent_session_id,
            "tool_name": tool_name,
            "tool_input_hash": tool_input_hash,
            "tool_output_hash": tool_output_hash,
            "reasoning_excerpt": reasoning_excerpt[:500],
            "confidence_score": confidence_score,
            "model_source": model_source,
            "reversibility": reversibility,
            "delegation_token_id": delegation_token_id,
            "entry_kind": kind_value,
            "action_id": action_id or record_id,
            "idempotency_key": idempotency_key or "",
            "policy_decision": policy_decision or "",
            "policy_gate": policy_gate or "",
            "approval_ref": approval_ref or "",
            "actor": actor or agent_session_id,
            "outcome": _summarize(outcome) if outcome else "",
            "tool_input_redacted": tool_input_redacted,
            "schema_version": _HASH_SCHEMA_VERSION,
        }

        with self._write_lock:
            row["prev_hash"] = self._last_record_hash()
            record_hash = _compute_record_hash(row)
            row["record_hash"] = record_hash
            row["record_signature"] = self._sign(record_hash)

            columns = [
                "record_id", "prev_hash", "timestamp", "agent_session_id",
                "tool_name", "tool_input_hash", "tool_output_hash",
                "reasoning_excerpt", "confidence_score", "model_source",
                "reversibility", "delegation_token_id", "record_hash",
                "record_signature", "entry_kind", "action_id",
                "idempotency_key", "policy_decision", "policy_gate",
                "approval_ref", "actor", "outcome", "tool_input_redacted",
                "schema_version",
            ]
            placeholders = ", ".join("?" for _ in columns)
            sql = (
                f"INSERT INTO ledger_records ({', '.join(columns)}) "
                f"VALUES ({placeholders})"
            )
            try:
                self._conn.execute(sql, tuple(row[c] for c in columns))
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                if idempotency_key and "idempotency_key" in str(exc):
                    raise DuplicateActionError(
                        f"idempotency key already present in ledger: {idempotency_key}"
                    ) from exc
                raise LedgerWriteError(
                    f"ledger append rejected ({kind_value} / {tool_name}): {exc}"
                ) from exc
            except Exception as exc:
                raise LedgerWriteError(
                    f"ledger append failed ({kind_value} / {tool_name}): {exc}"
                ) from exc

            # Durability read-back: the contract is "written AND chained".
            try:
                check = self._conn.execute(
                    "SELECT record_hash FROM ledger_records WHERE record_id = ?",
                    (record_id,),
                ).fetchone()
            except Exception as exc:
                raise LedgerWriteError(
                    f"ledger read-back failed ({kind_value} / {tool_name}): {exc}"
                ) from exc
            if check is None or check["record_hash"] != record_hash:
                raise LedgerWriteError(
                    f"ledger entry {record_id} ({kind_value}) was not durably "
                    "persisted; refusing to continue"
                )

        logger.debug("Ledger %s appended: %s (tool=%s)", kind_value, record_id, tool_name)
        return record_id

    # -- legacy primitive --------------------------------------------------

    def append(
        self,
        tool_name: str,
        tool_input: Any,
        tool_output: Any,
        agent_session_id: str,
        reasoning_excerpt: str = "",
        confidence_score: float = 0.0,
        model_source: str = "claude",
        reversibility: float = 0.5,
        delegation_token_id: Optional[str] = None,
        entry_kind: EntryKind = EntryKind.CONFIRMED,
    ) -> str:
        """Low-level single-entry append. Returns record_id, raises on failure.

        Prefer ``recorded_action()`` / ``execute_action()``: a bare append
        after the fact cannot prove the action was recorded *before* it ran.
        """
        return self._write_entry(
            entry_kind=entry_kind,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            agent_session_id=agent_session_id,
            reasoning_excerpt=reasoning_excerpt,
            confidence_score=confidence_score,
            model_source=model_source,
            reversibility=reversibility,
            delegation_token_id=delegation_token_id,
        )

    # -- vocabulary entry points ------------------------------------------

    def record_denial(
        self,
        *,
        tool_name: str,
        tool_input: Any,
        agent_session_id: str,
        gate: str,
        reason: str,
        approval_ref: Optional[str] = None,
        actor: str = "",
        reasoning_excerpt: str = "",
        delegation_token_id: Optional[str] = None,
    ) -> str:
        """Record a gate refusal. Call this BEFORE returning the refusal."""
        return self._write_entry(
            entry_kind=EntryKind.DENIED,
            tool_name=tool_name,
            tool_input=tool_input,
            agent_session_id=agent_session_id,
            policy_decision="deny",
            policy_gate=gate,
            approval_ref=approval_ref or "",
            actor=actor,
            outcome=reason,
            reasoning_excerpt=reasoning_excerpt,
            delegation_token_id=delegation_token_id,
        )

    def record_verification(
        self,
        *,
        action_id: str,
        matched: bool,
        detail: str = "",
        tool_name: str = "",
        agent_session_id: str = "",
    ) -> str:
        """Record an independent read-back as VERIFIED or MISMATCH."""
        prior = self.by_action(action_id)
        if prior:
            tool_name = tool_name or prior[0].tool_name
            agent_session_id = agent_session_id or prior[0].agent_session_id
        return self._write_entry(
            entry_kind=EntryKind.VERIFIED if matched else EntryKind.MISMATCH,
            tool_name=tool_name or "unknown",
            agent_session_id=agent_session_id or "unknown",
            action_id=action_id,
            outcome=detail or ("read-back agreed" if matched else "read-back disagreed"),
        )

    def record_recovery(
        self,
        *,
        action_id: str,
        outcome: str,
        tool_name: str = "",
        agent_session_id: str = "",
    ) -> str:
        """Reconcile a crash-orphaned INTENT with a terminal RECOVERED entry."""
        prior = self.by_action(action_id)
        if prior:
            tool_name = tool_name or prior[0].tool_name
            agent_session_id = agent_session_id or prior[0].agent_session_id
        return self._write_entry(
            entry_kind=EntryKind.RECOVERED,
            tool_name=tool_name or "unknown",
            agent_session_id=agent_session_id or "unknown",
            action_id=action_id,
            outcome=outcome,
        )

    # -- the protected-action path ----------------------------------------

    @contextmanager
    def recorded_action(
        self,
        *,
        tool_name: str,
        tool_input: Any,
        agent_session_id: str,
        policy_decision: str,
        policy_gate: str,
        approval_ref: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        actor: str = "",
        reasoning_excerpt: str = "",
        confidence_score: float = 0.0,
        model_source: str = "claude",
        reversibility: float = 0.5,
        delegation_token_id: Optional[str] = None,
    ) -> Iterator[ActionHandle]:
        """Durably record INTENT, then yield the handle that runs the action.

        Raises ``LedgerWriteError`` before yielding if INTENT cannot be
        written — the body never executes. Raises ``DuplicateActionError`` if
        ``idempotency_key`` was already used, so a post-crash replay cannot
        repeat a side effect.

        Exiting the block without a terminal entry writes FAILED and raises
        ``LedgerStateError``.
        """
        action_id = str(uuid.uuid4())
        key = idempotency_key or ""
        common = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "agent_session_id": agent_session_id,
            "policy_decision": policy_decision,
            "policy_gate": policy_gate,
            "approval_ref": approval_ref or "",
            "actor": actor,
            "reasoning_excerpt": reasoning_excerpt,
            "confidence_score": confidence_score,
            "model_source": model_source,
            "reversibility": reversibility,
            "delegation_token_id": delegation_token_id,
        }

        intent_record_id = self._write_entry(
            entry_kind=EntryKind.INTENT,
            action_id=action_id,
            idempotency_key=key,
            outcome="intent recorded; action not yet attempted",
            **common,
        )

        handle = ActionHandle(
            ledger=self,
            action_id=action_id,
            intent_record_id=intent_record_id,
            tool_name=tool_name,
            agent_session_id=agent_session_id,
            idempotency_key=key,
            common=common,
        )

        try:
            yield handle
        except LedgerError:
            raise
        except BaseException as exc:  # noqa: BLE001 — recorded then re-raised
            if not handle.resolved:
                handle._resolve_exception(exc)
            raise
        if not handle.resolved:
            handle.fail(
                None,
                outcome="UNRESOLVED: action scope exited without execution or denial",
            )
            raise LedgerStateError(
                f"action {action_id} ({tool_name}) left the ledger scope without a "
                "terminal entry; use action.arun()/execute()/confirm()/fail()/deny()"
            )

    def execute_action(
        self,
        *,
        tool_name: str,
        tool_input: Any,
        agent_session_id: str,
        fn: Callable[..., Any],
        policy_decision: str,
        policy_gate: str,
        approval_ref: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        actor: str = "",
        reasoning_excerpt: str = "",
        confidence_score: float = 0.0,
        model_source: str = "claude",
        reversibility: float = 0.5,
        delegation_token_id: Optional[str] = None,
    ) -> Any:
        """One-call synchronous form: INTENT → fn() → CONFIRMED/FAILED.

        Returns whatever ``fn`` returns. ``fn`` is never invoked unless INTENT
        was durably committed first.
        """
        with self.recorded_action(
            tool_name=tool_name,
            tool_input=tool_input,
            agent_session_id=agent_session_id,
            policy_decision=policy_decision,
            policy_gate=policy_gate,
            approval_ref=approval_ref,
            idempotency_key=idempotency_key,
            actor=actor,
            reasoning_excerpt=reasoning_excerpt,
            confidence_score=confidence_score,
            model_source=model_source,
            reversibility=reversibility,
            delegation_token_id=delegation_token_id,
        ) as action:
            return action.execute(fn)

    # -- recovery queries on the writer connection -------------------------

    def by_action(self, action_id: str) -> list[LedgerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM ledger_records WHERE action_id = ? ORDER BY seq",
            (action_id,),
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def unresolved_intents(self) -> list[LedgerRecord]:
        return _unresolved_intents(self._conn)

    def unreconciled_indeterminate(self) -> list[LedgerRecord]:
        """Actions dispatched whose real-world outcome is still UNKNOWN."""
        return _unreconciled_indeterminate(self._conn)

    def close(self) -> None:
        self._conn.close()


def _unreconciled_indeterminate(conn: sqlite3.Connection) -> list[LedgerRecord]:
    """INDETERMINATE actions with no RECOVERED/VERIFIED reconciliation yet.

    These are the actions whose real-world effect is unknown. They MUST be
    reconciled by a human (or a remote status query) before the same request
    is issued again — re-running one is exactly how a single approved action
    becomes two real-world effects.
    """
    rows = conn.execute(
        """SELECT * FROM ledger_records i
            WHERE i.entry_kind = 'INDETERMINATE'
              AND NOT EXISTS (
                  SELECT 1 FROM ledger_records t
                  WHERE t.action_id = i.action_id
                    AND t.entry_kind IN ('RECOVERED', 'VERIFIED')
              )
            ORDER BY i.seq"""
    ).fetchall()
    return [_row_to_record(r) for r in rows]


def _unresolved_intents(conn: sqlite3.Connection) -> list[LedgerRecord]:
    placeholders = ", ".join("?" for _ in TERMINAL_KINDS)
    rows = conn.execute(
        f"""SELECT * FROM ledger_records i
            WHERE i.entry_kind = 'INTENT'
              AND NOT EXISTS (
                  SELECT 1 FROM ledger_records t
                  WHERE t.action_id = i.action_id
                    AND t.entry_kind IN ({placeholders})
              )
            ORDER BY i.seq""",
        tuple(sorted(TERMINAL_KINDS)),
    ).fetchall()
    return [_row_to_record(r) for r in rows]


class LedgerQuery:
    """Query interface for the ledger chain."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            from ..platform import get_data_dir
            db_path = get_data_dir() / "cato.db"
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        _ensure_schema(self._conn)

    def _row_to_record(self, row: sqlite3.Row) -> LedgerRecord:
        return _row_to_record(row)

    def by_time_range(self, start: float, end: float) -> list[LedgerRecord]:
        # Use prefix-friendly bounds: start without suffix (lexicographically earlier),
        # end with trailing "Z~" so millisecond variants within the last second are included.
        start_s = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(start))
        end_s = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(end)) + "Z~"
        rows = self._conn.execute(
            "SELECT * FROM ledger_records WHERE timestamp >= ? AND timestamp <= ? ORDER BY seq",
            (start_s, end_s),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def by_tool(self, tool_name: str) -> list[LedgerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM ledger_records WHERE tool_name = ? ORDER BY seq",
            (tool_name,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def by_session(self, session_id: str) -> list[LedgerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM ledger_records WHERE agent_session_id = ? ORDER BY seq",
            (session_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def by_confidence_below(self, threshold: float) -> list[LedgerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM ledger_records WHERE confidence_score < ? ORDER BY seq",
            (threshold,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def by_delegation_token(self, token_id: str) -> list[LedgerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM ledger_records WHERE delegation_token_id = ? ORDER BY seq",
            (token_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def by_entry_kind(self, entry_kind: Any) -> list[LedgerRecord]:
        kind = entry_kind.value if isinstance(entry_kind, EntryKind) else str(entry_kind)
        rows = self._conn.execute(
            "SELECT * FROM ledger_records WHERE entry_kind = ? ORDER BY seq",
            (kind,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def by_action(self, action_id: str) -> list[LedgerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM ledger_records WHERE action_id = ? ORDER BY seq",
            (action_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def find_by_idempotency_key(self, key: str) -> Optional[LedgerRecord]:
        row = self._conn.execute(
            "SELECT * FROM ledger_records WHERE idempotency_key = ? LIMIT 1",
            (key,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def unresolved_intents(self) -> list[LedgerRecord]:
        """INTENT entries with no CONFIRMED/FAILED/DENIED/RECOVERED sibling.

        A non-empty result after a restart means the process died mid-action:
        the side effect may or may not have happened, and a recovery routine
        must reconcile it.
        """
        return _unresolved_intents(self._conn)

    def unreconciled_indeterminate(self) -> list[LedgerRecord]:
        """INDETERMINATE actions still awaiting reconciliation."""
        return _unreconciled_indeterminate(self._conn)

    def replay_session(self, session_id: str) -> list[dict]:
        records = self.by_session(session_id)
        return [
            {
                "record_id": r.record_id,
                "timestamp": r.timestamp,
                "tool_name": r.tool_name,
                "reasoning_excerpt": r.reasoning_excerpt,
                "confidence_score": r.confidence_score,
                "reversibility": r.reversibility,
                "entry_kind": r.entry_kind,
                "action_id": r.action_id,
                "policy_decision": r.policy_decision,
                "policy_gate": r.policy_gate,
                "outcome": r.outcome,
            }
            for r in records
        ]

    def last_n(self, n: int) -> list[LedgerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM ledger_records ORDER BY seq DESC LIMIT ?", (n,)
        ).fetchall()
        return [self._row_to_record(r) for r in reversed(rows)]

    def close(self) -> None:
        self._conn.close()


def unresolved_intents(db_path: Optional[Path] = None) -> list[LedgerRecord]:
    """Module-level convenience for recovery routines at startup."""
    q = LedgerQuery(db_path=db_path)
    try:
        return q.unresolved_intents()
    finally:
        q.close()


def unreconciled_indeterminate(db_path: Optional[Path] = None) -> list[LedgerRecord]:
    """Module-level convenience: actions whose real-world outcome is unknown."""
    q = LedgerQuery(db_path=db_path)
    try:
        return q.unreconciled_indeterminate()
    finally:
        q.close()


def verify_chain(db_path: Optional[Path] = None) -> tuple[bool, str]:
    """
    Walk the full chain and verify hash linkage.

    Returns (True, "VALID (N records...)") or
    (False, "TAMPERED at record {id} — {reason}").
    """
    if db_path is None:
        from ..platform import get_data_dir
        db_path = get_data_dir() / "cato.db"

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ledger_records'"
    ).fetchone()
    if table is None:
        conn.close()
        return True, "VALID (0 records, ledger not initialized)"
    _ensure_schema(conn)
    rows = conn.execute(
        "SELECT * FROM ledger_records ORDER BY seq ASC"
    ).fetchall()
    conn.close()

    if not rows:
        return True, "VALID (0 records, empty chain)"

    expected_prev = _GENESIS_PREV_HASH
    for i, row in enumerate(rows):
        # Verify prev_hash linkage
        if row["prev_hash"] != expected_prev:
            return False, (
                f"TAMPERED at record {row['record_id']} (index {i}) — "
                f"prev_hash mismatch: expected {expected_prev[:16]}…, "
                f"got {row['prev_hash'][:16]}…"
            )

        # Verify record_hash matches re-computed hash of all fields
        expected_hash = _compute_record_hash(row)
        if expected_hash != row["record_hash"]:
            return False, (
                f"TAMPERED at record {row['record_id']} (index {i}) — "
                f"field hash mismatch: stored {row['record_hash'][:16]}…, "
                f"recomputed {expected_hash[:16]}…"
            )

        expected_prev = row["record_hash"]

    return True, f"VALID ({len(rows)} records, chain intact)"
