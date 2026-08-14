"""Shared SwarmSync credential helpers."""

from __future__ import annotations

from typing import Any

CANONICAL_SWARMSYNC_KEY = "SWARMSYNC_API_KEY"
LEGACY_SWARMSYNC_KEYS = ("SWARM_SYNC_API_KEY",)


def _get_vault_value(vault: Any, key: str) -> str:
    if vault is None:
        return ""
    from .vault_bootstrap import CANONICAL_KEY_ALIASES

    for candidate in (key, *CANONICAL_KEY_ALIASES.get(key, ())):
        try:
            value = vault.get(candidate)
        except Exception:
            value = None
        if value:
            return str(value).strip()
    return ""


def get_swarmsync_api_key(vault: Any = None) -> tuple[str, str]:
    """Return ``(api_key, source)`` using vault-only canonical/legacy names."""
    canonical = _get_vault_value(vault, CANONICAL_SWARMSYNC_KEY)
    if canonical:
        return canonical, CANONICAL_SWARMSYNC_KEY
    for legacy_key in LEGACY_SWARMSYNC_KEYS:
        legacy = _get_vault_value(vault, legacy_key)
        if legacy:
            return legacy, legacy_key
    return "", ""


def swarmsync_key_status(vault: Any = None) -> dict[str, Any]:
    """Return non-secret diagnostics for SwarmSync key normalization."""
    key, source = get_swarmsync_api_key(vault)
    legacy_present = any(bool(_get_vault_value(vault, name)) for name in LEGACY_SWARMSYNC_KEYS)
    return {
        "present": bool(key),
        "source": source,
        "canonical_present": bool(_get_vault_value(vault, CANONICAL_SWARMSYNC_KEY)),
        "legacy_present": legacy_present,
        "env_canonical_present": False,
        "env_legacy_present": False,
        "needs_normalization": bool(key) and source in set(LEGACY_SWARMSYNC_KEYS),
        "prefix": "",
    }


def normalize_process_env() -> None:
    """Compatibility no-op; credentials are never copied into process env."""
    return None
