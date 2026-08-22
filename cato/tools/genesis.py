"""Genesis Agents tool — calls SwarmSync-hosted AP2 agents.

Sends signed AP2 envelopes to https://swarmsync-agents.onrender.com/agents/{slug}/run.
Bound to Cato's vault Ed25519 keypair via cato.vault_crypto.

The tool exposes the GENESIS_AGENTS registry (original marketplace slugs plus
14 E4L accounting specialists). Each
call builds a fresh AP2 envelope: payload + nonce + RFC3339 timestamp, signed
with the vault's long-lived Ed25519 identity key, then POSTed to the agent's
``/agents/{slug}/run`` endpoint with the public key on a sidecar header.

Public symbols:
    GENESIS_AGENTS         -- registry dict
    GENESIS_TOOL_SCHEMA    -- tool registry schema for task-03 wiring
    AP2_ENVELOPE_VERSION   -- wire protocol version (1)
    MONEY_DOMAIN_AGENTS    -- hardcoded money-domain slugs
    IMMUTABLE_DENIED_AGENTS -- money-domain slugs plus deployment
    FAIL_CLOSED_ACCOUNTING_ALLOWLIST -- 14 E4L specialist slugs Cato may grant
    build_envelope         -- pure function, builds + signs envelope
    list_agents            -- returns the registry as a flat list
    GenesisTool            -- the tool class (instance method ``execute``)

Containment model (see cato/tools/genesis.py execute() branches):
    - genesis_agent_allowlist fails CLOSED: empty or missing denies every
      agent; only an explicitly populated list grants anything.
    - IMMUTABLE_DENIED_AGENTS (deployment plus finance/billing/commerce/pricing) is denied
      independently of, and takes priority over, the allowlist -- it cannot
      be reinstated via config.
    - Allow/deny is derived only from the agent slug + Cato-side config,
      never from task text, params, or the remote response.
    - HTTP 200 is not treated as success if the body carries a stub/
      scaffold marker (see _detect_stub_response).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp

from cato import vault_crypto
from cato.config import CatoConfig

# ---------------------------------------------------------------------------
# 34-agent registry: 29 deployed, 5 pending.
# genesis-e4l-* are the only money-adjacent slugs Cato may grant for E4L books.
# genesis-finance/billing/commerce/pricing stay on MONEY_DOMAIN_AGENTS.
# genesis-e4l-accounting is REJECTED (one-hat) and must not reappear.
# ---------------------------------------------------------------------------
GENESIS_AGENTS: dict[str, dict[str, Any]] = {
    "genesis-meta":            {"name": "Genesis Meta Agent",      "route": "/orchestrate",            "price_usd": 100, "status": "deployed"},
    "genesis-builder":         {"name": "Genesis Builder Agent",   "route": "/generate/module",        "price_usd": 200, "status": "deployed"},
    "genesis-research":        {"name": "Genesis Research Agent",  "route": "/research/comprehensive", "price_usd": 150, "status": "deployed"},
    "genesis-deploy":          {"name": "Genesis Deploy Agent",    "route": "/deploy/advanced",        "price_usd": 300, "status": "deployed"},
    "genesis-qa":              {"name": "Genesis QA Agent",        "route": "/test/analysis",          "price_usd": 150, "status": "deployed"},
    "genesis-finance":         {"name": "Genesis Finance Agent",   "route": "/finance/strategy",       "price_usd": 400, "status": "deployed"},
    "genesis-marketing":       {"name": "Genesis Marketing Agent", "route": "/marketing/strategy",     "price_usd": 300, "status": "deployed"},
    "genesis-content":         {"name": "Genesis Content Agent",   "route": "/content/whitepaper",     "price_usd": 180, "status": "deployed"},
    "genesis-security":        {"name": "Genesis Security Agent",  "route": "/security/pentest",       "price_usd": 600, "status": "deployed"},
    "genesis-seo":             {"name": "Genesis SEO Agent",       "route": "/seo/strategy",           "price_usd": 180, "status": "deployed"},
    "genesis-support":         {"name": "Genesis Support Agent",   "route": "/support/system",         "price_usd":  75, "status": "deployed"},
    "genesis-email":           {"name": "Genesis Email Agent",     "route": "/email/campaign",         "price_usd": 120, "status": "deployed"},
    "genesis-analyst":         {"name": "Genesis Analyst Agent",   "route": "/analyze/strategy",       "price_usd": 200, "status": "deployed"},
    "genesis-commerce":        {"name": "Genesis Commerce Agent",  "route": "/commerce/integration",   "price_usd": 250, "status": "deployed"},
    "genesis-billing":         {"name": "Genesis Billing Agent",   "route": "/billing/revops",         "price_usd": 100, "status": "deployed"},
    "genesis-legal":              {"name": "Genesis Legal Agent",        "route": None, "price_usd": None, "status": "pending"},
    "genesis-hr":                 {"name": "Genesis HR Agent",           "route": None, "price_usd": None, "status": "pending"},
    "genesis-data-pipeline":      {"name": "Genesis Data Pipeline Agent","route": None, "price_usd": None, "status": "pending"},
    "genesis-workflow-automator": {"name": "Genesis Workflow Automator", "route": None, "price_usd": None, "status": "pending"},
    "genesis-ai-vision":          {"name": "Genesis AI Vision API",      "route": None, "price_usd": None, "status": "pending"},
    # The public Genesis catalog currently proves deployment status for these
    # slugs but publishes neither a route nor a price. Keep those unknowns null
    # instead of inventing accounting endpoints or commercial terms.
    "genesis-e4l-revenue":        {"name": "Genesis E4L Revenue",        "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-shopify":        {"name": "Genesis E4L Shopify",        "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-stripe":         {"name": "Genesis E4L Stripe",         "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-cash":           {"name": "Genesis E4L Cash",           "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-ap":             {"name": "Genesis E4L AP",             "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-ar":             {"name": "Genesis E4L AR",             "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-cogs-cm":        {"name": "Genesis E4L COGS & CM",      "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-commissions":    {"name": "Genesis E4L Commissions",    "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-intercompany":   {"name": "Genesis E4L Intercompany",   "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-close":          {"name": "Genesis E4L Close",          "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-journals":       {"name": "Genesis E4L Journals",       "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-fs-integrity":   {"name": "Genesis E4L FS Integrity",   "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-controller":     {"name": "Genesis E4L Controller",     "route": None, "price_usd": None, "status": "deployed"},
    "genesis-e4l-treasury":       {"name": "Genesis E4L Treasury",       "route": None, "price_usd": None, "status": "deployed"},
}

AP2_ENVELOPE_VERSION = 1

# Truncate upstream error bodies to keep tool output bounded.
_UPSTREAM_BODY_TRUNCATE = 500

_logger = logging.getLogger("cato.tools.genesis")

# ---------------------------------------------------------------------------
# Immutable high-impact denylist -- hardcoded, NOT configurable away.
#
# The money slugs front Genesis's finance/billing/commerce/pricing tool
# modules. Per the verified Genesis audit, those modules are stubs that
# return {"ok": true, "stub": true} for write actions and (in the pricing
# case) fabricate hardcoded revenue figures. Cato must never be able to
# invoke them, and deployment is equally prohibited, no matter what an
# operator puts in genesis_agent_allowlist.
#
# This set is independent of config: config.genesis_agent_denylist can only
# ADD slugs to the denylist, never remove one of these.
# ---------------------------------------------------------------------------
MONEY_DOMAIN_AGENTS: frozenset[str] = frozenset({
    "genesis-finance",
    "genesis-billing",
    "genesis-commerce",
    "genesis-pricing",
})
IMMUTABLE_DENIED_AGENTS: frozenset[str] = MONEY_DOMAIN_AGENTS | {"genesis-deploy"}

# Fail-closed grant set for E4L accounting. Empty config.genesis_agent_allowlist
# still denies every agent. These 14 slugs MAY appear on that allowlist.
# They are NOT on MONEY_DOMAIN_AGENTS (that set is stub marketplace tools).
FAIL_CLOSED_ACCOUNTING_ALLOWLIST: frozenset[str] = frozenset({
    "genesis-e4l-revenue",
    "genesis-e4l-shopify",
    "genesis-e4l-stripe",
    "genesis-e4l-cash",
    "genesis-e4l-ap",
    "genesis-e4l-ar",
    "genesis-e4l-cogs-cm",
    "genesis-e4l-commissions",
    "genesis-e4l-intercompany",
    "genesis-e4l-close",
    "genesis-e4l-journals",
    "genesis-e4l-fs-integrity",
    "genesis-e4l-controller",
    "genesis-e4l-treasury",
})

_QUEUED_JOB_STATES = frozenset({"QUEUED", "RUNNING", "PENDING", "PROCESSING"})
_SUCCESS_JOB_STATES = frozenset({"DELIVERED", "DELIVERED_WITH_ARTIFACT_WARNING", "COMPLETED"})
_FAILED_JOB_STATES = frozenset({"FAILED", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED"})
_POLL_INTERVAL_S = 0.25
_POLL_INTERVAL_MAX_S = 4.0
_PRINCIPAL_TOKEN_MAX_LENGTH = 4096

# Suffix used by the live SwarmSync gateway on some wire-form agent slugs
# (e.g. "genesis_finance_x402"). Stripped during canonicalization so a
# naming-convention mismatch can never be used to smuggle a money-domain
# slug past the denylist or an allowlist entry written in the other form.
_ALIAS_SUFFIX = "_x402"

# Markers that indicate a remote response is a stub/scaffold rather than
# genuine evidence that the requested operation happened. Any of these being
# truthy in a parsed JSON response body means Cato must report FAILURE to
# its caller even though the HTTP status was 200.
_STUB_MARKER_KEYS = ("stub", "scaffold", "placeholder", "mock", "not_implemented")

# How deep to look for a stub marker. Genesis nests real results under
# "result"/"data"/"output", so a top-level-only scan let
# {"ok": true, "result": {"stub": true}} through as a success (t14).
_STUB_SCAN_MAX_DEPTH = 6

# Keys a remote uses to report, in band, that the operation did NOT happen even
# though the HTTP status was 200. Cato must mirror that failure rather than
# wrap it in its own {"ok": true} envelope (t14).
_INBAND_OK_KEYS = ("ok", "success", "succeeded")
_INBAND_ERROR_KEYS = ("error", "errors", "error_message", "failure", "exception")


def _canonicalize_agent_slug(agent: Any) -> str:
    """Normalize an agent slug for allow/deny matching ONLY.

    Lowercases, strips a trailing ``_x402`` suffix, and converts underscores
    to hyphens, so "genesis_finance_x402", "genesis_finance", and
    "genesis-finance" all compare equal for allowlist/denylist purposes.

    This does NOT change registry lookup, dispatch, or the wire URL slug --
    it exists solely so a naming-convention mismatch between Cato's
    hyphenated registry and the gateway's underscored/_x402 wire forms can
    never be used to bypass the denylist or forge an allowlist match.
    """
    if not isinstance(agent, str):
        return ""
    normalized = agent.strip().lower()
    if normalized.endswith(_ALIAS_SUFFIX):
        normalized = normalized[: -len(_ALIAS_SUFFIX)]
    return normalized.replace("_", "-")


def _detect_stub_response(parsed_body: Any, _depth: int = 0) -> str | None:
    """Return a reason code if *parsed_body* looks like a stub/scaffold
    response rather than genuine evidence of a completed operation.

    Scans NESTED objects and arrays, not only the top level: Genesis returns
    its real payload under keys like ``result``/``data``/``output``, so a
    top-level-only scan reported ``{"ok": true, "result": {"stub": true}}``
    as a genuine success. Depth is bounded by ``_STUB_SCAN_MAX_DEPTH`` so a
    hostile deeply-nested body cannot turn validation into a stack overflow.

    Returns None when nothing in the body carries a stub marker.
    """
    if _depth > _STUB_SCAN_MAX_DEPTH:
        return None
    if isinstance(parsed_body, dict):
        for key in _STUB_MARKER_KEYS:
            if parsed_body.get(key):
                return f"remote_marked_{key}"
        for value in parsed_body.values():
            if isinstance(value, (dict, list)):
                reason = _detect_stub_response(value, _depth + 1)
                if reason is not None:
                    return reason
        return None
    if isinstance(parsed_body, list):
        for value in parsed_body:
            if isinstance(value, (dict, list)):
                reason = _detect_stub_response(value, _depth + 1)
                if reason is not None:
                    return reason
    return None


def _is_indeterminate_transport_error(exc: BaseException) -> bool:
    """True when a transport failure leaves the remote outcome UNKNOWN.

    The only failures we can prove did nothing are the ones where the TCP/TLS
    connection was never established (``aiohttp.ClientConnectorError`` and its
    DNS/SSL/proxy subclasses). Everything else happens at or after the request
    was handed to the socket, so the remote may have received and completed it.
    Fail closed: unknown means unknown, not "failed".
    """
    try:
        import aiohttp
    except Exception:  # pragma: no cover — aiohttp is a hard dependency
        return True
    connector_errors: tuple[type[BaseException], ...] = tuple(
        cls for cls in (
            getattr(aiohttp, "ClientConnectorError", None),
            getattr(aiohttp, "ClientProxyConnectionError", None),
        ) if isinstance(cls, type)
    )
    if connector_errors and isinstance(exc, connector_errors):
        return False
    return True


def _detect_inband_failure(parsed_body: Any) -> str | None:
    """Return a reason code when the remote reported failure inside a 200 body.

    SwarmSync's gateway answers ``200 OK`` with ``{"ok": false, "error": ...}``
    when an agent refuses or crashes. Cato used to wrap that in its own
    ``{"ok": true, "response": <body>}`` envelope, so:

      * the model was told the dispatch succeeded, and
      * ``_tool_result_failure`` (cato/agent_loop.py) saw no ``error`` key on
        the OUTER object and the audit ledger recorded CONFIRMED/success.

    A remote that says it failed is the strongest evidence available; it wins
    over the HTTP status. Only an EXPLICIT falsey ``ok``/``success`` field or a
    non-empty error field counts — a body that simply omits them is unchanged.
    """
    if not isinstance(parsed_body, dict):
        return None
    for key in _INBAND_OK_KEYS:
        if key in parsed_body and parsed_body[key] is not None and not parsed_body[key]:
            return f"remote_reported_{key}_false"
    for key in _INBAND_ERROR_KEYS:
        if parsed_body.get(key):
            return f"remote_reported_{key}"
    return None


def _parse_json_object(value: Any) -> dict[str, Any] | None:
    """Return a JSON object, unwrapping Genesis's string ``response`` once.

    ``/agents/{slug}/run`` uses a Pydantic ``RunResponse`` whose ``response``
    field is itself JSON text.  The explicit async ``/jobs`` route returns the
    job object directly.  Cato accepts both shapes without guessing at prose.
    """
    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(parsed, dict):
        return None
    nested = parsed.get("response")
    if isinstance(nested, str):
        try:
            decoded = json.loads(nested)
        except (json.JSONDecodeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            return decoded
    return parsed


def _successful_tool_call_count(payload: dict[str, Any]) -> int | None:
    """Count explicit successful Genesis tool calls, or None if no trace exists."""
    trace = payload.get("trace")
    if not isinstance(trace, dict):
        return None
    calls = trace.get("tool_calls")
    if not isinstance(calls, list):
        return 0
    return sum(1 for call in calls if isinstance(call, dict) and call.get("ok") is True)


def _valid_principal_token(value: Any) -> str | None:
    """Return a bounded opaque server token safe for an HTTP header."""
    if not isinstance(value, str):
        return None
    if not value or len(value) > _PRINCIPAL_TOKEN_MAX_LENGTH:
        return None
    if value != value.strip() or any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
        return None
    return value


# ---------------------------------------------------------------------------
# Envelope construction (pure, testable, no I/O)
# ---------------------------------------------------------------------------

def _canonical_signed_bytes(payload: dict[str, Any], nonce: str, timestamp: str) -> bytes:
    """Return the canonical-JSON bytes that get signed.

    Must NEVER include the signature or pubkey; if the wire format ever
    grows new signed fields, they MUST be added here in sorted-key form.

    ``ensure_ascii=False`` is load-bearing, not style. Genesis verifies against
    ``json.dumps(..., ensure_ascii=False).encode("utf-8")`` (Genesis Agents
    runtime/request_auth.py::_canonical_json), which is the RFC 8785 (JCS)
    canonical form. Signing with the json.dumps default escaped every
    non-ASCII character to ``\\uXXXX``, so the two sides hashed different byte
    strings and any task containing a smart quote, accent, arrow or emoji was
    rejected with 401 ap2_signature_invalid. ASCII-only payloads encode
    identically under both settings, so existing traffic is unaffected.
    """
    return json.dumps(
        {"payload": payload, "nonce": nonce, "timestamp": timestamp},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _rfc3339_utc_now() -> str:
    """RFC3339 UTC timestamp with a 'Z' suffix and second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_envelope(vault, agent: str, task: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a signed AP2 envelope for the given agent + task.

    Pure with respect to the vault: only uses ``vault_crypto.sign`` and
    ``vault_crypto.get_or_create_keypair``. Generates a fresh nonce + timestamp
    on every call (envelopes are intentionally not idempotent — that's how the
    server detects replays).
    """
    payload = {
        "agent": agent,
        "task": task,
        "params": params or {},
    }
    nonce = uuid.uuid4().hex
    timestamp = _rfc3339_utc_now()

    signed_bytes = _canonical_signed_bytes(payload, nonce, timestamp)
    signature = vault_crypto.sign(vault, signed_bytes)
    _priv, pub_bytes = vault_crypto.get_or_create_keypair(vault)

    return {
        "version": AP2_ENVELOPE_VERSION,
        "payload": payload,
        "nonce": nonce,
        "timestamp": timestamp,
        "pubkey": base64.b64encode(pub_bytes).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }


# ---------------------------------------------------------------------------
# Tool class
# ---------------------------------------------------------------------------

class GenesisTool:
    """Tool wrapper that POSTs signed AP2 envelopes to SwarmSync.

    Vault and config are lazily resolved on first ``execute()`` if not
    supplied to the constructor. The aiohttp session is also lazy — created
    on first use and reused for all subsequent calls until ``close()``.
    """

    def __init__(
        self,
        vault: Any = None,
        config: Any = None,
        budget: Any = None,
    ) -> None:
        self._vault = vault
        self._config = config
        self._budget = budget
        self._session: aiohttp.ClientSession | None = None
        self._warmed_up = False
        self._log = _logger

    # ---- lazy dependency resolution -------------------------------------

    def _get_vault(self) -> Any:
        """Resolve vault via constructor injection first, falling back to
        the cato.vault.get_vault() module-level accessor (matches the
        convention used in cato/api/integration_routes.py line 148)."""
        if self._vault is None:
            from cato.vault import get_vault  # lazy import: avoids vault load at import time
            self._vault = get_vault()
        return self._vault

    def _get_config(self) -> CatoConfig:
        if self._config is None:
            self._config = CatoConfig.load()
        return self._config

    # ---- HTTP session ---------------------------------------------------

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # Use ThreadedResolver (OS resolver via thread pool) instead of the
            # default async resolver. On Windows, aiohttp's default resolver has
            # been observed to raise ClientConnectorDNSError intermittently for
            # hosts that urllib (which uses the OS resolver) resolves cleanly.
            # ThreadedResolver gives us urllib-equivalent reliability without
            # pulling in aiodns as a dependency.
            resolver = aiohttp.ThreadedResolver()
            connector = aiohttp.TCPConnector(
                resolver=resolver,
                family=0,  # IPv4 + IPv6 — let the OS pick
                ssl=True,
                limit=10,
            )
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def _warmup(self, endpoint: str) -> None:
        """One-shot GET /health to wake the Render free-tier dyno.

        Failures are logged but never raised — the real POST will retry.
        Sets ``self._warmed_up`` regardless of success to avoid retry loops.
        """
        if self._warmed_up:
            return
        self._warmed_up = True  # set up-front so a hang/error doesn't trigger repeated warmups
        url = f"{endpoint.rstrip('/')}/health"
        try:
            session = await self._ensure_session()
            timeout = aiohttp.ClientTimeout(total=60)
            async with session.get(url, timeout=timeout) as resp:
                # Drain the body so the connection can be returned to the pool.
                await resp.read()
                self._log.debug("Genesis warmup %s -> %s", url, resp.status)
        except Exception as exc:  # noqa: BLE001 — warmup must never raise
            self._log.warning("Genesis warmup failed for %s: %s", url, exc)

    async def close(self) -> None:
        """Close the aiohttp session. Idempotent."""
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception as exc:  # noqa: BLE001
                self._log.warning("Error closing Genesis session: %s", exc)
        self._session = None

    @staticmethod
    def _wire_request(
        envelope: dict[str, Any], task: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the Genesis RunRequest without changing signed AP2 fields.

        Genesis validates a non-empty top-level ``prompt`` and reads structured
        runtime parameters from ``task``.  AP2 fields remain top-level for the
        signature middleware; the signed ``payload`` is not rewritten.
        """
        runtime_task = dict(params)
        runtime_task.setdefault("description", task)
        return {**envelope, "prompt": task, "task": runtime_task}

    @staticmethod
    def _terminal_result(
        payload: dict[str, Any], *, agent: str, elapsed: float,
    ) -> str:
        """Map one terminal Genesis payload to a truthful Cato tool result."""
        stub_reason = _detect_stub_response(payload)
        if stub_reason is not None:
            return json.dumps({
                "ok": False, "error": "stub_response", "reason": stub_reason,
                "agent": agent, "response": json.dumps(payload), "elapsed_s": elapsed,
            })

        inband_reason = _detect_inband_failure(payload)
        if inband_reason is not None:
            return json.dumps({
                "ok": False, "error": "remote_reported_failure", "reason": inband_reason,
                "agent": agent, "response": json.dumps(payload), "elapsed_s": elapsed,
            })

        successful_calls = _successful_tool_call_count(payload)
        if successful_calls == 0:
            return json.dumps({
                "ok": False,
                "error": "zero_successful_tool_calls",
                "reason": "Genesis returned an explicit trace with no successful tool execution",
                "agent": agent,
                "response": json.dumps(payload),
                "elapsed_s": elapsed,
            })

        return json.dumps({
            "ok": True,
            "agent": agent,
            "response": json.dumps(payload),
            "elapsed_s": elapsed,
            "successful_tool_calls": successful_calls,
        })

    async def _poll_job(
        self,
        *,
        endpoint: str,
        poll_url: str,
        principal_token: str,
        agent: str,
        deadline: float,
        started: float,
    ) -> str:
        """Poll a queued Genesis job until a terminal state or an unknown timeout."""
        # Poll locations are untrusted response data.  Accept only one leading
        # slash so the gateway credential can never be redirected to another
        # origin via an absolute, scheme-relative, or userinfo URL.
        if not poll_url.startswith("/") or poll_url.startswith("//") or "\\" in poll_url:
            return json.dumps({
                "ok": False,
                "error": "unsafe_job_poll_url",
                "outcome_unknown": True,
                "agent": agent,
                "reason": "Genesis returned a non-relative polling location",
            })
        url = f"{endpoint.rstrip('/')}{poll_url}"
        # LEAST PRIVILEGE, DELIBERATE: the poll carries ONLY the owner-scoped
        # principal token. The shared GATEWAY_API_KEY is an omni-privilege
        # credential — any holder can read any job — and `poll_url` arrives in
        # an untrusted response body, so it must never travel here.
        #
        # KNOWN OPEN CONTRACT GAP (Cato cannot close this alone): if Genesis's
        # `GET /agents/jobs/{id}` requires the gateway key and does not honour
        # `X-Genesis-Principal-Token`, every 202/QUEUED dispatch ends in
        # `job_poll_upstream_error` (401) -> outcome_unknown -> a ledger
        # INDETERMINATE a human must reconcile, for a job that ran fine. The
        # fix belongs on the Genesis side: accept the principal token. Do NOT
        # "fix" it here by sending the shared secret.
        # Pinned by tests/test_genesis_tool.py::
        #   test_expired_principal_token_fails_without_shared_gateway_header
        #   test_poll_redirect_is_not_followed_with_gateway_credential
        poll_headers = {
            "Content-Type": "application/json",
            "X-Genesis-Principal-Token": principal_token,
        }
        session = await self._ensure_session()
        # Bounded exponential backoff. A flat 0.25s interval issued up to
        # ~240 requests per queued job against a cold Render instance, which
        # is a retry storm dressed up as polling.
        interval = _POLL_INTERVAL_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return json.dumps({
                    "ok": False,
                    "error": "job_poll_timeout",
                    "outcome_unknown": True,
                    "agent": agent,
                    "reason": "Genesis job remained non-terminal through the polling deadline",
                })
            timeout = aiohttp.ClientTimeout(total=max(0.1, remaining))
            async with session.get(
                url, headers=poll_headers, timeout=timeout, allow_redirects=False,
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    truncated = body[:_UPSTREAM_BODY_TRUNCATE]
                    return json.dumps({
                        "ok": False,
                        "error": "job_poll_upstream_error",
                        "outcome_unknown": True,
                        "agent": agent,
                        "status": resp.status,
                        "body": truncated,
                    })
                payload = _parse_json_object(body)
                if payload is None:
                    return json.dumps({
                        "ok": False,
                        "error": "invalid_job_status",
                        "outcome_unknown": True,
                        "agent": agent,
                    })
                status = str(payload.get("status") or "").upper()
                if status in _QUEUED_JOB_STATES:
                    await asyncio.sleep(min(interval, max(0.0, remaining)))
                    interval = min(interval * 2, _POLL_INTERVAL_MAX_S)
                    continue
                if status in _FAILED_JOB_STATES:
                    return json.dumps({
                        "ok": False,
                        "error": "genesis_job_failed",
                        "agent": agent,
                        "status": status,
                        "response": json.dumps(payload),
                    })
                if status not in _SUCCESS_JOB_STATES:
                    return json.dumps({
                        "ok": False,
                        "error": "unknown_job_status",
                        "outcome_unknown": True,
                        "agent": agent,
                        "status": status or "MISSING",
                    })

                summary = payload.get("resultSummary", payload.get("result_summary"))
                terminal_payload = _parse_json_object(summary) or payload
                terminal_payload.setdefault("status", status)
                return self._terminal_result(
                    terminal_payload,
                    agent=agent,
                    elapsed=round(time.monotonic() - started, 3),
                )

    # ---- main entry point ----------------------------------------------

    async def execute(self, args: dict[str, Any]) -> str:
        """Traced wrapper over :meth:`_execute_inner`.

        Opens the ``genesis.dispatch`` span that is the Cato side of the
        Cato -> specialist boundary, and binds the specialist slug into the
        correlation context so the outbound HTTP span and anything the
        dispatch triggers carry it too. Only Cato's own result envelope keys
        (ok / error / elapsed) go on the span — never the task text, the
        params, or the upstream body.
        """
        from cato.core import phoenix_tracing as _pt

        slug = _canonicalize_agent_slug((args or {}).get("agent"))
        with _pt.correlation(specialist=slug or None):
            with _pt.span(
                "genesis.dispatch",
                kind="TOOL",
                attributes={
                    _pt.TOOL_NAME: "genesis",
                    "genesis.agent.slug": slug or "",
                    "genesis.task.chars": len(str((args or {}).get("task") or "")),
                },
            ) as sp:
                result = await self._execute_inner(args)
                try:
                    parsed = json.loads(result) if isinstance(result, str) else None
                except (json.JSONDecodeError, ValueError):
                    parsed = None
                if isinstance(parsed, dict):
                    _pt.set_attributes(sp, {
                        "genesis.ok": bool(parsed.get("ok")),
                        "genesis.error": parsed.get("error"),
                        "genesis.http.status": parsed.get("status"),
                        "genesis.elapsed_s": parsed.get("elapsed_s"),
                    })
                return result

    async def _execute_inner(self, args: dict[str, Any]) -> str:
        """Dispatch a call to a Genesis agent.

        Args:
            args: {"agent": str, "task": str, "params"?: dict}

        Returns:
            JSON-encoded string. Shape depends on outcome — see module docstring
            and task spec for the eight branches.
        """
        # The allow/deny decision below is derived ONLY from `agent` (the
        # slug argument) and Cato-side config. `task` and `params` are never
        # consulted for authorization -- Genesis cannot grant itself
        # execution authority by putting instructions in its own task text,
        # and (further down) a remote response can never influence this
        # decision either, since it isn't fetched yet.
        # Validate SHAPE before anything else. A model-written tool call can
        # carry any JSON type in any field: `agent: 42` and `agent: ["x"]` both
        # raised AttributeError out of `.strip()`, and a call with no `task` at
        # all (a schema-required field) reached the network with an empty task.
        # A call we cannot read is refused, never guessed at.
        if not isinstance(args, dict):
            return json.dumps({"ok": False, "error": "invalid_arguments",
                               "reason": "args must be a JSON object"})
        raw_agent = args.get("agent")
        raw_task = args.get("task")
        if not isinstance(raw_agent, str) or not raw_agent.strip():
            return json.dumps({
                "ok": False, "error": "invalid_arguments",
                "reason": "agent must be a non-empty string",
                "agent_type": type(raw_agent).__name__,
            })
        if not isinstance(raw_task, str) or not raw_task.strip():
            return json.dumps({
                "ok": False, "error": "invalid_arguments",
                "reason": "task must be a non-empty string",
                "agent": raw_agent.strip(),
                "task_type": type(raw_task).__name__,
            })
        raw_params = args.get("params")
        if raw_params is not None and not isinstance(raw_params, dict):
            return json.dumps({
                "ok": False, "error": "invalid_arguments",
                "reason": "params must be a JSON object",
                "agent": raw_agent.strip(),
            })

        agent = raw_agent.strip()
        task = raw_task
        params = dict(raw_params or {})

        # E4L scope map injection (2026-08-22 posting model) — fail closed
        if _canonicalize_agent_slug(agent) in FAIL_CLOSED_ACCOUNTING_ALLOWLIST:
            try:
                from cato.xero_scope import build_dispatch_scope_params

                params.update(build_dispatch_scope_params(_canonicalize_agent_slug(agent)))
            except Exception as exc:  # noqa: BLE001
                self._log.error("scope map injection failed for %s: %s", agent, exc)
                return json.dumps({
                    "ok": False,
                    "error": "scope_map_injection_failed",
                    "agent": agent,
                    "reason": str(exc),
                })

        config = self._get_config()
        canonical_agent = _canonicalize_agent_slug(agent)

        # --- branch 0: independent money-domain denylist.
        #
        # Evaluated FIRST, independently of the allowlist, and using the
        # canonicalized slug so aliases (genesis_finance_x402, etc.) can't
        # slip through. This ALWAYS wins -- even if `agent` also happens to
        # appear in config.genesis_agent_allowlist. The hardcoded
        # MONEY_DOMAIN_AGENTS set can never be overridden by config; the
        # config denylist can only add to it.
        configured_denylist = {
            _canonicalize_agent_slug(slug)
            for slug in (getattr(config, "genesis_agent_denylist", None) or [])
        }
        if canonical_agent in IMMUTABLE_DENIED_AGENTS or canonical_agent in configured_denylist:
            return json.dumps({
                "ok": False,
                "error": "denylisted",
                "agent": agent,
                "canonical_agent": canonical_agent,
            })

        # --- branch 1: unknown agent
        if agent not in GENESIS_AGENTS:
            return json.dumps({
                "ok": False,
                "error": "unknown_agent",
                "agent": agent,
                "known": list(GENESIS_AGENTS.keys()),
            })

        meta = GENESIS_AGENTS[agent]

        # --- branch 2: globally disabled
        if not getattr(config, "genesis_enabled", True):
            return json.dumps({"ok": False, "error": "genesis_disabled"})

        # --- branch 3: allowlist -- fail closed.
        #
        # An EMPTY or MISSING allowlist denies every agent. Only an
        # explicitly populated allowlist grants anything: removing
        # configuration must reduce capability, never expand it.
        allowlist = getattr(config, "genesis_agent_allowlist", None)
        canonical_allowlist = {
            _canonicalize_agent_slug(slug) for slug in (allowlist or [])
        }
        if canonical_agent not in canonical_allowlist:
            return json.dumps({
                "ok": False,
                "error": "not_in_allowlist",
                "agent": agent,
            })

        # --- branch 4: not cleared for dispatch from Cato
        #
        # These five slugs DO exist as real Genesis bundles and would answer a
        # request. The old message ("not yet deployed on SwarmSync ... try again
        # later") was verified false and sent the operator to wait on a
        # deployment that had already happened. The blocker is on Cato's side:
        # the slug has not been reviewed and cleared for dispatch. The error
        # code is retained for callers; the explanation must be true.
        if meta.get("status") == "pending":
            return json.dumps({
                "ok": False,
                "error": "pending_deployment",
                "agent": agent,
                "name": meta.get("name", agent),
                "message": (
                    "This Genesis agent exists on Genesis but is not cleared for "
                    "dispatch from Cato. Waiting will not change this — clearing "
                    "it requires a reviewed capability grant, not a deployment."
                ),
            })

        # Budget gate — flat per-call estimate from agent tier
        if self._budget is not None:
            price = meta.get("price_usd")
            try:
                cost_usd = min(max(float(price or 0.5) * 0.01, 0.10), 5.0)
            except (TypeError, ValueError):
                cost_usd = 0.50
            try:
                await self._budget.check_and_deduct_usd(
                    cost_usd,
                    label=f"genesis:{agent}",
                )
            except Exception as exc:
                return json.dumps({
                    "ok": False,
                    "error": "budget_exceeded",
                    "agent": agent,
                    "message": str(exc),
                })

        # --- deployed branch: sign envelope + POST
        endpoint = getattr(config, "genesis_endpoint", "https://swarmsync-agents.onrender.com")
        timeout_s = float(getattr(config, "genesis_timeout_s", 30.0))
        route = meta.get("route") or "/run"
        # The task spec pins the URL shape to /agents/{slug}/run. The per-agent
        # `route` is metadata for documentation/UI; the wire URL is always /run.
        url = f"{endpoint.rstrip('/')}/agents/{agent}/run"

        try:
            vault = self._get_vault()
            envelope = build_envelope(vault, agent, task, params)
        except Exception as exc:  # noqa: BLE001 — surface signing failures as tool errors
            return json.dumps({
                "ok": False,
                "error": "exception",
                "agent": agent,
                "type": type(exc).__name__,
                "message": str(exc),
            })

        # Cold start warmup before the very first real request (60s budget).
        is_cold = not self._warmed_up
        if is_cold:
            await self._warmup(endpoint)

        # Pull gateway API key from the vault. SwarmSync's agents-gateway
        # currently authenticates inbound requests by comparing the
        # X-Agent-Api-Key header against its GATEWAY_API_KEY env var
        # (apps/agents-gateway/main.py — verify_gateway_key()). The header
        # is only sent when the vault actually holds a non-empty value;
        # if the key is missing we omit the header so deployments that
        # have not yet configured a gateway secret continue to work.
        #
        # Operator setup: `cato vault set GATEWAY_API_KEY <value>`.
        #
        # Forward-looking: SwarmSync's signature-verification middleware
        # (see Protocols/VCAP-AP2-Binding-v1.0-draft.md and
        # apps/agents-gateway/trusted_ap2_clients.json) will validate
        # X-AP2-Pubkey against the trusted-client registry, at which point
        # the shared API key becomes optional. We keep both headers wired
        # so the transition is a server-side flip.
        api_key = None
        try:
            api_key = vault.get("GATEWAY_API_KEY")
        except Exception:
            api_key = None

        headers = {
            "Content-Type": "application/json",
            "X-AP2-Version": str(AP2_ENVELOPE_VERSION),
            "X-AP2-Pubkey": envelope["pubkey"],
        }
        if isinstance(api_key, str) and api_key:
            headers["X-Agent-Api-Key"] = api_key

        # W3C trace-context so the receiving service can continue this trace
        # instead of rooting a new one. Adds `traceparent` only (Cato sets no
        # baggage), so nothing but trace/span ids crosses the boundary. A
        # no-op when tracing is off or no span is active.
        from cato.core import phoenix_tracing as _phoenix_tracing

        _phoenix_tracing.inject_trace_context(headers)

        # Cold-start path budgets 60s total even though config asks for 30s;
        # subsequent calls use config.genesis_timeout_s.
        effective_timeout = 60.0 if is_cold else timeout_s
        client_timeout = aiohttp.ClientTimeout(total=effective_timeout)

        wire_request = self._wire_request(envelope, task, params)
        started = time.monotonic()
        deadline = started + effective_timeout
        try:
            session = await self._ensure_session()
            async with session.post(url, json=wire_request, headers=headers, timeout=client_timeout) as resp:
                body = await resp.text()
                elapsed = round(time.monotonic() - started, 3)

                if resp.status in (200, 202):
                    # HTTP 200 alone is not evidence of success. If the body
                    # carries a stub/scaffold marker, surface FAILURE to the
                    # caller -- a stub write action returning {"ok": true,
                    # "stub": true} must never be reported as a real success.
                    try:
                        raw_parsed: Any = json.loads(body)
                    except (json.JSONDecodeError, ValueError):
                        raw_parsed = None
                    raw_stub_reason = (
                        _detect_stub_response(raw_parsed)
                        if raw_parsed is not None and not isinstance(raw_parsed, dict)
                        else None
                    )
                    if raw_stub_reason is not None:
                        return json.dumps({
                            "ok": False,
                            "error": "stub_response",
                            "reason": raw_stub_reason,
                            "agent": agent,
                            "response": body,
                            "elapsed_s": elapsed,
                        })

                    parsed_body = _parse_json_object(raw_parsed)
                    if parsed_body is None:
                        return json.dumps({
                            "ok": False,
                            "error": "invalid_upstream_response",
                            "agent": agent,
                            "elapsed_s": elapsed,
                        })

                    status = str(parsed_body.get("status") or "").upper()
                    job_id = parsed_body.get("job_id") or parsed_body.get("id")
                    if resp.status == 202 or status in _QUEUED_JOB_STATES:
                        poll_url = parsed_body.get("poll_url") or (
                            f"/agents/jobs/{job_id}" if job_id else ""
                        )
                        if not poll_url:
                            return json.dumps({
                                "ok": False,
                                "error": "queued_job_missing_poll_url",
                                "outcome_unknown": True,
                                "agent": agent,
                            })
                        principal_token = _valid_principal_token(
                            parsed_body.get("principal_token")
                        )
                        if principal_token is None:
                            return json.dumps({
                                "ok": False,
                                "error": "invalid_principal_token",
                                "outcome_unknown": True,
                                "agent": agent,
                                "reason": (
                                    "Queued Genesis response did not provide a valid "
                                    "owner-scoped principal token"
                                ),
                            })
                        return await self._poll_job(
                            endpoint=endpoint,
                            poll_url=str(poll_url),
                            principal_token=principal_token,
                            agent=agent,
                            deadline=deadline,
                            started=started,
                        )

                    return self._terminal_result(parsed_body, agent=agent, elapsed=elapsed)

                # --- branch 6: upstream non-200
                truncated = body if len(body) <= _UPSTREAM_BODY_TRUNCATE else body[:_UPSTREAM_BODY_TRUNCATE]
                return json.dumps({
                    "ok": False,
                    "error": "upstream_error",
                    "agent": agent,
                    "status": resp.status,
                    "body": truncated,
                })

        except asyncio.TimeoutError:
            # The request was written to the wire and no answer came back, so
            # the remote MAY have completed the work. "failed" would be a
            # claim we cannot support; mark the outcome unknown so the ledger
            # records INDETERMINATE and a human reconciles before any retry.
            return json.dumps({
                "ok": False,
                "error": "timeout",
                "outcome_unknown": True,
                "agent": agent,
                "timeout_s": effective_timeout,
            })
        except Exception as exc:  # noqa: BLE001 — catch-all for connection / DNS / SSL / etc.
            return json.dumps({
                "ok": False,
                "error": "exception",
                "outcome_unknown": _is_indeterminate_transport_error(exc),
                "agent": agent,
                "type": type(exc).__name__,
                "message": str(exc),
            })


# ---------------------------------------------------------------------------
# Task 1 — live deploy probe + doctor
#
# The hardcoded "status": "deployed" on GENESIS_AGENTS entries is registry
# metadata, not proof anything is reachable right now. probe_live_agents()
# actually asks the gateway; build_doctor_report() combines that live truth
# with the LOCAL allowlist config so an operator can see "allowlisted" vs
# "live on gateway" vs "both" (only "both" is actually callable) instead of
# trusting either signal alone.
# ---------------------------------------------------------------------------

def _extract_agent_slugs(parsed: Any) -> list[str] | None:
    """Best-effort extraction of agent slugs from a GET /agents response.

    Handles the response shapes actually seen from the gateway (a bare list
    of slug strings, a list of {"slug": ...} objects, or an object with an
    "agents" key wrapping either of those). Returns None if the shape is not
    recognized -- callers must treat that as an inconclusive probe, not an
    empty listing.
    """
    candidate = parsed
    if isinstance(candidate, dict):
        candidate = candidate.get("agents", candidate.get("data", candidate))
    if not isinstance(candidate, list):
        return None
    slugs: list[str] = []
    for item in candidate:
        if isinstance(item, str):
            slugs.append(item)
        elif isinstance(item, dict):
            slug = item.get("slug") or item.get("name") or item.get("id")
            if isinstance(slug, str):
                slugs.append(slug)
    return slugs


async def probe_live_agents(
    endpoint: str, *, timeout_s: float = 10.0, session: Any = None,
) -> dict[str, Any]:
    """GET {endpoint}/agents and report which slugs the gateway actually
    lists right now. Never raises -- every failure mode returns
    ``{"ok": False, ...}`` so callers (the doctor command) can report a
    truthful "gateway unreachable" state rather than crashing or, worse,
    silently treating an unreachable gateway as an empty-but-valid listing.
    """
    url = f"{endpoint.rstrip('/')}/agents"
    owns_session = session is None
    if owns_session:
        resolver = aiohttp.ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=resolver, family=0, ssl=True, limit=10)
        session = aiohttp.ClientSession(connector=connector)
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with session.get(url, timeout=timeout) as resp:
            body = await resp.text()
            if resp.status != 200:
                return {
                    "ok": False, "error": "upstream_error",
                    "status": resp.status, "body": body[:_UPSTREAM_BODY_TRUNCATE],
                }
            try:
                parsed = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                return {"ok": False, "error": "invalid_response"}
            slugs = _extract_agent_slugs(parsed)
            if slugs is None:
                return {"ok": False, "error": "unrecognized_response_shape"}
            return {"ok": True, "slugs": slugs}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "timeout", "outcome_unknown": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "exception", "type": type(exc).__name__, "message": str(exc)}
    finally:
        if owns_session:
            await session.close()


def build_doctor_report(config: Any, live_result: dict[str, Any]) -> dict[str, Any]:
    """Pure function: combine the LOCAL allowlist with a live gateway probe
    result into one truthful report.

    Separates three states per e4l slug: allowlisted (local config only),
    live_on_gateway (remote probe only), and callable (both — the only state
    in which GenesisTool.execute() would actually dispatch it). Exits the
    caller should treat as failure (see cli.py's ``genesis doctor``) whenever
    the allowlist is empty, the gateway could not be reached, OR any of the
    14 e4l slugs is missing from the live listing.
    """
    allowlist = list(getattr(config, "genesis_agent_allowlist", None) or [])
    canonical_allowlist = {_canonicalize_agent_slug(s) for s in allowlist}
    allowlist_empty = len(canonical_allowlist) == 0

    target_slugs = sorted(FAIL_CLOSED_ACCOUNTING_ALLOWLIST)
    gateway_reachable = bool(live_result.get("ok"))
    live_slugs_raw = live_result.get("slugs") or []
    canonical_live = {_canonicalize_agent_slug(s) for s in live_slugs_raw}

    rows: list[dict[str, Any]] = []
    for slug in target_slugs:
        canon = _canonicalize_agent_slug(slug)
        allowlisted = canon in canonical_allowlist
        live_on_gateway = gateway_reachable and canon in canonical_live
        rows.append({
            "slug": slug,
            "allowlisted": allowlisted,
            "live_on_gateway": live_on_gateway,
            "callable": allowlisted and live_on_gateway,
        })

    missing_from_gateway = (
        [r["slug"] for r in rows if not r["live_on_gateway"]] if gateway_reachable else list(target_slugs)
    )
    scope_map_ok = False
    scope_map_version = None
    try:
        from cato.xero_scope import SCOPE_MAP_PATH, scope_map_version as _smv

        scope_map_ok = SCOPE_MAP_PATH.is_file()
        scope_map_version = _smv()
    except Exception:
        scope_map_ok = False

    healthy = (
        gateway_reachable
        and not allowlist_empty
        and not missing_from_gateway
        and scope_map_ok
    )

    return {
        "allowlist_empty": allowlist_empty,
        "gateway_reachable": gateway_reachable,
        "gateway_error": None if gateway_reachable else live_result,
        "scope_map_loaded": scope_map_ok,
        "scope_map_version": scope_map_version,
        "rows": rows,
        "missing_from_gateway": missing_from_gateway,
        "callable_count": sum(1 for r in rows if r["callable"]),
        "healthy": healthy,
    }


# ---------------------------------------------------------------------------
# Introspection helper
# ---------------------------------------------------------------------------

def list_agents(include_pending: bool = False) -> list[dict[str, Any]]:
    """Return the active agent registry as a list (CLI / introspection).

    Pending agents are excluded by default so callers only see agents that
    are actually reachable on SwarmSync. Pass ``include_pending=True`` to
    get the full 34-agent registry (e.g. for admin tooling).
    """
    result = []
    for slug, meta in GENESIS_AGENTS.items():
        if not include_pending and meta.get("status") == "pending":
            _logger.debug("list_agents: skipping pending agent %r", slug)
            continue
        result.append({"slug": slug, **meta})
    return result


# ---------------------------------------------------------------------------
# Tool schema (consumed by task-03 when wiring into the registry)
# ---------------------------------------------------------------------------

# OpenAI function-calling format — matches sibling entries in
# cato.agent_loop._BUILTIN_SCHEMAS so _sanitize_tool_defs (which reads
# ``d["function"]["name"]``) can normalize this schema uniformly with the
# rest of the tool registry. Anthropic-style ``{"name", "input_schema"}``
# at the top level breaks _sanitize_tool_defs with KeyError: 'function'.
GENESIS_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "genesis",
        "description": (
            "Call a hosted Genesis Agent on SwarmSync. The agent slug must be in "
            "GENESIS_AGENTS. E4L books use the 14 genesis-e4l-* specialists "
            "(revenue, shopify, stripe, cash, ap, ar, cogs-cm, commissions, "
            "intercompany, close, journals, fs-integrity, controller, treasury). "
            "Never genesis-finance/billing/commerce/pricing and never "
            "genesis-e4l-accounting. Returns the agent's response. "
            "Agents not cleared for dispatch return a 'pending_deployment' error."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Agent slug, e.g. 'genesis-research'."},
                "task": {"type": "string", "description": "Plain-text task for the agent to perform."},
                "params": {"type": "object", "description": "Optional structured parameters.", "additionalProperties": True},
            },
            "required": ["agent", "task"],
            "additionalProperties": False,
        },
    },
}


__all__ = [
    "GENESIS_AGENTS",
    "GENESIS_TOOL_SCHEMA",
    "AP2_ENVELOPE_VERSION",
    "MONEY_DOMAIN_AGENTS",
    "IMMUTABLE_DENIED_AGENTS",
    "FAIL_CLOSED_ACCOUNTING_ALLOWLIST",
    "GenesisTool",
    "build_envelope",
    "list_agents",
    "probe_live_agents",
    "build_doctor_report",
]
