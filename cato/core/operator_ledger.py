"""
cato/core/operator_ledger.py — ledger recording for OPERATOR-initiated actions.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This is NOT a second gate. It does not classify risk, ask for approval, or
authorize anything, and nothing here may ever be used in place of
:meth:`cato.agent_loop.AgentLoop.guarded_action`, which remains the single
pre-action gate for every model-reachable dispatch.

It exists because a handful of surfaces are genuinely operator-facing — they
are reachable only by a human holding the daemon token, and gating them would
break what they are for (you cannot ask for approval on every keystroke of an
interactive terminal). Those surfaces still spawn processes and still mutate
credentials, and an operator action that leaves no record is invisible to an
audit: after an incident there is no way to tell an operator's terminal
session apart from an attacker who stole the token.

So: gate what the model can reach; LEDGER what only the operator can reach.

FAIL CLOSED: if the INTENT entry cannot be durably written, the action does
not run. That is the same discipline ``AgentLoop._dispatch_recorded`` follows —
the record is written before the side effect, never after.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

_ledger: Any = None
_ledger_failed = False


def get_operator_ledger() -> Any:
    """Return the shared ledger writer, or None when it cannot be opened."""
    global _ledger, _ledger_failed
    if _ledger is not None or _ledger_failed:
        return _ledger
    try:
        from ..audit.ledger import LedgerMiddleware

        _ledger = LedgerMiddleware()
    except BaseException as exc:  # LedgerError derives from BaseException
        _ledger_failed = True
        logger.error("Operator ledger unavailable: %s", exc)
        return None
    return _ledger


def reset_operator_ledger() -> None:
    """Drop the cached writer (tests, and after a data-dir change)."""
    global _ledger, _ledger_failed
    if _ledger is not None:
        try:
            _ledger.close()
        except Exception:
            pass
    _ledger = None
    _ledger_failed = False


class OperatorLedgerUnavailable(RuntimeError):
    """The action was refused because it could not be recorded."""


async def record_operator_action(
    *,
    tool_name: str,
    tool_input: Any,
    session_id: str,
    run: Callable[[], Awaitable[Any]],
    actor: str = "operator",
    reversibility: float = 0.5,
    approval_ref: Optional[str] = None,
) -> Any:
    """Run ``run()`` inside a ledger INTENT and return its result.

    Writes INTENT → (await run()) → CONFIRMED, or FAILED with the exception,
    which is then re-raised unchanged. Raises
    :class:`OperatorLedgerUnavailable` WITHOUT running ``run`` when the ledger
    cannot record the intent.
    """
    ledger = get_operator_ledger()
    if ledger is None:
        raise OperatorLedgerUnavailable(
            f"refusing {tool_name!r}: the action ledger is unavailable, and an "
            "unrecorded operator action is invisible to an audit"
        )
    try:
        with ledger.recorded_action(
            tool_name=tool_name,
            tool_input=tool_input,
            agent_session_id=session_id,
            policy_decision="operator_initiated",
            policy_gate="operator_token",
            approval_ref=approval_ref,
            actor=actor,
            model_source="operator",
            reversibility=reversibility,
        ) as action:
            return await action.arun(run())
    except OperatorLedgerUnavailable:
        raise
    except BaseException as exc:
        from ..audit.ledger import LedgerError

        if isinstance(exc, LedgerError):
            raise OperatorLedgerUnavailable(
                f"refusing {tool_name!r}: ledger write failed ({exc})"
            ) from exc
        raise
