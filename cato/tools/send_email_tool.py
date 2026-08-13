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


def _coerce_draft_only(value: Any) -> bool:
    """Resolve ``draft_only`` fail-closed: anything unclear means DRAFT.

    The old coercion was ``args.get("draft_only", True)`` plus a string check,
    so ``{"draft_only": null}``, ``0``, ``[]`` and ``{}`` all evaluated falsey
    and selected the LIVE path. This value is written by the model, so an
    ambiguous value must never be read as permission to send.
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ("0", "false", "no", "off"):
            return False
        if token in ("1", "true", "yes", "on"):
            return True
        return True
    # Any other type is unreadable intent -> draft.
    return True


async def execute_send_email(args: dict[str, Any]) -> str:
    from ..core.night_shift_policy import assert_skill_allowed

    if not isinstance(args, dict):
        return json.dumps({
            "ok": False, "error": "invalid_arguments",
            "message": "args must be a JSON object",
        })

    draft_only = _coerce_draft_only(args.get("draft_only", True))

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

    # Live send path. There is NO send implementation behind this tool: the
    # Gmail adapter is deliberately draft-only and raises PermissionError at
    # `GmailAdapter._send_draft_sync`, and no other code path clicks Send.
    #
    # Returning ok:true here claimed a delivered email that never left the
    # machine, and `_tool_result_failure` reads the OUTER object — so the
    # hash-chained ledger recorded CONFIRMED/success for an email that does
    # not exist. That is the one failure mode this repo's own doctrine
    # forbids: nothing may report ok on the strength of its own narration.
    return json.dumps({
        "ok": False,
        "error": "not_implemented",
        "mode": "send",
        "to": to,
        "subject": subject,
        "message": (
            "Live send is not implemented. Cato is draft-only end to end "
            "(GmailAdapter._send_draft_sync refuses by design). Re-issue with "
            "draft_only=true and send the Gmail draft manually."
        ),
    })
