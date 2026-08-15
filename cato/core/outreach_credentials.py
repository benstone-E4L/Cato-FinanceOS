"""Vault-backed one-shot credential transport for the outreach child."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Exact keys accepted by the outreach child's in-memory credential channel.
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
    "CONDUITSCORE_API_BASE",
    "UNSUBSCRIBE_BASE_URL",
    "GOOGLE_SHEET_ID",
)

OUTREACH_REQUIRED_KEYS: tuple[str, ...] = ("CONDUITSCORE_API_KEY",)
OUTREACH_CREDENTIAL_PROTOCOL = "cato.outreach.credentials"
OUTREACH_CREDENTIAL_VERSION = 1
_MAX_CREDENTIAL_VALUE_BYTES = 16_384


class OutreachCredentialError(RuntimeError):
    """The vault cannot supply a valid outreach credential envelope."""

# Non-secret keys reported in `cato outreach status`.
OUTREACH_STATUS_KEYS: tuple[str, ...] = OUTREACH_VAULT_KEYS


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


def build_credential_envelope(*, vault: Any | None = None) -> tuple[bytes, tuple[str, ...]]:
    """Build a compact stdin payload from the unlocked vault only.

    The returned values tuple exists solely so the caller can detect and suppress a
    misbehaving child's accidental output.  Values are never logged or persisted.
    """
    if vault is None:
        from ..vault import Vault

        vault = Vault()

    credentials: dict[str, str] = {}
    for key in OUTREACH_VAULT_KEYS:
        try:
            value = vault.get(key)
        except Exception as exc:
            raise OutreachCredentialError("outreach vault is locked or unavailable") from exc
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise OutreachCredentialError(f"invalid vault credential metadata for {key}")
        if len(value.encode("utf-8")) > _MAX_CREDENTIAL_VALUE_BYTES:
            raise OutreachCredentialError(f"invalid vault credential metadata for {key}")
        credentials[key] = value

    missing = [key for key in OUTREACH_REQUIRED_KEYS if key not in credentials]
    if missing:
        raise OutreachCredentialError(
            "required vault credentials are unavailable: " + ", ".join(missing)
        )

    payload = json.dumps(
        {
            "protocol": OUTREACH_CREDENTIAL_PROTOCOL,
            "version": OUTREACH_CREDENTIAL_VERSION,
            "credentials": credentials,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return payload, tuple(credentials.values())


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
        "execution_available": bool(root) and all(
            vault_only.get(key, False) for key in OUTREACH_REQUIRED_KEYS
        ),
        "unavailable_reason": (
            None
            if bool(root) and all(vault_only.get(key, False) for key in OUTREACH_REQUIRED_KEYS)
            else "Outreach engine path or required vault credentials are unavailable."
        ),
    }
