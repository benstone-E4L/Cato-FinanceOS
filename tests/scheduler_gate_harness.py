"""
tests/scheduler_gate_harness.py — a REAL gate chain behind a fake gateway.

Not a test module (no ``test_`` prefix, so pytest does not collect it). It
exists because the t19 fix makes ``cato.core.scheduled_dispatch`` fail closed
when the safety/approval/ledger chain is unreachable: a scheduler test that
wants to observe the gates must therefore supply real ones.

Everything here is the REAL production class — SafetyGuard, TokenChecker,
ActionGuard, OutboundApprovalStore, LedgerMiddleware — with every persistent
store isolated under tmp_path. The only fakes are the transport-shaped seams
(gateway send/ingest), and no network call is made from this file.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import cato.agent_loop as agent_loop_mod
from cato.agent_loop import AgentLoop
from cato.audit import AuditLog
from cato.audit.ledger import LedgerMiddleware, LedgerQuery
from cato.budget import BudgetManager
from cato.config import CatoConfig
from cato.core.context_builder import ContextBuilder
from cato.core.memory import MemorySystem
from cato.core.outbound_approval import OutboundApprovalStore
from cato.safety import SafetyGuard


class FakeVault:
    """In-memory vault stand-in. Never touches disk; never a real credential."""

    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data = dict(data or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


class HarnessGateway:
    """A gateway with a REAL AgentLoop gate chain and fake I/O edges.

    ``dispatch_scheduled_skill`` reaches the gates through ``_agent_loop``,
    exactly as the production Gateway does (cato/gateway.py:_ensure_agent_loop).
    """

    def __init__(self, agent_loop: AgentLoop, budget: BudgetManager, vault: FakeVault) -> None:
        self._agent_loop = agent_loop
        self._budget = budget
        self._vault = vault
        self._cfg = SimpleNamespace(agent_name="cato-test")
        self.sent: list[tuple[str, str, str]] = []
        self.ingested: list[tuple[str, str, str, str]] = []

    async def send(self, session_id: str, text: str, channel: str) -> None:
        self.sent.append((session_id, text, channel))

    async def ingest(self, session_id: str, text: str, channel: str, agent_id: str) -> None:
        self.ingested.append((session_id, text, channel, agent_id))


def build_scheduler_gate_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    shell_exec_allowed: bool = True,
):
    """Build a HarnessGateway whose every gate is the real production class.

    ``safety_mode="off"``: see cato/safety.py's module docstring and the same
    choice in tests/test_control_chain_e2e.py::build_chain_env. A headless
    daemon has no TTY, so strict/permissive make check_and_confirm() deny any
    HIGH_STAKES tool outright and dispatch would stop BEFORE the approval-ticket
    gate — which is the gate these tests exist to observe. "off" still refuses
    any unclassified tool (fail-closed) and does not disable the ticket system.
    """
    monkeypatch.setattr(SafetyGuard, "_stop_file_path", staticmethod(lambda: tmp_path / "STOP"))
    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)

    approval_store = OutboundApprovalStore(db_path=tmp_path / "approvals.db")
    monkeypatch.setattr("cato.core.outbound_approval._store", approval_store)

    vault = FakeVault({})
    config = CatoConfig(
        default_model="claude-sonnet-5",
        workspace_dir=str(tmp_path / "workspace"),
        safety_mode="off",
        audit_enabled=True,
        auto_approved_tools=[],
        strict_approval=False,
    )
    budget = BudgetManager(
        budget_path=tmp_path / "budget.json",
        daily_cap=1000.0, monthly_cap=5000.0, session_cap=1000.0,
    )
    memory = MemorySystem(agent_id="sched-gate", memory_dir=tmp_path / "memory")
    audit_log = AuditLog(db_path=tmp_path / "audit_legacy.db")
    audit_log.connect()

    loop = AgentLoop(
        config=config,
        budget=budget,
        vault=vault,
        memory=memory,
        context_builder=ContextBuilder(),
        audit_log=audit_log,
        safety_guard=SafetyGuard(config={
            "safety_mode": "off",
            "shell_exec_allowed": shell_exec_allowed,
        }),
    )
    loop._ledger = LedgerMiddleware(db_path=tmp_path / "ledger.db")
    loop._ledger_required = True

    monkeypatch.setattr(agent_loop_mod, "_CATO_DIR", tmp_path / "cato_data")

    # ORDER-INDEPENDENCE: _TOOL_REGISTRY is process-global. ``AgentLoop.__init__``
    # registers "shell.exec"; only ``cato.tools.register_all_tools()`` registers a
    # BARE "shell". If an earlier test module ran that, ``_resolve_tool_name`` stops
    # at "shell" (which IS in _DEFAULT_ALLOWED_TOOLS) instead of resolving to
    # "shell.exec" (which is not), so a different gate fires first and these tests
    # become dependent on which modules ran before them. Pin the registry to what
    # THIS AgentLoop registered; monkeypatch restores the entry afterwards.
    if "shell" in agent_loop_mod._TOOL_REGISTRY:
        monkeypatch.delitem(agent_loop_mod._TOOL_REGISTRY, "shell")

    gateway = HarnessGateway(loop, budget, vault)
    return SimpleNamespace(
        gateway=gateway,
        loop=loop,
        approval_store=approval_store,
        ledger_path=tmp_path / "ledger.db",
        tmp_path=tmp_path,
        config=config,
    )


def ledger_kinds(ledger_path: Path) -> list[str]:
    q = LedgerQuery(db_path=ledger_path)
    try:
        return [r.entry_kind for r in q.last_n(1000)]
    finally:
        q.close()


def ledger_rows(ledger_path: Path, kind: str) -> list:
    q = LedgerQuery(db_path=ledger_path)
    try:
        return q.by_entry_kind(kind)
    finally:
        q.close()
