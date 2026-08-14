from __future__ import annotations

import os
from uuid import uuid4

import pytest

from cato.vault import Vault, VaultError
from cato.vault_bootstrap import (
    CANONICAL_KEY_ALIASES,
    OPERATOR_VAULT_KEYS,
    bootstrap_launch_credentials,
    migrate_env_to_vault,
    require_vault_password,
)


def _fresh_vault(tmp_path, monkeypatch):
    import cato.vault as vault_mod

    password = uuid4().hex
    monkeypatch.setattr(vault_mod, "_CACHED_VAULT_PASSWORD", None)
    monkeypatch.setenv("CATO_VAULT_PASSWORD", password)
    vault_path = tmp_path / "vault.enc"
    vault = Vault(vault_path=vault_path)
    vault.unlock(password, allow_create=True)
    return vault, vault_path, password


def test_require_vault_password_fails_when_unset(monkeypatch):
    import cato.vault as vault_mod

    monkeypatch.setattr(vault_mod, "_CACHED_VAULT_PASSWORD", None)
    monkeypatch.delenv("CATO_VAULT_PASSWORD", raising=False)
    with pytest.raises(VaultError, match="CATO_VAULT_PASSWORD"):
        require_vault_password()


def test_bootstrap_never_reads_repository_dotenv_or_exports_credentials(
    tmp_path, monkeypatch
):
    import cato.vault_bootstrap as bootstrap_mod

    vault, vault_path, _password = _fresh_vault(tmp_path, monkeypatch)
    vault_value = uuid4().hex
    process_value = uuid4().hex
    file_value = uuid4().hex
    vault.set("ANTHROPIC_API_KEY", vault_value)
    monkeypatch.setenv("ANTHROPIC_API_KEY", process_value)

    env_file = tmp_path / ".env"
    env_file.write_text(f"ANTHROPIC_API_KEY={file_value}\n", encoding="utf-8")
    monkeypatch.setattr(
        bootstrap_mod,
        "_read_dotenv_map",
        lambda _path: (_ for _ in ()).throw(AssertionError("dotenv was read")),
    )

    unlocked, report = bootstrap_launch_credentials(
        repo_root=tmp_path,
        vault_path=vault_path,
        env_file=env_file,
        require_password=True,
        load_dotenv=True,
    )

    assert unlocked is not None
    assert unlocked.get_stored("ANTHROPIC_API_KEY") == vault_value
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert report.applied_from_vault == ()
    assert report.filled_from_dotenv == ()
    assert report.env_file is None
    assert "CATO_VAULT_PASSWORD" not in os.environ


def test_bootstrap_unlocks_encrypted_vault_without_environment_export(
    tmp_path, monkeypatch
):
    vault, vault_path, _password = _fresh_vault(tmp_path, monkeypatch)
    stored_value = uuid4().hex
    vault.set("ANTHROPIC_API_KEY", stored_value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    unlocked, report = bootstrap_launch_credentials(
        vault_path=vault_path,
        require_password=True,
        load_dotenv=False,
    )

    assert unlocked is not None
    assert unlocked.get("ANTHROPIC_API_KEY") == stored_value
    assert report.vault_unlocked is True
    assert report.vault_keys_total >= 1
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "CATO_VAULT_PASSWORD" not in os.environ


def test_migrate_env_to_vault_is_explicit_and_lists_keys(tmp_path, monkeypatch):
    vault, vault_path, password = _fresh_vault(tmp_path, monkeypatch)
    values = {name: uuid4().hex for name in ("BREVO_API_KEY", "ANTHROPIC_API_KEY")}
    env_file = tmp_path / ".env"
    env_file.write_text(
        "".join(f"{name}={value}\n" for name, value in values.items()),
        encoding="utf-8",
    )

    report = migrate_env_to_vault(
        env_file=env_file,
        vault_path=vault_path,
        password=password,
        overwrite=False,
    )

    assert report.ok
    assert sorted(report.migrated) == sorted(values)
    reread = Vault(vault_path=vault_path)
    reread.unlock(password, allow_create=False)
    assert all(reread.get_stored(name) == value for name, value in values.items())
    assert all(name not in os.environ for name in values)


def test_migrate_skips_existing_without_overwrite(tmp_path, monkeypatch):
    vault, vault_path, password = _fresh_vault(tmp_path, monkeypatch)
    original = uuid4().hex
    candidate = uuid4().hex
    vault.set("BREVO_API_KEY", original)
    env_file = tmp_path / ".env"
    env_file.write_text(f"BREVO_API_KEY={candidate}\n", encoding="utf-8")

    report = migrate_env_to_vault(
        env_file=env_file,
        vault_path=vault_path,
        password=password,
        overwrite=False,
    )

    assert report.migrated == []
    assert "BREVO_API_KEY" in report.skipped_existing
    assert vault.get_stored("BREVO_API_KEY") == original


def test_operator_vault_keys_include_required_targets():
    required = {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "GITHUB_TOKEN",
        "PHOENIX_API_KEY",
        "FINANCEOS_CAPABILITY_TOKEN",
    }
    assert required <= set(OPERATOR_VAULT_KEYS)


def test_alias_map_only_covers_confirmed_legacy_names():
    assert CANONICAL_KEY_ALIASES == {
        "SWARMSYNC_API_KEY": ("SWARMSYNC_VERIFYAPI_KEY",),
        "SWARM_SYNC_API_KEY": ("SWARMSYNC_VERIFYAPI_KEY",),
        "GITHUB_TOKEN": ("GITHUB_FOXFIREPOETS_TOKEN",),
        "GH_TOKEN": ("GITHUB_FOXFIREPOETS_TOKEN",),
    }
