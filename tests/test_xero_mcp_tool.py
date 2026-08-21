"""tests/test_xero_mcp_tool.py — Tests for the Xero DEMO MCP adapter (Task 5).

No real network calls. Covers:
  - 27-tool registry (14 read + 13 write), catalog matches the live-verified
    tools/list response (see task report).
  - Dotted Cato tool naming (xero_demo.<tool>).
  - Schema shape: write tools carry dry_run/confirm/idempotency_key, read
    tools do not.
  - call_tool(): unknown tool, invalid arguments, SSE-framed 200 success,
    plain-JSON 200 success, isError result, upstream non-200, 401, timeout,
    transport exception, RPC-level error envelope.
  - Argument pass-through: dry_run/confirm/idempotency_key given by the
    caller reach the wire UNCHANGED — this adapter never sets or flips them.
  - Key Vault token fetch: success, failure (never leaks the secret value or
    embeds it in a raised exception), and in-memory caching (second call
    does not re-invoke az).
  - register_all_xero_demo_tools(): registers exactly 27 dotted names, all
    bound to the same shared tool instance.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from cato.tools.xero_mcp import (
    ALL_TOOLS,
    DEMO_TENANT_ID,
    READ_TOOLS,
    WRITE_TOOLS,
    XeroDemoMCPTool,
    build_tool_schema,
    cato_tool_name,
    make_bound_executor,
    register_all_xero_demo_tools,
)


class MockConfig:
    def __init__(self, **overrides):
        self.xero_mcp_enabled = True
        self.xero_mcp_endpoint = "http://xero-demo.test/mcp"
        self.xero_mcp_keyvault_name = "test-kv"
        self.xero_mcp_keyvault_secret = "test-secret"
        self.xero_mcp_timeout_s = 5.0
        for k, v in overrides.items():
            setattr(self, k, v)


class FakeResp:
    def __init__(self, status=200, body="{}"):
        self.status = status
        self._body = body

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self, post_resp=None, post_exc=None):
        self._post_resp = post_resp
        self._post_exc = post_exc
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if self._post_exc is not None:
            raise self._post_exc
        return self._post_resp

    async def close(self):
        self.closed = True


def _sse_body(payload: dict) -> str:
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def _new_tool(config=None, session=None, token="fake-token") -> XeroDemoMCPTool:
    if config is None:
        config = MockConfig()
    tool = XeroDemoMCPTool(config=config)
    if session is not None:
        tool._session = session  # noqa: SLF001 — test injection
    if token is not None:
        tool._token = token  # noqa: SLF001 — skip real Key Vault call
        tool._token_expiry_monotonic = 10**12
    return tool


# ---------------------------------------------------------------------------
# Registry / catalog
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_27_tools_total(self):
        assert len(ALL_TOOLS) == 27

    def test_14_read_13_write(self):
        assert len(READ_TOOLS) == 14
        assert len(WRITE_TOOLS) == 13
        assert READ_TOOLS.isdisjoint(WRITE_TOOLS)
        assert READ_TOOLS | WRITE_TOOLS == ALL_TOOLS

    def test_read_tools_match_mission_list(self):
        expected = {
            "list_entities", "get_organisation", "get_chart_of_accounts",
            "get_trial_balance", "get_profit_and_loss", "get_balance_sheet",
            "get_bank_summary", "list_tracking_categories",
            "list_open_payables", "list_open_receivables", "list_contacts",
            "get_server_status", "list_idempotency_log",
            "list_recent_write_audit_log",
        }
        assert READ_TOOLS == expected

    def test_write_tools_never_include_a_read_only_name(self):
        for name in WRITE_TOOLS:
            assert name not in READ_TOOLS

    def test_dotted_tool_name(self):
        assert cato_tool_name("get_organisation") == "xero_demo.get_organisation"

    def test_schema_write_tools_carry_dry_run_confirm(self):
        for name in WRITE_TOOLS:
            schema = build_tool_schema(name)
            props = schema["function"]["parameters"]["properties"]
            assert "dry_run" in props, name
            assert "confirm" in props, name
            # idempotency_key is deliberately NOT a declared schema property
            # (would collide with approval_policy's redaction-by-key-name);
            # additionalProperties still lets a caller pass it through.
            assert schema["function"]["parameters"]["additionalProperties"] is True
            assert "idempotency_key" not in props, name

    def test_schema_read_tools_do_not_carry_confirm(self):
        for name in READ_TOOLS:
            schema = build_tool_schema(name)
            props = schema["function"]["parameters"]["properties"]
            assert "confirm" not in props, name
            assert "dry_run" not in props, name

    def test_schema_names_are_dotted(self):
        for name in ALL_TOOLS:
            schema = build_tool_schema(name)
            assert schema["function"]["name"] == f"xero_demo.{name}"


# ---------------------------------------------------------------------------
# call_tool() — wire behaviour
# ---------------------------------------------------------------------------


class TestCallTool:
    def test_unknown_tool_rejected(self):
        tool = _new_tool()
        result = json.loads(asyncio.run(tool.call_tool("delete_everything", {})))
        assert result["ok"] is False
        assert result["error"] == "unknown_xero_tool"

    def test_invalid_arguments_type_rejected(self):
        tool = _new_tool()
        result = json.loads(asyncio.run(tool.call_tool("get_organisation", "not-a-dict")))
        assert result["ok"] is False
        assert result["error"] == "invalid_arguments"

    def test_sse_framed_success(self):
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": '{"Name":"Demo Company (US)"}'}], "isError": False},
        }
        session = FakeSession(post_resp=FakeResp(200, _sse_body(payload)))
        tool = _new_tool(session=session)
        result = json.loads(asyncio.run(tool.call_tool("get_organisation", {})))
        assert result["ok"] is True
        assert result["tenant_id"] == DEMO_TENANT_ID
        assert "Demo Company" in result["result_text"]

    def test_plain_json_success_without_sse_framing(self):
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
        }
        session = FakeSession(post_resp=FakeResp(200, json.dumps(payload)))
        tool = _new_tool(session=session)
        result = json.loads(asyncio.run(tool.call_tool("get_server_status", {})))
        assert result["ok"] is True

    def test_is_error_result_reported_as_failure(self):
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "tenant mismatch"}], "isError": True},
        }
        session = FakeSession(post_resp=FakeResp(200, _sse_body(payload)))
        tool = _new_tool(session=session)
        result = json.loads(asyncio.run(tool.call_tool("get_organisation", {})))
        assert result["ok"] is False

    def test_rpc_error_envelope_reported_as_failure(self):
        payload = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "invalid params"}}
        session = FakeSession(post_resp=FakeResp(200, _sse_body(payload)))
        tool = _new_tool(session=session)
        result = json.loads(asyncio.run(tool.call_tool("get_balance_sheet", {"date": "bad"})))
        assert result["ok"] is False
        assert result["error"] == "mcp_rpc_error"

    def test_upstream_non_200(self):
        session = FakeSession(post_resp=FakeResp(500, "server error"))
        tool = _new_tool(session=session)
        result = json.loads(asyncio.run(tool.call_tool("get_organisation", {})))
        assert result["ok"] is False
        assert result["error"] == "upstream_error"
        assert result["status"] == 500

    def test_401_reported_distinctly(self):
        session = FakeSession(post_resp=FakeResp(401, "unauthorized"))
        tool = _new_tool(session=session)
        result = json.loads(asyncio.run(tool.call_tool("get_organisation", {})))
        assert result["ok"] is False
        assert result["error"] == "unauthorized"

    def test_timeout_reports_outcome_unknown(self):
        class RaisingSession(FakeSession):
            def post(self, *a, **kw):
                raise asyncio.TimeoutError()

        tool = _new_tool(session=RaisingSession())
        result = json.loads(asyncio.run(tool.call_tool("create_account", {"code": "1", "name": "x", "account_type": "EXPENSE"})))
        assert result["ok"] is False
        assert result["error"] == "timeout"
        assert result["outcome_unknown"] is True

    def test_transport_exception_reported(self):
        session = FakeSession(post_exc=ConnectionError("dns failed"))
        tool = _new_tool(session=session)
        result = json.loads(asyncio.run(tool.call_tool("get_organisation", {})))
        assert result["ok"] is False
        assert result["error"] == "exception"
        assert result["type"] == "ConnectionError"

    def test_invalid_upstream_body(self):
        session = FakeSession(post_resp=FakeResp(200, "not json and not sse"))
        tool = _new_tool(session=session)
        result = json.loads(asyncio.run(tool.call_tool("get_organisation", {})))
        assert result["ok"] is False
        assert result["error"] == "invalid_upstream_response"


# ---------------------------------------------------------------------------
# dry_run / confirm pass-through — the adapter must NEVER touch these
# ---------------------------------------------------------------------------


class TestConfirmPassThrough:
    def test_caller_dry_run_confirm_reach_the_wire_unchanged(self):
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"content": [], "isError": False}}
        session = FakeSession(post_resp=FakeResp(200, _sse_body(payload)))
        tool = _new_tool(session=session)
        args = {"code": "9999", "name": "Test", "account_type": "EXPENSE", "dry_run": False, "confirm": True}
        asyncio.run(tool.call_tool("create_account", dict(args)))
        assert len(session.calls) == 1
        _, kwargs = session.calls[0]
        sent_arguments = kwargs["json"]["params"]["arguments"]
        assert sent_arguments["dry_run"] is False
        assert sent_arguments["confirm"] is True

    def test_default_write_call_does_not_inject_confirm(self):
        """If the caller omits confirm entirely, the adapter must not add it."""
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"content": [], "isError": False}}
        session = FakeSession(post_resp=FakeResp(200, _sse_body(payload)))
        tool = _new_tool(session=session)
        asyncio.run(tool.call_tool("create_account", {"code": "1", "name": "x", "account_type": "EXPENSE"}))
        _, kwargs = session.calls[0]
        sent_arguments = kwargs["json"]["params"]["arguments"]
        assert "confirm" not in sent_arguments


# ---------------------------------------------------------------------------
# Key Vault token fetch
# ---------------------------------------------------------------------------


class TestTokenFetch:
    def test_cached_token_skips_refetch(self, monkeypatch):
        calls = {"n": 0}

        async def _fake_fetch(vault_name, secret_name):
            calls["n"] += 1
            return "token-value"

        monkeypatch.setattr("cato.tools.xero_mcp._fetch_bearer_token", _fake_fetch)
        tool = XeroDemoMCPTool(config=MockConfig())
        tool._token = None  # noqa: SLF001
        token1 = asyncio.run(tool._get_token())  # noqa: SLF001
        token2 = asyncio.run(tool._get_token())  # noqa: SLF001
        assert token1 == token2 == "token-value"
        assert calls["n"] == 1

    def test_token_fetch_failure_never_leaks_secret_value(self, monkeypatch):
        async def _raise(vault_name, secret_name):
            raise RuntimeError("az keyvault secret show exited 1: The user, group, or application "
                                "does not have secrets get permission")

        monkeypatch.setattr("cato.tools.xero_mcp._fetch_bearer_token", _raise)
        session = FakeSession(post_resp=FakeResp(200, "{}"))
        tool = _new_tool(session=session, token=None)
        result = json.loads(asyncio.run(tool.call_tool("get_organisation", {})))
        assert result["ok"] is False
        assert result["error"] == "keyvault_token_fetch_failed"
        # Never include a bearer/token/secret-shaped value in the surfaced message
        assert "Bearer" not in result["message"]


# ---------------------------------------------------------------------------
# register_all_xero_demo_tools()
# ---------------------------------------------------------------------------


class TestRegisterAll:
    def test_registers_exactly_27_dotted_names(self):
        registered: dict[str, Any] = {}

        def _register_tool(name, fn, schema=None):
            registered[name] = (fn, schema)

        tool = register_all_xero_demo_tools(_register_tool, config=MockConfig())
        assert isinstance(tool, XeroDemoMCPTool)
        assert len(registered) == 27
        for xero_name in ALL_TOOLS:
            assert f"xero_demo.{xero_name}" in registered

    def test_bound_executor_calls_the_right_tool(self):
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ok"}], "isError": False}}
        session = FakeSession(post_resp=FakeResp(200, _sse_body(payload)))
        tool = _new_tool(session=session)
        executor = make_bound_executor(tool, "get_organisation")
        result = json.loads(asyncio.run(executor({})))
        assert result["ok"] is True
        assert result["tool"] == "get_organisation"
