from __future__ import annotations

import pytest

from cato.vault import Vault, VaultError


def test_rekey_preserves_entries_and_invalidates_old_password(tmp_path) -> None:
    path = tmp_path / "vault.enc"
    vault = Vault.create("old-password-strong", path)
    vault.set("ANTHROPIC_API_KEY", "test-value")

    Vault(path).rekey("old-password-strong", "new-password-strong")

    with pytest.raises(VaultError, match="Wrong master password"):
        Vault(path).unlock("old-password-strong")
    rotated = Vault(path)
    rotated.unlock("new-password-strong")
    assert rotated.get_stored("ANTHROPIC_API_KEY") == "test-value"


def test_rekey_rejects_short_new_password_without_modifying_vault(tmp_path) -> None:
    path = tmp_path / "vault.enc"
    Vault.create("old-password-strong", path).set("TOKEN", "preserved")
    before = path.read_bytes()

    with pytest.raises(VaultError, match="at least 12"):
        Vault(path).rekey("old-password-strong", "too-short")

    assert path.read_bytes() == before
