"""cato/audit/recovery.py — the ledger crash-recovery scan, run at daemon boot.

An INTENT with no terminal entry (CONFIRMED / FAILED / DENIED / RECOVERED)
means a previous process died between "we are about to do this" and "we did /
did not do it". The real-world effect is UNKNOWN and a human must reconcile it.

This scan used to have exactly one call site: the per-message run path in
``AgentLoop.run``. The AgentLoop is constructed lazily on the first message
(``Gateway._ensure_agent_loop``), so an operator who restarted after a crash and
did not happen to send a chat message was never told — even though the log line
says "found at startup". This module gives the scan a real startup trigger that
does not depend on the AgentLoop existing, needs no LLM, and cannot block boot.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: How many action descriptors to carry in the log line and health payload.
_MAX_REPORTED = 10

_LAST_SCAN: Optional[dict[str, Any]] = None


def _describe(records: list[Any]) -> list[dict[str, Any]]:
    described: list[dict[str, Any]] = []
    for record in records[:_MAX_REPORTED]:
        described.append(
            {
                "tool_name": getattr(record, "tool_name", None),
                "timestamp": getattr(record, "timestamp", None),
                "action_id": getattr(record, "action_id", None),
                "session_id": getattr(record, "session_id", None),
            }
        )
    return described


def run_startup_recovery_scan(db_path: Optional[Path] = None) -> dict[str, Any]:
    """Scan the ledger for unresolved INTENTs and unreconciled unknowns.

    Never raises: a ledger that cannot be opened must not stop the daemon from
    booting, but it must not be reported as clean either — ``error`` is set and
    ``clean`` is False so /health shows degraded rather than a green light.
    """
    global _LAST_SCAN

    result: dict[str, Any] = {
        "scanned_at": time.time(),
        "clean": False,
        "unresolved_intents": 0,
        "unreconciled_indeterminate": 0,
        "actions": [],
        "indeterminate_actions": [],
        "error": None,
    }

    query: Any = None
    try:
        from cato.audit.ledger import LedgerQuery

        query = LedgerQuery(db_path=db_path)
        orphans = list(query.unresolved_intents())
        unknown = list(query.unreconciled_indeterminate())
    except BaseException as exc:  # LedgerError derives from BaseException
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.error(
            "LEDGER RECOVERY: startup scan could not run (%s). Treat the ledger "
            "state as UNVERIFIED until 'cato doctor' succeeds.",
            result["error"],
        )
        _LAST_SCAN = result
        return result
    finally:
        if query is not None:
            try:
                query.close()
            except BaseException:  # noqa: BLE001 — close must never mask the scan
                logger.debug("Ledger recovery scan: close() failed", exc_info=True)

    result["unresolved_intents"] = len(orphans)
    result["unreconciled_indeterminate"] = len(unknown)
    result["actions"] = _describe(orphans)
    result["indeterminate_actions"] = _describe(unknown)
    result["clean"] = not orphans and not unknown

    if orphans:
        logger.critical(
            "LEDGER RECOVERY: %d unresolved INTENT(s) found at startup — a "
            "previous run died mid-action and the real-world effect is "
            "UNKNOWN. Reconcile with ledger.record_recovery(). Actions: %s",
            len(orphans),
            ", ".join(
                f"{r.tool_name}@{r.timestamp}(action={r.action_id})"
                for r in orphans[:_MAX_REPORTED]
            ),
        )
    if unknown:
        logger.critical(
            "LEDGER RECOVERY: %d action(s) with an UNKNOWN real-world outcome "
            "are awaiting reconciliation at startup. Do NOT re-issue these "
            "requests until each is confirmed against the remote. Actions: %s",
            len(unknown),
            ", ".join(
                f"{r.tool_name}@{r.timestamp}(action={r.action_id})"
                for r in unknown[:_MAX_REPORTED]
            ),
        )
    if result["clean"]:
        logger.info("Ledger recovery scan: no unresolved INTENTs at startup.")

    _LAST_SCAN = result
    return result


def get_last_recovery_scan() -> Optional[dict[str, Any]]:
    """Return the most recent startup scan result, or None if it never ran."""
    return _LAST_SCAN


def reset_recovery_scan() -> None:
    """Clear the cached scan result. For tests and for a re-scan on restart."""
    global _LAST_SCAN
    _LAST_SCAN = None
