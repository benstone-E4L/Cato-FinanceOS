"""
cato/receipt.py — Signed fare receipt built on the audit log.

Generates a human-readable and machine-readable billing transcript
for a completed session — one row per action, one hash per row.

CLI: `cato receipt --session <id>`

The signed_hash is SHA-256 of all row_hash values concatenated,
providing a single verifiable fingerprint for the entire session.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .audit import AuditLog


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ReceiptLine:
    """One billable action within a session."""
    index: int
    tool_name: str
    cost_cents: int
    timestamp: float
    row_hash: str
    action_type: str = ""
    error: str = ""


@dataclass
class Receipt:
    """Signed billing transcript for one session."""
    session_id: str
    actions: list[ReceiptLine] = field(default_factory=list)
    total_cents: int = 0
    signed_hash: str = ""          # SHA-256 of all row_hash values concatenated
    generated_at: float = field(default_factory=time.time)
    error_count: int = 0
    start_ts: Optional[float] = None
    end_ts: Optional[float] = None


# ---------------------------------------------------------------------------
# ReceiptWriter
# ---------------------------------------------------------------------------

class ReceiptWriter:
    """
    Builds Receipt objects from an AuditLog and renders them as text or JSONL.

    Usage::

        from cato.audit import AuditLog
        from cato.receipt import ReceiptWriter

        log = AuditLog()
        log.connect()
        writer = ReceiptWriter()
        receipt = writer.generate("sess-001", log)
        print(writer.export_text(receipt))
    """

    def generate(self, session_id: str, audit_log: "AuditLog") -> Receipt:
        """
        Build a Receipt for *session_id* from the audit log.

        Fetches all rows for the session, constructs ReceiptLine objects,
        computes the signed_hash from the hash chain, and returns a Receipt.
        """
        audit_log._ensure_connected()
        assert audit_log._conn is not None

        rows = audit_log._conn.execute(
            """
            SELECT id, action_type, tool_name, cost_cents, error, timestamp, row_hash
            FROM audit_log
            WHERE session_id = ?
            ORDER BY id
            """,
            (session_id,),
        ).fetchall()

        lines: list[ReceiptLine] = []
        total = 0
        error_count = 0
        hashes: list[str] = []

        for i, row in enumerate(rows):
            line = ReceiptLine(
                index=i + 1,
                tool_name=row["tool_name"],
                cost_cents=row["cost_cents"],
                timestamp=row["timestamp"],
                row_hash=row["row_hash"],
                action_type=row["action_type"],
                error=row["error"] or "",
            )
            lines.append(line)
            total += row["cost_cents"]
            hashes.append(row["row_hash"])
            if row["error"]:
                error_count += 1

        # Compute signed hash: SHA-256 of all row hashes concatenated
        combined = "".join(hashes)
        signed_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest() if hashes else ""

        timestamps = [r["timestamp"] for r in rows]
        return Receipt(
            session_id=session_id,
            actions=lines,
            total_cents=total,
            signed_hash=signed_hash,
            error_count=error_count,
            start_ts=min(timestamps) if timestamps else None,
            end_ts=max(timestamps) if timestamps else None,
        )

    def export_text(self, receipt: Receipt) -> str:
        """
        Render a Receipt as a human-readable text table.

        Example output::

            ============================================================
            CATO SESSION RECEIPT
            Session: sess-001
            Generated: 2026-03-04T12:00:00
            ============================================================
            #    Tool                Action       Cost   Error
            ---  ------------------  -----------  -----  -----
            1    browser.navigate    tool_call    1¢
            2    browser.click       tool_call    1¢
            ...
            ============================================================
            Total: 7¢  ($0.07)   Actions: 5   Errors: 0
            Signed: abc123...
            ============================================================
        """
        import datetime

        lines = [
            "=" * 64,
            "CATO SESSION RECEIPT",
            f"Session:   {receipt.session_id}",
        ]
        if receipt.generated_at:
            ts = datetime.datetime.fromtimestamp(receipt.generated_at, tz=datetime.timezone.utc)
            lines.append(f"Generated: {ts.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        if receipt.start_ts and receipt.end_ts:
            start = datetime.datetime.fromtimestamp(receipt.start_ts, tz=datetime.timezone.utc)
            end = datetime.datetime.fromtimestamp(receipt.end_ts, tz=datetime.timezone.utc)
            duration = receipt.end_ts - receipt.start_ts
            lines.append(f"Duration:  {duration:.1f}s  ({start.strftime('%H:%M:%S')} - {end.strftime('%H:%M:%S')} UTC)")
        lines.append("=" * 64)

        if receipt.actions:
            lines.append(f"{'#':<4} {'Tool':<22} {'Type':<14} {'Cost':>6}  {'Error'}")
            lines.append("-" * 64)
            for action in receipt.actions:
                cost_str = f"{action.cost_cents}c" if action.cost_cents else "0c"
                err = ("ERR: " + action.error[:30]) if action.error else ""
                lines.append(
                    f"{action.index:<4} {action.tool_name:<22} {action.action_type:<14}"
                    f" {cost_str:>6}  {err}"
                )
        else:
            lines.append("  (no actions recorded)")

        lines.append("=" * 64)
        total_usd = receipt.total_cents / 100
        lines.append(
            f"Total: {receipt.total_cents}c  (${total_usd:.4f})"
            f"   Actions: {len(receipt.actions)}"
            f"   Errors: {receipt.error_count}"
        )
        lines.append(f"Signed: {receipt.signed_hash[:32]}..." if receipt.signed_hash else "Signed: (empty)")
        lines.append("=" * 64)
        return "\n".join(lines)

    def export_jsonl(self, receipt: Receipt) -> str:
        """
        Render a Receipt as machine-readable JSONL.

        First line: session metadata.
        Subsequent lines: one ReceiptLine per line.
        Last line: summary with signed hash.
        """
        output_lines: list[str] = []

        # Header
        output_lines.append(json.dumps({
            "type": "session_header",
            "session_id": receipt.session_id,
            "generated_at": receipt.generated_at,
            "start_ts": receipt.start_ts,
            "end_ts": receipt.end_ts,
        }, ensure_ascii=True))

        # Action lines
        for action in receipt.actions:
            output_lines.append(json.dumps({
                "type": "action",
                "index": action.index,
                "tool_name": action.tool_name,
                "action_type": action.action_type,
                "cost_cents": action.cost_cents,
                "timestamp": action.timestamp,
                "row_hash": action.row_hash,
                "error": action.error,
            }, ensure_ascii=True))

        # Footer / summary
        output_lines.append(json.dumps({
            "type": "session_summary",
            "session_id": receipt.session_id,
            "total_cents": receipt.total_cents,
            "total_usd": round(receipt.total_cents / 100, 4),
            "action_count": len(receipt.actions),
            "error_count": receipt.error_count,
            "signed_hash": receipt.signed_hash,
        }, ensure_ascii=True))

        return "\n".join(output_lines)
