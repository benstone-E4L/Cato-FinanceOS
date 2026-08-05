"""Import validated contact CSV and Clay exports into normalized records."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TIER_RE = re.compile(r"band=(tier_[abc])", re.I)
_SCORE_RE = re.compile(r"score=(\d+)", re.I)

_FORBIDDEN_DOMAINS = frozenset({
    "conduitscore.com",
    "www.conduitscore.com",
})

# Clay / sheet aliases → canonical field
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "domain": ("domain", "website", "company domain", "company_domain", "url", "site"),
    "receiver_email": (
        "receiver_email",
        "email",
        "work email",
        "work_email",
        "business email",
        "primary email",
        "email address",
    ),
    "first_name": ("first_name", "first name", "firstname", "given name"),
    "company_name": ("company_name", "company name", "company", "organization", "org"),
    "notes": ("notes", "note", "tags", "description"),
    "scrape_source": ("scrape_source", "source", "scrape source", "origin"),
    "send_priority": ("send_priority", "priority", "rank"),
}


@dataclass
class ContactRow:
    domain: str
    receiver_email: str
    first_name: str = ""
    company_name: str = ""
    notes: str = ""
    scrape_source: str = ""
    tier: str = ""
    score: int = 0
    send_priority: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def contact_id(self) -> str:
        return (self.domain or self.receiver_email.split("@")[-1]).strip().lower()

    def validation_errors(self) -> list[str]:
        errs: list[str] = []
        if not self.domain:
            errs.append("missing domain")
        if not self.receiver_email or not _EMAIL_RE.match(self.receiver_email):
            errs.append("invalid receiver_email")
        dom = self.domain.lower().strip()
        if dom in _FORBIDDEN_DOMAINS:
            errs.append(f"forbidden sending domain {dom}")
        return errs


def _normalize_header(name: str) -> str:
    return re.sub(r"[\s_]+", " ", (name or "").strip().lower())


def _map_headers(fieldnames: list[str]) -> dict[str, str]:
    """Map CSV headers to canonical keys."""
    norm = {_normalize_header(h): h for h in fieldnames if h}
    out: dict[str, str] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            key = _normalize_header(alias)
            if key in norm:
                out[canonical] = norm[key]
                break
    return out


def _parse_tier_and_score(notes: str) -> tuple[str, int]:
    tier = ""
    score = 0
    if notes:
        m = _TIER_RE.search(notes)
        if m:
            tier = m.group(1).lower()
        sm = _SCORE_RE.search(notes)
        if sm:
            score = int(sm.group(1))
    return tier, score


def _clean_domain(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = v.split("/")[0].split("?")[0]
    if v.startswith("www."):
        v = v[4:]
    return v


def _row_from_mapped(mapped: dict[str, str], header_map: dict[str, str]) -> ContactRow:
    def cell(canonical: str) -> str:
        src = header_map.get(canonical)
        if not src:
            return ""
        return (mapped.get(src) or "").strip()

    domain = _clean_domain(cell("domain"))
    email = cell("receiver_email").lower()
    if not domain and email and "@" in email:
        domain = email.split("@", 1)[1]

    notes = cell("notes")
    tier, score = _parse_tier_and_score(notes)
    return ContactRow(
        domain=domain,
        receiver_email=email,
        first_name=cell("first_name"),
        company_name=cell("company_name"),
        notes=notes,
        scrape_source=cell("scrape_source"),
        tier=tier,
        score=score,
        send_priority=cell("send_priority"),
        raw={k: (mapped.get(k) or "") for k in mapped},
    )


def detect_format(fieldnames: list[str]) -> str:
    """Return ``validated``, ``clay``, or ``generic``."""
    norm_headers = {_normalize_header(h) for h in fieldnames if h}
    mapped = set(_map_headers(fieldnames).keys())
    clay_markers = {"work email", "website", "company name", "linkedin url"}
    if clay_markers & norm_headers and "notes" not in norm_headers:
        return "clay"
    if "domain" in mapped and "receiver_email" in mapped:
        if "notes" in norm_headers or "scrape_source" in norm_headers:
            return "validated"
        if "domain" in {_normalize_header(h) for h in fieldnames}:
            return "validated"
    if "receiver_email" in mapped:
        return "clay"
    return "generic"


def load_contacts_csv(
    path: Path,
    *,
    format_hint: str = "auto",
    limit: Optional[int] = None,
) -> tuple[list[ContactRow], list[str], dict[str, Any]]:
    """
    Load contacts from CSV.

    Returns (rows, warnings, meta).
    """
    warnings: list[str] = []
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(str(path))

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        fmt = format_hint if format_hint != "auto" else detect_format(reader.fieldnames)
        header_map = _map_headers(reader.fieldnames)
        if "receiver_email" not in header_map:
            raise ValueError(
                "Could not find an email column. Expected one of: "
                + ", ".join(_COLUMN_ALIASES["receiver_email"])
            )
        if fmt == "clay" and "domain" not in header_map:
            warnings.append(
                "No domain/website column — domain will be inferred from email where possible"
            )

        rows: list[ContactRow] = []
        for i, raw_row in enumerate(reader, start=2):
            row = _row_from_mapped(raw_row, header_map)
            errs = row.validation_errors()
            if errs:
                warnings.append(f"line {i} skipped ({row.receiver_email or '?' }): {', '.join(errs)}")
                continue
            rows.append(row)
            if limit and len(rows) >= limit:
                break

    meta = {
        "source_file": str(path.resolve()),
        "format": fmt,
        "header_map": header_map,
        "pool_size": len(rows),
    }
    return rows, warnings, meta


def summarize_pool(rows: Iterable[ContactRow]) -> dict[str, int]:
    counts: dict[str, int] = {"total": 0, "tier_a": 0, "tier_b": 0, "tier_c": 0, "tier_unknown": 0}
    for r in rows:
        counts["total"] += 1
        if r.tier == "tier_a":
            counts["tier_a"] += 1
        elif r.tier == "tier_b":
            counts["tier_b"] += 1
        elif r.tier == "tier_c":
            counts["tier_c"] += 1
        else:
            counts["tier_unknown"] += 1
    return counts
