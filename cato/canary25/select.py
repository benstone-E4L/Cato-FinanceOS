"""Select a supervised 25-contact canary batch from a validated pool."""

from __future__ import annotations

import random
from typing import Optional

from .contacts import ContactRow

_TIER_RANK = {"tier_a": 0, "tier_b": 1, "tier_c": 2}


def _sort_key(row: ContactRow) -> tuple:
    tier_rank = _TIER_RANK.get(row.tier, 3)
    priority = 0
    if row.send_priority:
        try:
            priority = -int(row.send_priority)
        except ValueError:
            priority = 0
    return (tier_rank, priority, -row.score, row.domain)


def dedupe_by_domain(rows: list[ContactRow]) -> list[ContactRow]:
    """Keep the best-ranked row per domain."""
    best: dict[str, ContactRow] = {}
    for row in sorted(rows, key=_sort_key):
        dom = row.domain.lower()
        if dom not in best:
            best[dom] = row
    return list(best.values())


def select_batch(
    pool: list[ContactRow],
    *,
    count: int = 25,
    seed: Optional[int] = None,
    exclude_contact_ids: Optional[set[str]] = None,
) -> tuple[list[ContactRow], dict]:
    """
    Select up to ``count`` contacts for canary outreach.

    Preference: tier_a → tier_b → tier_c → unknown, higher score, explicit send_priority.
    One contact per domain. Optional seeded shuffle within equal-rank bands for fairness.
    """
    exclude = {c.lower() for c in (exclude_contact_ids or set())}
    eligible = [r for r in pool if r.contact_id not in exclude]
    unique = dedupe_by_domain(eligible)
    ranked = sorted(unique, key=_sort_key)

    if seed is not None:
        # Stable shuffle within tier bands so selection is reproducible but not always same domains
        bands: dict[int, list[ContactRow]] = {}
        for row in ranked:
            band = _TIER_RANK.get(row.tier, 3)
            bands.setdefault(band, []).append(row)
        rng = random.Random(seed)
        ranked = []
        for band in sorted(bands):
            chunk = bands[band][:]
            rng.shuffle(chunk)
            ranked.extend(chunk)

    selected = ranked[:count]
    meta = {
        "pool_unique_domains": len(unique),
        "requested_count": count,
        "selected_count": len(selected),
        "seed": seed,
        "excluded_ids": len(exclude),
    }
    return selected, meta
