"""
cato/vault.py — Encrypted credential storage for CATO.

AES-256-GCM encryption with Argon2id key derivation.
Stores API keys, tokens, and passwords in ~/.cato/vault.enc.
Master password is prompted once on first run; derived key is cached in memory only.
"""

from __future__ import annotations

import base64
import contextlib
import getpass
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from argon2.low_level import hash_secret_raw, Type
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .platform import get_data_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Process-level vault password cache (F-07)
# ---------------------------------------------------------------------------

_CACHED_VAULT_PASSWORD: str | None = None


def _get_vault_password() -> str | None:
    """Return the vault password, caching it on first read to survive env var removal."""
    global _CACHED_VAULT_PASSWORD
    if _CACHED_VAULT_PASSWORD:
        return _CACHED_VAULT_PASSWORD
    env_password = os.environ.get("CATO_VAULT_PASSWORD")
    if env_password:
        _CACHED_VAULT_PASSWORD = env_password
        os.environ.pop("CATO_VAULT_PASSWORD", None)
        return _CACHED_VAULT_PASSWORD
    return None


# ---------------------------------------------------------------------------
# Canary key (P2-11)
# ---------------------------------------------------------------------------

CANARY_KEY_NAME = "_cato_canary_"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VAULT_FILE = get_data_dir() / "vault.enc"
_SALT_SIZE = 32       # bytes — stored inside the vault file
_NONCE_SIZE = 12      # bytes — per-encryption nonce
_KEY_SIZE = 32        # bytes — AES-256

# Argon2id parameters (OWASP recommended minimum)
_ARGON2_TIME_COST = 3
_ARGON2_MEMORY_COST = 65536   # 64 MiB
_ARGON2_PARALLELISM = 4


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit key from *password* using Argon2id."""
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=_ARGON2_TIME_COST,
        memory_cost=_ARGON2_MEMORY_COST,
        parallelism=_ARGON2_PARALLELISM,
        hash_len=_KEY_SIZE,
        type=Type.ID,
    )


def _encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Return nonce || ciphertext using AES-256-GCM."""
    nonce = secrets.token_bytes(_NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def _decrypt(blob: bytes, key: bytes) -> bytes:
    """Decrypt nonce || ciphertext produced by _encrypt."""
    nonce = blob[:_NONCE_SIZE]
    ciphertext = blob[_NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------

class VaultError(Exception):
    """Raised on vault authentication or I/O failures."""


def _backup_existing_vault(path: Path, *, reason: str, rolling: bool = False) -> Optional[Path]:
    """Copy *path* to a backup before it is overwritten or replaced.

    Called immediately before any step that would destroy the current
    contents of an existing vault file. Raises VaultError (rather than
    proceeding) if the backup itself cannot be written, since a destructive
    step must never run without a recoverable copy sitting next to it.

    rolling=True (routine set()/delete() saves) writes to a single fixed
    filename that is overwritten each time, so ordinary use doesn't
    accumulate one file per credential change. rolling=False (a real
    recreate/reinit event) always writes a distinct timestamped file that is
    never overwritten or pruned — those are rare, and each one is forensic
    evidence of a destructive event worth keeping.
    """
    if not path.exists():
        return None
    if rolling:
        backup_path = path.with_name(f"{path.name}.lkg.bak")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = path.with_name(f"{path.name}.{reason}-{stamp}.bak")
    try:
        backup_path.write_bytes(path.read_bytes())
    except OSError as exc:
        raise VaultError(
            f"Refusing to proceed: could not write a backup of the existing "
            f"vault to {backup_path} before replacing it: {exc}"
        ) from exc
    logger.warning("Vault backup written before replace: %s (reason=%s)", backup_path, reason)
    return backup_path


class _VaultLockTimeout(VaultError):
    """Raised when another process holds the vault write lock too long."""


@contextlib.contextmanager
def _vault_file_lock(vault_path: Path, *, timeout: float = 15.0, stale_after: float = 60.0):
    """Advisory cross-process lock guarding vault.enc writes.

    Uses atomic exclusive file creation (O_CREAT|O_EXCL) so no new dependency
    is needed. A lock file older than *stale_after* seconds is treated as
    belonging to a crashed holder and reclaimed.
    """
    lock_path = vault_path.with_suffix(vault_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd: Optional[int] = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > stale_after:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() > deadline:
                raise _VaultLockTimeout(
                    f"Timed out waiting for the vault write lock at {lock_path} "
                    "— another process appears to be writing vault.enc."
                )
            time.sleep(0.1)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass


class Vault:
    """
    AES-256-GCM encrypted credential store.

    The on-disk layout of ``vault.enc`` is:

        base64( salt[32] + nonce[12] + aesgcm_ciphertext )

    The plaintext inside the ciphertext is a UTF-8 JSON object
    mapping string keys to string values.

    Usage::

        vault = Vault()
        vault.set("OPENAI_API_KEY", "sk-...")
        key = vault.get("OPENAI_API_KEY")
        vault.delete("OPENAI_API_KEY")
    """

    def __init__(self, vault_path: Optional[Path] = None) -> None:
        self._path: Path = vault_path or _VAULT_FILE
        self._key: Optional[bytes] = None          # in-memory only
        self._data: Optional[dict[str, str]] = None
        # Key count as of the last successful unlock/create/save — used to
        # refuse a save that would silently lose more than one key at once.
        self._loaded_key_count: Optional[int] = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _prompt_password(self, confirm: bool = False) -> str:
        """Prompt for the master password, with optional confirmation."""
        import sys
        # Check process-level cache and environment variable first
        cached = _get_vault_password()
        if cached:
            return cached

        if not sys.stdin.isatty():
            raise VaultError(
                "Vault is locked and no TTY is available to prompt for the master password. "
                "Run 'cato init' interactively first, then set CATO_VAULT_PASSWORD "
                "in the environment or call vault.unlock(password) before starting the daemon."
            )
        password = getpass.getpass("Vault master password: ")
        if confirm:
            confirm_pw = getpass.getpass("Confirm master password: ")
            if password != confirm_pw:
                raise VaultError("Passwords do not match.")
        return password

    def _unlock(self) -> None:
        """Load and decrypt the vault, caching the key and data in memory."""
        if self._key is not None and self._data is not None:
            return  # already unlocked

        if not self._path.exists():
            # First run — create new vault
            password = self._prompt_password(confirm=True)
            salt = secrets.token_bytes(_SALT_SIZE)
            self._key = _derive_key(password, salt)
            self._data = {}
            self._save(salt)
            return

        # Existing vault
        raw = base64.b64decode(self._path.read_bytes())
        salt = raw[:_SALT_SIZE]
        blob = raw[_SALT_SIZE:]

        password = self._prompt_password(confirm=False)
        key = _derive_key(password, salt)

        try:
            plaintext = _decrypt(blob, key)
        except Exception as exc:
            raise VaultError("Wrong master password or corrupted vault.") from exc

        self._key = key
        self._data = json.loads(plaintext.decode("utf-8"))
        self._loaded_key_count = len(self._data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self, salt: Optional[bytes] = None) -> None:
        """Encrypt current _data and atomically replace the file on disk.

        Lock-protected against concurrent writers, fsync'd, verified by
        decrypting the freshly written temp file before it replaces the
        real one, and backed up before any existing vault is overwritten.
        Refuses to silently drop more than one key relative to the last
        successful unlock/save — that pattern means data loss, not a
        normal single-key delete.
        """
        assert self._key is not None and self._data is not None

        with _vault_file_lock(self._path):
            is_replace = self._path.exists()

            if salt is None:
                # Re-read existing salt from disk
                existing = base64.b64decode(self._path.read_bytes())
                salt = existing[:_SALT_SIZE]

            if (
                is_replace
                and self._loaded_key_count is not None
                and len(self._data) < self._loaded_key_count - 1
            ):
                raise VaultError(
                    f"Refusing to save: key count would drop from "
                    f"{self._loaded_key_count} to {len(self._data)} in a "
                    "single write. That looks like unexpected data loss, not "
                    "a normal single-key delete — aborting without touching "
                    "the file on disk."
                )

            plaintext = json.dumps(self._data, ensure_ascii=True).encode("utf-8")
            blob = _encrypt(plaintext, self._key)
            payload = base64.b64encode(salt + blob)

            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(f"{self._path.name}.tmp{os.getpid()}")
            with open(tmp, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())

            # Verify the temp file is actually readable with the key we hold
            # before it ever touches the real path.
            try:
                verify_raw = base64.b64decode(tmp.read_bytes())
                _decrypt(verify_raw[_SALT_SIZE:], self._key)
            except Exception as exc:
                tmp.unlink(missing_ok=True)
                raise VaultError(
                    "Refusing to replace vault.enc: the freshly written file "
                    "failed to verify (it would have been unreadable)."
                ) from exc

            if is_replace:
                _backup_existing_vault(self._path, reason="pre-save-lkg", rolling=True)

            try:
                os.replace(tmp, self._path)
            except OSError:
                tmp.unlink(missing_ok=True)
                raise
            self._loaded_key_count = len(self._data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        """Return the vault-stored value for *key*, or ``None``.

        If the returned value matches the canary key, logs a warning
        to alert of a potential credential leak.  Credential lookup is
        deliberately fail-closed: a locked vault or missing key never falls
        back to the process environment.
        """
        try:
            self._unlock()
        except Exception:
            return None
        assert self._data is not None
        value = self._data.get(key)
        if value is None or str(value).strip() == "":
            return None
        # Canary detection: if the value looks like our canary, warn
        if value is not None and key != CANARY_KEY_NAME:
            canary_val = self._data.get(CANARY_KEY_NAME)
            if canary_val and value == canary_val:
                logger.warning(
                    "CANARY KEY ACCESSED — possible credential leak! "
                    "Key '%s' returned the canary value. Investigate immediately.", key
                )
        return value

    def set(self, key: str, value: str) -> None:
        """Store *value* under *key* and persist to disk."""
        self._unlock()
        assert self._data is not None
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> bool:
        """Remove *key* from the vault. Returns True if it existed."""
        self._unlock()
        assert self._data is not None
        existed = key in self._data
        if existed:
            del self._data[key]
            self._save()
        return existed

    def list_keys(self) -> list[str]:
        """Return sorted list of stored key names (not values).

        Excludes the internal canary key from the public listing.
        """
        self._unlock()
        assert self._data is not None
        return sorted(k for k in self._data.keys() if k != CANARY_KEY_NAME)

    def get_stored(self, key: str) -> Optional[str]:
        """Return the vault-stored value for *key* with no environment fallback.

        This explicit name remains useful for launch and migration checks;
        ``get()`` now has the same vault-only source policy.
        """
        self._unlock()
        assert self._data is not None
        value = self._data.get(key)
        if value is None or str(value).strip() == "":
            return None
        return str(value)

    def stored_mapping(self) -> dict[str, str]:
        """Return a copy of non-empty vault entries (excludes the canary key).

        Values are returned to the caller for in-process use only — never log
        or print them.
        """
        self._unlock()
        assert self._data is not None
        return {
            k: str(v)
            for k, v in self._data.items()
            if k != CANARY_KEY_NAME and v is not None and str(v).strip() != ""
        }

    # ------------------------------------------------------------------
    # Canary key (P2-11)
    # ------------------------------------------------------------------

    def create_canary(self) -> str:
        """
        Generate a synthetic API key, store it as _cato_canary_, and return it.

        The canary looks like a real API key (starts with 'sk-cato-canary-')
        so it would trigger external API rejections if accidentally used.
        If any real key in the vault ever returns this value, a warning is logged.
        """
        self._unlock()
        assert self._data is not None
        # Generate a realistic-looking synthetic key
        canary_val = "sk-cato-canary-" + secrets.token_hex(24)
        self._data[CANARY_KEY_NAME] = canary_val
        self._save()
        logger.info("Vault canary key created (stored as %s)", CANARY_KEY_NAME)
        return canary_val

    def check_canary_used(self, key_val: str) -> bool:
        """
        Return True if *key_val* matches the stored canary value.

        Used by external monitors to detect if the canary key was used
        in any outbound request.
        """
        self._unlock()
        assert self._data is not None
        canary = self._data.get(CANARY_KEY_NAME)
        return canary is not None and key_val == canary

    def is_locked(self) -> bool:
        """Return True if the vault has not yet been unlocked this session."""
        return self._key is None

    @classmethod
    def create(cls, password: str, vault_path: Path | None = None, *, force: bool = False) -> "Vault":
        """Create a new vault. Refuses to overwrite an existing one unless force=True.

        force=True must only follow an explicit, operator-confirmed decision
        to reinitialize (e.g. the `cato init` reinit flow, only reached after
        the operator answers yes to "Config already exists. Reinitialise?").
        This is never a substitute for password recovery: a forgotten or
        wrong password does not by itself justify force=True. Even with
        force=True, the existing file is backed up first — it is never
        deleted without a recoverable copy sitting next to it.
        """
        v = cls(vault_path)
        if v._path.exists():
            if not force:
                raise VaultError(
                    f"Vault already exists at {v._path}. Refusing to "
                    "overwrite an existing vault. A locked-out or wrong "
                    "password is not grounds to recreate it — that destroys "
                    "every credential currently stored. Pass force=True only "
                    "after explicit, informed operator confirmation."
                )
            _backup_existing_vault(v._path, reason="create-force-reinit")
            v._path.unlink()
        v.unlock(password, allow_create=True)
        return v

    def unlock(self, password: str, *, allow_create: bool = False) -> None:
        """Unlock the vault with the given password (bypasses getpass prompt).

        Raises VaultError on wrong password or corruption. Also raises if no
        vault file exists yet, unless allow_create=True is passed explicitly
        — silent vault creation is never a fallback from a failed unlock; it
        is only for a caller that is deliberately initializing a new vault
        (e.g. `cato init`, or `cato vault migrate-env` on first run).
        """
        if self._key is not None and self._data is not None:
            return  # already unlocked

        if not self._path.exists():
            if not allow_create:
                raise VaultError(
                    f"No vault found at {self._path}. Refusing to silently "
                    "create one. Pass allow_create=True only when you are "
                    "deliberately initializing a new vault."
                )
            salt = secrets.token_bytes(_SALT_SIZE)
            self._key = _derive_key(password, salt)
            self._data = {}
            self._save(salt)
            self._loaded_key_count = 0
            return

        raw = base64.b64decode(self._path.read_bytes())
        salt = raw[:_SALT_SIZE]
        blob = raw[_SALT_SIZE:]
        key = _derive_key(password, salt)
        try:
            plaintext = _decrypt(blob, key)
        except Exception as exc:
            raise VaultError("Wrong master password or corrupted vault.") from exc
        self._key = key
        self._data = json.loads(plaintext.decode("utf-8"))
        self._loaded_key_count = len(self._data)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_vault_instance: Optional[Vault] = None


def get_vault() -> Vault:
    """Return the module-level Vault singleton."""
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = Vault()
    return _vault_instance
