"""
cato/vault_bootstrap.py — Launch-time credential loading with vault preference.

Order of precedence for operator secrets:
  1. Values already in the process environment (explicit operator overrides)
  2. Encrypted vault.enc (preferred durable store)
  3. Optional plaintext .env fill for keys still missing (legacy fallback)

Never logs or prints secret values. CATO_VAULT_PASSWORD must be present in the
environment (or the process-level vault password cache) before unlock.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from .platform import get_data_dir
from .vault import CANARY_KEY_NAME, Vault, VaultError, _get_vault_password

logger = logging.getLogger(__name__)

# Operator secrets the launch path prefers from the vault when present.
OPERATOR_VAULT_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "CATODESKTOP_BOT_TOKEN",
    "SWARMSYNC_API_KEY",
    "SWARM_SYNC_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GATEWAY_API_KEY",
    "BREVO_SMTP_KEY",
    "BREVO_API_KEY",
    "CONDUITSCORE_API_KEY",
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
)

# Keys that must never be copied from .env into the vault via migrate-env.
_MIGRATE_SKIP_KEYS: frozenset[str] = frozenset(
    {
        "CATO_VAULT_PASSWORD",  # unlock secret — keep out of vault payload
        CANARY_KEY_NAME,
    }
)


@dataclass(frozen=True)
class BootstrapReport:
    """Safe summary of launch credential loading (no secret values)."""

    vault_path: Path
    vault_present: bool
    vault_unlocked: bool
    vault_keys_total: int
    applied_from_vault: tuple[str, ...] = ()
    filled_from_dotenv: tuple[str, ...] = ()
    env_file: Optional[Path] = None
    errors: tuple[str, ...] = ()

    def as_log_dict(self) -> dict[str, object]:
        return {
            "vault_path": str(self.vault_path),
            "vault_present": self.vault_present,
            "vault_unlocked": self.vault_unlocked,
            "vault_keys_total": self.vault_keys_total,
            "applied_from_vault": list(self.applied_from_vault),
            "filled_from_dotenv": list(self.filled_from_dotenv),
            "env_file": str(self.env_file) if self.env_file else None,
            "errors": list(self.errors),
        }


@dataclass
class MigrateReport:
    """Safe summary of .env → vault migration (no secret values)."""

    env_file: Path
    vault_path: Path
    migrated: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    skipped_empty: list[str] = field(default_factory=list)
    skipped_blocklist: list[str] = field(default_factory=list)
    dry_run: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def resolve_repo_root(explicit: Path | str | None = None) -> Path:
    """Resolve the Cato repo root for .env discovery and launch scripts."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env_root = os.environ.get("CATO_REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    # cato/vault_bootstrap.py → repo root is parent of package dir
    return Path(__file__).resolve().parent.parent


def require_vault_password() -> str:
    """Return the vault password or raise VaultError if unset.

    Uses the process-level cache / CATO_VAULT_PASSWORD. Never logs the value.
    """
    cached = _get_vault_password()
    if cached:
        return cached
    raise VaultError(
        "CATO_VAULT_PASSWORD environment variable is not set. "
        "Set it before launching the daemon or migrating credentials."
    )


def _read_dotenv_map(env_file: Path) -> dict[str, str]:
    """Parse a .env file into key→value without printing values."""
    if not env_file.is_file():
        return {}
    try:
        from dotenv import dotenv_values
    except ImportError:
        return _parse_dotenv_fallback(env_file)

    out: dict[str, str] = {}
    for key, val in (dotenv_values(env_file) or {}).items():
        if key and val is not None and str(val).strip() != "":
            out[str(key)] = str(val)
    return out


def _parse_dotenv_fallback(env_file: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser when python-dotenv is unavailable."""
    out: dict[str, str] = {}
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and value:
            out[key] = value
    return out


def fill_environ_from_dotenv(
    env_file: Path,
    *,
    keys: Sequence[str] | None = None,
    environ: Optional[dict[str, str]] = None,
) -> tuple[str, ...]:
    """Fill missing environ keys from .env. Never overwrites existing values.

    Returns the names of keys that were filled (values never returned).
    """
    target = environ if environ is not None else os.environ
    parsed = _read_dotenv_map(env_file)
    allow = set(keys) if keys is not None else None
    filled: list[str] = []
    for key, value in parsed.items():
        if allow is not None and key not in allow:
            continue
        if key in _MIGRATE_SKIP_KEYS:
            continue
        existing = (target.get(key) or "").strip()
        if existing:
            continue
        if not str(value).strip():
            continue
        target[key] = str(value)
        filled.append(key)
    return tuple(sorted(filled))


def apply_vault_to_environ(
    vault: Vault,
    *,
    keys: Sequence[str] | None = None,
    environ: Optional[dict[str, str]] = None,
    only_if_present: bool = True,
) -> tuple[str, ...]:
    """Copy vault-stored secrets into *environ*, vault winning over .env fills.

    Only writes keys that have a non-empty stored vault value. Existing process
    env values that were set before bootstrap are overwritten when the vault
    has the key (vault is the preferred durable store).

    Returns key names applied — never values.
    """
    target = environ if environ is not None else os.environ
    stored = vault.stored_mapping()
    wanted: Iterable[str]
    if keys is None:
        wanted = sorted(set(OPERATOR_VAULT_KEYS) | set(stored.keys()))
    else:
        wanted = keys

    applied: list[str] = []
    for key in wanted:
        if key in _MIGRATE_SKIP_KEYS or key == CANARY_KEY_NAME:
            continue
        value = stored.get(key)
        if value is None or not str(value).strip():
            if only_if_present:
                continue
            continue
        target[key] = str(value)
        applied.append(key)
    return tuple(sorted(set(applied)))


def unlock_vault(
    *,
    vault_path: Path | None = None,
    password: str | None = None,
) -> Vault:
    """Unlock the vault using CATO_VAULT_PASSWORD. Never creates one silently.

    Daemon/CLI launch paths must fail closed if the vault is missing rather
    than bootstrapping an empty one — see `bootstrap_launch_credentials`,
    which only calls this after confirming the file already exists.
    """
    path = vault_path or (get_data_dir() / "vault.enc")
    pw = password or require_vault_password()
    vault = Vault(vault_path=path)
    vault.unlock(pw, allow_create=False)
    return vault


def bootstrap_launch_credentials(
    *,
    repo_root: Path | str | None = None,
    vault_path: Path | None = None,
    env_file: Path | None = None,
    require_password: bool = True,
    load_dotenv: bool = True,
) -> tuple[Optional[Vault], BootstrapReport]:
    """Prepare process env for daemon launch: .env fill, then vault preference.

    Raises VaultError when require_password is True and the password is unset,
    or when the vault file exists but cannot be unlocked.
    """
    root = resolve_repo_root(repo_root)
    vpath = Path(vault_path) if vault_path else (get_data_dir() / "vault.enc")
    epath = Path(env_file) if env_file else (root / ".env")

    errors: list[str] = []
    filled: tuple[str, ...] = ()
    applied: tuple[str, ...] = ()
    vault: Optional[Vault] = None
    unlocked = False
    keys_total = 0

    if load_dotenv and epath.is_file():
        # Fill any missing keys from .env (legacy). Vault wins next for
        # operator secrets it actually stores.
        filled = fill_environ_from_dotenv(epath, keys=None)

    if require_password:
        # Fail closed before touching the vault file when password is missing.
        require_vault_password()

    if vpath.exists():
        try:
            vault = unlock_vault(vault_path=vpath)
            unlocked = True
            keys_total = len(vault.list_keys())
            applied = apply_vault_to_environ(vault, keys=OPERATOR_VAULT_KEYS)
            logger.info(
                "Vault bootstrap: unlocked %s (%d keys); applied %d operator key(s) to environ",
                vpath,
                keys_total,
                len(applied),
            )
        except VaultError as exc:
            errors.append(f"vault_unlock_failed: {exc}")
            logger.error("Vault bootstrap failed to unlock %s: %s", vpath, exc)
            if require_password:
                raise
        except Exception as exc:
            errors.append(f"vault_error: {type(exc).__name__}")
            logger.error("Vault bootstrap error for %s: %s", vpath, type(exc).__name__)
            if require_password:
                raise VaultError(f"Vault bootstrap failed: {type(exc).__name__}") from exc
    else:
        msg = f"vault_absent: {vpath}"
        errors.append(msg)
        logger.warning(
            "Vault file not found at %s — using .env/environ only. "
            "Run 'cato init' then 'cato vault migrate-env'.",
            vpath,
        )

    if filled:
        logger.info(
            "Vault bootstrap: filled %d missing key(s) from dotenv (vault still preferred when present)",
            len(filled),
        )

    report = BootstrapReport(
        vault_path=vpath,
        vault_present=vpath.exists(),
        vault_unlocked=unlocked,
        vault_keys_total=keys_total,
        applied_from_vault=applied,
        filled_from_dotenv=filled,
        env_file=epath if epath.is_file() else None,
        errors=tuple(errors),
    )
    return vault, report


def migrate_env_to_vault(
    *,
    env_file: Path | str | None = None,
    vault_path: Path | None = None,
    keys: Sequence[str] | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
    password: str | None = None,
) -> MigrateReport:
    """Copy operator secrets from a .env file into vault.enc without echoing values.

    One-command path::

        set CATO_VAULT_PASSWORD=<password>
        python -m cato vault migrate-env

    Only key *names* appear in the report / logs.
    """
    root = resolve_repo_root()
    epath = Path(env_file) if env_file else (root / ".env")
    vpath = Path(vault_path) if vault_path else (get_data_dir() / "vault.enc")
    report = MigrateReport(env_file=epath, vault_path=vpath, dry_run=dry_run)

    if not epath.is_file():
        report.error = f"env_file_not_found: {epath}"
        return report

    try:
        pw = password or require_vault_password()
    except VaultError as exc:
        report.error = str(exc)
        return report

    parsed = _read_dotenv_map(epath)
    wanted = tuple(keys) if keys is not None else OPERATOR_VAULT_KEYS

    try:
        vault = Vault(vault_path=vpath)
        # Explicit operator command (`cato vault migrate-env`) — creating a
        # vault on first run here is the deliberate, documented entry point.
        vault.unlock(pw, allow_create=True)
    except VaultError as exc:
        report.error = f"vault_unlock_failed: {exc}"
        return report

    existing = set(vault.list_keys())

    for key in wanted:
        if key in _MIGRATE_SKIP_KEYS:
            report.skipped_blocklist.append(key)
            continue
        raw = parsed.get(key)
        if raw is None or not str(raw).strip():
            report.skipped_empty.append(key)
            continue
        if key in existing and not overwrite:
            report.skipped_existing.append(key)
            continue
        if not dry_run:
            vault.set(key, str(raw))
        report.migrated.append(key)
        existing.add(key)

    logger.info(
        "Vault migrate-env: migrated=%d skipped_existing=%d skipped_empty=%d dry_run=%s",
        len(report.migrated),
        len(report.skipped_existing),
        len(report.skipped_empty),
        dry_run,
    )
    return report


def redact_mapping_keys(data: Mapping[str, object]) -> dict[str, object]:
    """Return a copy safe for proof artifacts (booleans / counts only for secrets)."""
    safe: dict[str, object] = {}
    for key, value in data.items():
        if key.upper().endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_SID")):
            safe[key] = bool(value)
        else:
            safe[key] = value
    return safe
