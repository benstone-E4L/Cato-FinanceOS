"""
cato/vault_bootstrap.py — Launch-time credential loading with vault preference.

Production operator secrets are resolved only from the encrypted vault.
Repository dotenv parsing is available only to the explicit one-shot migration
command and is never part of launch or runtime credential resolution.

Never logs or prints secret values. CATO_VAULT_PASSWORD must be present in the
environment (or the process-level vault password cache) before unlock.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence

from .platform import get_data_dir
from .vault import CANARY_KEY_NAME, Vault, VaultError, _get_vault_password

logger = logging.getLogger(__name__)

# Operator secrets the launch path prefers from the vault when present.
OPERATOR_VAULT_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "CATODESKTOP_BOT_TOKEN",
    "SWARMSYNC_API_KEY",
    "SWARM_SYNC_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GATEWAY_API_KEY",
    "BREVO_SMTP_KEY",
    "BREVO_SMTP_LOGIN",
    "BREVO_API_KEY",
    "CONDUITSCORE_API_KEY",
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "FINANCEOS_CAPABILITY_TOKEN",
    "PHOENIX_API_KEY",
    "SWARMSYNC_VERIFYAPI_KEY",
    "CATO_DAEMON_TOKEN",
    "CLAUDE_BRIDGE_TOKEN",
    "SMTP_ACCOUNTS",
    "CATO_APPROVAL_SIGNING_KEY",
    "SLACK_BOT_TOKEN",
    "BRAVE_API_KEY",
    "EXA_API_KEY",
    "TAVILY_API_KEY",
    "PERPLEXITY_API_KEY",
    "SEMANTIC_SCHOLAR_API_KEY",
)

# Keys that must never be copied from .env into the vault via migrate-env.
_MIGRATE_SKIP_KEYS: frozenset[str] = frozenset(
    {
        "CATO_VAULT_PASSWORD",  # unlock secret — keep out of vault payload
        CANARY_KEY_NAME,
    }
)

# Historical vault entries may use a differently-named key than current
# consumers. This metadata maps canonical names to aliases without copying any
# value into the process environment.
CANONICAL_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "SWARMSYNC_API_KEY": ("SWARMSYNC_VERIFYAPI_KEY",),
    "SWARM_SYNC_API_KEY": ("SWARMSYNC_VERIFYAPI_KEY",),
    "GITHUB_TOKEN": ("GITHUB_FOXFIREPOETS_TOKEN",),
    "GH_TOKEN": ("GITHUB_FOXFIREPOETS_TOKEN",),
}


def safe_subprocess_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the minimal non-secret environment required to launch a child."""
    source = os.environ if environ is None else environ
    if os.name == "nt":
        allowed = {
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "COMSPEC",
            "WINDIR",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "USERNAME",
        }
    else:
        allowed = {"PATH", "HOME", "USER", "LANG", "TERM", "TMPDIR", "TMP", "TEMP"}
    return {key: value for key, value in source.items() if key.upper() in allowed}


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
    load_dotenv: bool = False,
) -> tuple[Optional[Vault], BootstrapReport]:
    """Unlock the daemon vault without loading or exporting credentials.

    Raises VaultError when require_password is True and the password is unset,
    or when the vault file exists but cannot be unlocked.  The legacy dotenv
    arguments remain accepted for compatibility but never cause a read; dotenv
    is supported only by the explicit ``migrate_env_to_vault`` command.
    """
    del repo_root, env_file
    vpath = Path(vault_path) if vault_path else (get_data_dir() / "vault.enc")

    errors: list[str] = []
    filled: tuple[str, ...] = ()
    applied: tuple[str, ...] = ()
    vault: Optional[Vault] = None
    unlocked = False
    keys_total = 0

    if load_dotenv:
        logger.warning(
            "Repository dotenv loading is disabled for launch; use the encrypted vault"
        )

    if require_password:
        # Fail closed before touching the vault file when password is missing.
        require_vault_password()

    # Refuse inherited plaintext operator credentials even though all consumers
    # are vault-only.  Pop by key name without reading, printing, or retaining
    # values so child processes cannot inherit stale credentials.
    purged_count = 0
    for key in OPERATOR_VAULT_KEYS:
        if key in os.environ:
            del os.environ[key]
            purged_count += 1
    if purged_count:
        logger.warning(
            "Removed %d plaintext operator credential(s) from process environment",
            purged_count,
        )

    if vpath.exists():
        try:
            vault = unlock_vault(vault_path=vpath)
            unlocked = True
            keys_total = len(vault.list_keys())
            logger.info(
                "Vault bootstrap: unlocked %s (%d keys); credentials retained in vault",
                vpath,
                keys_total,
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
            "Vault file not found at %s; launch credentials are unavailable. "
            "Run 'cato init' before starting the daemon.",
            vpath,
        )

    report = BootstrapReport(
        vault_path=vpath,
        vault_present=vpath.exists(),
        vault_unlocked=unlocked,
        vault_keys_total=keys_total,
        applied_from_vault=applied,
        filled_from_dotenv=filled,
        env_file=None,
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
