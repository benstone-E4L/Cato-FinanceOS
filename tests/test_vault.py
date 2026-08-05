"""Basic vault tests."""
import pytest
from pathlib import Path
import tempfile
from cato.vault import Vault, VaultError


def test_round_trip(tmp_path):
    v = Vault(tmp_path / "vault.enc")
    v.unlock("testpassword")
    v.set("API_KEY", "sk-test-123")
    assert v.get("API_KEY") == "sk-test-123"


def test_wrong_password(tmp_path):
    v1 = Vault(tmp_path / "vault.enc")
    v1.unlock("correct")
    v1.set("KEY", "value")

    v2 = Vault(tmp_path / "vault.enc")
    with pytest.raises((VaultError, Exception)):
        v2.unlock("wrong")


def test_key_case_sensitive(tmp_path):
    v = Vault(tmp_path / "vault.enc")
    v.unlock("pw")
    v.set("UPPER_KEY", "value")
    assert v.get("UPPER_KEY") == "value"
    assert v.get("upper_key") is None  # case sensitive


def test_list_keys(tmp_path):
    v = Vault(tmp_path / "vault.enc")
    v.unlock("pw")
    v.set("KEY1", "a")
    v.set("KEY2", "b")
    keys = v.list_keys()
    assert "KEY1" in keys
    assert "KEY2" in keys


def test_delete(tmp_path):
    v = Vault(tmp_path / "vault.enc")
    v.unlock("pw")
    v.set("KEY", "val")
    v.delete("KEY")
    assert v.get("KEY") is None
