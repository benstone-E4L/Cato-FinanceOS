"""
cato/tools/send_email_tool.py — Outbound email tool with draft-only default.

Never clicks Gmail Send without approval + live_outreach policy gate.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

SEND_EMAIL_SCHEMA = {
    "name": "send_email",
    "description": (
        "Prepare or send email via Gmail UI automation. "
        "Default is draft_only=true. Live send requires Telegram approval and G1 gate."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "draft_only": {
                "type": "boolean",
                "description": "If true (default), compose only — do not send.",
            },
        },
        "required": ["to", "subject", "body"],
    },
}


async def execute_send_email(args: dict[str, Any]) -> str:
    from ..core.night_shift_policy import assert_skill_allowed

    draft_only = args.get("draft_only", True)
    if isinstance(draft_only, str):
        draft_only = draft_only.lower() in ("1", "true", "yes")

    check_args = {**args, "draft_only": draft_only}
    try:
        assert_skill_allowed("send_email", check_args)
    except PermissionError as exc:
        return json.dumps({"ok": False, "error": "policy_blocked", "message": str(exc)})

    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")

    if draft_only:
        return json.dumps({
            "ok": True,
            "mode": "draft_only",
            "to": to,
            "subject": subject,
            "preview": body[:500],
            "message": "Draft prepared (dry). No Gmail Send action executed.",
        })

    # Live send path — must pass approval gate in agent_loop before reaching here
    return json.dumps({
        "ok": True,
        "mode": "send",
        "to": to,
        "subject": subject,
        "message": "Send approved — Gmail automation should complete Send click.",
    })
