"""
cato/core/outreach_credentials.py — Merge vault + outreach .env for subprocess tools.

Secrets never logged. Brevo SMTP and ConduitScore API keys live in the encrypted vault
and/or the outreach pipeline's local .env (gitignored).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Keys Cato may inject when calling conduit_outreach_pipeline (values from vault override .env).
OUTREACH_VAULT_KEYS: tuple[str, ...] = (
    "BREVO_SMTP_KEY",
    "BREVO_SMTP_LOGIN",
    "BREVO_API_KEY",
    "CONDUITSCORE_API_KEY",
    "SMTP_HOST",
    "SMTP_PORT",
    "SENDER_EMAIL",
    "SENDER_NAME",
    "CANSPAM_POSTAL_ADDRESS",
)

# Non-secret keys reported in `cato outreach status`.
OUTREACH_STATUS_KEYS: tuple[str, ...] = OUTREACH_VAULT_KEYS + (
    "UNSUBSCRIBE_BASE_URL",
    "CONDUITSCORE_API_BASE",
    "GOOGLE_SHEET_ID",
)


def default_outreach_engine_root() -> Path | None:
    """Resolve conduit_outreach_pipeline root (policy path or Desktop convention)."""
    try:
        from .night_shift_policy import load_night_shift_policy

        policy = load_night_shift_policy()
        raw = (policy.paths or {}).get("outreach_engine_cli") or ""
        if raw:
            p = Path(raw).expanduser()
            if p.exists():
                return p if p.is_dir() else p.parent
    except Exception:
        pass
    desktop = Path.home() / "Desktop"
    for name in ("ConduitScore/conduit_outreach_pipeline", "conduit_outreach_pipeline"):
        cand = desktop / name
        if cand.is_dir():
            return cand
    return None


def _load_dotenv_file(path: Path, env: dict[str, str]) -> None:
    if not path.is_file():
        return
    try:
        from dotenv import dotenv_values

        for key, val in (dotenv_values(path) or {}).items():
            if key and val is not None and key not in env:
                env[key] = str(val)
    except OSError as exc:
        logger.debug("outreach .env read skipped: %s", exc)


def _vault_secrets() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        from ..vault import Vault

        vault = Vault()
        for key in OUTREACH_VAULT_KEYS:
            val = vault.get(key)
            if val:
                out[key] = val
    except Exception:
        pass
    return out


def build_outreach_env(
    *,
    engine_root: Path | None = None,
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build env dict for outreach subprocess: OS env → pipeline .env → vault overrides."""
    env = dict(base or os.environ)
    root = engine_root or default_outreach_engine_root()
    if root:
        _load_dotenv_file(root / ".env", env)
    env.update(_vault_secrets())
    return env


def outreach_credentials_status(engine_root: Path | None = None) -> dict[str, Any]:
    """Safe status for CLI — never returns secret values."""
    root = engine_root or default_outreach_engine_root()
    env = build_outreach_env(engine_root=root)
    vault_only: dict[str, bool] = {}
    try:
        from ..vault import Vault

        vault = Vault()
        for key in OUTREACH_VAULT_KEYS:
            vault_only[key] = bool(vault.get(key))
    except Exception:
        vault_only = {}

    configured = {}
    for key in OUTREACH_STATUS_KEYS:
        val = (env.get(key) or "").strip()
        configured[key] = bool(val) or vault_only.get(key, False)

    return {
        "engine_root": str(root) if root else None,
        "env_file": str(root / ".env") if root else None,
        "env_file_exists": (root / ".env").is_file() if root else False,
        "template_version_hint": "1.2-halbert (ConduitScore templates/VERSION)",
        "keys_configured": configured,
        "postal_address_set": bool((env.get("CANSPAM_POSTAL_ADDRESS") or "").strip()),
        "brevo_smtp_ready": bool(
            (env.get("BREVO_SMTP_KEY") or env.get("SMTP_ACCOUNTS") or "").strip()
        ),
    }
