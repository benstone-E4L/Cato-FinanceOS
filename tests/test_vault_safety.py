"""Regression tests for the 2026-08-13 vault-destruction incident.

Root cause: Vault.create() unconditionally deleted any existing vault file
before writing a fresh one, and Vault.unlock() silently created an empty
vault whenever the file was absent — with no distinction between "true
first run" and "recovery from a locked-out vault". Something (an ad-hoc
recovery script bypassing the interactive `cato init` confirmation gate)
called Vault.create() repeatedly while diagnosing a password mismatch,
each time destroying the previous vault's contents.

These tests pin the required behavior:
  - a failed unlock (wrong password) never touches the file on disk
  - Vault.create() refuses to overwrite an existing vault unless force=True
  - force=True always backs up the existing file first
  - writes are atomic and verified before they ever replace the real file
  - a save that would silently drop more than one key at once is refused
  - two processes cannot write vault.enc concurrently and corrupt it
"""
from __future__ import annotations

import base64
import os
import threading
import time

import pytest

from cato.vault import Vault, VaultError, _backup_existing_vault, _vault_file_lock


def test_unlock_never_creates_by_default(tmp_path):
    """unlock() without allow_create must fail closed on a missing vault."""
    v = Vault(tmp_path / "vault.enc")
    with pytest.raises(VaultError, match="Refusing to silently create"):
        v.unlock("some-password")
    assert not (tmp_path / "vault.enc").exists()


def test_wrong_password_never_touches_the_file(tmp_path):
    """The exact incident: unlock fails -> file must be byte-for-byte unchanged."""
    vault_path = tmp_path / "vault.enc"
    v1 = Vault(vault_path)
    v1.unlock("correct-password", allow_create=True)
    v1.set("ANTHROPIC_API_KEY", "sk-real-key")
    v1.set("OPENAI_API_KEY", "sk-other-key")

    before_bytes = vault_path.read_bytes()
    before_mtime = vault_path.stat().st_mtime

    v2 = Vault(vault_path)
    with pytest.raises(VaultError, match="Wrong master password"):
        v2.unlock("wrong-password")

    after_bytes = vault_path.read_bytes()
    after_mtime = vault_path.stat().st_mtime
    assert after_bytes == before_bytes, "a failed unlock must never modify vault.enc"
    assert after_mtime == before_mtime

    # And the original credentials must still be readable with the right password.
    v3 = Vault(vault_path)
    v3.unlock("correct-password")
    assert v3.get("ANTHROPIC_API_KEY") == "sk-real-key"
    assert v3.get("OPENAI_API_KEY") == "sk-other-key"


def test_create_refuses_to_overwrite_existing_vault(tmp_path):
    vault_path = tmp_path / "vault.enc"
    Vault.create("original-password", vault_path=vault_path)
    v = Vault(vault_path)
    v.unlock("original-password")
    v.set("GMAIL_REFRESH_TOKEN", "irreplaceable-token")

    with pytest.raises(VaultError, match="Refusing to overwrite"):
        Vault.create("brand-new-password", vault_path=vault_path)

    # The original vault and its credential must survive the refused attempt.
    v2 = Vault(vault_path)
    v2.unlock("original-password")
    assert v2.get("GMAIL_REFRESH_TOKEN") == "irreplaceable-token"


def test_create_force_backs_up_before_overwriting(tmp_path):
    vault_path = tmp_path / "vault.enc"
    Vault.create("old-password", vault_path=vault_path)
    v = Vault(vault_path)
    v.unlock("old-password")
    v.set("SOME_KEY", "old-value")

    # The set() above already left a *rolling* lkg backup (routine saves do
    # that too) — the force-reinit backup is a distinct, timestamped file
    # that is never overwritten, so it must exist in addition to that one.
    reinit_backups_before = list(tmp_path.glob("vault.enc.create-force-reinit-*.bak"))
    assert reinit_backups_before == []

    Vault.create("new-password", vault_path=vault_path, force=True)

    backups = list(tmp_path.glob("vault.enc.create-force-reinit-*.bak"))
    assert len(backups) == 1, "force=True must leave exactly one recoverable backup"

    # The backup must still be openable with the OLD password and hold the OLD data.
    v_old = Vault(backups[0])
    v_old.unlock("old-password")
    assert v_old.get("SOME_KEY") == "old-value"

    # The live path now holds the NEW vault.
    v_new = Vault(vault_path)
    v_new.unlock("new-password")
    assert v_new.list_keys() == []


def test_save_is_atomic_and_readable_after_crash_simulation(tmp_path, monkeypatch):
    """If the process dies mid-write, the *original* file must still be intact
    (no partial/truncated vault.enc) because writes go to a temp file first."""
    vault_path = tmp_path / "vault.enc"
    v = Vault(vault_path)
    v.unlock("pw", allow_create=True)
    v.set("KEY1", "value1")
    good_bytes = vault_path.read_bytes()

    # Simulate a crash after the temp file is written but before os.replace().
    real_replace = os.replace

    def _boom(*a, **kw):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        v.set("KEY2", "value2")
    monkeypatch.setattr(os, "replace", real_replace)

    # Original file must be untouched — no truncation, no corruption.
    assert vault_path.read_bytes() == good_bytes
    v2 = Vault(vault_path)
    v2.unlock("pw")
    assert v2.get("KEY1") == "value1"
    assert v2.get("KEY2") is None

    # No stray temp files left behind.
    leftovers = list(tmp_path.glob("vault.enc.tmp*"))
    assert leftovers == []


def test_save_refuses_to_shrink_by_more_than_one_key(tmp_path):
    """Guards against an in-memory bug silently dropping most of the vault."""
    vault_path = tmp_path / "vault.enc"
    v = Vault(vault_path)
    v.unlock("pw", allow_create=True)
    v.set("KEY1", "a")
    v.set("KEY2", "b")
    v.set("KEY3", "c")
    v.set("KEY4", "d")

    # Simulate accidental data loss in memory (not a normal single delete()).
    v._data = {"KEY1": "a"}
    with pytest.raises(VaultError, match="Refusing to save"):
        v._save()

    # File on disk must still hold all four keys.
    v2 = Vault(vault_path)
    v2.unlock("pw")
    assert sorted(v2.list_keys()) == ["KEY1", "KEY2", "KEY3", "KEY4"]


def test_normal_single_delete_is_still_allowed(tmp_path):
    vault_path = tmp_path / "vault.enc"
    v = Vault(vault_path)
    v.unlock("pw", allow_create=True)
    v.set("KEY1", "a")
    v.set("KEY2", "b")
    v.delete("KEY1")
    assert v.list_keys() == ["KEY2"]


def test_shared_instance_concurrent_writes_never_corrupt_and_preserve_all_keys(tmp_path):
    """The realistic in-process race: several threads sharing one Vault
    object (e.g. concurrent request handlers inside the daemon) calling
    set() at the same time. They share one in-memory _data dict, so this
    isolates exactly what the file lock is responsible for: the file on
    disk must never be corrupted/torn, and every completed write must be
    durably persisted — no key silently lost to an interleaved write."""
    vault_path = tmp_path / "vault.enc"
    v = Vault(vault_path)
    v.unlock("pw", allow_create=True)

    errors: list[Exception] = []

    def writer(idx: int):
        try:
            for n in range(5):
                v.set(f"WRITER{idx}_KEY{n}", f"value-{idx}-{n}")
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent writers raised: {errors}"

    # File must be fully valid and contain every key from every writer —
    # a lock that failed to serialize the actual disk writes would show
    # torn/unreadable content or missing keys here.
    final = Vault(vault_path)
    final.unlock("pw")
    keys = set(final.list_keys())
    for idx in range(6):
        for n in range(5):
            assert f"WRITER{idx}_KEY{n}" in keys

    # No lock file left behind.
    assert not (tmp_path / "vault.enc.lock").exists()


def test_lock_serializes_a_genuine_external_holder(tmp_path):
    """A second process/instance racing for the SAME lock must wait, not
    barge in and write concurrently — proven by measuring that the second
    acquirer's critical section never overlaps the first's."""
    vault_path = tmp_path / "vault.enc"
    vault_path.write_bytes(b"placeholder")  # lock only cares about the path

    order: list[str] = []
    release_first = threading.Event()

    def hold_first():
        with _vault_file_lock(vault_path, timeout=10.0):
            order.append("first-acquired")
            release_first.wait(timeout=10.0)
            order.append("first-released")

    def hold_second():
        # Give the first thread a head start so it holds the lock first.
        time.sleep(0.2)
        with _vault_file_lock(vault_path, timeout=10.0):
            order.append("second-acquired")

    t1 = threading.Thread(target=hold_first)
    t2 = threading.Thread(target=hold_second)
    t1.start()
    t2.start()
    time.sleep(0.5)
    release_first.set()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert order == ["first-acquired", "first-released", "second-acquired"], (
        "the second holder must not acquire the lock until the first releases it"
    )


def test_lock_reclaims_stale_lock_from_a_dead_holder(tmp_path):
    vault_path = tmp_path / "vault.enc"
    lock_path = tmp_path / "vault.enc.lock"
    tmp_path.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, b"99999999")  # a PID that is not this test process
    os.close(fd)
    # Backdate the lock file so it looks stale.
    old = time.time() - 120
    os.utime(lock_path, (old, old))

    with _vault_file_lock(vault_path, timeout=5.0, stale_after=60.0):
        pass  # must not raise / must not hang

    assert not lock_path.exists()


def test_backup_helper_refuses_silently_when_write_fails(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault.enc"
    vault_path.write_bytes(b"not-empty")

    def _boom(self, data):
        raise OSError("disk full")

    import pathlib

    monkeypatch.setattr(pathlib.Path, "write_bytes", _boom)
    with pytest.raises(VaultError, match="could not write a backup"):
        _backup_existing_vault(vault_path, reason="test")
