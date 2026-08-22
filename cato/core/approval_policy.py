"""
cato/core/approval_policy.py — Declarative, fail-closed approval policy engine.

Replaces the hardcoded `if tool_name in (...)` routing that used to live in
`outbound_approval.requires_approval`.

Design rules (all of these are security properties, not style preferences):

1.  FAIL CLOSED. A tool that is not in the policy REQUIRES approval. Deleting a
    row from the policy therefore makes that tool *more* restricted, never less.
    A missing/corrupt policy file falls back to the built-in policy; a policy
    that fails to parse never widens the gate.

2.  THE MODEL DOES NOT VOTE. Nothing inside ``args`` can remove an approval
    requirement. ``dry_run`` / ``draft_only`` / ``_approval_granted`` and
    friends are model-supplied strings and are treated as *evidence of intent*,
    never as authority. A genuine simulation bypass requires an
    :class:`ApprovalContext` constructed by the calling Python code — an object
    the model has no way to forge through a JSON tool call.

3.  IDENTITY BEFORE POLICY. ``send_email``, ``send-email``, ``sendEmail`` and
    ``email.send`` are the same capability and must land on the same policy row.
    Names are normalised and then run through an explicit alias table.

4.  NO SUBSTRING MATCHING. The old code decided whether ``genesis`` was
    dangerous by looking for the substring "send" in a model-written task
    string; "dispatch" walked straight through. Capability classification is
    now explicit: dispatcher tools are tiered ``dispatch`` and always gate.

5.  APPROVE A PAYLOAD, NOT AN INTENT. Tickets bind to a sha256 over the
    canonical JSON of (canonical tool, redacted args). Change the arguments
    after approval and the ticket no longer verifies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ticket timing. Mirrors the ProofRail approval binding Cato integrates with:
# 24h TTL, 60s tolerance for clock skew between the issuing daemon and the
# consuming process. Skew is applied symmetrically: a ticket stamped slightly
# in the future is accepted within the tolerance and rejected beyond it, so a
# rolled-back clock cannot mint an effectively immortal ticket.
# ---------------------------------------------------------------------------
DEFAULT_TTL_SECONDS = 86_400
DEFAULT_CLOCK_SKEW_SECONDS = 60

TICKET_PREFIX = "cato-appr-v1"

# ---------------------------------------------------------------------------
# Redaction (recursive — the audit_log._sanitize_inputs version is top-level
# only and misses {"headers": {"authorization": "..."}}).
# ---------------------------------------------------------------------------

REDACTED = "[redacted]"

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "api-key",
    "_key",
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "id_token",
    "bearer",
    "token",
    "secret",
    "password",
    "passwd",
    "passphrase",
    "credential",
    "private_key",
    "client_secret",
    "session_key",
    "cookie",
    "vault",
    "signature",
    "otp",
)

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(['\"\s:=]+)([^,'\"\s}]+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_\-]{30,}\b"),  # telegram bot token
]

_MAX_REDACT_DEPTH = 24


def is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def redact_text(text: str) -> str:
    """Mask credential-shaped values inside a free-text string."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            redacted = pattern.sub(r"\1\2" + REDACTED, redacted)
        else:
            redacted = pattern.sub(REDACTED, redacted)
    return redacted


def redact(value: Any, key: str = "", _depth: int = 0) -> Any:
    """Recursively redact a payload before it is persisted or displayed.

    Redacts on the *key* (so ``{"headers": {"authorization": "..."}}`` is
    caught at any nesting depth) and on the *value* shape (so a bare
    ``sk-...`` under an innocent key is caught too).
    """
    if _depth > _MAX_REDACT_DEPTH:
        return REDACTED

    if key and is_sensitive_key(key):
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return REDACTED if value else value

    if isinstance(value, dict):
        return {
            str(k): redact(v, str(k), _depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item, "", _depth + 1) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return redact_text(str(value))


# ---------------------------------------------------------------------------
# Canonical tool identity
# ---------------------------------------------------------------------------

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_IDENT = re.compile(r"[^a-z0-9]+")


def normalize_tool_name(name: Any) -> str:
    """Fold spelling variants onto one shape.

    ``sendEmail`` / ``send-email`` / ``Send Email`` / ``send.email`` all
    normalise to ``send_email``. This runs *before* the alias table, so the
    alias table only has to carry genuinely different names
    (``email.send`` -> ``send_email``), not every punctuation variant.
    """
    raw = str(name or "").strip()
    if not raw:
        return ""
    spaced = _CAMEL_BOUNDARY.sub("_", raw)
    lowered = spaced.lower()
    return _NON_IDENT.sub("_", lowered).strip("_")


# ---------------------------------------------------------------------------
# Args handling
#
# _CONTROL_KEYS have no legitimate execution meaning — they exist only to try
# to talk the gate out of firing. They are stripped from the canonical payload
# and their presence is reported as a bypass attempt.
#
# _SIMULATION_ARG_KEYS DO have legitimate execution meaning (send_email really
# does behave differently with draft_only=True), so they are preserved in the
# payload and in the digest. They are simply never consulted when deciding
# whether approval is required.
# ---------------------------------------------------------------------------

_CONTROL_KEYS = frozenset({
    "_approval_granted",
    "approval_granted",
    "_approved",
    "_approval",
    "skip_approval",
    "no_approval",
    "auto_approve",
    "bypass_approval",
    "_bypass",
    "_trusted",
})

_SIMULATION_ARG_KEYS = frozenset({
    "dry_run",
    "dryrun",
    "draft_only",
    "draftonly",
    "simulate",
    "simulation",
    "preview_only",
    "test_mode",
})


def detect_bypass_attempt(args: Any) -> list[str]:
    """Return the model-supplied keys that were trying to skip the gate."""
    if not isinstance(args, dict):
        return []
    found = []
    for k, v in args.items():
        lowered = normalize_tool_name(k)
        if k in _CONTROL_KEYS or lowered in _CONTROL_KEYS:
            found.append(str(k))
        elif (lowered in _SIMULATION_ARG_KEYS or k in _SIMULATION_ARG_KEYS) and v:
            found.append(str(k))
    return sorted(found)


def strip_control_keys(args: Any) -> dict[str, Any]:
    """Drop bypass-only control keys. Execution-meaningful keys are kept."""
    if not isinstance(args, dict):
        return {}
    return {
        str(k): v
        for k, v in args.items()
        if str(k) not in _CONTROL_KEYS and normalize_tool_name(k) not in _CONTROL_KEYS
    }


def canonical_json(obj: Any) -> str:
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def canonical_args(args: Any) -> dict[str, Any]:
    """The exact payload an approval binds to: control keys removed, redacted."""
    return redact(strip_control_keys(args))


def compute_args_digest(tool_name: Any, args: Any) -> str:
    """sha256 over canonical JSON of (canonical tool identity, canonical args).

    The tool is inside the digest, so an approval for ``send_email`` cannot be
    replayed against ``shell.exec`` even with identical arguments.
    """
    payload = {
        "tool": resolve_tool(tool_name, args=args).canonical,
        "args": canonical_args(args),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def build_preview(tool_name: Any, args: Any, limit: int = 500) -> str:
    """Operator-facing preview string. ALWAYS redacted, never raw.

    This is the function the dispatch path must call instead of
    ``json.dumps(args)[:500]``.
    """
    safe = canonical_args(args)
    body = json.dumps(safe, default=str, ensure_ascii=False)
    text = f"{resolve_tool(tool_name, args=args).canonical}: {body}"
    return redact_text(text)[:limit]


# ---------------------------------------------------------------------------
# Policy model
# ---------------------------------------------------------------------------

REQUIRE = "require"
ALLOW = "allow"

_ALWAYS = "always"
_NEVER = "never"


@dataclass(frozen=True)
class ApprovalContext:
    """Caller-side authorization context.

    The model cannot construct this — it is a Python object supplied by the
    dispatch code, not a value inside a JSON tool call. This is the ONLY way a
    simulation/dry-run may downgrade an approval requirement, and it only
    applies to tools the policy explicitly marks ``simulation_exempt``.

    ``execution_authorized`` is the live-write counterpart: it asserts that a
    human-approved ticket was redeemed for this exact call. Tools must treat it
    as the only acceptable substitute for :func:`take_execution_grant`.
    """

    actor: str = "model"
    simulation_authorized: bool = False
    execution_authorized: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Execution grants
#
# The recurring vulnerability in this codebase is a model-supplied boolean
# (`approved`, `dry_run`, `_approval_granted`) being accepted as human
# authorization. The fix is to make authorization something that CANNOT be
# expressed as a JSON tool argument at all.
#
# A grant is a short-lived entry in this process's memory, minted only by
# OutboundApprovalStore.consume() at the moment a human-approved ticket is
# redeemed, and keyed by (canonical tool, argument digest) so it authorizes
# exactly one payload. Taking a grant removes it, so it authorizes exactly one
# execution.
# ---------------------------------------------------------------------------

_GRANT_TTL_SECONDS = 300.0


class ExecutionGrants:
    """Single-use, payload-bound, in-process authorizations to execute."""

    def __init__(self, ttl: float = _GRANT_TTL_SECONDS) -> None:
        self._ttl = ttl
        self._lock = threading.Lock()
        self._grants: dict[tuple[str, str], float] = {}

    def _prune(self, now: float) -> None:
        expired = [k for k, minted in self._grants.items() if now - minted > self._ttl]
        for key in expired:
            self._grants.pop(key, None)

    def grant(self, tool: str, args_digest: str, now: Optional[float] = None) -> None:
        stamp = time.time() if now is None else now
        with self._lock:
            self._prune(stamp)
            self._grants[(str(tool), str(args_digest))] = stamp

    def take(self, tool: str, args_digest: str, now: Optional[float] = None) -> bool:
        """Consume a grant. Returns False if there is none — the fail-closed answer."""
        stamp = time.time() if now is None else now
        with self._lock:
            self._prune(stamp)
            return self._grants.pop((str(tool), str(args_digest)), None) is not None

    def clear(self) -> None:
        with self._lock:
            self._grants.clear()

    def pending(self) -> int:
        with self._lock:
            return len(self._grants)


_execution_grants = ExecutionGrants()


def grant_execution(tool: str, args_digest: str) -> None:
    """Mint a single-use execution grant. Only ticket redemption may call this."""
    _execution_grants.grant(tool, args_digest)


def take_execution_grant(tool_name: Any, args: Any) -> bool:
    """True exactly once per approved (tool, args) pair; False otherwise.

    A tool that is about to cause an irreversible external effect calls this
    and refuses to proceed when it returns False.
    """
    return _execution_grants.take(
        resolve_tool(tool_name, args=args).canonical,
        compute_args_digest(tool_name, args),
    )


def clear_execution_grants() -> None:
    _execution_grants.clear()


@dataclass(frozen=True)
class PolicyDecision:
    tool: str                 # as supplied
    canonical: str            # canonical capability id
    tier: str
    decision: str             # REQUIRE | ALLOW
    reason: str
    bypass_attempted: tuple[str, ...] = ()

    @property
    def requires_approval(self) -> bool:
        return self.decision == REQUIRE


@dataclass(frozen=True)
class ToolRule:
    canonical: str
    tier: str
    simulation_exempt: bool = False
    known: bool = True
    dispatcher: bool = False


# Tools that carry their real capability in an argument rather than in their
# name. `file` and `browser` are one registered tool each but cover everything
# from a read to a delete, so tiering them by name alone would either gate every
# file read or wave through every file write. The action keys and their
# precedence match cato/safety.py::_dispatcher_key exactly, so both gates
# resolve the same call to the same sub-identity.
_DISPATCH_ACTION_KEYS = ("action", "op", "operation")


def _dispatch_action(args: Any) -> Optional[str]:
    if not isinstance(args, dict):
        return None
    for key in _DISPATCH_ACTION_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


# `root: "absolute"` tells cato/tools/file.py:_run to skip workspace scoping
# entirely and resolve any path on the machine (file.py: "Absolute-path mode:
# bypass workspace scoping"). The sub-action alone therefore under-describes
# the call: `file` + `action=read` is genuinely read_only inside the sandbox,
# but with root=absolute it is an arbitrary read of the vault, the ledger, the
# .env or an SSH key — the exact escalation an indirect prompt injection needs.
# Kept in sync with cato/safety.py::_requests_unsandboxed_root.
_UNSANDBOXED_ROOTS = frozenset({"absolute"})

#: Tiers that do NOT require approval and so must be escalated when the call
#: leaves the sandbox. Escalation only ever raises the tier, never lowers it.
_UNGATED_TIERS = frozenset({"read_only", "reversible"})

#: The tier an otherwise-ungated dispatcher call is escalated to when it opts
#: out of the sandbox. `elevated` is gated (_BUILTIN_TIERS), so the operator
#: approves an out-of-sandbox path once, rather than it happening invisibly.
_UNSANDBOXED_TIER = "elevated"


def requests_unsandboxed_root(args: Any) -> bool:
    """True when the call opts out of workspace scoping via ``root``."""
    if not isinstance(args, dict):
        return False
    root = args.get("root")
    return isinstance(root, str) and root.strip().lower() in _UNSANDBOXED_ROOTS


# ---------------------------------------------------------------------------
# `genesis` sub-capability tiering
#
# WHY THIS IS NOT THE OLD SUBSTRING BUG (see design rule 4 in the header).
#
# The old gate asked "does the model's task string contain 'send'?" — a
# question about model-written prose, which "dispatch" walked straight past.
# This resolver never reads `task`. It asks two questions, both answered
# entirely by Cato-side code:
#
#   Q1 (load-bearing, unforgeable): is the agent this call is addressed to
#       STRUCTURALLY INCAPABLE of writing?  `agent` is model-written, but it
#       only ever SELECTS an element of a closed set Cato defines
#       (cato.tools.genesis.FAIL_CLOSED_ACCOUNTING_ALLOWLIST) whose
#       write-capability is declared Cato-side
#       (cato.xero_scope.specialist_writes_forbidden, backed by
#       XERO_SCOPE_TO_AGENT_MAP.yaml `specialist_overrides`). The model can
#       pick which specialist; it cannot give a write-forbidden specialist
#       Xero write scopes. Today exactly one slug qualifies:
#       genesis-e4l-fs-integrity ("writes_forbidden: true", constitution test
#       `fs_integrity_write`). Blast radius is bounded by the credential the
#       remote holds, not by what the model asked it to do.
#
#   Q2 (granularity only, never widening): is the DECLARED operation a member
#       of the closed operation enum cato.xero_scope.OPERATION_SCOPE_FAMILY,
#       and does Cato's own scope map classify that (agent, operation) pair as
#       a read?  This is a model-supplied token, so it is deliberately
#       consulted ONLY AFTER Q1 already proved the call cannot write. It can
#       therefore make an ungated call gated (declare a write op and you gate)
#       and can never make a gated call ungated. Declaring
#       `operation=get_trial_balance` on genesis-e4l-ap — an agent that DOES
#       hold write scopes — fails Q1 and gates, which is precisely the forgery
#       this ordering exists to defeat.
#
# Everything else fails closed to the `genesis` row's own tier (`dispatch`,
# always gated): unknown slug, denylisted slug, non-allowlisted slug,
# unreadable/absent/contradictory operation, unknown operation, malformed
# args, or any import/lookup failure resolving the capability facts.
#
# IMMUTABILITY: IMMUTABLE_DENIED_AGENTS (the money-domain slugs plus
# genesis-deploy) is checked before anything else here AND is disjoint from
# the allowlist, so a denied slug is unreachable on the ungated path twice
# over. See tests/test_genesis_subaction_tiering.py.
#
# This resolver keys on the canonical id, NOT on the rule's `dispatcher`
# flag, so `docs/approval-policy.yaml` cannot turn `genesis` into a generic
# `args["action"]` dispatcher and thereby skip Q1.
# ---------------------------------------------------------------------------

GENESIS_CANONICAL = "genesis"

#: Canonical id reported for a genesis dispatch that resolved to the ungated
#: read path. Distinct from `genesis` so audit rows, tickets and execution
#: grants never confuse the two capabilities.
GENESIS_READ_ONLY_CANONICAL = "genesis_read_only_specialist"
_GENESIS_READ_ONLY_TIER = "read_only"

#: Keys the declared Xero operation may be carried under. Top level and inside
#: `params` are both accepted (GENESIS_TOOL_SCHEMA declares `params` as an open
#: object, so `params.operation` is schema-legal today). Order does not matter:
#: two DIFFERENT values anywhere is treated as unreadable and gates.
_GENESIS_OPERATION_KEYS = ("operation", "action", "op")

#: `operation_allowed()` reasons that mean "this agent cannot write at all and
#: this is one of its reads". Any other reason — including a permissive
#: `primary_write` — gates.
_GENESIS_READ_REASONS = frozenset({"read_only_specialist"})

_genesis_facts_cache: Optional[dict[str, Any]] = None
_genesis_facts_failed = False


def _genesis_facts() -> Optional[dict[str, Any]]:
    """Cato-side capability facts for genesis, or None (=> gate everything).

    Imported lazily: `cato.tools.genesis` pulls in aiohttp and the vault, and
    the policy engine must stay importable without them. Any failure here is
    an unresolvable capability, which fails closed.
    """
    global _genesis_facts_cache, _genesis_facts_failed
    if _genesis_facts_cache is not None or _genesis_facts_failed:
        return _genesis_facts_cache
    try:
        from cato.tools.genesis import (
            FAIL_CLOSED_ACCOUNTING_ALLOWLIST,
            IMMUTABLE_DENIED_AGENTS,
            _canonicalize_agent_slug,
        )
        from cato.xero_scope import (
            OPERATION_SCOPE_FAMILY,
            operation_allowed,
            specialist_writes_forbidden,
        )
    except Exception as exc:  # pragma: no cover — defensive, fails closed
        _genesis_facts_failed = True
        logger.error(
            "genesis capability facts unavailable (%s); every genesis dispatch "
            "will require approval", exc,
        )
        return None
    _genesis_facts_cache = {
        "canonicalize": _canonicalize_agent_slug,
        "denied": frozenset(IMMUTABLE_DENIED_AGENTS),
        "allowlist": frozenset(FAIL_CLOSED_ACCOUNTING_ALLOWLIST),
        "operations": frozenset(OPERATION_SCOPE_FAMILY),
        "writes_forbidden": specialist_writes_forbidden,
        "operation_allowed": operation_allowed,
    }
    return _genesis_facts_cache


def _reset_genesis_facts_cache() -> None:
    """Test hook. Drops the memoised capability facts."""
    global _genesis_facts_cache, _genesis_facts_failed
    _genesis_facts_cache = None
    _genesis_facts_failed = False


def _genesis_declared_operation(args: Any) -> Optional[str]:
    """The single declared Xero operation, or None when it is unreadable.

    None is returned for: non-dict args, no operation key anywhere, a
    non-string/blank value, or two different values across the accepted keys.
    Every one of those gates.
    """
    if not isinstance(args, dict):
        return None
    containers: list[dict[str, Any]] = [args]
    params = args.get("params")
    if isinstance(params, dict):
        containers.append(params)
    found: set[str] = set()
    for container in containers:
        for key in _GENESIS_OPERATION_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                found.add(value.strip().lower())
    if len(found) != 1:
        return None
    return found.pop()


def declared_genesis_operation(args: Any) -> Optional[str]:
    """Public reader for the declared Xero operation on a genesis dispatch.

    Exists so `cato.tools.genesis` narrows the outbound scope grant using the
    EXACT same parse the gate used. Two readers would eventually disagree, and
    a disagreement here means the operator approved one call while a different
    one went on the wire.
    """
    return _genesis_declared_operation(args)


def _resolve_genesis_rule(rule: ToolRule, args: Any) -> ToolRule:
    """Resolve a `genesis` dispatch to its sub-capability row.

    Returns *rule* unchanged (tier `dispatch`, always gated) unless every
    fail-closed condition for the read path is met. See the block comment
    above for why the ordering of the checks is the security property.
    """
    if not isinstance(args, dict):
        return rule

    facts = _genesis_facts()
    if facts is None:
        return rule

    raw_agent = args.get("agent")
    if not isinstance(raw_agent, str) or not raw_agent.strip():
        return rule

    try:
        slug = facts["canonicalize"](raw_agent)
    except Exception:  # pragma: no cover — defensive
        return rule
    if not slug:
        return rule

    # Immutable denylist first, and independently of everything below, so the
    # ungated path can never become a route around it.
    if slug in facts["denied"]:
        return rule

    # Only the fail-closed E4L specialist set is eligible at all. An unknown or
    # unlisted slug gates.
    if slug not in facts["allowlist"]:
        return rule

    # Q1 — LOAD-BEARING. The specialist must be declared write-forbidden.
    try:
        if not facts["writes_forbidden"](slug):
            return rule
    except Exception:  # pragma: no cover — defensive
        return rule

    # Q2 — granularity only. Reached only when Q1 already proved no write is
    # possible, so this can narrow but never widen.
    operation = _genesis_declared_operation(args)
    if operation is None or operation not in facts["operations"]:
        return rule
    try:
        allowed, reason = facts["operation_allowed"](slug, operation)
    except Exception:  # pragma: no cover — defensive
        return rule
    if not allowed or reason not in _GENESIS_READ_REASONS:
        return rule

    return ToolRule(
        canonical=GENESIS_READ_ONLY_CANONICAL,
        tier=_GENESIS_READ_ONLY_TIER,
        simulation_exempt=False,
        known=True,
        dispatcher=False,
    )


@dataclass
class ApprovalPolicy:
    version: str = "1.0"
    default_decision: str = REQUIRE
    tiers: dict[str, str] = field(default_factory=dict)
    tools: dict[str, ToolRule] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS
    source: str = "builtin"


# ---------------------------------------------------------------------------
# Built-in policy — the always-available default.
#
# `docs/approval-policy.yaml` overrides/extends this. If that file is missing
# or unparseable, THIS is what runs, and it fails closed on anything unlisted.
# ---------------------------------------------------------------------------

_BUILTIN_TIERS: dict[str, str] = {
    "read_only": _NEVER,
    "reversible": _NEVER,
    "elevated": _ALWAYS,
    "outbound": _ALWAYS,
    "dispatch": _ALWAYS,
    "financial": _ALWAYS,
    "critical": _ALWAYS,
}

# canonical id -> (tier, simulation_exempt, [extra aliases], dispatcher)
#
# Tiers here mirror cato/safety.py::_TOOL_TIER through the inverse of
# safety.py::_POLICY_TIER_TO_RISK:
#     READ -> read_only, REVERSIBLE_WRITE -> reversible,
#     IRREVERSIBLE -> elevated, HIGH_STAKES -> outbound/dispatch/financial/critical
_BUILTIN_TOOLS: dict[str, tuple[str, bool, list[str], bool]] = {
    # --- read-only / reversible: no approval -------------------------------
    "memory_search":    ("read_only", False, ["memory.search", "memorySearch"], False),
    "memory_federated": ("read_only", False, ["memory.federated"], False),
    "web_search":       ("read_only", False, ["web.search", "webSearch"], False),
    "web_code":         ("read_only", False, ["web.code", "webCode"], False),
    "web_news":         ("read_only", False, ["web.news", "webNews"], False),
    "graph_query":      ("read_only", False, ["graph.query"], False),
    "graph_related":    ("read_only", False, ["graph.related"], False),
    "academic_arxiv":   ("read_only", False, ["academic.arxiv"], False),
    "github_issue_list": ("read_only", False, ["github.issue_list"], False),
    "github_pr_list":   ("read_only", False, ["github.pr_list"], False),
    "integration_status": ("read_only", False, ["integration.status"], False),
    # DELIBERATE DIVERGENCE from safety.py, which tiers integration.action
    # REVERSIBLE_WRITE. Do not "correct" this back to match.
    #
    # safety.py classifies the reversibility of a LOCAL effect. This policy has
    # to classify EXTERNAL BLAST RADIUS. integration.action reaches Stripe
    # create_payment_link / create_checkout_session, GitHub create_repo, Vercel
    # create_deployment and every other registered third-party write. An action
    # that creates a live payment link is not "reversible" in any sense that
    # matters, and REVERSIBLE_WRITE clears without an approval ticket at
    # default settings.
    "integration_action": ("financial", False, ["integration.action"], False),
    "conduit_crawl":    ("read_only", False, ["conduit.crawl"], False),
    "conduit_monitor":  ("reversible", False, ["conduit.monitor"], False),

    # --- dispatcher tools: real tier lives in args["action"] ---------------
    # The dispatcher row itself is `critical`, which is what applies when no
    # readable action is supplied — the same fail-closed answer safety.py gives.
    "browser": ("critical", False, [], True),
    "file":    ("critical", False, [], True),

    # browser sub-actions (safety.py: browser.*)
    "browser_navigate":       ("read_only", False, ["browser.navigate"], False),
    "browser_navigate_back":  ("read_only", False, ["browser.navigate_back"], False),
    "browser_extract":        ("read_only", False, ["browser.extract"], False),
    "browser_extract_main":   ("read_only", False, ["browser.extract_main"], False),
    "browser_screenshot":     ("read_only", False, ["browser.screenshot"], False),
    "browser_search":         ("read_only", False, ["browser.search"], False),
    "browser_snapshot":       ("read_only", False, ["browser.snapshot"], False),
    "browser_accessibility_snapshot": ("read_only", False, ["browser.accessibility_snapshot"], False),
    "browser_network_requests": ("read_only", False, ["browser.network_requests"], False),
    "browser_console_messages": ("read_only", False, ["browser.console_messages"], False),
    "browser_wait":           ("read_only", False, ["browser.wait"], False),
    "browser_wait_for":       ("read_only", False, ["browser.wait_for"], False),
    "browser_scroll":         ("read_only", False, ["browser.scroll"], False),
    "browser_hover":          ("read_only", False, ["browser.hover"], False),
    "browser_click":          ("reversible", False, ["browser.click"], False),
    "browser_type":           ("reversible", False, ["browser.type"], False),
    "browser_fill":           ("reversible", False, ["browser.fill"], False),
    "browser_key_press":      ("reversible", False, ["browser.key_press"], False),
    "browser_select_option":  ("reversible", False, ["browser.select_option"], False),
    "browser_handle_dialog":  ("reversible", False, ["browser.handle_dialog"], False),
    "browser_pdf":            ("reversible", False, ["browser.pdf"], False),
    "browser_output_to_file": ("reversible", False, ["browser.output_to_file"], False),
    # browser.eval runs attacker-reachable JavaScript in the page context.
    "browser_eval":           ("elevated", False, ["browser.eval"], False),

    # file sub-actions (safety.py: file.*)
    "file_read":   ("read_only", False, ["file.read"], False),
    "file_list":   ("read_only", False, ["file.list"], False),
    "file_exists": ("read_only", False, ["file.exists"], False),
    "file_roots":  ("read_only", False, ["file.roots"], False),
    "file_append": ("elevated", False, ["file.append"], False),
    "file_patch":  ("elevated", False, ["file.patch"], False),

    # --- outbound: always gated -------------------------------------------
    "send_email": ("outbound", False, [
        "send_email", "send-email", "sendEmail", "SendEmail",
        "email.send", "email_send", "emailSend",
        "send_mail", "sendmail", "mail.send", "mail_send",
        "send_email_tool", "tools.send_email",
    ], False),
    "outreach_run": ("outbound", True, [
        "outreach.run", "outreachRun", "outreach-run",
        "outreach_bridge", "outreach.bridge", "outreachBridge",
        "execute_outreach_run", "outreach.execute",
    ], False),
    "site_services_send_outreach": ("outbound", False, [
        "site_services.send_outreach", "siteServices.sendOutreach",
    ], False),
    "site_services_match_apply": ("outbound", False, [
        "site_services.match_apply", "siteServices.matchApply",
    ], False),
    "telegram_send": ("outbound", False, ["telegram.send", "telegramSend"], False),

    # --- dispatch: a tool that runs other tools/agents. Always gated.
    # The old code tried to decide this by substring-matching a model-written
    # task description; "dispatch" instead of "send" defeated it. A dispatcher
    # is dangerous because of what it can reach, not because of how the model
    # described it.
    "genesis": ("dispatch", False, [
        "genesis", "genesis-email", "genesis_email", "genesisEmail",
        "genesis.run", "genesis_bridge",
    ], False),
    "clawflows_run": ("dispatch", False, ["clawflows.run", "flow.run", "flowRun"], False),

    # --- elevated / critical ----------------------------------------------
    "shell_exec":     ("critical", False, ["shell.exec", "shell", "shellExec", "bash", "exec"], False),
    "python_execute": ("critical", False, ["python.execute", "pythonExecute", "python"], False),
    "file_write":     ("elevated", False, ["file.write", "write_file", "fileWrite"], False),
    "file_delete":    ("elevated", False, ["file.delete", "delete_file", "fileDelete"], False),
    "github_pr_review":   ("elevated", False, ["github.pr_review"], False),
    "github_issue_create": ("elevated", False, ["github.issue_create"], False),
    "api_payment":    ("financial", False, ["api.payment", "payment", "stripe.charge"], False),
    "vault_set":      ("critical", False, ["vault.set", "vaultSet"], False),

    # --- scheduler / cron skills -------------------------------------------
    # cato/core/scheduled_dispatch.py routes every scheduled skill through
    # AgentLoop.guarded_action, so each one needs a policy identity here or it
    # resolves "unknown" and gates unconditionally. These tiers are the honest
    # blast radius of each skill, NOT a convenience downgrade:
    #
    #   * digests/pulses read state and notify the OPERATOR'S OWN channel via
    #     gateway.send. No third-party write, and re-sending is harmless ->
    #     reversible.
    #   * the fallback ingest path only queues a prompt for the agent loop,
    #     which then runs THIS gate chain again per tool call -> reversible.
    #
    # A skill name that is NOT listed here has no policy identity, resolves
    # "unknown", and is gated unconditionally by `default_decision = REQUIRE`.
    # That is the intended outcome for a retired skill: the removal of a row
    # must make a name MORE restricted, never less. `arbitrage.cycle`,
    # `arbitrage.cycle.write`, `arbitrage.preflight` and `arbitrage.pulse` were
    # removed here in t22 along with the subsystem they named, and
    # tests/test_retired_skill_names_fail_closed.py pins that they now refuse.
    "schedule_digest": ("reversible", False, [
        "night_shift.digest", "night-shift-digest",
        "site_services.digest", "site-services-digest",
    ], False),
    "schedule_pulse": ("reversible", False, [
        "site_services.pulse", "site-services-inbox",
    ], False),
    "schedule_ingest": ("reversible", False, ["schedule.ingest"], False),
}


def _builtin_policy() -> ApprovalPolicy:
    tools: dict[str, ToolRule] = {}
    aliases: dict[str, str] = {}
    for canonical, (tier, sim_exempt, alias_list, dispatcher) in _BUILTIN_TOOLS.items():
        tools[canonical] = ToolRule(
            canonical=canonical, tier=tier, simulation_exempt=sim_exempt,
            dispatcher=dispatcher,
        )
        aliases[canonical] = canonical
        for alias in alias_list:
            aliases[normalize_tool_name(alias)] = canonical
    return ApprovalPolicy(
        version="1.0",
        default_decision=REQUIRE,
        tiers=dict(_BUILTIN_TIERS),
        tools=tools,
        aliases=aliases,
        source="builtin",
    )


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------

_REPO_POLICY = Path(__file__).resolve().parents[2] / "docs" / "approval-policy.yaml"

_cached: Optional[ApprovalPolicy] = None


def policy_path() -> Path:
    override = os.environ.get("CATO_APPROVAL_POLICY")
    if override:
        return Path(override)
    return _REPO_POLICY


def _merge_yaml(policy: ApprovalPolicy, data: dict[str, Any], source: str) -> ApprovalPolicy:
    policy.source = source
    policy.version = str(data.get("version") or policy.version)

    # default_decision may only ever be `require`. A policy file that tries to
    # set the default to `allow` would turn every unlisted tool into a silent
    # bypass, which is exactly the fail-open bug being removed.
    declared_default = str(data.get("default_decision") or REQUIRE).strip().lower()
    if declared_default != REQUIRE:
        logger.error(
            "approval policy %s tried to set default_decision=%r; forcing 'require'",
            source, declared_default,
        )
    policy.default_decision = REQUIRE

    for tier, rule in (data.get("tiers") or {}).items():
        approval = rule.get("approval") if isinstance(rule, dict) else rule
        approval = str(approval or _ALWAYS).strip().lower()
        policy.tiers[str(tier)] = _NEVER if approval == _NEVER else _ALWAYS

    ticket = data.get("ticket") or {}
    if isinstance(ticket, dict):
        try:
            policy.ttl_seconds = max(1, int(ticket.get("ttl_seconds", policy.ttl_seconds)))
            policy.clock_skew_seconds = max(
                0, int(ticket.get("clock_skew_seconds", policy.clock_skew_seconds))
            )
        except (TypeError, ValueError):
            logger.error("approval policy %s has a malformed ticket block; keeping defaults", source)

    for name, spec in (data.get("tools") or {}).items():
        canonical = normalize_tool_name(name)
        if not canonical:
            continue
        spec = spec if isinstance(spec, dict) else {}
        tier = str(spec.get("tier") or "critical")
        if tier not in policy.tiers:
            logger.error(
                "approval policy %s: tool %s uses unknown tier %r; treating as critical",
                source, canonical, tier,
            )
            tier = "critical"
        policy.tools[canonical] = ToolRule(
            canonical=canonical,
            tier=tier,
            simulation_exempt=bool(spec.get("simulation_exempt", False)),
            dispatcher=bool(spec.get("dispatcher", False)),
        )
        policy.aliases[canonical] = canonical
        for alias in spec.get("aliases") or []:
            norm = normalize_tool_name(alias)
            if norm:
                policy.aliases[norm] = canonical

    return policy


def load_policy(path: Optional[Path] = None, reload: bool = False) -> ApprovalPolicy:
    """Load the policy. Never raises; never widens the gate on failure."""
    global _cached
    if _cached is not None and not reload and path is None:
        return _cached

    policy = _builtin_policy()
    target = Path(path) if path is not None else policy_path()

    if target.exists():
        try:
            import yaml

            data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                policy = _merge_yaml(policy, data, str(target))
            else:
                logger.error(
                    "approval policy %s is not a mapping; using built-in policy", target
                )
        except Exception as exc:
            # Fail closed: keep the built-in policy, which requires approval for
            # everything not explicitly tiered read-only.
            logger.error(
                "approval policy %s failed to load (%s); using built-in fail-closed policy",
                target, exc,
            )
            policy = _builtin_policy()
    else:
        logger.debug("approval policy %s not found; using built-in policy", target)

    if path is None:
        _cached = policy
    return policy


def resolve_tool(
    tool_name: Any,
    policy: Optional[ApprovalPolicy] = None,
    args: Any = None,
) -> ToolRule:
    """Resolve any spelling/alias of a tool to its canonical policy row.

    An unresolvable name yields an UNKNOWN rule tiered ``critical`` — unknown
    tools gate.

    For dispatcher tools (``file``, ``browser``) the sub-action carried in
    ``args`` selects the real policy row, so ``file`` + ``action=read`` is
    read_only while ``file`` + ``action=delete`` is elevated. Three fail-closed
    rules apply:

      * no ``args`` and no readable action -> the dispatcher's own tier, which
        is ``critical``. Matches safety.py, which calls this UNCLASSIFIED.
      * an unrecognised sub-action -> unknown, therefore gated.
      * only rules declared ``dispatcher`` ever consult ``args``, so adding
        ``action`` to a non-dispatcher call cannot redirect its policy row.

    ``genesis`` is tiered per sub-capability by a dedicated resolver rather
    than the generic dispatcher path, because its ``action`` is a claim about
    what a REMOTE agent will do rather than a description of what this process
    will do. See ``_resolve_genesis_rule``.
    """
    pol = policy or load_policy()
    normalized = normalize_tool_name(tool_name)
    if not normalized:
        return ToolRule(canonical="<empty>", tier="critical", known=False)
    canonical = pol.aliases.get(normalized, normalized)
    rule = pol.tools.get(canonical)
    if rule is None:
        return ToolRule(canonical=canonical, tier="critical", known=False)

    # Keyed on the canonical id, not on rule.dispatcher: a policy FILE must not
    # be able to route `genesis` through the generic args["action"] dispatcher
    # and skip the agent-capability check.
    if canonical == GENESIS_CANONICAL:
        return _resolve_genesis_rule(rule, args)

    if rule.dispatcher:
        action = _dispatch_action(args)
        if action is None:
            return rule
        sub = normalize_tool_name(f"{canonical}_{action}")
        sub_canonical = pol.aliases.get(sub, sub)
        sub_rule = pol.tools.get(sub_canonical)
        if sub_rule is None:
            return ToolRule(canonical=sub_canonical, tier="critical", known=False)
        # A call that opts out of workspace scoping is not the same capability
        # as the sandboxed one. Escalate only — an already-gated sub-action
        # keeps its own (stricter or equal) tier.
        if requests_unsandboxed_root(args) and sub_rule.tier in _UNGATED_TIERS:
            return ToolRule(
                canonical=f"{sub_canonical}_absolute",
                tier=_UNSANDBOXED_TIER,
                simulation_exempt=False,
                known=True,
                dispatcher=False,
            )
        return sub_rule

    return rule


def evaluate(
    tool_name: Any,
    args: Any = None,
    context: Optional[ApprovalContext] = None,
    policy: Optional[ApprovalPolicy] = None,
) -> PolicyDecision:
    """Resolve the approval requirement for a call. Fail-closed at every step."""
    pol = policy or load_policy()
    rule = resolve_tool(tool_name, pol, args=args)

    bypass = detect_bypass_attempt(args)
    if bypass:
        logger.warning(
            "approval bypass attempt on tool=%s via model-supplied args=%s (ignored)",
            rule.canonical, bypass,
        )

    # Malformed / missing args fail closed. We cannot reason about a payload we
    # cannot read, so we gate it.
    if args is not None and not isinstance(args, dict):
        return PolicyDecision(
            tool=str(tool_name), canonical=rule.canonical, tier=rule.tier,
            decision=REQUIRE, reason="malformed_args", bypass_attempted=tuple(bypass),
        )

    if not rule.known:
        return PolicyDecision(
            tool=str(tool_name), canonical=rule.canonical, tier=rule.tier,
            decision=REQUIRE, reason="unknown_tool_default_require",
            bypass_attempted=tuple(bypass),
        )

    tier_rule = pol.tiers.get(rule.tier, _ALWAYS)
    if tier_rule == _NEVER:
        return PolicyDecision(
            tool=str(tool_name), canonical=rule.canonical, tier=rule.tier,
            decision=ALLOW, reason=f"tier:{rule.tier}:never",
            bypass_attempted=tuple(bypass),
        )

    # The ONLY downgrade path. Requires BOTH an operator-authored policy opt-in
    # AND a caller-constructed context. Model-supplied args never reach here.
    if (
        context is not None
        and context.simulation_authorized
        and rule.simulation_exempt
    ):
        return PolicyDecision(
            tool=str(tool_name), canonical=rule.canonical, tier=rule.tier,
            decision=ALLOW,
            reason=f"caller_authorized_simulation:{context.actor}",
            bypass_attempted=tuple(bypass),
        )

    return PolicyDecision(
        tool=str(tool_name), canonical=rule.canonical, tier=rule.tier,
        decision=REQUIRE, reason=f"tier:{rule.tier}:always",
        bypass_attempted=tuple(bypass),
    )


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


class TicketError(Exception):
    """Ticket failed verification. The message is the machine-readable reason."""


@dataclass(frozen=True)
class ApprovalTicket:
    ticket_id: str
    approval_id: str
    tool: str          # canonical tool identity
    args_digest: str
    session_id: str
    issued_at: float
    expires_at: float
    nonce: str
    approved_by: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "approval_id": self.approval_id,
            "tool": self.tool,
            "args_digest": self.args_digest,
            "session_id": self.session_id,
            "issued_at": round(self.issued_at, 3),
            "expires_at": round(self.expires_at, 3),
            "nonce": self.nonce,
            "approved_by": self.approved_by,
        }


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(key: bytes, encoded_payload: str) -> str:
    return hmac.new(key, encoded_payload.encode("ascii"), hashlib.sha256).hexdigest()


def issue_ticket(
    key: bytes,
    approval_id: str,
    tool_name: Any,
    args: Any,
    session_id: str = "",
    approved_by: str = "",
    now: Optional[float] = None,
    policy: Optional[ApprovalPolicy] = None,
) -> tuple[ApprovalTicket, str]:
    """Mint a signed, single-use, argument-bound ticket. Returns (ticket, token)."""
    pol = policy or load_policy()
    issued = time.time() if now is None else now
    ticket = ApprovalTicket(
        ticket_id=uuid.uuid4().hex,
        approval_id=approval_id,
        tool=resolve_tool(tool_name, pol, args=args).canonical,
        args_digest=compute_args_digest(tool_name, args),
        session_id=session_id,
        issued_at=issued,
        expires_at=issued + pol.ttl_seconds,
        nonce=secrets.token_hex(16),
        approved_by=approved_by,
    )
    return ticket, encode_ticket(key, ticket)


def encode_ticket(key: bytes, ticket: ApprovalTicket) -> str:
    encoded = _b64u(canonical_json(ticket.payload()).encode("utf-8"))
    return f"{TICKET_PREFIX}.{encoded}.{_sign(key, encoded)}"


def decode_ticket(key: bytes, token: Any) -> ApprovalTicket:
    """Decode + verify the signature. Raises TicketError on any tampering."""
    if not isinstance(token, str) or not token:
        raise TicketError("ticket_missing")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TICKET_PREFIX:
        raise TicketError("ticket_malformed")
    _, encoded, signature = parts

    expected = _sign(key, encoded)
    if not hmac.compare_digest(expected, signature):
        raise TicketError("ticket_signature_invalid")

    try:
        data = json.loads(_b64u_decode(encoded).decode("utf-8"))
    except Exception as exc:  # pragma: no cover - unreachable once signature holds
        raise TicketError("ticket_undecodable") from exc
    if not isinstance(data, dict):
        raise TicketError("ticket_undecodable")

    try:
        return ApprovalTicket(
            ticket_id=str(data["ticket_id"]),
            approval_id=str(data["approval_id"]),
            tool=str(data["tool"]),
            args_digest=str(data["args_digest"]),
            session_id=str(data.get("session_id") or ""),
            issued_at=float(data["issued_at"]),
            expires_at=float(data["expires_at"]),
            nonce=str(data["nonce"]),
            approved_by=str(data.get("approved_by") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TicketError("ticket_incomplete") from exc


def verify_ticket(
    key: bytes,
    token: Any,
    tool_name: Any,
    args: Any,
    approval_id: Optional[str] = None,
    now: Optional[float] = None,
    policy: Optional[ApprovalPolicy] = None,
) -> ApprovalTicket:
    """Full verification: signature, expiry, scope, and argument digest.

    Raises :class:`TicketError` with a machine-readable reason. Callers must
    treat ANY exception here as "not approved".
    """
    pol = policy or load_policy()
    ticket = decode_ticket(key, token)
    current = time.time() if now is None else now
    skew = pol.clock_skew_seconds

    if current > ticket.expires_at + skew:
        raise TicketError("ticket_expired")
    if current < ticket.issued_at - skew:
        raise TicketError("ticket_not_yet_valid")

    if approval_id is not None and ticket.approval_id != approval_id:
        raise TicketError("ticket_approval_mismatch")

    if ticket.tool != resolve_tool(tool_name, pol, args=args).canonical:
        raise TicketError("ticket_tool_mismatch")

    if not hmac.compare_digest(ticket.args_digest, compute_args_digest(tool_name, args)):
        raise TicketError("ticket_args_mismatch")

    return ticket


__all__ = [
    "ALLOW",
    "GENESIS_CANONICAL",
    "GENESIS_READ_ONLY_CANONICAL",
    "REQUIRE",
    "ApprovalContext",
    "ApprovalPolicy",
    "ApprovalTicket",
    "PolicyDecision",
    "TicketError",
    "ToolRule",
    "build_preview",
    "canonical_args",
    "canonical_json",
    "compute_args_digest",
    "decode_ticket",
    "detect_bypass_attempt",
    "encode_ticket",
    "evaluate",
    "is_sensitive_key",
    "issue_ticket",
    "load_policy",
    "normalize_tool_name",
    "policy_path",
    "redact",
    "redact_text",
    "resolve_tool",
    "strip_control_keys",
    "verify_ticket",
]
