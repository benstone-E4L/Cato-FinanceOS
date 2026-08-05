"""
cato/audit — Audit, ledger, and reversibility subsystem.

Re-exports AuditLog from audit_log.py to preserve the existing
`from cato.audit import AuditLog` import pattern across the codebase.
"""
from .audit_log import AuditLog

__all__ = ["AuditLog"]
