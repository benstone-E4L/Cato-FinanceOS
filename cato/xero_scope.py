"""Xero OAuth scope map loader and per-specialist tool allowlists.

Canonical map: cato/accounting/XERO_SCOPE_TO_AGENT_MAP.yaml
Amendment: docs/AMENDMENT_2026-08-22_POSTING_MODEL.md
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import os
import yaml

SCOPE_MAP_PATH = Path(__file__).resolve().parent / "accounting" / "XERO_SCOPE_TO_AGENT_MAP.yaml"

# Operation families specialists may invoke via xero_scoped_invoke on Genesis gateway.
OPERATION_SCOPE_FAMILY: dict[str, str] = {
    "create_draft_bill": "accounting.contacts",
    "create_draft_invoice": "accounting.invoices",
    "create_draft_manual_journal": "accounting.manualjournals",
    "create_bank_transaction": "accounting.banktransactions",
    "attach_file_to_bill": "accounting.attachments",
    "attach_file_to_invoice": "accounting.attachments",
    "get_trial_balance": "accounting.reports.trialbalance.read",
    "get_balance_sheet": "accounting.reports.balancesheet.read",
    "get_profit_and_loss": "accounting.reports.profitandloss.read",
    "list_open_payables": "accounting.contacts.read",
    "list_open_receivables": "accounting.contacts.read",
    "get_chart_of_accounts": "accounting.settings.read",
    "get_bank_summary": "accounting.reports.banksummary.read",
}

# Explicit operation owners (authoritative for posting model; YAML scopes are OAuth registry)
OPERATION_PRIMARY_AGENTS: dict[str, frozenset[str]] = {
    "create_draft_bill": frozenset({"genesis-e4l-ap"}),
    "create_draft_invoice": frozenset({"genesis-e4l-ar", "genesis-e4l-revenue", "genesis-e4l-shopify"}),
    "create_draft_manual_journal": frozenset({"genesis-e4l-journals", "genesis-e4l-intercompany", "genesis-e4l-close"}),
    "create_bank_transaction": frozenset({"genesis-e4l-cash", "genesis-e4l-treasury", "genesis-e4l-stripe"}),
    "attach_file_to_bill": frozenset({"genesis-e4l-ap"}),
    "attach_file_to_invoice": frozenset({"genesis-e4l-ar"}),
}

E4L_SPECIALIST_PREFIX = "genesis-e4l-"


@lru_cache(maxsize=1)
def load_scope_map() -> dict[str, Any]:
    if not SCOPE_MAP_PATH.is_file():
        return {"_meta": {}, "scopes": {}, "specialist_overrides": {}}
    with SCOPE_MAP_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    validate_scope_map_structure(data)
    return data


def validate_scope_map_structure(data: dict[str, Any]) -> None:
    """Raise ValueError when YAML scopes are flat (broken indentation)."""
    scopes = data.get("scopes") or {}
    if not isinstance(scopes, dict):
        raise ValueError("scope map scopes must be a mapping")
    for key, entry in scopes.items():
        if key in ("primary_write", "read", "cato_remediation", "policy_note"):
            raise ValueError(
                f"scope map YAML malformed: '{key}' is a top-level scopes key — "
                "indent primary_write/read under each scope family"
            )
        if entry is None:
            raise ValueError(f"scope map entry for {key!r} is null — check YAML indentation")
        if not isinstance(entry, dict):
            raise ValueError(f"scope map entry for {key!r} must be a mapping, got {type(entry).__name__}")


def scope_map_version() -> str:
    meta = load_scope_map().get("_meta") or {}
    return str(meta.get("schema_version", "0.0.0"))


def _expand_read(slug: str, entry: dict[str, Any]) -> list[str]:
    raw = entry.get("read") or []
    if raw == "all_specialists":
        meta = load_scope_map().get("_meta") or {}
        return list(meta.get("specialists") or [])
    return list(raw)


def _primary_write_slugs(scope_key: str) -> list[str]:
    entry = (load_scope_map().get("scopes") or {}).get(scope_key) or {}
    return list(entry.get("primary_write") or [])


def specialist_writes_forbidden(agent_slug: str) -> bool:
    overrides = (load_scope_map().get("specialist_overrides") or {})
    spec = overrides.get(agent_slug) or {}
    return bool(spec.get("writes_forbidden"))


def operation_allowed(agent_slug: str, operation: str) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    if not agent_slug.startswith(E4L_SPECIALIST_PREFIX):
        return False, "not_e4l_specialist"
    if specialist_writes_forbidden(agent_slug):
        family = OPERATION_SCOPE_FAMILY.get(operation, "")
        if family.endswith(".read") or operation.startswith("get_") or operation.startswith("list_"):
            return True, "read_only_specialist"
        return False, "fs_integrity_write_forbidden"
    primary = OPERATION_PRIMARY_AGENTS.get(operation)
    if primary is not None:
        if agent_slug in primary:
            return True, "primary_write"
        return False, f"operation_denied:{operation}"
    family = OPERATION_SCOPE_FAMILY.get(operation)
    if not family:
        return False, f"unknown_operation:{operation}"
    if family.endswith(".read"):
        entry = (load_scope_map().get("scopes") or {}).get(family) or {}
        return agent_slug in _expand_read(agent_slug, entry), "read_scope"
    allowed = agent_slug in _primary_write_slugs(family)
    return allowed, "primary_write" if allowed else f"scope_denied:{family}"


def allowed_operations(agent_slug: str) -> list[str]:
    out: list[str] = []
    for op in set(OPERATION_SCOPE_FAMILY) | set(OPERATION_PRIMARY_AGENTS):
        ok, _ = operation_allowed(agent_slug, op)
        if ok:
            out.append(op)
    return sorted(out)


def build_dispatch_scope_params(agent_slug: str) -> dict[str, Any]:
    """Inject into Genesis dispatch params from Cato."""
    realm = os.environ.get("CATO_EXECUTION_REALM", "demo_mcp").strip() or "demo_mcp"
    if realm == "cato_remediation":
        realm = "genesis_specialist"
    return {
        "scope_map_version": scope_map_version(),
        "allowed_xero_operations": allowed_operations(agent_slug),
        "executor_default": "genesis_specialist",
        "execution_realm": realm,
    }
