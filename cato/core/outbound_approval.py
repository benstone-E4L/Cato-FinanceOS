"""
cato/core/outbound_approval.py — Human-in-the-loop gate for outbound actions.

Persists pending actions in cato.db until approved via Telegram or API.

Security properties (see cato/core/approval_policy.py for the engine):

* Routing is policy-driven and FAIL CLOSED. Unknown tools require approval.
* Nothing in model-supplied ``args`` can remove an approval requirement.
* Everything is recursively REDACTED before it touches SQLite or a preview.
* Approvals are TICKETS: unique id, bound to (canonical tool + argument
  digest), 24h TTL with 60s skew tolerance, single-use, HMAC-signed.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .approval_policy import (
    ApprovalContext,
    ApprovalTicket,
    TicketError,
    build_preview,
    canonical_args,
    compute_args_digest,
    evaluate,
    grant_execution,
    issue_ticket,
    redact_text,
    resolve_tool,
    verify_ticket,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbound_approvals (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    args_json       TEXT NOT NULL,
    preview         TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      REAL NOT NULL,
    resolved_at     REAL,
    resolved_by     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_outbound_status ON outbound_approvals(status);
CREATE TABLE IF NOT EXISTS outbound_approval_meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""

# Columns added by the policy engine. Applied with ALTER TABLE so existing
# cato.db files migrate in place.
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("canonical_tool", "TEXT NOT NULL DEFAULT ''"),
    ("args_digest",    "TEXT NOT NULL DEFAULT ''"),
    ("ticket_id",      "TEXT NOT NULL DEFAULT ''"),
    ("ticket_token",   "TEXT NOT NULL DEFAULT ''"),
    ("expires_at",     "REAL"),
    ("consumed_at",    "REAL"),
)

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_CONSUMED = "consumed"


@dataclass
class OutboundApproval:
    id: str
    session_id: str
    tool_name: str
    args: dict[str, Any]
    preview: str
    status: str
    created_at: float
    resolved_at: Optional[float]
    resolved_by: str
    canonical_tool: str = ""
    args_digest: str = ""
    ticket_id: str = ""
    expires_at: Optional[float] = None
    consumed_at: Optional[float] = None


class OutboundApprovalStore:
    """Thread-safe store for pending outbound tool executions.

    ``args`` and ``preview`` are recursively redacted on the way in, so an
    unredacted credential can never be written to the database or forwarded to
    an operator's phone — regardless of what the caller passes.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            from ..platform import get_data_dir
            db_path = get_data_dir() / "cato.db"
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = self._open()
        self._signing_key = self._load_or_create_signing_key()

    def _open(self) -> sqlite3.Connection:
        if str(self._db_path) != ":memory:":
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        existing = {
            r["name"] for r in conn.execute("PRAGMA table_info(outbound_approvals)")
        }
        for column, decl in _MIGRATIONS:
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE outbound_approvals ADD COLUMN {column} {decl}"
                )
        conn.commit()
        return conn

    # ------------------------------------------------------------------
    # Ticket signing key
    # ------------------------------------------------------------------

    def _load_or_create_signing_key(self) -> bytes:
        """Per-installation HMAC key for approval tickets.

        A 32-byte application key is generated once and stored alongside the
        approvals.  Process-environment signing-key overrides are deliberately
        unsupported so operator credentials cannot enter through plaintext env.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT v FROM outbound_approval_meta WHERE k = 'signing_key'"
            ).fetchone()
            if row is not None and row["v"]:
                return bytes.fromhex(row["v"])
            key = secrets.token_bytes(32)
            self._conn.execute(
                "INSERT OR REPLACE INTO outbound_approval_meta (k, v) VALUES ('signing_key', ?)",
                (key.hex(),),
            )
            self._conn.commit()
            return key

    # ------------------------------------------------------------------
    # Monotonic clock floor — defeats a backwards clock jump
    # ------------------------------------------------------------------

    def _clock_floor(self, now: float) -> float:
        """Return a wall-clock reading that can never move backwards.

        ``verify_ticket`` expires a ticket with ``now > expires_at + skew``.
        Wall-clock time is settable, so moving the system clock back extended
        every outstanding approval by the size of the jump — an expired ticket
        became redeemable again. The highest timestamp this installation has
        ever observed is persisted next to the approvals; a reading below it is
        replaced by it, so time only ever advances for expiry purposes.

        A persistence failure returns ``now`` unchanged rather than blocking:
        the ticket's signature, single-use consumption and argument digest all
        still bind, and this is a hardening layer on top of them.
        """
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT v FROM outbound_approval_meta WHERE k = 'clock_high_water'"
                ).fetchone()
                seen = float(row["v"]) if row is not None and row["v"] else 0.0
                if now > seen:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO outbound_approval_meta "
                        "(k, v) VALUES ('clock_high_water', ?)",
                        (repr(float(now)),),
                    )
                    self._conn.commit()
                    return now
            if seen > now:
                logger.error(
                    "System clock reads %.0f but this installation has already "
                    "seen %.0f — using the later value so a backwards clock "
                    "cannot un-expire an approval ticket.", now, seen,
                )
            return max(now, seen)
        except (sqlite3.Error, TypeError, ValueError) as exc:  # pragma: no cover
            logger.warning("Clock high-water check unavailable: %s", exc)
            return now

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        session_id: str,
        tool_name: str,
        args: dict[str, Any],
        preview: str = "",
    ) -> OutboundApproval:
        """Record a pending approval.

        Redaction happens HERE, not at the call site, so a caller that forgets
        to redact still cannot leak a credential into the database.
        """
        approval_id = uuid.uuid4().hex[:12]
        now = time.time()

        safe_args = canonical_args(args)
        digest = compute_args_digest(tool_name, args)
        canonical = resolve_tool(tool_name, args=args).canonical
        args_json = json.dumps(safe_args, default=str, ensure_ascii=False)

        # A caller-supplied preview is a free-text string that may itself carry
        # a secret; scrub it. An empty preview is generated (already redacted).
        safe_preview = (
            redact_text(str(preview))[:4000]
            if preview
            else build_preview(tool_name, args, limit=4000)
        )

        with self._lock:
            self._conn.execute(
                """INSERT INTO outbound_approvals
                   (id, session_id, tool_name, args_json, preview, status, created_at,
                    canonical_tool, args_digest)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (
                    approval_id, session_id, tool_name, args_json, safe_preview, now,
                    canonical, digest,
                ),
            )
            self._conn.commit()
        return OutboundApproval(
            id=approval_id,
            session_id=session_id,
            tool_name=tool_name,
            args=safe_args,
            preview=safe_preview,
            status=STATUS_PENDING,
            created_at=now,
            resolved_at=None,
            resolved_by="",
            canonical_tool=canonical,
            args_digest=digest,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, approval_id: str) -> Optional[OutboundApproval]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM outbound_approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_obj(row)

    def list_pending(self, limit: int = 50) -> list[OutboundApproval]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM outbound_approvals
                   WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self._row_to_obj(r) for r in rows]

    # ------------------------------------------------------------------
    # Resolve / approve
    # ------------------------------------------------------------------

    def resolve(
        self,
        approval_id: str,
        status: str,
        resolved_by: str = "operator",
    ) -> Optional[OutboundApproval]:
        """Approve or deny a pending approval.

        Approving mints the ticket; the row can only move out of ``pending``
        once, so a double-approve returns None.
        """
        if status not in (STATUS_APPROVED, STATUS_DENIED):
            return None
        now = time.time()

        ticket: Optional[ApprovalTicket] = None
        token = ""
        if status == STATUS_APPROVED:
            existing = self.get(approval_id)
            if existing is None or existing.status != STATUS_PENDING:
                return None
            ticket, token = issue_ticket(
                key=self._signing_key,
                approval_id=approval_id,
                tool_name=existing.tool_name,
                args=existing.args,
                session_id=existing.session_id,
                approved_by=resolved_by,
                now=now,
            )

        with self._lock:
            cur = self._conn.execute(
                """UPDATE outbound_approvals
                   SET status = ?, resolved_at = ?, resolved_by = ?,
                       ticket_id = ?, ticket_token = ?, expires_at = ?
                   WHERE id = ? AND status = 'pending'""",
                (
                    status, now, resolved_by,
                    ticket.ticket_id if ticket else "",
                    token,
                    ticket.expires_at if ticket else None,
                    approval_id,
                ),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get(approval_id)

    def approve(
        self, approval_id: str, resolved_by: str = "operator"
    ) -> Optional[tuple[OutboundApproval, str]]:
        """Approve and return ``(approval, ticket_token)``."""
        row = self.resolve(approval_id, STATUS_APPROVED, resolved_by=resolved_by)
        if row is None:
            return None
        return row, self.ticket_token(approval_id)

    def ticket_token(self, approval_id: str) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT ticket_token FROM outbound_approvals WHERE id = ?",
                (approval_id,),
            ).fetchone()
        return (row["ticket_token"] if row else "") or ""

    # ------------------------------------------------------------------
    # Consume — the only sanctioned way to execute an approved action
    # ------------------------------------------------------------------

    def consume(
        self,
        approval_id: str,
        args: Any = None,
        token: Optional[str] = None,
        now: Optional[float] = None,
    ) -> tuple[ApprovalTicket, dict[str, Any]]:
        """Redeem an approval exactly once.

        Verifies signature, expiry, tool scope and argument digest, then marks
        the ticket consumed atomically. Returns ``(ticket, approved_args)`` —
        callers MUST execute ``approved_args``, not their own copy.

        Raises :class:`TicketError` for every failure mode: not found, not
        approved, already consumed, expired, tampered, wrong tool, or arguments
        that changed after approval.
        """
        row = self.get(approval_id)
        if row is None:
            raise TicketError("approval_not_found")
        if row.status == STATUS_CONSUMED or row.consumed_at is not None:
            raise TicketError("ticket_already_consumed")
        if row.status != STATUS_APPROVED:
            raise TicketError(f"approval_status_{row.status}")

        supplied_token = token if token is not None else self.ticket_token(approval_id)
        # Default to the approved payload. Passing args re-checks the digest of
        # what the caller is about to run against what the operator approved.
        check_args = row.args if args is None else args

        # Expiry is evaluated against a clock that cannot run backwards.
        effective_now = self._clock_floor(time.time() if now is None else now)

        ticket = verify_ticket(
            key=self._signing_key,
            token=supplied_token,
            tool_name=row.tool_name,
            args=check_args,
            approval_id=approval_id,
            now=effective_now,
        )

        stamp = time.time() if now is None else now
        with self._lock:
            cur = self._conn.execute(
                """UPDATE outbound_approvals
                   SET status = 'consumed', consumed_at = ?
                   WHERE id = ? AND status = 'approved' AND consumed_at IS NULL""",
                (stamp, approval_id),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                # Lost the race with a concurrent consumer.
                raise TicketError("ticket_already_consumed")

        # Mint the in-process execution grant only now — after the ticket has
        # verified AND been atomically marked consumed. A tool about to cause an
        # irreversible external effect takes this grant instead of trusting an
        # `approved` flag in its own arguments.
        grant_execution(ticket.tool, ticket.args_digest)
        return ticket, row.args

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _row_to_obj(self, row: sqlite3.Row) -> OutboundApproval:
        d = dict(row)
        return OutboundApproval(
            id=d["id"],
            session_id=d["session_id"],
            tool_name=d["tool_name"],
            args=json.loads(d["args_json"] or "{}"),
            preview=d.get("preview") or "",
            status=d["status"],
            created_at=float(d["created_at"]),
            resolved_at=d.get("resolved_at"),
            resolved_by=d.get("resolved_by") or "",
            canonical_tool=d.get("canonical_tool") or "",
            args_digest=d.get("args_digest") or "",
            ticket_id=d.get("ticket_id") or "",
            expires_at=d.get("expires_at"),
            consumed_at=d.get("consumed_at"),
        )


_store: Optional[OutboundApprovalStore] = None


def get_approval_store() -> OutboundApprovalStore:
    global _store
    if _store is None:
        _store = OutboundApprovalStore()
    return _store


def requires_approval(
    tool_name: str,
    args: dict[str, Any],
    context: Optional[ApprovalContext] = None,
) -> bool:
    """Does this call need a human?

    Resolved from the declarative policy, not a literal list. Unknown tools,
    malformed args and unparseable names all return True.

    ``context`` is the caller's authorization context — a Python object the
    model cannot forge through a JSON tool call. It is the ONLY thing that can
    downgrade a requirement, and only for tools the policy marks
    ``simulation_exempt``. ``args["dry_run"]`` and ``args["draft_only"]``
    are ignored for routing purposes.
    """
    return evaluate(tool_name, args, context=context).requires_approval


def approval_decision(
    tool_name: str,
    args: dict[str, Any],
    context: Optional[ApprovalContext] = None,
):
    """Full :class:`PolicyDecision` — tier, reason, and any bypass attempt."""
    return evaluate(tool_name, args, context=context)


__all__ = [
    "ApprovalContext",
    "ApprovalTicket",
    "OutboundApproval",
    "OutboundApprovalStore",
    "STATUS_APPROVED",
    "STATUS_CONSUMED",
    "STATUS_DENIED",
    "STATUS_PENDING",
    "TicketError",
    "approval_decision",
    "build_preview",
    "get_approval_store",
    "requires_approval",
]
