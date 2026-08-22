"""Tests for Xero scope map and posting policy (2026-08-22 model)."""

from __future__ import annotations

import json
import pytest

from cato.posting_policy import cato_may_execute
from cato.xero_scope import (
    build_dispatch_scope_params,
    load_scope_map,
    operation_allowed,
    scope_map_version,
    validate_scope_map_structure,
)


def test_scope_map_loads() -> None:
    assert scope_map_version() == "1.0.0"


def test_scope_map_yaml_structure_valid() -> None:
    validate_scope_map_structure(load_scope_map())
    contacts = (load_scope_map().get("scopes") or {}).get("accounting.contacts") or {}
    assert "genesis-e4l-ap" in contacts.get("primary_write", [])


def test_ap_may_create_draft_bill() -> None:
    ok, reason = operation_allowed("genesis-e4l-ap", "create_draft_bill")
    assert ok is True
    assert reason == "primary_write"


def test_fs_integrity_cannot_post_bill() -> None:
    ok, reason = operation_allowed("genesis-e4l-fs-integrity", "create_draft_bill")
    assert ok is False
    assert reason == "fs_integrity_write_forbidden"


def test_fs_integrity_may_read_tb() -> None:
    ok, _ = operation_allowed("genesis-e4l-fs-integrity", "get_trial_balance")
    assert ok is True


def test_dispatch_params_include_operations() -> None:
    params = build_dispatch_scope_params("genesis-e4l-ap")
    assert params["scope_map_version"] == "1.0.0"
    assert "create_draft_bill" in params["allowed_xero_operations"]
    assert params["executor_default"] == "genesis_specialist"


def test_cato_remediation_requires_reason() -> None:
    ok, reason = cato_may_execute(
        "create_draft_bill",
        execution_realm="cato_remediation",
        remediation_reason=None,
    )
    assert ok is False
    assert reason == "remediation_reason_required"


def test_cato_routine_bill_blocked_without_override() -> None:
    ok, reason = cato_may_execute(
        "create_draft_bill",
        execution_realm="cato_remediation",
        remediation_reason="fix typo",
    )
    assert ok is False
    assert reason == "routine_domain_must_use_specialist"


def test_cato_override_allowed() -> None:
    ok, reason = cato_may_execute(
        "create_draft_bill",
        execution_realm="cato_remediation",
        remediation_reason="override: specialist failed read-back",
    )
    assert ok is True
    assert reason == "ok"


@pytest.mark.asyncio
async def test_scope_injection_failure_blocks_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from cato.tools.genesis import GenesisTool

    def _boom(_slug: str) -> dict:
        raise RuntimeError("broken scope map")

    monkeypatch.setattr("cato.xero_scope.build_dispatch_scope_params", _boom)
    tool = GenesisTool(
        config=type("Cfg", (), {
            "genesis_enabled": True,
            "genesis_agent_allowlist": ["genesis-e4l-ap"],
        })(),
    )
    result = json.loads(
        await tool._execute_inner({
            "agent": "genesis-e4l-ap",
            "task": "test scope injection",
        })
    )
    assert result["ok"] is False
    assert result["error"] == "scope_map_injection_failed"
