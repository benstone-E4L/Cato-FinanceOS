"""Vault-only credential lookup helpers for integration tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CredentialLookup:
    """Result of resolving one integration credential group."""

    names: tuple[str, ...]
    found: bool
    source: str = ""
    key_name: str = ""
    value: str = ""

    def public_dict(self) -> dict[str, Any]:
        """Return a non-secret representation safe for tool output."""
        return {
            "names": list(self.names),
            "found": self.found,
            "source": self.source,
            "key_name": self.key_name,
        }


def resolve_credential(vault: Any, names: tuple[str, ...]) -> CredentialLookup:
    """Resolve the first available credential from the encrypted vault."""
    if vault is not None:
        for name in names:
            try:
                value = vault.get(name)
            except Exception:
                value = None
            if value:
                return CredentialLookup(
                    names=names,
                    found=True,
                    source="vault",
                    key_name=name,
                    value=str(value),
                )

    return CredentialLookup(names=names, found=False)


def resolve_credential_groups(
    vault: Any,
    groups: tuple[tuple[str, ...], ...],
) -> list[CredentialLookup]:
    """Resolve all credential groups for an integration."""
    return [resolve_credential(vault, group) for group in groups]
