"""
cato/adapters/base.py — Abstract base class for all channel adapters.

Every adapter receives three shared dependencies at construction time:
  gateway  — Gateway instance (call gateway.ingest() to route incoming messages)
  vault    — Vault instance (fetch credentials without hardcoding)
  config   — CatoConfig instance (read runtime settings)

Subclasses must implement start(), stop(), and send().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import CatoConfig
    from ..gateway import Gateway
    from ..vault import Vault


class BaseAdapter(ABC):
    """Base class for all channel adapters."""

    channel_name: str = ""  # Set by subclasses, e.g. "telegram", "whatsapp"

    def __init__(self, gateway: "Gateway", vault: "Vault", config: "CatoConfig") -> None:
        self.gateway = gateway   # Gateway instance
        self.vault   = vault     # Vault instance
        self.config  = config    # CatoConfig instance
        self.running = False

    # ------------------------------------------------------------------
    # Abstract interface — every adapter must implement these three
    # ------------------------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages on this channel."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop listening and release resources."""

    @abstractmethod
    async def send(self, session_id: str, text: str) -> None:
        """Send a reply back to the user identified by session_id."""

    # ------------------------------------------------------------------
    # Session ID helpers
    # ------------------------------------------------------------------

    def make_session_id(self, channel: str, user_id: str) -> str:
        """Build a canonical session_id string.

        Format: ``{agent_id}:{channel}:{user_id}``
        Example: ``main:telegram:123456789``

        Isolation is controlled by ``config.dm_scope`` (falls back to
        ``"per-channel-peer"`` when the field is absent — this is the
        safe default that prevents session cross-contamination, which
        was the root cause of the OpenClaw pooled-session bug).

        Values:
          - ``"per-channel-peer"`` (default) — one independent session
            per (agent, channel, user) triple. Recommended for all
            production deployments.
          - ``"main"`` — all users on this channel share a single
            session. Matches the historic OpenClaw default but is
            inherently insecure: messages from different users will be
            processed with each other's context.
        """
        # CatoConfig may not yet declare agent_id / dm_scope; fall back safely.
        agent_id = getattr(self.config, "agent_id", None) or getattr(
            self.config, "agent_name", "main"
        )
        dm_scope = getattr(self.config, "dm_scope", "per-channel-peer")

        if dm_scope == "main":
            return f"{agent_id}:{channel}:main"
        return f"{agent_id}:{channel}:{user_id}"

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{type(self).__name__} running={self.running}>"
