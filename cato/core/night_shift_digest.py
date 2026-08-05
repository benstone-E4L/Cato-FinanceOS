"""
cato/core/night_shift_digest.py — Daily Telegram summary for night-shift operations.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..audit import AuditLog
from ..audit.ledger import verify_chain
from ..budget import BudgetManager
from ..core.night_shift_policy import load_night_shift_policy
from ..core.outbound_approval import get_approval_store

logger = logging.getLogger(__name__)


async def build_night_shift_digest(
    budget: BudgetManager,
    audit: Optional[AuditLog] = None,
) -> str:
    """Compose a plain-text digest for Telegram or logs."""
    policy = load_night_shift_policy()
    status = budget.get_status()
    pending = get_approval_store().list_pending(limit=10)

    chain_ok, chain_msg = verify_chain()
    chain_head = chain_msg.split("(")[0].strip() if chain_msg else "unknown"

    lines = [
        "Cato Night-Shift Digest",
        "",
        f"Outreach phase: {policy.outreach.get('phase', 'manual')}",
        f"Live outreach allowed: {'yes' if policy.live_outreach_allowed else 'NO (G1 required)'}",
        f"G1 proven: {'yes' if policy.gates.get('g1_manual_loop_proven') else 'no'}",
        "",
        "Budget (today / month):",
        f"  ${status['daily_spend']:.2f} / ${status['daily_cap']:.2f} ({status['daily_pct_remaining']:.0f}% left)",
        f"  ${status['monthly_spend']:.2f} / ${status['monthly_cap']:.2f}",
        "",
        f"Pending approvals: {len(pending)}",
    ]
    for p in pending[:5]:
        lines.append(f"  - {p.id}: {p.tool_name} ({p.preview[:60]}...)")

    lines.extend([
        "",
        f"Audit chain: {chain_head}",
        f"Ledger verify: {chain_msg[:80]}",
    ])

    return "\n".join(lines)


async def send_digest_via_gateway(gateway: Any) -> None:
    """Push digest to Telegram if adapter is registered."""
    text = await build_night_shift_digest(gateway._budget)
    for adapter in gateway._adapters:
        if type(adapter).__name__ == "TelegramAdapter":
            try:
                chat_id = getattr(adapter, "_digest_chat_id", None)
                if chat_id and adapter.app and adapter.app.bot:
                    await adapter.app.bot.send_message(chat_id=chat_id, text=text[:4000])
                    return
                # Fallback: no chat pinned yet — log only
                logger.info("Night-shift digest:\n%s", text)
            except Exception as exc:
                logger.warning("Failed to send night-shift digest: %s", exc)
            return
    logger.info("Night-shift digest (no Telegram):\n%s", text)
