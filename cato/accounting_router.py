"""cato/accounting_router.py — Cato-side E4L accounting specialist router.

Task 3 of E4L_CATO_GENESIS_EXECUTION_PLAN.md: the operator/LLM never has to
name a Genesis specialist slug by guessing. Cato loads its own
version-pinned copy of the routing matrix
(``cato/accounting/CATO_GENESIS_ROUTING_MATRIX.yaml``, copied from
``Genesis Agents/accounting/CATO_GENESIS_ROUTING_MATRIX.yaml`` — the matrix
is small, changes rarely, and pinning a copy here means Cato does not
depend on the Genesis Agents repo being present on disk at runtime) and
reuses ``route_question()``'s matching logic, ported rather than
reimplemented from ``Genesis Agents/accounting/router.py`` per the
execution plan's explicit instruction not to reinvent the routing rules.

Differences from the Genesis-side router, both required by the plan's
acceptance criteria:

  * Ambiguous matches return NEED_CLARIFICATION instead of silently picking
    the first-scanned zero-score route. The Genesis-side router always picks
    *a* route (score starts at -1, so even an all-zero-score prompt matches
    route S1 by iteration order) because it is only ever exercised with the
    ten example prompts from CROSS_AGENT_HANDOFF_CONTRACT.yaml. Cato is
    exposed to arbitrary operator/LLM phrasing, so "no route scored above a
    floor" and "top two routes tied" must both surface as a real
    clarification request rather than a silent guess.
  * ``route_question()`` here always returns a ``RouteDecision`` OR raises
    ``NeedClarification`` — never a decision the caller has to sanity-check
    itself.
  * ``genesis-finance`` (and the other three money-domain stub slugs) can
    never appear in ``SPECIALIST_SLUGS`` here, so they can never be a
    routing target — enforced by an assertion at import time, not by trusting
    the YAML.

Fan-out: a route's ``then_fanout`` list is surfaced on ``RouteDecision`` so a
planner can dispatch the fanout agents in parallel once the primary agent(s)
finish (or in parallel with them, for routes where the fanout does not
depend on the primary's output) — this module does not itself schedule the
calls, that is ``cato.agent_loop``'s job; it only tells the planner which
slugs belong together for one question.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from cato.tools.genesis import FAIL_CLOSED_ACCOUNTING_ALLOWLIST, MONEY_DOMAIN_AGENTS

ACCOUNTING_DIR = Path(__file__).resolve().parent / "accounting"
MATRIX_PATH = ACCOUNTING_DIR / "CATO_GENESIS_ROUTING_MATRIX.yaml"

# Single source of truth for which slugs are legal routing targets: the same
# 14-slug set GenesisTool.execute() will actually let an allowlisted call
# through for. Anything else (money-domain stubs, the rejected one-hat slug,
# entity-name packs, unguarded personas) can never be selected.
SPECIALIST_SLUGS: frozenset[str] = FAIL_CLOSED_ACCOUNTING_ALLOWLIST
ONE_HAT_SLUG = "genesis-e4l-accounting"
ENTITY_KEYS: tuple[str, ...] = ("energy4life", "ibe", "xpo", "massey", "nesllc", "nespty")

FORBIDDEN_SLUGS: frozenset[str] = MONEY_DOMAIN_AGENTS | {"a2x", "a2x-specialist", ONE_HAT_SLUG, *ENTITY_KEYS}

assert SPECIALIST_SLUGS.isdisjoint(MONEY_DOMAIN_AGENTS), (
    "genesis-finance/billing/commerce/pricing must never be routing targets"
)
assert ONE_HAT_SLUG not in SPECIALIST_SLUGS, "genesis-e4l-accounting is REJECTED, one-hat architecture"

# A route must beat this floor to be selected outright. Below it, and on
# ties at or above it, the caller gets NEED_CLARIFICATION instead of a guess.
_MIN_CONFIDENT_SCORE = 30
_TIE_MARGIN = 5  # top two scores within this margin counts as ambiguous


class NeedClarification(Exception):
    """Raised by route_question() when no route is a confident, unambiguous
    match. Callers (the Cato planner / webchat) should surface
    ``candidates`` to the operator instead of guessing a specialist."""

    def __init__(self, prompt: str, candidates: list[tuple[str, int]]):
        self.prompt = prompt
        self.candidates = candidates  # [(route_id, score), ...] sorted desc
        top = ", ".join(f"{rid} ({score})" for rid, score in candidates[:3])
        super().__init__(
            f"NEED_CLARIFICATION: no confident, unambiguous route for {prompt!r}. "
            f"Closest candidates: {top or 'none'}"
        )


@dataclass(frozen=True)
class RouteDecision:
    agents: tuple[str, ...]
    then_fanout: tuple[str, ...]
    entities: tuple[str, ...]
    scenario_id: str | None = None
    escalate_to: str | None = None
    announce: str | None = None
    note: str | None = None
    write: str | None = None
    forbidden: tuple[str, ...] = ()
    answer_constraint: str | None = None
    ben_only_examples: tuple[str, ...] = ()
    do_not_invoke: tuple[str, ...] = ()
    matrix_route: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def parallel_dispatch(self) -> tuple[str, ...]:
        """All slugs a planner may fan out to in parallel for this question
        (primary agents + then_fanout). Order is not significance —
        dependencies, if any, are expressed via ``escalate_to`` (conflict
        resolution only), not via this list."""
        seen: list[str] = []
        for slug in (*self.agents, *self.then_fanout):
            if slug not in seen:
                seen.append(slug)
        return tuple(seen)


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


@lru_cache(maxsize=1)
def load_routing_matrix() -> dict[str, Any]:
    if not MATRIX_PATH.is_file():
        raise FileNotFoundError(f"routing matrix missing: {MATRIX_PATH}")
    with MATRIX_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("routing matrix is not a mapping")
    if data.get("dispatch_contract", {}).get("pattern") != "one_agent_one_job":
        raise ValueError("routing matrix must dispatch one_agent_one_job specialists")
    if ONE_HAT_SLUG in str(data.get("dispatch_contract") or {}):
        raise ValueError("rejected one-hat slug still in dispatch_contract")
    meta = data.get("_meta") or {}
    if not meta.get("last_verified"):
        raise ValueError("routing matrix _meta.last_verified is required (version pin)")
    return data


def _hint_score(prompt_n: str, route: dict[str, Any]) -> int:
    """Ported verbatim (not reinvented) from Genesis Agents'
    accounting/router.py::_hint_score — same scoring weights, so the same
    S1-S10 prompts land on the same routes as the Genesis-side test suite."""
    score = 0
    rid = str(route.get("id") or "")
    for ex in (_norm(x) for x in (route.get("examples") or [])):
        if prompt_n == ex:
            return 10_000
        if ex and ex in prompt_n:
            score += 400
        score += len(set(ex.split()) & set(prompt_n.split())) * 3
    hints: dict[str, tuple[str, ...]] = {
        "S1": ("stripe cash", "cash not match", "not match xero", "stripe"),
        "S2": ("close july", "all e4l entities", "close for all"),
        "S3": ("trusting the p&l", "trust the p&l", "preventing us from trusting"),
        "S4": ("contribution margin",),
        "S5": ("intercompany", "don't agree", "do not agree"),
        "S6": ("shopify/a2x/stripe", "reconcile shopify", "a2x", "shopify"),
        "S7": ("financeos complete", "complete itself today", "can financeos"),
        "S8": ("requires ben", "what specifically requires"),
        "S9": ("material accounting anomaly", "anomalies across all", "all xero organization"),
        "S10": ("journal entries", "do not post", "don't post them", "finish close"),
    }
    for hint in hints.get(rid, ()):
        if hint in prompt_n:
            score += 80 if len(hint) > 12 else 35
    if rid == "S10" and "journal" in prompt_n:
        score += 60
    if rid == "S2" and "journal" in prompt_n:
        score -= 40
    if rid == "S6" and ("shopify" in prompt_n or "a2x" in prompt_n):
        score += 50
    if rid == "S1" and "shopify" in prompt_n:
        score -= 30
    if rid == "S1" and "stripe" in prompt_n and "cash" in prompt_n:
        score += 40
    return score


def _entities_for(route: dict[str, Any], prompt_n: str) -> tuple[str, ...]:
    defaults = tuple(route.get("entities_default") or ())
    if defaults:
        return defaults
    found: list[str] = []
    mapping = {
        "nesllc": ("stripe", "shopify", "portal"),
        "massey": ("kraken", "interactive brokers", "interactive broker"),
        "xpo": ("hsbc", "uk vat", "vat"),
        "nespty": ("aud", "gst", "june year"),
        "ibe": ("donation", "ibe"),
        "energy4life": ("intangible", "gem ip"),
    }
    for entity, tokens in mapping.items():
        if any(tok in prompt_n for tok in tokens) and entity not in found:
            found.append(entity)
    return tuple(found) if found else defaults


def _assert_agents(agents: tuple[str, ...], label: str) -> None:
    if not agents:
        raise ValueError(f"{label} is empty")
    bad = [a for a in agents if a not in SPECIALIST_SLUGS]
    if bad:
        raise ValueError(f"{label} contains non-specialists: {bad}")
    banned = [a for a in agents if a in FORBIDDEN_SLUGS]
    if banned:
        raise ValueError(f"{label} contains forbidden slugs: {banned}")


def route_question(prompt: str) -> RouteDecision:
    """Select real specialist slugs for a user question. Never asks the
    user to name them, and never guesses on an ambiguous prompt — raises
    ``NeedClarification`` instead (see module docstring).
    """
    matrix = load_routing_matrix()
    prompt_n = _norm(prompt)
    routes: list[dict[str, Any]] = list(matrix.get("intent_routes") or [])
    if not routes:
        raise ValueError("routing matrix has no intent_routes")

    scored: list[tuple[dict[str, Any], int]] = [
        (route, _hint_score(prompt_n, route)) for route in routes
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    best, best_score = scored[0]

    if best_score < _MIN_CONFIDENT_SCORE:
        raise NeedClarification(prompt, [(str(r.get("id")), s) for r, s in scored])
    if len(scored) > 1:
        _, second_score = scored[1]
        if best_score < 10_000 and (best_score - second_score) <= _TIE_MARGIN:
            raise NeedClarification(prompt, [(str(r.get("id")), s) for r, s in scored])

    agents = tuple(best.get("agents") or ())
    fanout = tuple(best.get("then_fanout") or ())
    _assert_agents(agents, f"route {best.get('id')} agents")
    if fanout:
        _assert_agents(fanout, f"route {best.get('id')} then_fanout")
    escalate = best.get("escalate_to")
    if escalate:
        _assert_agents((escalate,), "escalate_to")

    entities = _entities_for(best, prompt_n)
    if not entities and set(agents) & {
        "genesis-e4l-close", "genesis-e4l-intercompany", "genesis-e4l-fs-integrity",
    }:
        entities = ENTITY_KEYS

    return RouteDecision(
        agents=agents,
        then_fanout=fanout,
        entities=entities,
        scenario_id=str(best.get("id") or "") or None,
        escalate_to=escalate,
        announce=best.get("announce"),
        note=best.get("note"),
        write=best.get("write"),
        forbidden=tuple(best.get("forbidden") or ()),
        answer_constraint=best.get("answer_constraint"),
        ben_only_examples=tuple(best.get("ben_only_examples") or ()),
        do_not_invoke=tuple(best.get("do_not_invoke") or ()),
        matrix_route=dict(best),
    )


__all__ = [
    "ACCOUNTING_DIR",
    "MATRIX_PATH",
    "SPECIALIST_SLUGS",
    "ONE_HAT_SLUG",
    "ENTITY_KEYS",
    "FORBIDDEN_SLUGS",
    "NeedClarification",
    "RouteDecision",
    "load_routing_matrix",
    "route_question",
]
