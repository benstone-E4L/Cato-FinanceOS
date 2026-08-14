"""Vault-backed outreach status without subprocess credential transport."""

from __future__ import annotations

import logging
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


def build_outreach_env(
    *,
    engine_root: Path | None = None,
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return a non-secret child environment; outreach credentials are not injected."""
    from ..vault_bootstrap import safe_subprocess_environment

    return safe_subprocess_environment(base)


def outreach_credentials_status(engine_root: Path | None = None) -> dict[str, Any]:
    """Safe status for CLI — never returns secret values."""
    root = engine_root or default_outreach_engine_root()
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
        configured[key] = vault_only.get(key, False)

    return {
        "engine_root": str(root) if root else None,
        "env_file": str(root / ".env") if root else None,
        "env_file_exists": (root / ".env").is_file() if root else False,
        "template_version_hint": "1.2-halbert (ConduitScore templates/VERSION)",
        "keys_configured": configured,
        "postal_address_set": vault_only.get("CANSPAM_POSTAL_ADDRESS", False),
        "brevo_smtp_ready": vault_only.get("BREVO_SMTP_KEY", False),
        "execution_available": False,
        "unavailable_reason": "External outreach transport lacks a secure credential channel.",
    }
