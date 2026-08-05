"""

cato/tools/site_services_bridge.py — Site-services permit arbitrage API bridge.



Vault keys: SITE_SERVICES_BASE_URL, SITE_SERVICES_INTERNAL_SECRET (fallback INTERNAL_SECRET).

"""



from __future__ import annotations



import asyncio

import json

import logging

import os

import re

from typing import Any, Optional



import aiohttp

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from telegram.ext import ContextTypes



logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)

_REQUEST_TIMEOUT_SEC = 45



# Callback prefixes (Telegram callback_data max 64 bytes)

CB_DRAFT = "ss_dft_"

CB_SKIP = "ss_skp_"

CB_QUOTE = "ss_qte_"

CB_MATCH = "ss_mtc_"

CB_APPROVE = "ss_ok_"

CB_DENY = "ss_no_"

CB_MATCH_SKIP = "ss_msk_"

CB_REVIEW_OK = "ss_rok_"

CB_REVIEW_NO = "ss_rno_"



INBOX_SCHEMA = {

    "name": "site_services.inbox",

    "description": "Fetch permit arbitrage inbox from SwarmSync site-services (/api/cato/inbox).",

    "parameters": {"type": "object", "properties": {}},

}



STUCK_SCHEMA = {

    "name": "site_services.stuck",

    "description": "Fetch stuck site-services jobs (/api/cato/jobs/stuck).",

    "parameters": {"type": "object", "properties": {}},

}





def _vault_get(vault: Any, key: str) -> Optional[str]:

    if vault is None:

        return None

    try:

        val = vault.get(key)

        return (val or "").strip() or None

    except Exception as exc:

        logger.warning("Vault read failed for %s: %s", key, exc)

        return None





def resolve_site_services_config(vault: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:

    """Return (base_url, secret, error_detail)."""

    secret = _vault_get(vault, "SITE_SERVICES_INTERNAL_SECRET") or _vault_get(vault, "INTERNAL_SECRET")

    if not secret:

        return None, None, "SITE_SERVICES_INTERNAL_SECRET missing in Cato vault — run scripts/sync_site_services_vault.py"



    base_url = _vault_get(vault, "SITE_SERVICES_BASE_URL")
    if not base_url:
        return None, None, (
            "SITE_SERVICES_BASE_URL missing in Cato vault — run scripts/sync_site_services_vault.py"
        )

    return base_url.rstrip("/"), secret, None


def _require_uuid(value: str, label: str) -> Optional[str]:
    if not _UUID_RE.match((value or "").strip()):
        return f"Invalid {label}: expected UUID"
    return None





def _auth_headers(secret: str) -> dict[str, str]:

    return {

        "Authorization": f"Bearer {secret}",

        "Accept": "application/json",

        "Content-Type": "application/json",

    }





async def _fetch_json(

    base_url: str,

    secret: str,

    path: str,

    *,

    method: str = "GET",

    body: Optional[dict[str, Any]] = None,

) -> tuple[int, Any]:

    url = f"{base_url}{path}"

    headers = _auth_headers(secret)

    timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SEC)

    async with aiohttp.ClientSession(timeout=timeout) as session:

        kwargs: dict[str, Any] = {"headers": headers}

        if body is not None:

            kwargs["json"] = body

        async with session.request(method, url, **kwargs) as resp:

            text = await resp.text()

            try:

                parsed = json.loads(text) if text.strip() else {}

            except json.JSONDecodeError:

                parsed = {"raw": text[:500]}

            return resp.status, parsed





def _normalize_items(payload: Any, *, list_key: str = "items") -> list[dict[str, Any]]:

    if isinstance(payload, list):

        return [x for x in payload if isinstance(x, dict)]

    if isinstance(payload, dict):

        for key in (list_key, "inbox", "jobs", "data", "results"):

            val = payload.get(key)

            if isinstance(val, list):

                return [x for x in val if isinstance(x, dict)]

    return []





async def fetch_inbox(vault: Any) -> dict[str, Any]:

    base_url, secret, err = resolve_site_services_config(vault)

    if err:

        return {"ok": False, "error": err, "items": []}



    try:

        status, body = await _fetch_json(base_url, secret, "/api/cato/inbox")

    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:

        return {"ok": False, "error": f"network error: {exc}", "items": []}

    if status != 200:

        return {

            "ok": False,

            "error": f"inbox HTTP {status}",

            "items": [],

            "body": body,

        }

    items = _normalize_items(body)

    return {"ok": True, "items": items, "count": len(items), "base_url": base_url}





async def fetch_stuck(vault: Any) -> dict[str, Any]:

    base_url, secret, err = resolve_site_services_config(vault)

    if err:

        return {"ok": False, "error": err, "jobs": []}



    try:

        status, body = await _fetch_json(base_url, secret, "/api/cato/jobs/stuck")

    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:

        return {"ok": False, "error": f"network error: {exc}", "jobs": []}

    if status != 200:

        return {

            "ok": False,

            "error": f"stuck HTTP {status}",

            "jobs": [],

            "body": body,

        }

    jobs = _normalize_stuck_jobs(body)

    return {"ok": True, "jobs": jobs, "count": len(jobs), "base_url": base_url}


def _normalize_stuck_jobs(payload: Any) -> list[dict[str, Any]]:
    """Merge stuck + review arrays from /api/cato/jobs/stuck."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("stuck", "review", "jobs", "items"):
        val = payload.get(key)
        if not isinstance(val, list):
            continue
        for row in val:
            if not isinstance(row, dict):
                continue
            job_id = _job_id_from_item(row)
            if job_id:
                if job_id in seen:
                    continue
                seen.add(job_id)
            merged.append(row)
    return merged





async def fetch_audit_summary(vault: Any, *, since: str = "24h") -> dict[str, Any]:

    base_url, secret, err = resolve_site_services_config(vault)

    if err:

        return {"ok": False, "error": err}



    path = f"/api/cato/audit/summary?since={since}"

    status, body = await _fetch_json(base_url, secret, path)

    if status != 200:

        return {"ok": False, "error": f"audit HTTP {status}", "body": body}

    return {"ok": True, "summary": body, "base_url": base_url}





async def draft_outreach(vault: Any, quote_id: str) -> dict[str, Any]:

    base_url, secret, err = resolve_site_services_config(vault)

    if err:

        return {"ok": False, "error": err}

    uuid_err = _require_uuid(quote_id, "quote_id")
    if uuid_err:
        return {"ok": False, "error": uuid_err}

    path = f"/api/cato/opportunities/{quote_id}/draft-outreach"

    status, body = await _fetch_json(base_url, secret, path, method="POST", body={})

    if status != 200:

        return {"ok": False, "error": f"draft-outreach HTTP {status}", "body": body}

    return {"ok": True, "draft": body, "base_url": base_url}





async def send_outreach(

    vault: Any,

    quote_id: str,

    *,

    approved_by: str = "cato-telegram",

) -> dict[str, Any]:

    base_url, secret, err = resolve_site_services_config(vault)

    if err:

        return {"ok": False, "error": err}

    uuid_err = _require_uuid(quote_id, "quote_id")
    if uuid_err:
        return {"ok": False, "error": uuid_err}

    path = f"/api/cato/opportunities/{quote_id}/send-outreach"

    status, body = await _fetch_json(

        base_url,

        secret,

        path,

        method="POST",

        body={"approvedBy": approved_by},

    )

    if status not in (200, 201, 202):

        return {"ok": False, "error": f"send-outreach HTTP {status}", "body": body}

    return {"ok": True, "result": body, "base_url": base_url}





async def match_preview(vault: Any, job_id: str) -> dict[str, Any]:

    base_url, secret, err = resolve_site_services_config(vault)

    if err:

        return {"ok": False, "error": err}

    uuid_err = _require_uuid(job_id, "job_id")
    if uuid_err:
        return {"ok": False, "error": uuid_err}

    status, body = await _fetch_json(

        base_url,

        secret,

        "/api/match/preview",

        method="POST",

        body={"jobId": job_id},

    )

    if status != 200:

        return {"ok": False, "error": f"match/preview HTTP {status}", "body": body}

    matches = body.get("matches") if isinstance(body, dict) else []

    if not isinstance(matches, list):

        matches = []

    return {"ok": True, "matches": matches, "body": body, "base_url": base_url}





async def match_apply(

    vault: Any,

    job_id: str,

    supplier_id: str,

    *,

    approved_by: str = "cato-telegram",

) -> dict[str, Any]:

    base_url, secret, err = resolve_site_services_config(vault)

    if err:

        return {"ok": False, "error": err}

    for value, label in ((job_id, "job_id"), (supplier_id, "supplier_id")):
        uuid_err = _require_uuid(value, label)
        if uuid_err:
            return {"ok": False, "error": uuid_err}

    status, body = await _fetch_json(

        base_url,

        secret,

        "/api/match/apply",

        method="POST",

        body={

            "jobId": job_id,

            "supplierId": supplier_id,

            "approvedBy": approved_by,

        },

    )

    if status not in (200, 201, 202):

        return {"ok": False, "error": f"match/apply HTTP {status}", "body": body}

    return {"ok": True, "result": body, "base_url": base_url}





async def review_job(

    vault: Any,

    job_id: str,

    *,

    action: str,

) -> dict[str, Any]:

    """action: approve | reject"""

    if action not in ("approve", "reject"):

        return {"ok": False, "error": f"invalid review action: {action}"}



    base_url, secret, err = resolve_site_services_config(vault)

    if err:

        return {"ok": False, "error": err}

    uuid_err = _require_uuid(job_id, "job_id")
    if uuid_err:
        return {"ok": False, "error": uuid_err}

    path = f"/api/cato/review/{job_id}/{action}"

    status, body = await _fetch_json(base_url, secret, path, method="POST", body={})

    if status not in (200, 201, 202):

        return {"ok": False, "error": f"review/{action} HTTP {status}", "body": body}

    return {"ok": True, "result": body, "base_url": base_url}





def _quote_id_from_item(item: dict[str, Any]) -> str:

    for key in ("quoteId", "quote_id", "id"):

        val = item.get(key)

        if val is not None and str(val).strip():

            return str(val).strip()

    return ""





def _job_id_from_item(item: dict[str, Any]) -> str:

    for key in ("jobId", "job_id", "id"):

        val = item.get(key)

        if val is not None and str(val).strip():

            return str(val).strip()

    return ""





def _quote_url_from_item(item: dict[str, Any]) -> str:

    for key in ("quoteUrl", "quote_url"):

        val = item.get(key)

        if val is not None and str(val).strip():

            return str(val).strip()

    return ""





def format_inbox_item_text(item: dict[str, Any]) -> str:

    address = item.get("projectAddress") or item.get("address") or item.get("siteAddress") or "—"

    sku = item.get("sku") or item.get("category") or "—"

    price = item.get("totalPriceUsd") or item.get("price") or item.get("quotedPrice") or item.get("amount")

    price_str = f"${price}" if price is not None else "—"

    name = item.get("applicantName") or ""

    lines = [

        "Site-services inbox",

        f"Address: {address}",

        f"SKU: {sku}",

        f"Price: {price_str}",

    ]

    if name:

        lines.append(f"Applicant: {name}")

    quote_id = _quote_id_from_item(item)

    if quote_id:

        lines.append(f"Quote ID: {quote_id}")

    return "\n".join(lines)


def format_stuck_job_text(job: dict[str, Any]) -> str:
    address = job.get("projectAddress") or job.get("address") or "—"
    sku = job.get("sku") or "—"
    status = job.get("status") or "—"
    vcap = job.get("vcapState") or "—"
    reason = job.get("reason") or "needs review"
    supplier = job.get("supplierName") or "—"
    elapsed = job.get("elapsedMinutes")
    elapsed_str = f"{elapsed}m" if elapsed is not None else "—"
    job_id = _job_id_from_item(job)
    lines = [
        "Site-services stuck job",
        f"Job: {job_id or '—'}",
        f"Address: {address}",
        f"SKU: {sku}",
        f"Status: {status} / {vcap}",
        f"Reason: {reason}",
        f"Supplier: {supplier}",
        f"Elapsed: {elapsed_str}",
    ]
    return "\n".join(lines)


def stuck_job_keyboard(job: dict[str, Any]) -> InlineKeyboardMarkup:
    job_id = _job_id_from_item(job)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Approve", callback_data=f"{CB_REVIEW_OK}{job_id}"),
            InlineKeyboardButton("Reject", callback_data=f"{CB_REVIEW_NO}{job_id}"),
        ],
    ])


def inbox_item_keyboard(item: dict[str, Any]) -> InlineKeyboardMarkup:

    quote_id = _quote_id_from_item(item)

    job_id = _job_id_from_item(item)

    rows: list[list[InlineKeyboardButton]] = [

        [

            InlineKeyboardButton("Draft Email", callback_data=f"{CB_DRAFT}{quote_id}"),

            InlineKeyboardButton("Open Quote", callback_data=f"{CB_QUOTE}{quote_id}"),

        ],

        [

            InlineKeyboardButton("Skip", callback_data=f"{CB_SKIP}{quote_id}"),

        ],

    ]

    if job_id:

        rows[1].insert(0, InlineKeyboardButton("Propose Match", callback_data=f"{CB_MATCH}{job_id}"))

    return InlineKeyboardMarkup(rows)





def _approval_keyboard(approval_id: str) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton("Approve Send", callback_data=f"{CB_APPROVE}{approval_id}"),

            InlineKeyboardButton("Deny", callback_data=f"{CB_DENY}{approval_id}"),

        ],

    ])





def _match_keyboard(approval_id: str) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton("Approve Match", callback_data=f"{CB_APPROVE}{approval_id}"),

            InlineKeyboardButton("Skip", callback_data=f"{CB_MATCH_SKIP}{approval_id}"),

        ],

    ])





def resolve_telegram_chat_id(gateway: Any) -> Optional[int]:

    """Resolve Telegram chat for site-services notifications."""

    for adapter in getattr(gateway, "_adapters", []):

        if type(adapter).__name__ != "TelegramAdapter":

            continue

        chat_id = getattr(adapter, "_digest_chat_id", None)

        if chat_id is not None:

            return int(chat_id)



    raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if raw:

        try:

            return int(raw.split(",")[0].strip())

        except ValueError:

            pass



    vault = getattr(gateway, "_vault", None)

    if vault is not None:

        vault_chat = _vault_get(vault, "TELEGRAM_CHAT_ID")

        if vault_chat:

            try:

                return int(vault_chat.split(",")[0].strip())

            except ValueError:

                pass

    return None





def _telegram_bot(gateway: Any):

    for adapter in getattr(gateway, "_adapters", []):

        if type(adapter).__name__ == "TelegramAdapter":

            app = getattr(adapter, "app", None)

            if app is not None and app.bot is not None:

                return app.bot

    return None





async def send_telegram_message(

    gateway: Any,

    text: str,

    *,

    reply_markup: Optional[InlineKeyboardMarkup] = None,

) -> bool:

    bot = _telegram_bot(gateway)

    chat_id = resolve_telegram_chat_id(gateway)

    if bot is None or chat_id is None:

        return False

    try:

        await bot.send_message(

            chat_id=chat_id,

            text=text[:4000],

            reply_markup=reply_markup,

        )

        return True

    except Exception as exc:

        logger.warning("site-services Telegram send failed: %s", exc)

        return False





async def notify_new_inbox_item(gateway: Any, item: dict[str, Any]) -> bool:

    """Send inbox item to Telegram with action keyboard."""

    text = format_inbox_item_text(item)

    markup = inbox_item_keyboard(item)

    return await send_telegram_message(gateway, text, reply_markup=markup)





def register_site_services_callbacks(app: Any) -> None:

    """Register Telegram callback handlers on the Application."""

    from telegram.ext import CallbackQueryHandler



    app.add_handler(

        CallbackQueryHandler(

            handle_site_services_callback,

            pattern=r"^ss_(dft|skp|qte|mtc|ok|no|msk|rok|rno)_",

        )

    )





async def handle_site_services_callback(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE,

) -> None:

    """Route site-services inline button taps."""

    query = update.callback_query

    if query is None:

        return

    await query.answer()



    data = query.data or ""

    gateway = context.application.bot_data.get("cato_gateway")

    vault = getattr(gateway, "_vault", None) if gateway else None



    if data.startswith(CB_SKIP):

        quote_id = data[len(CB_SKIP):]

        await query.edit_message_reply_markup(reply_markup=None)

        await query.message.reply_text(f"Skipped quote {quote_id}.")

        return



    if data.startswith(CB_QUOTE):

        quote_id = data[len(CB_QUOTE):]

        url = ""

        if gateway is not None:

            inbox = await fetch_inbox(vault)

            if inbox.get("ok"):

                for item in inbox.get("items") or []:

                    if _quote_id_from_item(item) == quote_id:

                        url = _quote_url_from_item(item)

                        break

        if not url and vault is not None:

            base_url, _, _ = resolve_site_services_config(vault)

            if base_url:

                url = f"{base_url}/quote/{quote_id}"

        await query.message.reply_text(url or f"Quote {quote_id} (URL unavailable)")

        return



    if data.startswith(CB_DRAFT):

        quote_id = data[len(CB_DRAFT):]

        await _handle_draft_outreach(query, vault, quote_id)

        return



    if data.startswith(CB_MATCH):

        job_id = data[len(CB_MATCH):]

        await _handle_match_preview(query, vault, job_id)

        return



    if data.startswith(CB_REVIEW_OK):
        job_id = data[len(CB_REVIEW_OK):]
        await _handle_review_action(query, vault, job_id, action="approve")
        return

    if data.startswith(CB_REVIEW_NO):
        job_id = data[len(CB_REVIEW_NO):]
        await _handle_review_action(query, vault, job_id, action="reject")
        return

    if data.startswith(CB_APPROVE):

        approval_id = data[len(CB_APPROVE):]

        await _handle_approval(query, vault, approval_id, approved=True)

        return



    if data.startswith(CB_DENY) or data.startswith(CB_MATCH_SKIP):

        prefix = CB_DENY if data.startswith(CB_DENY) else CB_MATCH_SKIP

        approval_id = data[len(prefix):]

        await _handle_approval(query, vault, approval_id, approved=False)

        return



    await query.message.reply_text("Unknown site-services action.")





async def _handle_review_action(
    query: Any,
    vault: Any,
    job_id: str,
    *,
    action: str,
) -> None:
    result = await review_job(vault, job_id, action=action)
    await query.edit_message_reply_markup(reply_markup=None)
    if result.get("ok"):
        await query.message.reply_text(f"Job {job_id}: {action}d.")
    else:
        err = result.get("error") or f"{action} failed"
        await query.message.reply_text(f"Job {job_id}: {err}")


async def notify_stuck_job(gateway: Any, job: dict[str, Any]) -> bool:
    text = format_stuck_job_text(job)
    markup = stuck_job_keyboard(job)
    return await send_telegram_message(gateway, text, reply_markup=markup)


async def _handle_draft_outreach(query: Any, vault: Any, quote_id: str) -> None:

    from cato.core.outbound_approval import get_approval_store



    result = await draft_outreach(vault, quote_id)

    if not result.get("ok"):

        err = result.get("error") or "draft failed"

        await query.message.reply_text(f"Draft failed: {err}")

        return



    draft = result.get("draft") or {}

    subject = str(draft.get("subject") or "(no subject)")

    recipient = str(draft.get("recipient") or "—")

    checkout = str(draft.get("checkoutUrl") or "")

    preview = f"To: {recipient}\nSubject: {subject}"

    if checkout:

        preview += f"\nCheckout: {checkout}"



    store = get_approval_store()

    approval = store.create(

        session_id="site-services",

        tool_name="site_services.send_outreach",

        args={"quoteId": quote_id, "recipient": recipient, "subject": subject},

        preview=preview,

    )



    await query.edit_message_reply_markup(reply_markup=None)

    html_preview = str(draft.get("html") or "")[:400]

    body_lines = [

        f"Draft ready ({approval.id})",

        preview,

    ]

    if html_preview:

        body_lines.append(f"\nHTML preview:\n{html_preview}")

    await query.message.reply_text(

        "\n".join(body_lines)[:4000],

        reply_markup=_approval_keyboard(approval.id),

    )





async def _handle_match_preview(query: Any, vault: Any, job_id: str) -> None:

    from cato.core.outbound_approval import get_approval_store



    result = await match_preview(vault, job_id)

    if not result.get("ok"):

        err = result.get("error") or "match preview failed"

        await query.message.reply_text(f"Match preview failed: {err}")

        return



    matches = result.get("matches") or []

    if not matches:

        await query.message.reply_text(f"No supplier matches for job {job_id}.")

        return



    top = matches[0]

    supplier_id = str(top.get("supplierId") or "")

    supplier_name = str(top.get("supplierName") or supplier_id or "—")

    score = top.get("matchScore")

    review_flag = top.get("requiresHumanReview")

    preview = f"Match: {supplier_name} (score={score}, review={review_flag})"



    store = get_approval_store()

    approval = store.create(

        session_id="site-services",

        tool_name="site_services.match_apply",

        args={"jobId": job_id, "supplierId": supplier_id},

        preview=preview,

    )



    await query.edit_message_reply_markup(reply_markup=None)

    extra = ""

    if len(matches) > 1:

        extra = f"\n(+{len(matches) - 1} more candidates — top match shown)"

    await query.message.reply_text(

        f"Job {job_id}\n{preview}{extra}",

        reply_markup=_match_keyboard(approval.id),

    )





async def _handle_approval(

    query: Any,

    vault: Any,

    approval_id: str,

    *,

    approved: bool,

) -> None:

    from cato.core.outbound_approval import get_approval_store



    store = get_approval_store()

    if not approved:

        row = store.resolve(approval_id, "denied", resolved_by="cato-telegram")

        if row is None:

            await query.answer("Already resolved.", show_alert=True)

            return

        await query.edit_message_reply_markup(reply_markup=None)

        await query.message.reply_text(f"Denied {approval_id}.")

        return



    row = store.get(approval_id)

    if row is None:

        await query.answer("Approval not found.", show_alert=True)

        return

    if row.status != "pending":

        await query.answer("Already resolved.", show_alert=True)

        return



    store.resolve(approval_id, "approved", resolved_by="cato-telegram")

    await query.edit_message_reply_markup(reply_markup=None)



    if row.tool_name == "site_services.send_outreach":

        quote_id = str(row.args.get("quoteId") or "")

        result = await send_outreach(vault, quote_id, approved_by="cato-telegram")

    elif row.tool_name == "site_services.match_apply":

        job_id = str(row.args.get("jobId") or "")

        supplier_id = str(row.args.get("supplierId") or "")

        result = await match_apply(

            vault,

            job_id,

            supplier_id,

            approved_by="cato-telegram",

        )

    else:

        await query.message.reply_text(f"Unknown tool for approval {approval_id}.")

        return



    if result.get("ok"):

        await query.message.reply_text(f"Approved {approval_id}. Done.")

    else:

        err = result.get("error") or "action failed"

        await query.message.reply_text(f"Approved {approval_id} but failed: {err}")





async def execute_site_services_inbox(args: dict[str, Any]) -> str:

    from ..vault import get_vault



    result = await fetch_inbox(get_vault())

    return json.dumps(result, default=str)[:8000]





async def execute_site_services_stuck(args: dict[str, Any]) -> str:

    from ..vault import get_vault



    result = await fetch_stuck(get_vault())

    return json.dumps(result, default=str)[:8000]


