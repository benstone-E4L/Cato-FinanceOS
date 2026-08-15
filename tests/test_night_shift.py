"""Night-shift policy, outbound approval, and outreach tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from cato.core.night_shift_policy import NightShiftPolicy, load_night_shift_policy
from cato.core.outbound_approval import (
    OutboundApprovalStore,
    requires_approval,
)


@pytest.fixture
def policy_yaml(tmp_path: Path, monkeypatch) -> Path:
    data = {
        "version": "1.0",
        "gates": {"g1_manual_loop_proven": False},
        "outreach": {"phase": "manual"},
        "forbidden_until_g1": ["flow.run:conduitscore-revenue-loop"],
    }
    p = tmp_path / "night-shift-policy.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    monkeypatch.setattr(
        "cato.core.night_shift_policy._cached",
        None,
    )
    return p


def test_policy_blocks_outbound_without_g1(policy_yaml: Path) -> None:
    policy = load_night_shift_policy(policy_yaml, reload=True)
    blocked, reason = policy.blocks_skill("send_email", {"draft_only": False})
    assert blocked is True
    assert "G1" in reason or "disabled" in reason.lower()


def test_policy_allows_draft_only(policy_yaml: Path) -> None:
    policy = load_night_shift_policy(policy_yaml, reload=True)
    blocked, _ = policy.blocks_skill("send_email", {"draft_only": True})
    assert blocked is False


def test_policy_blocks_flow_without_dry_run() -> None:
    policy = NightShiftPolicy(gates={"g1_manual_loop_proven": False})
    blocked, reason = policy.blocks_flow_def({
        "name": "conduitscore-revenue-loop",
        "dry_run": False,
    })
    assert blocked is True
    assert "G1" in reason or "dry_run" in reason


def test_policy_allows_dry_run_flow() -> None:
    policy = NightShiftPolicy(gates={"g1_manual_loop_proven": False})
    blocked, _ = policy.blocks_flow_def({
        "name": "conduitscore-revenue-loop",
        "dry_run": True,
    })
    assert blocked is False


def test_requires_approval_for_live_send() -> None:
    """Outbound sends always gate.

    CHANGED (t06): this test previously asserted that
    ``{"draft_only": True}`` and ``{"dry_run": True}`` REMOVED the approval
    requirement. Those args are supplied by the model, so the assertion was
    encoding the bypass as intended behaviour: any model that wanted to skip
    the human could add one key. A real dry-run must now be asserted by the
    caller via ApprovalContext (see test_approval_policy_engine.py), never by
    the payload.
    """
    assert requires_approval("send_email", {"draft_only": False}) is True
    assert requires_approval("send_email", {"draft_only": True}) is True
    assert requires_approval("outreach.run", {"dry_run": True}) is True


def test_approval_store_create_resolve(tmp_path: Path) -> None:
    db = tmp_path / "cato.db"
    store = OutboundApprovalStore(db_path=db)
    row = store.create("sess-1", "send_email", {"to": "a@b.com"}, preview="hi")
    assert row.status == "pending"
    denied = store.resolve(row.id, "denied", resolved_by="test")
    assert denied is not None
    assert denied.status == "denied"


@pytest.mark.asyncio
async def test_send_email_draft_only(policy_yaml: Path, monkeypatch) -> None:
    from cato.tools.send_email_tool import execute_send_email

    monkeypatch.setattr(
        "cato.core.night_shift_policy._cached",
        None,
    )
    load_night_shift_policy(policy_yaml, reload=True)
    out = await execute_send_email({
        "to": "test@example.com",
        "subject": "Hi",
        "body": "Body",
        "draft_only": True,
    })
    data = json.loads(out)
    assert data["ok"] is True
    assert data["mode"] == "draft_only"


@pytest.mark.asyncio
async def test_outreach_dry_run(policy_yaml: Path, monkeypatch, tmp_path: Path) -> None:
    from cato.tools.outreach_bridge import execute_outreach_run

    monkeypatch.setattr(
        "cato.core.night_shift_policy._cached",
        None,
    )
    load_night_shift_policy(policy_yaml, reload=True)

    artifact = tmp_path / "prospect.json"
    artifact.write_text(
        json.dumps({
            "domain": "example.com",
            "receiver_email": "ceo@example.com",
            "first_name": "Alex",
        }),
        encoding="utf-8",
    )

    out = await execute_outreach_run({
        "contact_id": "example.com",
        "artifact_path": str(artifact),
        "dry_run": True,
    })
    data = json.loads(out)
    assert data["ok"] is True
    if "mode" in data:
        assert data["mode"] == "dry_run"
    elif data.get("stdout"):
        payload = json.loads(data["stdout"].strip().splitlines()[-1])
        assert payload.get("ok") is True


@pytest.mark.asyncio
async def test_outreach_transport_fails_closed_without_starting_subprocess(
    monkeypatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    import cato.core.night_shift_policy as policy_mod
    from cato.tools import outreach_bridge

    engine_root = tmp_path / "engine"
    (engine_root / "src").mkdir(parents=True)
    secret_value = uuid4().hex
    monkeypatch.setenv("BREVO_SMTP_KEY", secret_value)
    monkeypatch.setattr(policy_mod, "assert_skill_allowed", lambda *_a, **_k: None)
    monkeypatch.setattr(
        policy_mod,
        "load_night_shift_policy",
        lambda: SimpleNamespace(paths={}),
    )
    monkeypatch.setattr(
        outreach_bridge,
        "_resolve_engine_root",
        lambda *_a, **_k: engine_root,
    )
    spawn = AsyncMock()
    monkeypatch.setattr(outreach_bridge.asyncio, "create_subprocess_exec", spawn)

    result = json.loads(
        await outreach_bridge.execute_outreach_run(
            {"contact_id": "synthetic-contact", "dry_run": False}
        )
    )

    assert result["ok"] is False
    assert result["error"] == "secure_outreach_entrypoint_unavailable"
    assert secret_value not in json.dumps(result)
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_outreach_uses_stdin_envelope_and_safe_environment(
    monkeypatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    import cato.core.night_shift_policy as policy_mod
    from cato.tools import outreach_bridge

    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    runner = engine_root / "run_batch.py"
    runner.write_text("# synthetic runner", encoding="utf-8")
    canary = uuid4().hex
    env_noise = uuid4().hex
    monkeypatch.setenv("CONDUITSCORE_API_KEY", env_noise)
    monkeypatch.setattr(policy_mod, "assert_skill_allowed", lambda *_a, **_k: None)
    monkeypatch.setattr(
        policy_mod,
        "load_night_shift_policy",
        lambda: SimpleNamespace(paths={}),
    )
    monkeypatch.setattr(
        outreach_bridge,
        "_resolve_engine_root",
        lambda *_a, **_k: engine_root,
    )

    class FakeVault:
        def get(self, key: str):
            return canary if key == "CONDUITSCORE_API_KEY" else None

    monkeypatch.setattr("cato.vault.Vault", FakeVault)
    proc = SimpleNamespace(
        returncode=0,
        communicate=AsyncMock(
            return_value=(b'{"ok":true,"mode":"dry_run"}\n', b"")
        ),
        kill=MagicMock(),
    )
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(outreach_bridge.asyncio, "create_subprocess_exec", spawn)

    result = json.loads(
        await outreach_bridge.execute_outreach_run(
            {"contact_id": "synthetic-contact", "dry_run": True}
        )
    )

    assert result["ok"] is True
    assert result["mode"] == "dry_run"
    call = spawn.await_args
    assert call.kwargs["stdin"] is outreach_bridge.asyncio.subprocess.PIPE
    assert call.kwargs["stdout"] is outreach_bridge.asyncio.subprocess.PIPE
    assert call.kwargs["stderr"] is outreach_bridge.asyncio.subprocess.PIPE
    assert canary not in call.args
    assert env_noise not in call.args
    assert canary not in call.kwargs["env"].values()
    assert env_noise not in call.kwargs["env"].values()
    assert call.kwargs["env"]["CATO_OUTREACH_DRY_RUN"] == "1"
    sent = proc.communicate.await_args.kwargs["input"]
    assert canary in sent.decode("utf-8")
    assert env_noise not in sent.decode("utf-8")
    assert canary not in json.dumps(result)


@pytest.mark.asyncio
async def test_outreach_missing_vault_key_fails_before_subprocess(
    monkeypatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import cato.core.night_shift_policy as policy_mod
    from cato.tools import outreach_bridge

    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    (engine_root / "run_batch.py").write_text("# synthetic runner", encoding="utf-8")
    monkeypatch.setattr(policy_mod, "assert_skill_allowed", lambda *_a, **_k: None)
    monkeypatch.setattr(
        policy_mod,
        "load_night_shift_policy",
        lambda: SimpleNamespace(paths={}),
    )
    monkeypatch.setattr(
        outreach_bridge,
        "_resolve_engine_root",
        lambda *_a, **_k: engine_root,
    )

    class EmptyVault:
        def get(self, key: str):
            return None

    monkeypatch.setattr("cato.vault.Vault", EmptyVault)
    spawn = AsyncMock()
    monkeypatch.setattr(outreach_bridge.asyncio, "create_subprocess_exec", spawn)

    result = json.loads(
        await outreach_bridge.execute_outreach_run(
            {"contact_id": "synthetic-contact", "dry_run": True}
        )
    )

    assert result["ok"] is False
    assert result["error"] == "outreach_credentials_unavailable"
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_loop_gates_outbound_tool(monkeypatch) -> None:
    from cato.agent_loop import AgentLoop, ToolCall

    loop = MagicMock(spec=AgentLoop)
    loop._audit_log = None
    loop._outbound_notify = None

    store = OutboundApprovalStore(db_path=Path(":memory:"))
    monkeypatch.setattr(
        "cato.core.outbound_approval._store",
        store,
    )

    tc = ToolCall(
        name="send_email",
        args={"to": "x@y.com", "subject": "s", "body": "b", "draft_only": False},
        call_id="1",
    )
    result = await AgentLoop._maybe_gate_outbound_tool(loop, tc, "telegram:1")
    data = json.loads(result)
    assert data["error"] == "approval_required"
    assert "approval_id" in data
    store.close()
