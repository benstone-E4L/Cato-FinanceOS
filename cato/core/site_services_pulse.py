"""

Poll SwarmSync site-services Cato inbox + stuck jobs; notify Telegram per new item.

"""



from __future__ import annotations



import json

import logging

from datetime import datetime, timezone

from pathlib import Path

from typing import Any



from ..platform import get_data_dir

from ..tools.site_services_bridge import (
    fetch_inbox,
    fetch_stuck,
    format_inbox_item_text,
    format_stuck_job_text,
    notify_new_inbox_item,
    notify_stuck_job,
    send_telegram_message,
)



logger = logging.getLogger(__name__)



_SESSION_ID = "sched-site-services-inbox"

_STATE_FILE = "site_services_pulse_state.json"





def _state_path() -> Path:

    return get_data_dir() / _STATE_FILE





def _load_state() -> dict[str, Any]:

    path = _state_path()

    if not path.is_file():

        return {"seen_ids": [], "seen_stuck_ids": []}

    try:

        data = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(data, dict):

            return {"seen_ids": [], "seen_stuck_ids": []}

        return data

    except Exception as exc:

        logger.warning("Could not read pulse state: %s", exc)

        return {"seen_ids": [], "seen_stuck_ids": []}





def _save_state(state: dict[str, Any]) -> None:

    path = _state_path()

    path.parent.mkdir(parents=True, exist_ok=True)

    seen = state.get("seen_ids") or []

    if isinstance(seen, set):

        seen = list(seen)

    state["seen_ids"] = list(seen)[-500:]
    stuck_seen = state.get("seen_stuck_ids") or []
    if isinstance(stuck_seen, set):
        stuck_seen = list(stuck_seen)
    state["seen_stuck_ids"] = list(stuck_seen)[-500:]

    path.write_text(json.dumps(state, indent=2), encoding="utf-8")





def _item_id(item: dict[str, Any]) -> str:

    for key in ("quoteId", "quote_id", "id", "permitSignalId", "signalId"):

        val = item.get(key)

        if val is not None and str(val).strip():

            return str(val)

    address = str(item.get("projectAddress") or item.get("address") or item.get("siteAddress") or "")

    sku = str(item.get("sku") or item.get("category") or "")

    return f"{address}|{sku}|{item.get('quoteUrl') or item.get('quote_url') or ''}"


def _stuck_job_id(job: dict[str, Any]) -> str:
    for key in ("jobId", "job_id", "id"):
        val = job.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""





async def run_site_services_inbox_pulse(

    gateway: Any,

    *,

    notify: bool = True,

    session_id: str = _SESSION_ID,

) -> dict[str, Any]:

    """Poll /api/cato/inbox and /api/cato/jobs/stuck; notify on new inbox items."""

    vault = getattr(gateway, "_vault", None)



    inbox_result = await fetch_inbox(vault)

    if not inbox_result.get("ok"):

        detail = inbox_result.get("error") or "inbox fetch failed"

        if notify:

            await gateway.send(session_id, f"Site-services pulse skipped: {detail}", "cron")

            await send_telegram_message(gateway, f"Site-services pulse skipped: {detail}")

        return {"ok": False, "inbox_count": 0, "stuck_count": 0, "detail": detail}



    stuck_result = await fetch_stuck(vault)

    stuck_jobs = stuck_result.get("jobs") or [] if stuck_result.get("ok") else []

    stuck_count = len(stuck_jobs)



    items = inbox_result.get("items") or []

    inbox_count = len(items)

    state = _load_state()

    seen = set(state.get("seen_ids") or [])
    seen_stuck = set(state.get("seen_stuck_ids") or [])

    new_items = [it for it in items if _item_id(it) not in seen]
    new_stuck = [job for job in stuck_jobs if _stuck_job_id(job) and _stuck_job_id(job) not in seen_stuck]

    if notify:
        for item in new_items:
            sent = await notify_new_inbox_item(gateway, item)
            if not sent:
                await gateway.send(
                    session_id,
                    format_inbox_item_text(item)[:3500],
                    "cron",
                )

        for job in new_stuck:
            sent = await notify_stuck_job(gateway, job)
            if not sent:
                await gateway.send(
                    session_id,
                    format_stuck_job_text(job)[:3500],
                    "cron",
                )

        if stuck_count and not new_items and not new_stuck:
            summary = f"Site-services pulse: {inbox_count} inbox, {stuck_count} stuck (no new items)."
            await gateway.send(session_id, summary, "cron")
            await send_telegram_message(gateway, summary)
        elif not new_items and not new_stuck and inbox_count == 0:

            msg = "Site-services pulse: inbox empty."

            await gateway.send(session_id, msg, "cron")

            await send_telegram_message(gateway, msg)



    for item in new_items:
        seen.add(_item_id(item))

    for job in new_stuck:
        jid = _stuck_job_id(job)
        if jid:
            seen_stuck.add(jid)

    detail_parts = [
        f"inbox={inbox_count}",
        f"new={len(new_items)}",
        f"stuck={stuck_count}",
        f"new_stuck={len(new_stuck)}",
    ]

    if not stuck_result.get("ok"):

        detail_parts.append(f"stuck_err={stuck_result.get('error', 'unknown')}")



    detail = "Site-services pulse complete: " + ", ".join(detail_parts)

    state["seen_ids"] = list(seen)
    state["seen_stuck_ids"] = list(seen_stuck)

    state["last_detail"] = detail

    state["last_run_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    state["inbox_count"] = inbox_count

    state["stuck_count"] = stuck_count

    _save_state(state)



    return {

        "ok": True,

        "inbox_count": inbox_count,

        "stuck_count": stuck_count,

        "new_count": len(new_items),

        "detail": detail,

    }


