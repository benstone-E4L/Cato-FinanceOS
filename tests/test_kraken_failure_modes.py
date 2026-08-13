"""
tests/test_kraken_failure_modes.py — proving tests for the Kraken FMEA fixes.

Every test in this file FAILS on the code as it stood before the matching fix.
Each references the finding id from the failure-mode audit so the link between
a defect, its fix and its proof stays legible.

Findings covered:
  K-01  Anthropic primary path rejects OpenAI-shaped `role: "tool"` messages
        (LIVE-PROVEN 400 invalid_request_error) — cato/model_policy.py
  K-02  ActionGuard construction failure silently deletes the gate — agent_loop
  K-03  Ledger hash-chain forks under concurrent writers — audit/ledger.py
  K-04  verify_chain performs DDL on the audit trail it verifies — audit/ledger
  K-05  Genesis job-poll credential posture (RESOLVED: least privilege
        upheld, my fix reverted; the contract gap is Genesis-side, still OPEN)
  K-06  Genesis polling has no backoff (retry storm)
  K-07  send_email live path reports ok:true for a send that never happens
  K-08  send_email draft_only coercion fails OPEN on null/0/[]
  K-09  Router circuit breaker state is written and never read
  K-10  Router fails over onto a partially-streamed answer
  K-11  MODEL_TRANSLATIONS and MODEL_REGISTRY disagree on every anthropic id
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# K-01 — Anthropic message-shape translation at the wire boundary
# ---------------------------------------------------------------------------

class TestAnthropicMessageShape:
    """LIVE-PROVEN: sending role="tool" to /v1/messages returns
    400 invalid_request_error 'messages: Unexpected role "tool"'.
    That killed every tool-using conversation on its SECOND turn."""

    def _payload(self, messages):
        from datetime import date

        from cato.model_policy import (
            ModelTier, Provider, RiskBand, RoutingDecision, TaskType,
            ThinkingMode, build_request_payload,
        )
        decision = RoutingDecision(
            model_id="claude-sonnet-5",
            tier=ModelTier.SONNET,
            rule_id="test",
            reason="test",
            effort="medium",
            thinking_mode=ThinkingMode.ADAPTIVE,
            thinking_budget_tokens=None,
            supports_interleaved_thinking=True,
            max_output_tokens=1024,
            input_tokens=10,
            projected_cost_usd=0.0,
            cost_ceiling_usd=1.0,
            risk_band=list(RiskBand)[0],
            task_type=TaskType.GENERAL_TOOL_USE,
            escalation_level=0,
            constraints_applied=(),
            decision_id="test",
            priced_on=date.today(),
            provider=Provider.ANTHROPIC,
        )
        return build_request_payload(decision, messages)

    def test_no_tool_role_reaches_the_anthropic_payload(self):
        """The exact conversation shape that produced the live 400."""
        messages = [
            {"role": "user", "content": "search memory"},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "toolu_01Cw791VZHL9jREnBH6VeYWD",
                "type": "function",
                "function": {"name": "memory__search", "arguments": "{}"},
            }]},
            {"role": "tool",
             "tool_call_id": "toolu_01Cw791VZHL9jREnBH6VeYWD",
             "content": "[]"},
        ]
        payload = self._payload(messages)
        roles = [m["role"] for m in payload["messages"]]
        assert "tool" not in roles, (
            "Anthropic /v1/messages has no 'tool' role — this is the live 400"
        )
        assert roles == ["user", "assistant", "user"]

    def test_tool_call_becomes_tool_use_block(self):
        messages = [
            {"role": "assistant", "content": "thinking", "tool_calls": [{
                "id": "tu_1", "type": "function",
                "function": {"name": "web__search", "arguments": '{"q": "x"}'},
            }]},
        ]
        blocks = self._payload(messages)["messages"][0]["content"]
        assert blocks[0] == {"type": "text", "text": "thinking"}
        assert blocks[1] == {
            "type": "tool_use", "id": "tu_1", "name": "web__search",
            "input": {"q": "x"},
        }

    def test_tool_result_carries_the_matching_tool_use_id(self):
        messages = [
            {"role": "tool", "tool_call_id": "tu_9", "content": "RESULT"},
        ]
        block = self._payload(messages)["messages"][0]["content"][0]
        assert block == {
            "type": "tool_result", "tool_use_id": "tu_9", "content": "RESULT",
        }

    def test_parallel_tool_results_merge_into_one_user_turn(self):
        """Anthropic requires every tool_result answering one assistant turn to
        live in the SAME following user message. Emitting one user message per
        result is a second, subtly different 400."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "a", "type": "function",
                 "function": {"name": "t1", "arguments": "{}"}},
                {"id": "b", "type": "function",
                 "function": {"name": "t2", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "a", "content": "A"},
            {"role": "tool", "tool_call_id": "b", "content": "B"},
        ]
        msgs = self._payload(messages)["messages"]
        assert len(msgs) == 2, f"expected assistant+user, got {[m['role'] for m in msgs]}"
        ids = [b["tool_use_id"] for b in msgs[1]["content"]]
        assert ids == ["a", "b"], "tool_result order must follow call order"

    def test_malformed_tool_arguments_do_not_raise(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "x", "type": "function",
                "function": {"name": "t", "arguments": "not json{{"},
            }]},
        ]
        block = self._payload(messages)["messages"][0]["content"][0]
        assert block["input"] == {}

    def test_translation_is_idempotent(self):
        """Messages already in Anthropic shape must survive untouched."""
        from cato.model_policy import to_anthropic_messages
        already = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "z", "name": "t", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "z", "content": "ok"},
            ]},
        ]
        assert to_anthropic_messages(already) == already
        assert to_anthropic_messages(to_anthropic_messages(already)) == already


# ---------------------------------------------------------------------------
# K-02 — ActionGuard must fail CLOSED when it could not be constructed
# ---------------------------------------------------------------------------

class _FakeLedgerDenial:
    def __init__(self):
        self.denials = []


class TestActionGuardFailsClosed:
    """The ledger already refuses when it is required and unavailable. The
    reversibility guard swallowed its construction error and left None, and
    `_check_action_guard` reads None as 'proceed' — so a broken import deleted
    the gate from every dispatch and left only a log line."""

    def _loop(self):
        from cato.agent_loop import AgentLoop
        loop = AgentLoop.__new__(AgentLoop)   # no I/O; we test one method
        loop._action_guard = None
        loop._autonomy_level = 0.5
        recorded = []
        loop._record_denial = lambda **kw: recorded.append(kw)
        return loop, recorded

    def test_unconstructable_guard_refuses_dispatch(self):
        loop, recorded = self._loop()
        loop._action_guard_unavailable = "ImportError: no module named action_guard"

        out = loop._check_action_guard("shell.exec", {"cmd": "rm -rf /"}, "s1")

        assert out is not None, "a gate with no verdict is not a licence to proceed"
        payload = json.loads(out)
        assert payload["guard_denied"] is True
        assert recorded and recorded[0]["gate"] == "action_guard"
        assert "guard_unavailable" in recorded[0]["reason"]

    def test_guard_legitimately_absent_still_proceeds(self):
        """Auditing turned off is an operator choice; a BROKEN guard is not."""
        loop, _ = self._loop()
        loop._action_guard_unavailable = None
        assert loop._check_action_guard("memory.search", {}, "s1") is None


# ---------------------------------------------------------------------------
# K-03 / K-04 — ledger integrity
# ---------------------------------------------------------------------------

class TestLedgerConcurrency:
    def test_concurrent_writers_do_not_fork_the_hash_chain(self, tmp_path):
        """Two AuditLedger instances on one cato.db is a real configuration —
        the daemon plus any `cato` CLI command, or the startup recovery scan
        racing a live daemon. The RLock only serialises writers inside ONE
        process, so both could read the same tail hash and both append,
        forking the chain and making verify_chain report TAMPERED against
        records nobody tampered with."""
        from cato.audit.ledger import LedgerMiddleware, verify_chain

        db = tmp_path / "cato.db"
        writers = [LedgerMiddleware(db_path=db) for _ in range(4)]
        errors: list[BaseException] = []
        barrier = threading.Barrier(len(writers))

        def hammer(ledger, tag):
            try:
                barrier.wait(timeout=30)
                for i in range(25):
                    ledger.append(
                        tool_name=f"tool.{tag}",
                        tool_input={"i": i},
                        tool_output={"ok": True},
                        agent_session_id=f"sess-{tag}",
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=hammer, args=(w, i))
            for i, w in enumerate(writers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
        for w in writers:
            w.close()

        assert not errors, f"ledger writes raised: {errors[:3]}"

        conn = sqlite3.connect(str(db))
        total = conn.execute("select count(*) from ledger_records").fetchone()[0]
        conn.close()
        assert total == 100, f"lost writes: {total}/100"

        ok, msg = verify_chain(db)
        assert ok, f"hash chain forked under concurrent writers: {msg}"


class TestVerifyChainIsReadOnly:
    def test_verify_chain_runs_no_ddl_on_a_v1_ledger(self, tmp_path):
        """Verification must never write to the artifact it verifies. The old
        implementation opened the ledger read-write and ran `_ensure_schema`
        (ALTER TABLE + CREATE UNIQUE INDEX) on a tamper-evident audit trail
        every single time someone asked whether it was intact — silently
        upgrading a v1 archive during what the operator was told was a
        read-only integrity check.

        A v1 ledger makes that visible: if any DDL runs, the v2 columns appear.
        """
        from cato.audit.ledger import (
            _GENESIS_PREV_HASH, _SCHEMA, _compute_record_hash, verify_chain,
        )

        db = tmp_path / "v1.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(_SCHEMA)          # v1 table ONLY — no v2 columns
        row = {
            "record_id": "r1", "prev_hash": _GENESIS_PREV_HASH,
            "timestamp": "2026-01-01T00:00:00Z", "agent_session_id": "s",
            "tool_name": "t", "tool_input_hash": "a", "tool_output_hash": "b",
            "reasoning_excerpt": "", "confidence_score": 0.0,
            "model_source": "claude", "reversibility": 0.5,
            "delegation_token_id": None,
        }
        row["record_hash"] = _compute_record_hash(row)
        cols = list(row)
        conn.execute(
            f"INSERT INTO ledger_records ({','.join(cols)}) "
            f"VALUES ({','.join('?' for _ in cols)})",
            tuple(row[c] for c in cols),
        )
        conn.commit()
        before = {r[1] for r in conn.execute("PRAGMA table_info(ledger_records)")}
        conn.close()
        assert "schema_version" not in before, "fixture is not a v1 ledger"

        ok, msg = verify_chain(db)
        assert ok, msg

        conn = sqlite3.connect(str(db))
        after = {r[1] for r in conn.execute("PRAGMA table_info(ledger_records)")}
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        conn.close()
        assert after == before, (
            f"verify_chain ran DDL on the ledger it verified: added {after - before}"
        )
        assert "idx_ledger_idem" not in indexes, (
            "verify_chain created a UNIQUE INDEX on an audit archive"
        )

    def test_verify_chain_works_on_a_read_only_copy(self, tmp_path):
        """Reviewing a ledger copied to read-only media is exactly when you
        most want verification to work."""
        import os
        import stat

        from cato.audit.ledger import LedgerMiddleware, verify_chain

        src = tmp_path / "cato.db"
        ledger = LedgerMiddleware(db_path=src)
        ledger.append(tool_name="t", tool_input={}, tool_output={},
                      agent_session_id="s")
        ledger.close()

        copy = tmp_path / "readonly.db"
        copy.write_bytes(src.read_bytes())
        os.chmod(copy, stat.S_IREAD)
        try:
            ok, msg = verify_chain(copy)
            assert ok, msg
        finally:
            os.chmod(copy, stat.S_IWRITE | stat.S_IREAD)


# ---------------------------------------------------------------------------
# K-05 / K-06 — Genesis async polling
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _RecordingSession:
    """Captures every poll GET so the headers and the cadence are assertable."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.calls: list[dict] = []

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        status = self._statuses.pop(0) if self._statuses else "DELIVERED"
        return _FakeResponse(200, json.dumps({
            "status": status,
            "resultSummary": json.dumps({
                "trace": {"tool_calls": [{"ok": True}]},
            }),
        }))


def _genesis_tool(session):
    from cato.tools.genesis import GenesisTool
    tool = GenesisTool.__new__(GenesisTool)

    async def _ensure():
        return session

    tool._ensure_session = _ensure
    return tool


class TestGenesisPolling:
    def test_poll_carries_only_the_owner_scoped_principal_token(self):
        """K-05 — RESOLVED THE OTHER WAY.

        My first fix added the shared GATEWAY_API_KEY to the poll so a
        gateway-key-guarded `GET /agents/jobs/{id}` would authenticate. Two
        existing tests encode the opposite decision deliberately
        (test_expired_principal_token_fails_without_shared_gateway_header,
        test_poll_redirect_is_not_followed_with_gateway_credential) and they
        are right: the gateway key is an omni-privilege credential — any holder
        reads any job — and `poll_url` arrives inside an untrusted response
        body. Least privilege wins; the fix was reverted.

        The FINDING is not closed. It is a cross-repo contract gap that only
        Genesis can close by honouring X-Genesis-Principal-Token on the job
        route. This test pins Cato's side so the mistake is not repeated.
        """
        session = _RecordingSession(["DELIVERED"])
        tool = _genesis_tool(session)

        out = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            tool._poll_job(
                endpoint="https://genesis.example",
                poll_url="/agents/jobs/job-abc",
                principal_token="ptok",
                agent="genesis-research",
                deadline=__import__("time").monotonic() + 30,
                started=__import__("time").monotonic(),
            )
        )
        assert json.loads(out)["ok"] is True
        hdrs = session.calls[0]["headers"]
        assert hdrs.get("X-Genesis-Principal-Token") == "ptok"
        assert "X-Agent-Api-Key" not in hdrs, (
            "the shared gateway credential must never travel to a poll_url "
            "supplied by the remote"
        )

    def test_poll_backs_off_instead_of_hammering(self):
        """A flat 0.25s interval issued ~240 requests per queued job against a
        cold Render instance. That is a retry storm dressed as polling."""
        import cato.tools.genesis as gmod

        session = _RecordingSession(["QUEUED"] * 5 + ["DELIVERED"])
        tool = _genesis_tool(session)
        sleeps: list[float] = []

        real_sleep = asyncio.sleep

        async def _spy(delay):
            sleeps.append(delay)
            await real_sleep(0)

        loop = asyncio.get_event_loop_policy().new_event_loop()
        orig = gmod.asyncio.sleep
        gmod.asyncio.sleep = _spy
        try:
            loop.run_until_complete(tool._poll_job(
                endpoint="https://genesis.example",
                poll_url="/agents/jobs/j",
                principal_token="ptok",
                agent="genesis-research",
                deadline=__import__("time").monotonic() + 300,
                started=__import__("time").monotonic(),
            ))
        finally:
            gmod.asyncio.sleep = orig

        assert len(sleeps) >= 3
        assert sleeps == sorted(sleeps), f"interval must not shrink: {sleeps}"
        assert sleeps[-1] > sleeps[0], f"no backoff applied: {sleeps}"
        assert max(sleeps) <= gmod._POLL_INTERVAL_MAX_S

    def test_cross_origin_poll_url_is_still_refused(self):
        """Regression guard on the existing same-origin check — the poll now
        carries a credential, so this matters more than it did."""
        tool = _genesis_tool(_RecordingSession([]))
        loop = asyncio.get_event_loop_policy().new_event_loop()
        for hostile in ("//evil.example/x", "https://evil.example/x",
                        "/\\evil.example/x", "evil"):
            out = loop.run_until_complete(tool._poll_job(
                endpoint="https://genesis.example",
                poll_url=hostile,
                principal_token="ptok",
                agent="genesis-research",
                deadline=__import__("time").monotonic() + 5,
                started=__import__("time").monotonic(),
            ))
            payload = json.loads(out)
            assert payload["error"] == "unsafe_job_poll_url", hostile
            assert payload["outcome_unknown"] is True


# ---------------------------------------------------------------------------
# K-07 / K-08 — send_email must not narrate a send it cannot perform
# ---------------------------------------------------------------------------

class TestSendEmailTruthfulness:
    def _run(self, args, allow_live=True):
        import cato.tools.send_email_tool as mod
        from cato.tools.send_email_tool import execute_send_email

        # Neutralise the night-shift policy so the TOOL's own behaviour is
        # what is under test, not the gate in front of it.
        import cato.core.night_shift_policy as nsp
        orig = nsp.assert_skill_allowed
        nsp.assert_skill_allowed = (lambda *a, **k: None) if allow_live else orig
        try:
            loop = asyncio.get_event_loop_policy().new_event_loop()
            return json.loads(loop.run_until_complete(execute_send_email(args)))
        finally:
            nsp.assert_skill_allowed = orig

    def test_live_send_never_claims_success(self):
        """No code path in Cato clicks Gmail Send — GmailAdapter._send_draft_sync
        raises PermissionError by design. Returning ok:true made the
        hash-chained ledger record CONFIRMED/success for an email that does not
        exist."""
        out = self._run({
            "to": "controller@e4l.com", "subject": "s", "body": "b",
            "draft_only": False,
        })
        assert out["ok"] is False, "reported a delivered email that never left the machine"
        assert out["error"] == "not_implemented"

    @pytest.mark.parametrize("value", [None, 0, [], {}, "", "maybe", 0.0])
    def test_ambiguous_draft_only_falls_back_to_draft(self, value):
        """`draft_only` is written by the MODEL. An unreadable value must never
        be read as permission to send."""
        out = self._run({
            "to": "x@y.z", "subject": "s", "body": "b", "draft_only": value,
        })
        assert out["mode"] == "draft_only", f"{value!r} selected the live path"
        assert out["ok"] is True

    @pytest.mark.parametrize("value", [False, "false", "no", "0", "off"])
    def test_explicit_false_still_selects_the_live_path(self, value):
        out = self._run({
            "to": "x@y.z", "subject": "s", "body": "b", "draft_only": value,
        })
        assert out["mode"] == "send"

    def test_default_is_draft(self):
        out = self._run({"to": "x@y.z", "subject": "s", "body": "b"})
        assert out["mode"] == "draft_only"


# ---------------------------------------------------------------------------
# K-09 / K-10 / K-11 — router
# ---------------------------------------------------------------------------

class _StubVault:
    def __init__(self, keys=None):
        self._keys = keys or {}

    def get(self, k):
        return self._keys.get(k)


def _router(keys=None):
    from cato.router import ModelRouter
    return ModelRouter(
        vault=_StubVault(keys or {"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k"}),
        preferred_model="claude-sonnet-5",
    )


class TestRouterCircuitBreaker:
    def test_breaker_opens_and_refuses(self):
        """`_direct_cb_open_until` was written and never read anywhere in the
        module, so the 'circuit breaker' counted failures forever and never
        opened a circuit."""
        router = _router()
        router._direct_cb_failures = 0

        async def _boom(model, messages, tools=None):
            raise RuntimeError("provider down")
            yield  # pragma: no cover

        router._complete_single = _boom
        loop = asyncio.get_event_loop_policy().new_event_loop()

        async def drain():
            async for _ in router.complete([{"role": "user", "content": "x"}], "claude-sonnet-5"):
                pass

        for _ in range(router._CB_THRESHOLD):
            with pytest.raises(Exception):
                loop.run_until_complete(drain())

        assert router._direct_cb_open_until > 0
        with pytest.raises(RuntimeError, match="circuit breaker open"):
            loop.run_until_complete(drain())

    def test_success_closes_the_breaker(self):
        router = _router()
        router._direct_cb_failures = 9
        router._direct_cb_open_until = 0.0

        async def _ok(model, messages, tools=None):
            yield "hello"

        router._complete_single = _ok
        loop = asyncio.get_event_loop_policy().new_event_loop()

        async def drain():
            return [c async for c in router.complete([], "claude-sonnet-5")]

        assert loop.run_until_complete(drain()) == ["hello"]
        assert router._direct_cb_failures == 0
        assert router._direct_cb_open_until == 0.0


class TestRouterNoFailoverAfterFirstByte:
    def test_partial_stream_is_not_concatenated_with_a_retry(self):
        """`_stream_collect` joins whatever chunks arrive. Failing over after
        the first byte handed it a truncated answer glued to a whole new one
        and called the result the model's reply."""
        router = _router({"ANTHROPIC_API_KEY": "k", "OPENROUTER_API_KEY": "k"})
        attempts: list[str] = []

        async def _flaky(model, messages, tools=None):
            attempts.append(model)
            if len(attempts) == 1:
                yield "The answer is "
                # A classified-retryable error: without the first-byte guard
                # the router WILL rotate to the next model and append a whole
                # second answer to this truncated one.
                raise TimeoutError("upstream timed out mid-stream")
            yield "COMPLETELY DIFFERENT ANSWER"

        router._complete_single = _flaky
        loop = asyncio.get_event_loop_policy().new_event_loop()
        collected: list[str] = []

        async def drain():
            async for c in router.complete([], "claude-sonnet-5"):
                collected.append(c)

        with pytest.raises(TimeoutError):
            loop.run_until_complete(drain())

        assert len(attempts) == 1, "failed over on top of a partial answer"
        assert "".join(collected) == "The answer is "

    def test_failover_still_happens_before_the_first_byte(self):
        router = _router({"ANTHROPIC_API_KEY": "k", "OPENROUTER_API_KEY": "k"})
        attempts: list[str] = []

        async def _flaky(model, messages, tools=None):
            attempts.append(model)
            if len(attempts) == 1:
                raise TimeoutError("upstream timed out before first byte")
                yield  # pragma: no cover
            yield "recovered"

        router._complete_single = _flaky
        loop = asyncio.get_event_loop_policy().new_event_loop()

        async def drain():
            return [c async for c in router.complete([], "claude-sonnet-5")]

        assert loop.run_until_complete(drain()) == ["recovered"]
        assert len(attempts) == 2


class TestRouterTranslationsMatchRegistry:
    def test_router_translations_cover_registry(self):
        """Two model tables that disagree is how the live HTTP 400 happened for
        `openai/gpt-4o-mini`. Every anthropic entry in MODEL_TRANSLATIONS
        pointed at an id MODEL_REGISTRY does not contain, and not one of the
        registry's own anthropic ids had a translation at all."""
        from cato.model_policy import MODEL_REGISTRY
        from cato.router import MODEL_TRANSLATIONS

        missing = [
            m for m in MODEL_REGISTRY
            if m.startswith("claude-") and f"anthropic/{m}" not in MODEL_TRANSLATIONS
        ]
        assert not missing, f"no provider-qualified translation for {missing}"

        for model in MODEL_REGISTRY:
            if model.startswith("claude-"):
                assert MODEL_TRANSLATIONS[f"anthropic/{model}"] == model

    def test_no_provider_prefix_survives_to_the_wire(self):
        """The exact live failure: 'openai/gpt-4o-mini' -> HTTP 400
        'invalid model ID'. Reproduced against api.openai.com on 2026-08-12."""
        from cato.router import MODEL_TRANSLATIONS

        for slug in ("openai/gpt-4o-mini", "openai/gpt-4o",
                     "anthropic/claude-sonnet-5", "anthropic/claude-opus-5"):
            resolved = MODEL_TRANSLATIONS.get(slug, slug)
            assert "/" not in resolved, (
                f"{slug!r} reaches a native provider as {resolved!r}"
            )


# ---------------------------------------------------------------------------
# K-12 — Gmail: the no-send property, and truthful failure on the error path
# ---------------------------------------------------------------------------

class _FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kw):
        self.messages.append(kw)


class _FakeTelegramApp:
    def __init__(self):
        self.bot = _FakeBot()


def _gmail_adapter():
    from cato.adapters.gmail_adapter import GmailAdapter
    a = GmailAdapter.__new__(GmailAdapter)
    a._telegram_app = _FakeTelegramApp()
    a._telegram_chat_id = "1"
    return a


class TestGmailNoSendProperty:
    """LIVE-VERIFIED 2026-08-12: the stored GMAIL_REFRESH_TOKEN refreshes
    successfully (HTTP 200) but carries scope `gmail.readonly` ONLY and
    authenticates swarmsync@gmail.com, while GMAIL_ADDRESS is
    controller@e4l.com. So drafts().create() 403s on every call — the error
    path below is the path that actually runs, not a hypothetical."""

    def test_every_send_seam_refuses(self):
        """There must be no reachable code path that transmits mail."""
        from cato.adapters.gmail_adapter import GmailAdapter

        a = GmailAdapter.__new__(GmailAdapter)
        with pytest.raises(PermissionError, match="draft-only"):
            a._send_draft_sync("draft-1")

        loop = asyncio.get_event_loop_policy().new_event_loop()
        with pytest.raises(PermissionError, match="draft-only"):
            loop.run_until_complete(a.send_draft("draft-1"))

        src = Path(GmailAdapter.__module__.replace(".", "/") + ".py")
        text = (Path(__file__).resolve().parents[1] / src).read_text(encoding="utf-8")
        for forbidden in (".send(", "drafts().send", "messages().send"):
            assert forbidden not in text, f"a transmit seam appeared: {forbidden}"

    def test_identity_mismatch_disables_the_adapter(self):
        """The live credential authenticates a DIFFERENT mailbox than
        GMAIL_ADDRESS. Fail closed, do not poll someone else's inbox."""
        import os as _os

        from cato.adapters.gmail_adapter import GmailAdapter

        a = GmailAdapter.__new__(GmailAdapter)

        class _Svc:
            def users(self):
                return self

            def getProfile(self, userId):  # noqa: N802 - Google API shape
                return self

            def execute(self):
                return {"emailAddress": "swarmsync@gmail.com"}

        prev = _os.environ.get("GMAIL_ADDRESS")
        _os.environ["GMAIL_ADDRESS"] = "controller@e4l.com"
        try:
            assert a._verify_mailbox_identity_sync(_Svc()) is False
            _os.environ["GMAIL_ADDRESS"] = "swarmsync@gmail.com"
            assert a._verify_mailbox_identity_sync(_Svc()) is True
            _os.environ["GMAIL_ADDRESS"] = ""
            assert a._verify_mailbox_identity_sync(_Svc()) is False, (
                "unset GMAIL_ADDRESS must disable Gmail, not match everything"
            )
        finally:
            if prev is None:
                _os.environ.pop("GMAIL_ADDRESS", None)
            else:
                _os.environ["GMAIL_ADDRESS"] = prev

    def test_failed_draft_is_not_announced_as_a_ready_draft(self):
        """The error path that the read-only scope makes certain: Cato told the
        operator a draft was waiting in Gmail and offered an Approve button for
        it, when drafts().create() had just 403'd and nothing was saved."""
        a = _gmail_adapter()
        loop = asyncio.get_event_loop_policy().new_event_loop()
        loop.run_until_complete(a._notify_telegram(
            {"subject": "s", "from_email": "a@b.c", "snippet": "x"},
            "the drafted reply", 7, draft_created=False,
        ))
        msg = a._telegram_app.bot.messages[-1]
        assert "NOT SAVED TO GMAIL" in msg["text"]
        buttons = msg["reply_markup"].inline_keyboard[0]
        labels = [b.text for b in buttons]
        assert "Approve Draft" not in labels, (
            "offered Approve for a draft that does not exist in Gmail"
        )

    def test_successful_draft_still_offers_approve(self):
        a = _gmail_adapter()
        loop = asyncio.get_event_loop_policy().new_event_loop()
        loop.run_until_complete(a._notify_telegram(
            {"subject": "s", "from_email": "a@b.c", "snippet": "x"},
            "the drafted reply", 7, draft_created=True,
        ))
        msg = a._telegram_app.bot.messages[-1]
        labels = [b.text for b in msg["reply_markup"].inline_keyboard[0]]
        assert "Approve Draft" in labels
        assert "NOT SAVED TO GMAIL" not in msg["text"]


# ---------------------------------------------------------------------------
# K-13 — tools the model can reach but cannot parameterise
# ---------------------------------------------------------------------------

class TestToolSchemaCoverage:
    """LIVE-OBSERVED 2026-08-12 in an isolated data dir: claude-sonnet-5 called
    `memory__search` with `arguments: "{}"` because the auto-generated schema
    declares no properties. The tool ran, returned nothing, and the ledger
    recorded INTENT -> ATTEMPTED -> CONFIRMED / "success". A no-op audited as
    a success is worse than a refusal."""

    def test_auto_generated_schema_is_open_and_says_so(self):
        import cato.agent_loop as al

        name = "kraken.unschematised.probe"
        al.register_tool(name, lambda args: "")
        try:
            defn = next(
                d for d in al.get_tool_definitions()
                if d["function"]["name"] == name
            )
        finally:
            al._TOOL_REGISTRY.pop(name, None)

        params = defn["function"]["parameters"]
        assert params["properties"] == {}
        assert params.get("additionalProperties") is True, (
            "a closed empty object leaves the model no way to pass arguments"
        )
        assert "no parameter schema is registered" in defn["function"]["description"]

    def test_unschematised_tools_are_enumerable(self):
        """Make the gap countable so it can be closed and cannot grow unseen."""
        import cato.agent_loop as al

        missing = al.tools_without_schema()
        assert isinstance(missing, list)
        assert all(m not in al._TOOL_SCHEMAS for m in missing)

    def test_execution_tools_registered_twice_under_divergent_names(self):
        """`shell` / `python.exec` carry schemas; their `shell.exec` /
        `python.execute` twins do not. Two names for one capability, one of
        them unusable, is the concrete cost of the duplicated registration
        path (two functions called `register_all_tools`)."""
        import cato.agent_loop as al

        al.register_all_tools(al.register_tool)
        schemas = al._BUILTIN_SCHEMAS
        assert "shell" in schemas and "python.exec" in schemas
        missing = set(al.tools_without_schema())
        assert {"shell.exec", "python.execute"} <= missing, (
            "expected the unschematised execution twins to still be present; "
            "if this now fails the duplication was fixed — delete this test"
        )


# ---------------------------------------------------------------------------
# K-14 — silent audit divergence between the two data roots
# ---------------------------------------------------------------------------

class TestLegacyAuditDivergenceIsVisible:
    """The real shape of the split-brain, verified read-only on 2026-08-12:

      %APPDATA%/cato/cato.db  -> ledger_records=1107, audit_log=0
      ~/.cato/cato.db         -> NO ledger_records,   audit_log=11
                                 (+ conduit_billing, conduit_bundle_chain)

    The legacy audit_log carries columns the canonical one does not have
    (inputs_digest, outputs_digest, schema_version). Every verification
    surface reads get_data_dir()/cato.db only, so eleven audit records sat
    outside the reach of `cato verify-ledger`, `cato audit`, `cato receipt`,
    `cato replay` and GET /api/audit/* — and nothing raised an alarm. Reporting
    that a stranded cato.db merely EXISTS understates that by a wide margin.
    """

    def _legacy_root(self, tmp_path, monkeypatch, rows):
        import cato.platform as plat

        canonical = tmp_path / "canonical"
        legacy = tmp_path / "home" / ".cato"
        canonical.mkdir(parents=True)
        legacy.mkdir(parents=True)
        monkeypatch.setattr(plat, "get_data_dir", lambda: canonical)
        monkeypatch.setattr(plat.Path, "home", staticmethod(lambda: tmp_path / "home"))

        conn = sqlite3.connect(str(legacy / "cato.db"))
        conn.execute(
            "CREATE TABLE audit_log (id INTEGER PRIMARY KEY, tool_name TEXT, "
            "inputs_digest TEXT, schema_version INTEGER)"
        )
        for i in range(rows):
            conn.execute(
                "INSERT INTO audit_log (tool_name, inputs_digest, schema_version) "
                "VALUES (?,?,?)", (f"browser.navigate{i}", "d", 2),
            )
        conn.commit()
        conn.close()
        return legacy

    def test_inventory_reports_stranded_audit_ROWS_not_just_the_file(
        self, tmp_path, monkeypatch,
    ):
        import cato.platform as plat

        self._legacy_root(tmp_path, monkeypatch, rows=11)
        inv = plat.get_legacy_data_inventory()
        assert inv, "the stranded root was not discovered at all"
        item = inv[0]
        assert "cato.db" in item["present"]
        assert "cato.db:audit_log" in item["present"], (
            "reported only that a legacy cato.db exists — not that it holds "
            "audit records no verification command can see"
        )
        assert item["counts"]["cato.db:audit_log"] == 11

    def test_discovery_never_writes_to_the_legacy_database(
        self, tmp_path, monkeypatch,
    ):
        """The legacy root may hold the only copy of some records."""
        import cato.platform as plat

        legacy = self._legacy_root(tmp_path, monkeypatch, rows=3)
        db = legacy / "cato.db"
        before = db.read_bytes()
        plat.get_legacy_data_inventory()
        assert db.read_bytes() == before

    def test_empty_legacy_tables_are_not_reported_as_findings(
        self, tmp_path, monkeypatch,
    ):
        import cato.platform as plat

        self._legacy_root(tmp_path, monkeypatch, rows=0)
        inv = plat.get_legacy_data_inventory()
        item = inv[0]
        assert "cato.db:audit_log" not in item["present"]
