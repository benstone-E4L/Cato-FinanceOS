"""Tracking sheet CSV sync with manifest."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional

from .manifest import TRACKING_CSV_NAME, recompute_tracking_totals

TRACKING_FIELDS = [
    "contact_id",
    "domain",
    "receiver_email",
    "tier",
    "score",
    "send_status",
    "approved_at",
    "sent_at",
    "reply",
    "audit_view",
    "complaint",
    "bounce",
    "operator_notes",
]


def write_tracking_csv(manifest: dict[str, Any], path: Path) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TRACKING_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for c in manifest.get("contacts") or []:
            row = {k: c.get(k, "") for k in TRACKING_FIELDS}
            for flag in ("reply", "audit_view", "complaint", "bounce"):
                row[flag] = "yes" if c.get(flag) else "no"
            writer.writerow(row)
    return path


def _parse_bool(val: str) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "y")


def load_tracking_csv(path: Path) -> list[dict[str, str]]:
    path = Path(path).expanduser()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def merge_tracking_into_manifest(
    manifest: dict[str, Any],
    csv_path: Path,
) -> int:
    """Apply tracking-sheet rows onto manifest contacts. Returns rows updated."""
    rows = load_tracking_csv(csv_path)
    by_id = {str(c.get("contact_id", "")).lower(): c for c in manifest.get("contacts") or []}
    updated = 0
    for row in rows:
        cid = str(row.get("contact_id", "")).lower()
        if not cid or cid not in by_id:
            continue
        dest = by_id[cid]
        for field in (
            "send_status",
            "approved_at",
            "sent_at",
            "operator_notes",
        ):
            if row.get(field):
                dest[field] = row[field].strip()
        for flag in ("reply", "audit_view", "complaint", "bounce"):
            if row.get(flag) is not None and str(row.get(flag)).strip() != "":
                dest[flag] = _parse_bool(row[flag])
        updated += 1
    recompute_tracking_totals(manifest)
    return updated


def start_tracking_window(manifest: dict[str, Any], *, days: int = 7) -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(microsecond=0)
    tr = manifest.setdefault("tracking", {})
    tr["window_start"] = now.isoformat()
    tr["window_end"] = (now + timedelta(days=days)).isoformat()
    tr["window_days"] = days
    if manifest.get("status") == "selected":
        manifest["status"] = "in_progress"
