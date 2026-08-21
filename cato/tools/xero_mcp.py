"""cato/tools/xero_mcp.py — Streamable-HTTP MCP client adapter for the
tenant-locked Xero DEMO server.

Task 5 of E4L_CATO_GENESIS_EXECUTION_PLAN.md. Cato hosts the Xero MCP client
directly (architecture decision already made — see
``Xero DEMO COMPANY/CATO_GENESIS_DEMO_BUILD_CHECKPOINT.md``), pointed at the
already-built, already-tested, tenant-locked DEMO Xero MCP server:

    https://xero-mcp-demo.orangedune-dad71fcc.westus2.azurecontainerapps.io/mcp

That server is hard-locked to demo tenant
``c00a07d6-2681-45f9-a278-bacb418ff6c1`` ("Demo Company (US)") at BOTH the
credential level (its OAuth grant can physically reach no other tenant) and
the code level (rejects any other tenant ID even if asked). This module is
completely separate from, and must never default to, the LIVE E4L Xero MCP
server at ``E4L-FinanceOS/app/mcp-servers/xero/server.py``.

Design constraints (do not weaken these without a documented decision):

  * The bearer token is loaded from Azure Key Vault (``fin-financeos-kv`` /
    secret ``xero-mcp-bearer-demo``) at runtime via the ``az`` CLI. It is
    never hardcoded, never logged, never written to disk, and never included
    in any tool result. Only ``type(exc).__name__`` and Azure CLI's own
    stderr text (which never contains the secret value) are surfaced on
    failure.
  * ``dry_run`` and ``confirm`` are the CALLER's parameters, forwarded
    verbatim to the MCP server. This adapter never sets, flips, or defaults
    ``confirm=True`` on behalf of a caller — that stays a human-gated,
    per-call decision same as every other irreversible action in Cato (see
    ``cato/auth/token_checker.py``).
  * Every one of the 27 tools the demo server exposes is registered as its
    own dotted Cato tool name (``xero_demo.<tool>``), mirroring the existing
    ``web.search`` / ``conduit.crawl`` / ``github.issue_list`` convention.
    This is deliberate: Cato's per-call approval gate
    (``cato.auth.token_checker.TokenChecker``) authorizes by top-level tool
    name, so giving every underlying Xero operation its own Cato tool name is
    what lets the 14 read tools be auto-approved while the 13 write tools
    stay individually human-gated — a single generic ``xero_demo(tool=...)``
    tool would collapse that distinction into "all or nothing" for the whole
    Xero surface, which is not the contract this server was built for.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from typing import Any, Callable

import aiohttp

from cato.config import CatoConfig

_logger = logging.getLogger("cato.tools.xero_mcp")

# ---------------------------------------------------------------------------
# Server identity (for evidence/labeling only — never used to bypass the
# server's own tenant lock, which is enforced server-side, not here).
# ---------------------------------------------------------------------------
DEMO_TENANT_ID = "c00a07d6-2681-45f9-a278-bacb418ff6c1"
DEMO_ORG_NAME = "Demo Company (US)"

DEFAULT_ENDPOINT = "https://xero-mcp-demo.orangedune-dad71fcc.westus2.azurecontainerapps.io/mcp"
DEFAULT_KEYVAULT_NAME = "fin-financeos-kv"
DEFAULT_KEYVAULT_SECRET = "xero-mcp-bearer-demo"
DEFAULT_TIMEOUT_S = 30.0
_TOKEN_CACHE_TTL_S = 1800.0  # 30 min in-memory only; never persisted to disk

# ---------------------------------------------------------------------------
# The 27-tool catalog, live-verified against the demo server's `tools/list`
# response on 2026-08-21 (see task report). Read tools have no dry_run/
# confirm gate server-side (GET only). Write tools all default to
# dry_run=True, confirm=False server-side; this adapter does not change that.
# ---------------------------------------------------------------------------
READ_TOOLS: frozenset[str] = frozenset({
    "list_entities",
    "get_server_status",
    "get_organisation",
    "get_chart_of_accounts",
    "get_profit_and_loss",
    "get_balance_sheet",
    "get_trial_balance",
    "get_bank_summary",
    "list_open_receivables",
    "list_open_payables",
    "list_tracking_categories",
    "list_contacts",
    "list_recent_write_audit_log",
    "list_idempotency_log",
})

WRITE_TOOLS: frozenset[str] = frozenset({
    "create_draft_bill",
    "create_draft_invoice",
    "create_draft_manual_journal",
    "create_tracking_category",
    "create_tracking_option",
    "update_tracking_category",
    "create_account",
    "create_contact",
    "approve_invoice",
    "approve_bill",
    "post_manual_journal",
    "void_transaction",
    "reverse_manual_journal",
})

ALL_TOOLS: frozenset[str] = READ_TOOLS | WRITE_TOOLS
assert len(ALL_TOOLS) == 27, f"expected 27 demo MCP tools, registry has {len(ALL_TOOLS)}"

_WRITE_COMMON_PROPS: dict[str, Any] = {
    "dry_run": {"type": "boolean", "description": "Preview only, no Xero call. Server default True."},
    "confirm": {"type": "boolean", "description": "Must be explicitly True (together with dry_run=False) for a real write. Never set automatically by Cato."},
    # Intentionally NOT declared here even though the server accepts it
    # (auto-generated server-side if omitted): a schema property literally
    # named "...key" trips cato.core.approval_policy.is_sensitive_key's
    # generic "key" substring match and gets masked wherever tool args are
    # logged/audited, which would silently hide a non-secret dedup token
    # from the audit trail this server's idempotency contract depends on
    # (see tests/test_approval_policy_engine.py::
    # test_no_real_tool_argument_name_collides_with_redaction). A caller
    # that wants to pin a specific key can still pass ``idempotency_key``
    # through ``additionalProperties: True`` below; it reaches the wire
    # unchanged either way (call_tool() forwards ``arguments`` verbatim).
}

# name -> (description, extra properties beyond the write-common ones, required)
_TOOL_SPECS: dict[str, tuple[str, dict[str, Any], list[str]]] = {
    "list_entities": ("List the single entity this server can reach (the demo org).", {}, []),
    "get_server_status": ("Read-only, no network call. Local write-scope status, denylist size, idempotency/audit store sizes.", {}, []),
    "get_organisation": ("Get Xero organisation details for the demo org (read-only).", {}, []),
    "get_chart_of_accounts": ("Get the demo org's chart of accounts (read-only).", {}, []),
    "get_profit_and_loss": ("Get the demo org's Profit & Loss report (read-only).", {
        "from_date": {"type": "string", "description": "ISO YYYY-MM-DD"},
        "to_date": {"type": "string", "description": "ISO YYYY-MM-DD"},
    }, ["from_date", "to_date"]),
    "get_balance_sheet": ("Get the demo org's Balance Sheet as at an ISO date (read-only).", {
        "date": {"type": "string", "description": "ISO YYYY-MM-DD"},
    }, ["date"]),
    "get_trial_balance": ("Get the demo org's Trial Balance as at an ISO date (read-only).", {
        "date": {"type": "string", "description": "ISO YYYY-MM-DD"},
    }, ["date"]),
    "get_bank_summary": ("Get the demo org's Bank Summary report (read-only).", {
        "from_date": {"type": "string", "description": "ISO YYYY-MM-DD"},
        "to_date": {"type": "string", "description": "ISO YYYY-MM-DD"},
    }, ["from_date", "to_date"]),
    "list_open_receivables": ("List open (authorised, unpaid) AR invoices (read-only).", {}, []),
    "list_open_payables": ("List open (authorised, unpaid) AP bills (read-only).", {}, []),
    "list_tracking_categories": ("List tracking categories in the demo org (read-only).", {}, []),
    "list_contacts": ("List contacts in the demo org (read-only).", {}, []),
    "list_recent_write_audit_log": ("Read-only. Most recent write-tool audit entries, actor-attributed, secrets redacted.", {
        "limit": {"type": "integer", "description": "Default 20."},
    }, []),
    "list_idempotency_log": ("Read-only. Most recent idempotency-key records.", {
        "limit": {"type": "integer", "description": "Default 20."},
    }, []),
    "create_draft_bill": ("DRAFT-tier write, reversible with void_transaction. contact_name must exactly match an existing contact.", {
        "contact_name": {"type": "string"},
        "line_items": {"type": "array", "items": {"type": "object"}, "description": "[{description, quantity, unit_amount, account_code, tracking?}]"},
        "date": {"type": "string"},
        "due_date": {"type": "string"},
        "reference": {"type": "string"},
    }, ["contact_name", "line_items", "date"]),
    "create_draft_invoice": ("DRAFT-tier write, reversible with void_transaction. Same contract as create_draft_bill.", {
        "contact_name": {"type": "string"},
        "line_items": {"type": "array", "items": {"type": "object"}},
        "date": {"type": "string"},
        "due_date": {"type": "string"},
        "reference": {"type": "string"},
    }, ["contact_name", "line_items", "date"]),
    "create_draft_manual_journal": ("DRAFT-tier write, reversible with reverse_manual_journal after posting.", {
        "narration": {"type": "string"},
        "journal_lines": {"type": "array", "items": {"type": "object"}, "description": "[{account_code, line_amount, description}], signed amounts summing to 0"},
        "date": {"type": "string"},
    }, ["narration", "journal_lines", "date"]),
    "create_tracking_category": ("IMMEDIATELY LIVE once confirmed — no draft state for tracking categories.", {
        "name": {"type": "string"},
    }, ["name"]),
    "create_tracking_option": ("Adds an Option to an existing Tracking Category. IMMEDIATELY LIVE once confirmed.", {
        "category_name": {"type": "string"},
        "option_name": {"type": "string"},
    }, ["category_name", "option_name"]),
    "update_tracking_category": ("Renames an existing Tracking Category. IMMEDIATELY LIVE once confirmed.", {
        "category_name": {"type": "string"},
        "new_name": {"type": "string"},
    }, ["category_name", "new_name"]),
    "create_account": ("Creates a Chart of Accounts entry. IMMEDIATELY LIVE once confirmed; no reversal tool (archive manually).", {
        "code": {"type": "string"},
        "name": {"type": "string"},
        "account_type": {"type": "string", "description": "Xero AccountType enum, e.g. EXPENSE, REVENUE, CURRENT, CURRLIAB."},
        "tax_type": {"type": "string"},
        "description": {"type": "string"},
    }, ["code", "name", "account_type"]),
    "create_contact": ("Creates a contact. Refuses if a contact with this exact name already exists. IMMEDIATELY LIVE once confirmed.", {
        "name": {"type": "string"},
        "email": {"type": "string"},
    }, ["name"]),
    "approve_invoice": ("Approves (AUTHORISES) an ACCREC invoice in DRAFT/SUBMITTED. Reversible with void_transaction.", {
        "invoice_id": {"type": "string"},
    }, ["invoice_id"]),
    "approve_bill": ("Approves (AUTHORISES) an ACCPAY bill in DRAFT/SUBMITTED. Reversible with void_transaction.", {
        "invoice_id": {"type": "string"},
    }, ["invoice_id"]),
    "post_manual_journal": ("Posts a manual journal currently in DRAFT status. Reversible with reverse_manual_journal.", {
        "manual_journal_id": {"type": "string"},
    }, ["manual_journal_id"]),
    "void_transaction": ("Rollback tool for invoices/bills. DRAFT/SUBMITTED -> DELETED; AUTHORISED -> VOIDED. Refuses on PAID.", {
        "invoice_id": {"type": "string"},
    }, ["invoice_id"]),
    "reverse_manual_journal": ("Rollback tool for POSTED manual journals — creates a new POSTED journal with every line negated.", {
        "manual_journal_id": {"type": "string"},
        "narration": {"type": "string"},
    }, ["manual_journal_id"]),
}
assert set(_TOOL_SPECS.keys()) == ALL_TOOLS, "tool spec table drifted from ALL_TOOLS registry"


def cato_tool_name(xero_tool: str) -> str:
    """Cato-side dotted tool name for one underlying Xero demo MCP tool."""
    return f"xero_demo.{xero_tool}"


def build_tool_schema(xero_tool: str) -> dict[str, Any]:
    """OpenAI function-calling schema for one demo MCP tool (mirrors
    GENESIS_TOOL_SCHEMA's format in cato/tools/genesis.py)."""
    description, extra_props, required = _TOOL_SPECS[xero_tool]
    properties = dict(extra_props)
    if xero_tool in WRITE_TOOLS:
        properties.update(_WRITE_COMMON_PROPS)
        description = (
            f"{description} dry_run defaults True and confirm defaults False on the "
            "server; you must pass both dry_run=False and confirm=True explicitly to "
            "make a real change. Tenant is hard-locked server-side to the DEMO org "
            f"({DEMO_ORG_NAME}, {DEMO_TENANT_ID}) — this tool can never reach a live "
            "E4L entity."
        )
    return {
        "type": "function",
        "function": {
            "name": cato_tool_name(xero_tool),
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": True,
            },
        },
    }


# ---------------------------------------------------------------------------
# Key Vault token fetch — never logs, never persists, never returns the
# value in an exception message.
# ---------------------------------------------------------------------------

def _resolve_az_executable() -> str:
    """Resolve the real ``az`` executable path.

    On Windows the Azure CLI ships as ``az.cmd``, which
    ``asyncio.create_subprocess_exec`` cannot launch directly (it does not
    go through a shell, so ``.cmd``/``.bat`` resolution never happens and the
    bare name ``az`` raises ``FileNotFoundError``). ``shutil.which`` performs
    the same PATH + PATHEXT resolution the shell would and hands back a
    concrete, directly-executable path on every platform.
    """
    resolved = shutil.which("az")
    if not resolved:
        raise RuntimeError("az CLI not found on PATH")
    return resolved


async def _fetch_bearer_token(vault_name: str, secret_name: str) -> str:
    az_path = _resolve_az_executable()
    proc = await asyncio.create_subprocess_exec(
        az_path, "keyvault", "secret", "show",
        "--vault-name", vault_name,
        "--name", secret_name,
        "--query", "value",
        "-o", "tsv",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        # az CLI error text describes the failure (vault/permission/network);
        # it never contains the secret value itself.
        raise RuntimeError(
            f"az keyvault secret show exited {proc.returncode}: "
            f"{stderr.decode('utf-8', errors='replace').strip()[:300]}"
        )
    token = stdout.decode("utf-8", errors="replace").strip()
    if not token:
        raise RuntimeError("az keyvault secret show returned an empty value")
    return token


# ---------------------------------------------------------------------------
# MCP Streamable-HTTP wire helpers
# ---------------------------------------------------------------------------

def _parse_mcp_response_body(body: str) -> dict[str, Any] | None:
    """Parse a Streamable-HTTP MCP response body.

    The demo server answers with SSE framing (``event: message\\ndata:
    {...}``) even for a single synchronous reply. Falls back to plain JSON
    in case a future server/version answers with ``content-type:
    application/json`` directly (per the MCP spec, both are valid).
    """
    stripped = body.strip()
    if not stripped:
        return None
    for line in stripped.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            candidate = line[len("data:"):].strip()
            try:
                parsed = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_text_content(content: Any) -> str:
    """Join the text blocks of an MCP ``tools/call`` result's content list."""
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tool class
# ---------------------------------------------------------------------------

class XeroDemoMCPTool:
    """Generic Streamable-HTTP MCP client bound to the tenant-locked demo
    Xero server. One instance is shared across all 27 registered Cato tool
    names (see ``register_all_xero_demo_tools``)."""

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self._token: str | None = None
        self._token_expiry_monotonic: float = 0.0
        self._request_id = 0
        self._log = _logger

    def _get_config(self) -> CatoConfig:
        if self._config is None:
            self._config = CatoConfig.load()
        return self._config

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # ThreadedResolver (OS resolver via thread pool) instead of
            # aiohttp's default async resolver — same fix as
            # cato/tools/genesis.py._ensure_session, for the same reason:
            # on Windows the default resolver has been observed to raise
            # ClientConnectorDNSError intermittently for hosts the OS
            # resolver handles fine.
            resolver = aiohttp.ThreadedResolver()
            connector = aiohttp.TCPConnector(resolver=resolver, family=0, ssl=True, limit=10)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception as exc:  # noqa: BLE001
                self._log.warning("Error closing Xero demo MCP session: %s", exc)
        self._session = None

    async def _get_token(self, *, force_refresh: bool = False) -> str:
        now = time.monotonic()
        if not force_refresh and self._token and now < self._token_expiry_monotonic:
            return self._token
        config = self._get_config()
        vault_name = getattr(config, "xero_mcp_keyvault_name", DEFAULT_KEYVAULT_NAME)
        secret_name = getattr(config, "xero_mcp_keyvault_secret", DEFAULT_KEYVAULT_SECRET)
        token = await _fetch_bearer_token(vault_name, secret_name)
        self._token = token
        self._token_expiry_monotonic = now + _TOKEN_CACHE_TTL_S
        return token

    async def call_tool(self, xero_tool: str, arguments: dict[str, Any]) -> str:
        """Call one of the 27 demo MCP tools. Returns a JSON-encoded string.

        ``arguments`` (including ``dry_run``/``confirm``/``idempotency_key``
        for write tools) is forwarded to the server exactly as given — this
        method never adds, removes, or overrides any of those fields.
        """
        if xero_tool not in ALL_TOOLS:
            return json.dumps({
                "ok": False, "error": "unknown_xero_tool", "tool": xero_tool,
                "known": sorted(ALL_TOOLS),
            })
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return json.dumps({
                "ok": False, "error": "invalid_arguments", "tool": xero_tool,
                "reason": "arguments must be a JSON object",
            })

        config = self._get_config()
        endpoint = getattr(config, "xero_mcp_endpoint", DEFAULT_ENDPOINT)
        timeout_s = float(getattr(config, "xero_mcp_timeout_s", DEFAULT_TIMEOUT_S))

        try:
            token = await self._get_token()
        except Exception as exc:  # noqa: BLE001
            return json.dumps({
                "ok": False, "error": "keyvault_token_fetch_failed", "tool": xero_tool,
                "type": type(exc).__name__, "message": str(exc),
            })

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": xero_tool, "arguments": arguments},
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        client_timeout = aiohttp.ClientTimeout(total=timeout_s)
        started = time.monotonic()
        try:
            session = await self._ensure_session()
            async with session.post(endpoint, json=payload, headers=headers, timeout=client_timeout) as resp:
                body = await resp.text()
                elapsed = round(time.monotonic() - started, 3)

                if resp.status == 401:
                    return json.dumps({
                        "ok": False, "error": "unauthorized", "tool": xero_tool,
                        "status": resp.status, "elapsed_s": elapsed,
                    })
                if resp.status != 200:
                    return json.dumps({
                        "ok": False, "error": "upstream_error", "tool": xero_tool,
                        "status": resp.status, "body": body[:500], "elapsed_s": elapsed,
                    })

                parsed = _parse_mcp_response_body(body)
                if parsed is None:
                    return json.dumps({
                        "ok": False, "error": "invalid_upstream_response", "tool": xero_tool,
                        "elapsed_s": elapsed,
                    })

                rpc_error = parsed.get("error")
                if rpc_error:
                    return json.dumps({
                        "ok": False, "error": "mcp_rpc_error", "tool": xero_tool,
                        "detail": rpc_error, "elapsed_s": elapsed,
                    })

                result = parsed.get("result") or {}
                is_error = bool(result.get("isError"))
                text_out = _extract_text_content(result.get("content"))
                return json.dumps({
                    "ok": not is_error,
                    "tool": xero_tool,
                    "tenant_id": DEMO_TENANT_ID,
                    "result_text": text_out,
                    "elapsed_s": elapsed,
                })

        except asyncio.TimeoutError:
            return json.dumps({
                "ok": False, "error": "timeout", "tool": xero_tool,
                "outcome_unknown": True, "timeout_s": timeout_s,
            })
        except Exception as exc:  # noqa: BLE001
            return json.dumps({
                "ok": False, "error": "exception", "tool": xero_tool,
                "type": type(exc).__name__, "message": str(exc),
            })


def make_bound_executor(tool: XeroDemoMCPTool, xero_tool: str) -> Callable[[dict[str, Any]], Any]:
    """Return an async ``execute(args)`` closure bound to one Xero tool name,
    for registration under its own dotted Cato tool name."""

    async def _execute(args: dict[str, Any]) -> str:
        args = args if isinstance(args, dict) else {}
        return await tool.call_tool(xero_tool, dict(args))

    return _execute


def register_all_xero_demo_tools(register_tool: Callable[..., None], config: Any = None) -> XeroDemoMCPTool:
    """Register all 27 demo-MCP tools under their dotted ``xero_demo.*``
    names using the caller's ``register_tool(name, fn, schema)`` function
    (matches the signature of ``cato.agent_loop.register_tool``).

    Returns the shared ``XeroDemoMCPTool`` instance so callers can close its
    HTTP session on shutdown.
    """
    tool = XeroDemoMCPTool(config=config)
    for xero_tool in sorted(ALL_TOOLS):
        register_tool(
            cato_tool_name(xero_tool),
            make_bound_executor(tool, xero_tool),
            build_tool_schema(xero_tool),
        )
    return tool


__all__ = [
    "DEMO_TENANT_ID",
    "DEMO_ORG_NAME",
    "DEFAULT_ENDPOINT",
    "DEFAULT_KEYVAULT_NAME",
    "DEFAULT_KEYVAULT_SECRET",
    "READ_TOOLS",
    "WRITE_TOOLS",
    "ALL_TOOLS",
    "cato_tool_name",
    "build_tool_schema",
    "XeroDemoMCPTool",
    "make_bound_executor",
    "register_all_xero_demo_tools",
]
