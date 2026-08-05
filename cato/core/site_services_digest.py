"""
Morning digest: site-services audit summary, inbox pulse stats, pending approvals.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..platform import get_data_dir
from ..core.outbound_approval import get_approval_store
from ..tools.site_services_bridge import fetch_audit_summary, fetch_inbox, fetch_stuck

logger = logging.getLogger(__name__)

_PULSE_STATE = "site_services_pulse_state.json"


def _read_pulse_state() -> dict[str, Any]:
    path = get_data_dir() / _PULSE_STATE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Could not read pulse state: %s", exc)
        return {}


async def build_site_services_digest(vault: Any) -> str:
    """Compose plain-text digest for Telegram."""
    pending = get_approval_store().list_pending(limit=50)
    site_pending = [p for p in pending if p.tool_name.startswith("site_services.")]

    pulse_state = _read_pulse_state()
    last_detail = pulse_state.get("last_detail") or "—"
    last_run = pulse_state.get("last_run_at") or "—"

    inbox_result = await fetch_inbox(vault)
    stuck_result = await fetch_stuck(vault)
    audit_result = await fetch_audit_summary(vault, since="24h")

    inbox_count = inbox_result.get("count", 0) if inbox_result.get("ok") else "?"
    stuck_count = stuck_result.get("count", 0) if stuck_result.get("ok") else "?"

    lines = [
        "Site-Services Morning Digest",
        "",
        "Inbox / stuck:",
        f"  Inbox: {inbox_count} pending quotes",
        f"  Stuck jobs: {stuck_count}",
        f"  Last pulse: {last_run}",
        f"  {last_detail}",
        "",
        f"Outbound approvals (site-services): {len(site_pending)}",
        f"Outbound approvals (all): {len(pending)}",
    ]
    for p in site_pending[:5]:
        lines.append(f"  • {p.id}: {p.preview[:70]}")

    if audit_result.get("ok"):
        summary = audit_result.get("summary") or {}
        since = summary.get("since") or "24h"
        counts = summary.get("countByEventType") or {}
        lines.extend(["", f"Audit (since {since}):"])
        if counts:
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:6]
            for event_type, count in top:
                lines.append(f"  • {event_type}: {count}")
        else:
            lines.append("  • No audit events in window")
    else:
        err = audit_result.get("error") or "audit fetch failed"
        lines.extend(["", f"Audit: unavailable ({err})"])

    return "\n".join(lines)


async def send_site_services_digest_via_gateway(gateway: Any) -> None:
    """Push digest to Telegram if adapter is registered."""
    from ..tools.site_services_bridge import send_telegram_message

    vault = getattr(gateway, "_vault", None)
    text = await build_site_services_digest(vault)
    sent = await send_telegram_message(gateway, text[:4000])
    if not sent:
        logger.info("Site-services digest (no Telegram):\n%s", text)
