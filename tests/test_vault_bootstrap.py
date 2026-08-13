"""Tests for vault-preferring launch bootstrap and .env → vault migration.

Never asserts on secret *values* in stdout — only key names, sizes, and presence.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cato.vault import Vault, VaultError
from cato.vault_bootstrap import (
    OPERATOR_VAULT_KEYS,
    apply_vault_to_environ,
    bootstrap_launch_credentials,
    fill_environ_from_dotenv,
    migrate_env_to_vault,
    require_vault_password,
)


def test_require_vault_password_fails_when_unset(monkeypatch):
    monkeypatch.delenv("CATO_VAULT_PASSWORD", raising=False)
    import cato.vault as vault_mod

    monkeypatch.setattr(vault_mod, "_CACHED_VAULT_PASSWORD", None)
    with pytest.raises(VaultError, match="CATO_VAULT_PASSWORD"):
        require_vault_password()


def test_fill_environ_from_dotenv_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=from-dotenv\nOPENROUTER_API_KEY=or-from-dotenv\n",
        encoding="utf-8",
    )
    environ = {"TELEGRAM_BOT_TOKEN": "already-set"}
    filled = fill_environ_from_dotenv(env_file, environ=environ)
    assert "OPENROUTER_API_KEY" in filled
    assert "TELEGRAM_BOT_TOKEN" not in filled
    assert environ["TELEGRAM_BOT_TOKEN"] == "already-set"
    assert environ["OPENROUTER_API_KEY"] == "or-from-dotenv"


def test_apply_vault_prefers_vault_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("CATO_VAULT_PASSWORD", "unit-test-vault-pw")
    import cato.vault as vault_mod

    monkeypatch.setattr(vault_mod, "_CACHED_VAULT_PASSWORD", None)

    vault_path = tmp_path / "vault.enc"
    vault = Vault(vault_path=vault_path)
    vault.unlock("unit-test-vault-pw", allow_create=True)
    vault.set("TELEGRAM_BOT_TOKEN", "vault-telegram")
    vault.set("OPENROUTER_API_KEY", "vault-openrouter")

    environ = {
        "TELEGRAM_BOT_TOKEN": "dotenv-telegram",
        "OPENROUTER_API_KEY": "dotenv-openrouter",
        "ANTHROPIC_API_KEY": "dotenv-only",
    }
    applied = apply_vault_to_environ(vault, environ=environ)
    assert "TELEGRAM_BOT_TOKEN" in applied
    assert "OPENROUTER_API_KEY" in applied
    assert environ["TELEGRAM_BOT_TOKEN"] == "vault-telegram"
    assert environ["OPENROUTER_API_KEY"] == "vault-openrouter"
    assert environ["ANTHROPIC_API_KEY"] == "dotenv-only"


def test_bootstrap_launch_credentials_prefers_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("CATO_VAULT_PASSWORD", "bootstrap-pw")
    import cato.vault as vault_mod

    monkeypatch.setattr(vault_mod, "_CACHED_VAULT_PASSWORD", None)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=dotenv-tg\nOPENROUTER_API_KEY=dotenv-or\nEXTRA_LEGACY=keep-me\n",
        encoding="utf-8",
    )
    vault_path = tmp_path / "vault.enc"
    v = Vault(vault_path=vault_path)
    v.unlock("bootstrap-pw", allow_create=True)
    v.set("TELEGRAM_BOT_TOKEN", "vault-tg")
    v.set("OPENROUTER_API_KEY", "vault-or")

    # Clear target keys so fill + apply are observable on real os.environ
    for key in ("TELEGRAM_BOT_TOKEN", "OPENROUTER_API_KEY", "EXTRA_LEGACY"):
        monkeypatch.delenv(key, raising=False)

    vault, report = bootstrap_launch_credentials(
        repo_root=tmp_path,
        vault_path=vault_path,
        env_file=env_file,
        require_password=True,
        load_dotenv=True,
    )
    assert vault is not None
    assert report.vault_unlocked is True
    assert report.vault_keys_total >= 2
    assert "TELEGRAM_BOT_TOKEN" in report.applied_from_vault
    assert "OPENROUTER_API_KEY" in report.applied_from_vault
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "vault-tg"
    assert os.environ["OPENROUTER_API_KEY"] == "vault-or"
    assert os.environ.get("EXTRA_LEGACY") == "keep-me"


def test_migrate_env_to_vault_grows_vault_and_lists_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("CATO_VAULT_PASSWORD", "migrate-pw")
    import cato.vault as vault_mod

    monkeypatch.setattr(vault_mod, "_CACHED_VAULT_PASSWORD", None)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=tg-secret-value",
                "OPENROUTER_API_KEY=or-secret-value",
                "ANTHROPIC_API_KEY=anth-secret-value",
                "CATO_VAULT_PASSWORD=must-not-migrate",
                "UNRELATED=skip-unless-operator",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    vault_path = tmp_path / "vault.enc"
    # Create empty vault first
    Vault(vault_path=vault_path).unlock("migrate-pw", allow_create=True)
    size_before = vault_path.stat().st_size
    assert size_before > 0

    report = migrate_env_to_vault(
        env_file=env_file,
        vault_path=vault_path,
        password="migrate-pw",
        overwrite=False,
        dry_run=False,
    )
    assert report.ok
    assert "TELEGRAM_BOT_TOKEN" in report.migrated
    assert "OPENROUTER_API_KEY" in report.migrated
    assert "ANTHROPIC_API_KEY" in report.migrated
    assert "CATO_VAULT_PASSWORD" not in report.migrated
    assert "UNRELATED" not in report.migrated

    size_after = vault_path.stat().st_size
    assert size_after > size_before

    # Relock via fresh instance — list keys only (no values in assertions on stdout)
    v2 = Vault(vault_path=vault_path)
    v2.unlock("migrate-pw", allow_create=False)
    keys = v2.list_keys()
    assert "TELEGRAM_BOT_TOKEN" in keys
    assert "OPENROUTER_API_KEY" in keys
    assert "ANTHROPIC_API_KEY" in keys
    assert "CATO_VAULT_PASSWORD" not in keys


def test_migrate_skips_existing_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("CATO_VAULT_PASSWORD", "migrate-pw-2")
    import cato.vault as vault_mod

    monkeypatch.setattr(vault_mod, "_CACHED_VAULT_PASSWORD", None)

    vault_path = tmp_path / "vault.enc"
    v = Vault(vault_path=vault_path)
    v.unlock("migrate-pw-2", allow_create=True)
    v.set("TELEGRAM_BOT_TOKEN", "already-in-vault")

    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=from-dotenv\n", encoding="utf-8")

    report = migrate_env_to_vault(
        env_file=env_file,
        vault_path=vault_path,
        password="migrate-pw-2",
        overwrite=False,
    )
    assert report.migrated == []
    assert "TELEGRAM_BOT_TOKEN" in report.skipped_existing
    assert v.get_stored("TELEGRAM_BOT_TOKEN") == "already-in-vault"


def test_operator_vault_keys_include_required_targets():
    assert "TELEGRAM_BOT_TOKEN" in OPERATOR_VAULT_KEYS
    assert "OPENROUTER_API_KEY" in OPERATOR_VAULT_KEYS
    assert "ANTHROPIC_API_KEY" in OPERATOR_VAULT_KEYS
