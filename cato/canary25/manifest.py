"""Read/write canary-25 manifest.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .contacts import ContactRow
from .paths import default_canary_dir

MANIFEST_NAME = "manifest.json"
TRACKING_CSV_NAME = "tracking-sheet.csv"
SELECTION_DOC_NAME = "selection-criteria.md"

PASS_MIN_ENGAGEMENT = 1
PASS_MAX_COMPLAINT_RATE_PCT = 0.1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _empty_tracking() -> dict[str, Any]:
    return {
        "window_start": "",
        "window_end": "",
        "window_days": 7,
        "sent_count": 0,
        "replies": 0,
        "audit_views": 0,
        "complaints": 0,
        "bounces": 0,
        "complaint_rate_pct": 0.0,
        "bounce_rate_pct": 0.0,
    }


def _contact_to_dict(row: ContactRow) -> dict[str, Any]:
    return {
        "contact_id": row.contact_id,
        "domain": row.domain,
        "receiver_email": row.receiver_email,
        "first_name": row.first_name,
        "company_name": row.company_name,
        "notes": row.notes,
        "scrape_source": row.scrape_source,
        "tier": row.tier,
        "score": row.score,
        "send_status": "pending",
        "approved_at": "",
        "sent_at": "",
        "reply": False,
        "audit_view": False,
        "complaint": False,
        "bounce": False,
        "operator_notes": "",
    }


def build_manifest(
    selected: list[ContactRow],
    *,
    source_file: str,
    selection_meta: dict[str, Any],
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    bid = batch_id or f"canary-25-{stamp}"
    return {
        "batch_id": bid,
        "created": _utc_now_iso(),
        "status": "selected",
        "g1_safety": {
            "live_outreach_via_cato": False,
            "operator_hand_approve_each_send": True,
            "notes": "Cato does not enqueue live sends until G1. Use outreach engine manually per contact.",
        },
        "source_file": source_file,
        "selection": {
            "criteria_version": "1.0",
            "pool_size": selection_meta.get("pool_unique_domains", 0),
            "selected_count": len(selected),
            "seed": selection_meta.get("seed"),
            "excluded_contact_ids": selection_meta.get("excluded_ids", 0),
        },
        "tracking": _empty_tracking(),
        "pass_criteria": {
            "min_replies_or_audit_views": PASS_MIN_ENGAGEMENT,
            "max_complaint_rate_pct": PASS_MAX_COMPLAINT_RATE_PCT,
            "description": "Row 4 loop-proof-card: >=1 reply OR >=1 audit view; complaints <0.1%",
        },
        "contacts": [_contact_to_dict(r) for r in selected],
        "evidence": {
            "deliverability_report": "proof-artifacts/fp1/",
            "tracking_sheet": f"proof-artifacts/canary-25/{TRACKING_CSV_NAME}",
            "stripe_payment_url": "",
            "fulfillment_artifact": "",
        },
        "notes": "",
    }


def load_manifest(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or (default_canary_dir() / MANIFEST_NAME)
    p = Path(p).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Manifest not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_manifest(data: dict[str, Any], path: Optional[Path] = None) -> Path:
    p = path or (default_canary_dir() / MANIFEST_NAME)
    p = Path(p).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def find_contact(manifest: dict[str, Any], contact_id: str) -> Optional[dict[str, Any]]:
    cid = contact_id.strip().lower()
    for c in manifest.get("contacts") or []:
        if str(c.get("contact_id", "")).lower() == cid:
            return c
    return None


def recompute_tracking_totals(manifest: dict[str, Any]) -> None:
    contacts = manifest.get("contacts") or []
    tr = manifest.setdefault("tracking", _empty_tracking())
    sent = sum(1 for c in contacts if c.get("send_status") == "sent")
    replies = sum(1 for c in contacts if c.get("reply"))
    views = sum(1 for c in contacts if c.get("audit_view"))
    complaints = sum(1 for c in contacts if c.get("complaint"))
    bounces = sum(1 for c in contacts if c.get("bounce"))
    tr["sent_count"] = sent
    tr["replies"] = replies
    tr["audit_views"] = views
    tr["complaints"] = complaints
    tr["bounces"] = bounces
    if sent > 0:
        tr["complaint_rate_pct"] = round(100.0 * complaints / sent, 4)
        tr["bounce_rate_pct"] = round(100.0 * bounces / sent, 4)
    else:
        tr["complaint_rate_pct"] = 0.0
        tr["bounce_rate_pct"] = 0.0


def evaluate_pass(manifest: dict[str, Any]) -> dict[str, Any]:
    tr = manifest.get("tracking") or {}
    sent = int(tr.get("sent_count") or 0)
    replies = int(tr.get("replies") or 0)
    views = int(tr.get("audit_views") or 0)
    engagement = replies + views
    complaint_rate = float(tr.get("complaint_rate_pct") or 0)
    criteria = manifest.get("pass_criteria") or {}
    min_eng = int(criteria.get("min_replies_or_audit_views") or PASS_MIN_ENGAGEMENT)
    max_complaint = float(criteria.get("max_complaint_rate_pct") or PASS_MAX_COMPLAINT_RATE_PCT)

    checks = {
        "sent_complete": sent >= len(manifest.get("contacts") or []),
        "engagement_ok": engagement >= min_eng,
        "complaint_rate_ok": complaint_rate < max_complaint,
    }
    row4_pass = (
        checks["sent_complete"]
        and checks["engagement_ok"]
        and checks["complaint_rate_ok"]
        and sent > 0
    )
    return {
        "row4_pass": row4_pass,
        "checks": checks,
        "engagement_total": engagement,
        "sent_count": sent,
        "target_sends": len(manifest.get("contacts") or []),
    }
