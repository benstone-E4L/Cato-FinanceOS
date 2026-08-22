"""Cato remediation gate — call before any Cato-side Xero write.

Specialist domain posts use Genesis xero_scoped_invoke; this module guards
the separate Cato remediation lane when that path is wired.
"""

from __future__ import annotations

from typing import Literal

ExecutionRealm = Literal[
    "genesis_specialist",
    "cato_remediation",
    "production_worker",
    "demo_mcp",
]

ROUTINE_DOMAIN_OPERATIONS = frozenset({
    "create_draft_bill",
    "create_draft_invoice",
    "create_bank_transaction",
    "create_draft_manual_journal",
})


def cato_may_execute(
    operation: str,
    *,
    execution_realm: ExecutionRealm,
    remediation_reason: str | None = None,
) -> tuple[bool, str]:
    """Cato full books access; routine domain work must not use cato_remediation without reason."""
    if execution_realm != "cato_remediation":
        return False, "not_cato_remediation_path"
    if not remediation_reason or not remediation_reason.strip():
        return False, "remediation_reason_required"
    if operation in ROUTINE_DOMAIN_OPERATIONS and not remediation_reason.startswith("override:"):
        return False, "routine_domain_must_use_specialist"
    return True, "ok"


def default_executor_for_operation(operation: str) -> str:
    if operation in ROUTINE_DOMAIN_OPERATIONS:
        return "genesis_specialist"
    return "genesis_specialist"
