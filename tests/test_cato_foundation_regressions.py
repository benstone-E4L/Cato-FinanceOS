"""Regression proof for Cato data custody, config secrecy, and Gmail startup."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from cato.config import CatoConfig
from cato.platform import (
    get_data_dir,
    get_legacy_data_dirs,
    get_legacy_data_inventory,
)


def test_pytest_process_uses_private_cato_data_root():
    data_dir = get_data_dir().resolve()
    assert "cato-pytest-" in str(data_dir)
    assert data_dir.name == "cato"
    assert data_dir.parent.name == "appdata"


def test_platform_root_is_canonical_and_legacy_discovery_is_read_only(
    tmp_path, monkeypatch
):
    appdata = tmp_path / "appdata"
    canonical = appdata / "cato"
    legacy = tmp_path / "profile" / ".cato"
    legacy.mkdir(parents=True)
    marker = legacy / "operator-marker"
    marker.write_text("unchanged", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "profile")

    assert get_data_dir() == canonical
    assert get_legacy_data_dirs() == (legacy,)
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert not (canonical / "operator-marker").exists()


def test_legacy_inventory_names_state_without_copying_it(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    legacy = tmp_path / "profile" / ".cato"
    (legacy / "skills" / "one").mkdir(parents=True)
    (legacy / "agents" / "cato").mkdir(parents=True)
    (legacy / "workspace").mkdir(parents=True)
    (legacy / "config.yaml").write_text("agent_name: cato", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "profile")

    inventory = get_legacy_data_inventory()

    assert inventory[0]["present"] == ("config.yaml", "skills", "agents")
    assert inventory[0]["counts"] == {"skills": 1, "agents": 1}
    assert not (appdata / "cato" / "skills" / "one").exists()


def test_legacy_inventory_surfaces_stranded_key_material(tmp_path, monkeypatch):
    """Key material in a non-canonical root is the split-brain, not a leftover.

    store.key and conduit_identity.key protect records that live under the
    canonical root. An inventory that lists skills and databases but stays
    silent about the keys tells the operator the split is smaller than it is.
    """
    appdata = tmp_path / "appdata"
    legacy = tmp_path / "profile" / ".cato"
    legacy.mkdir(parents=True)
    for name in ("store.key", "conduit_identity.key", "vault.enc"):
        (legacy / name).write_bytes(b"x")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "profile")

    present = get_legacy_data_inventory()[0]["present"]

    assert "store.key" in present
    assert "conduit_identity.key" in present
    assert "vault.enc" in present
    # Read-only discovery: nothing is copied into the canonical root.
    assert not (appdata / "cato" / "store.key").exists()


def test_init_directory_contract_creates_canonical_skills_dir(tmp_path):
    from cato.cli import _ensure_data_dirs

    created = _ensure_data_dirs(tmp_path)

    assert tmp_path / "skills" in created
    assert (tmp_path / "skills").is_dir()


def test_status_surfaces_legacy_inventory_without_mutating_it(tmp_path):
    from cato.cli import main

    legacy = tmp_path / ".cato"
    marker = legacy / "skills" / "one" / "SKILL.md"
    marker.parent.mkdir(parents=True)
    marker.write_text("unchanged", encoding="utf-8")
    config = SimpleNamespace(
        _path=tmp_path / "config.yaml",
        workspace_dir=str(tmp_path / "workspace"),
        default_model="test-model",
        swarmsync_enabled=False,
        safety_mode="strict",
        conduit_enabled=False,
        webchat_port=8080,
        telegram_enabled=False,
        session_cap=1.0,
        monthly_cap=1.0,
        daily_cap=1.0,
    )
    inventory = ({
        "root": str(legacy),
        "present": ("skills",),
        "counts": {"skills": 1},
    },)
    budget = MagicMock()
    budget.get_status.return_value = {"daily_calls": 0, "monthly_calls": 0}
    budget.format_footer.return_value = "budget ok"

    with patch("cato.cli.CatoConfig.load", return_value=config), patch(
        "cato.cli._read_live_pid", return_value=None
    ), patch("cato.platform.get_legacy_data_inventory", return_value=inventory), patch(
        "cato.cli.BudgetManager", return_value=budget
    ):
        result = CliRunner().invoke(main, ["status"])

    assert result.exit_code == 0
    assert "Legacy data requires review" in result.output
    assert "skills" in result.output
    assert marker.read_text(encoding="utf-8") == "unchanged"


def test_plaintext_config_never_serializes_messaging_token(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = CatoConfig()
    cfg.telegram_bot_token = "token-that-must-not-persist"
    cfg.save(path)

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "telegram_bot_token" not in raw
    assert "token-that-must-not-persist" not in path.read_text(encoding="utf-8")
    assert "telegram_bot_token" not in cfg.to_dict()


@pytest.mark.asyncio
async def test_gmail_starts_without_telegram_and_is_registered_for_desktop():
    from cato.cli import _start_messaging_adapters

    gateway = SimpleNamespace(_adapters=[])
    gateway.register_adapter = gateway._adapters.append
    config = SimpleNamespace(telegram_enabled=False)
    vault = MagicMock()
    log = MagicMock()
    started = asyncio.Event()

    class FakeGmail:
        def __init__(self, vault):
            self._task = None
            self._router = None

        async def start(self):
            started.set()

    with patch("cato.adapters.gmail_adapter.GmailAdapter", FakeGmail), patch(
        "cato.router.ModelRouter", return_value=MagicMock()
    ):
        gmail = await _start_messaging_adapters(gateway, vault, config, log)
        await asyncio.wait_for(started.wait(), timeout=1)

    assert gmail is gateway._gmail_adapter
    assert gateway._adapters == []
    assert gmail._task is not None
    await gmail._task


def test_audit_public_import_resolves_to_package_implementation():
    import cato.audit
    from cato.audit.audit_log import AuditLog

    assert cato.audit.AuditLog is AuditLog
    assert Path(cato.audit.__file__).name == "__init__.py"
    assert not (Path(cato.__file__).parent / "audit.py").exists()
