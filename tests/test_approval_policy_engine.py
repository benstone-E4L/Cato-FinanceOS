"""
tests/test_approval_policy_engine.py — policy-driven approval engine.

Covers the four defect classes the engine exists to close:

A. Fail-open routing        -> unknown tools gate; aliases converge; no
                               substring matching on model-supplied text.
B. Model-controlled bypass  -> dry_run / draft_only / _approval_granted in
                               args cannot remove an approval requirement.
C. Weak approvals           -> tickets carry identity, argument-digest scope,
                               TTL, single-use, and tamper protection.
D. Secret leakage           -> nested credentials appear in neither the
                               persisted row nor the preview.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cato.core.approval_policy import (
    ALLOW,
    REQUIRE,
    ApprovalContext,
    ExecutionGrants,
    TicketError,
    clear_execution_grants,
    grant_execution,
    take_execution_grant,
    build_preview,
    canonical_args,
    compute_args_digest,
    decode_ticket,
    detect_bypass_attempt,
    encode_ticket,
    evaluate,
    is_sensitive_key,
    issue_ticket,
    load_policy,
    normalize_tool_name,
    policy_path,
    redact,
    resolve_tool,
    verify_ticket,
)
from cato.core.outbound_approval import (
    OutboundApprovalStore,
    approval_decision,
    requires_approval,
)

SECRET = "sk-live-DO-NOT-LOG-0123456789abcdef"
KEY = b"\x01" * 32


@pytest.fixture
def store(tmp_path: Path) -> OutboundApprovalStore:
    s = OutboundApprovalStore(db_path=tmp_path / "cato.db")
    yield s
    s.close()


# ===========================================================================
# A. Fail-closed routing
# ===========================================================================


class TestFailClosedRouting:
    def test_unknown_tool_requires_approval(self) -> None:
        """An unlisted tool must gate. This is the fail-open bug."""
        assert requires_approval("totally_unregistered_tool_xyz", {}) is True

    def test_unknown_tool_decision_reason_is_explicit(self) -> None:
        d = approval_decision("some_new_exfiltration_tool", {"to": "a@b.com"})
        assert d.decision == REQUIRE
        assert d.reason == "unknown_tool_default_require"
        assert d.tier == "critical"

    def test_removing_a_tool_from_policy_makes_it_more_restricted(self, tmp_path: Path) -> None:
        """Deleting a policy row must never open the gate."""
        pol = copy.deepcopy(load_policy(reload=True))
        assert evaluate("memory.search", {}, policy=pol).decision == ALLOW
        # Simulate the row being removed by an operator edit.
        del pol.tools["memory_search"]
        assert evaluate("memory.search", {}, policy=pol).decision == REQUIRE

    def test_policy_file_cannot_set_default_to_allow(self, tmp_path: Path) -> None:
        """A policy file asking for a fail-open default is overruled in code."""
        p = tmp_path / "bad-policy.yaml"
        p.write_text(
            "version: '9'\ndefault_decision: allow\ntools: {}\n", encoding="utf-8"
        )
        pol = load_policy(p, reload=True)
        assert pol.default_decision == REQUIRE
        assert evaluate("anything_at_all", {}, policy=pol).decision == REQUIRE

    def test_corrupt_policy_file_falls_back_fail_closed(self, tmp_path: Path) -> None:
        p = tmp_path / "corrupt.yaml"
        p.write_text("this: [is: not: valid: yaml\n", encoding="utf-8")
        pol = load_policy(p, reload=True)
        assert pol.source == "builtin"
        assert evaluate("send_email", {}, policy=pol).decision == REQUIRE

    def test_unknown_tier_in_policy_is_coerced_to_critical(self, tmp_path: Path) -> None:
        p = tmp_path / "tier.yaml"
        p.write_text(
            "version: '1'\ntools:\n  my_tool:\n    tier: totally_safe_trust_me\n",
            encoding="utf-8",
        )
        pol = load_policy(p, reload=True)
        assert pol.tools["my_tool"].tier == "critical"
        assert evaluate("my_tool", {}, policy=pol).decision == REQUIRE

    def test_policy_file_that_is_not_a_mapping_falls_back(self, tmp_path: Path) -> None:
        p = tmp_path / "list.yaml"
        p.write_text("- just\n- a\n- list\n", encoding="utf-8")
        pol = load_policy(p, reload=True)
        assert pol.source == "builtin"
        assert evaluate("send_email", {}, policy=pol).decision == REQUIRE

    def test_missing_policy_file_uses_builtin(self, tmp_path: Path) -> None:
        pol = load_policy(tmp_path / "nope.yaml", reload=True)
        assert pol.source == "builtin"
        assert evaluate("send_email", {}, policy=pol).decision == REQUIRE
        assert evaluate("memory.search", {}, policy=pol).decision == ALLOW

    def test_malformed_ticket_block_keeps_safe_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "ticket.yaml"
        p.write_text(
            "version: '1'\nticket:\n  ttl_seconds: forever\n  clock_skew_seconds: lots\n",
            encoding="utf-8",
        )
        pol = load_policy(p, reload=True)
        assert pol.ttl_seconds == 86_400
        assert pol.clock_skew_seconds == 60

    def test_unnameable_policy_row_is_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "blank.yaml"
        p.write_text("version: '1'\ntools:\n  '!!!':\n    tier: read_only\n", encoding="utf-8")
        pol = load_policy(p, reload=True)
        assert "" not in pol.tools
        assert evaluate("!!!", {}, policy=pol).decision == REQUIRE

    def test_env_var_selects_the_policy_file(self, tmp_path: Path, monkeypatch) -> None:
        p = tmp_path / "custom.yaml"
        p.write_text(
            "version: '7'\ntools:\n  my_reader:\n    tier: read_only\n", encoding="utf-8"
        )
        monkeypatch.setenv("CATO_APPROVAL_POLICY", str(p))
        assert policy_path() == p
        pol = load_policy(reload=True)
        assert pol.version == "7"
        assert evaluate("my_reader", {}, policy=pol).decision == ALLOW
        monkeypatch.delenv("CATO_APPROVAL_POLICY")
        load_policy(reload=True)  # restore the module cache for other tests

    def test_empty_and_none_tool_names_gate(self) -> None:
        assert requires_approval("", {}) is True
        assert requires_approval(None, {}) is True  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [None, "not-a-dict", 42, ["a"], object()])
    def test_malformed_args_fail_closed(self, bad: object) -> None:
        """A payload we cannot read is a payload we cannot vouch for."""
        d = approval_decision("send_email", bad)  # type: ignore[arg-type]
        assert d.decision == REQUIRE

    def test_missing_args_still_gates_outbound(self) -> None:
        assert requires_approval("send_email", {}) is True

    def test_read_only_tools_do_not_gate(self) -> None:
        for safe in ("memory.search", "web.search", "graph.query", "github.pr_list"):
            assert requires_approval(safe, {}) is False, safe


# ===========================================================================
# A2. Alias / indirect invocation convergence
# ===========================================================================


class TestAliasResolution:
    SEND_EMAIL_FORMS = [
        "send_email",
        "send-email",
        "sendEmail",
        "SendEmail",
        "Send Email",
        "send.email",
        "email.send",
        "email_send",
        "emailSend",
        "send_mail",
        "sendmail",
        "mail.send",
        "tools.send_email",
    ]

    @pytest.mark.parametrize("alias", SEND_EMAIL_FORMS)
    def test_send_email_aliases_share_one_policy_row(self, alias: str) -> None:
        rule = resolve_tool(alias)
        assert rule.canonical == "send_email", alias
        assert rule.known is True
        assert requires_approval(alias, {"to": "a@b.com"}) is True, alias

    @pytest.mark.parametrize(
        "alias",
        ["outreach.run", "outreach-run", "outreachRun", "outreach_bridge",
         "outreachBridge", "execute_outreach_run"],
    )
    def test_outreach_aliases_share_one_policy_row(self, alias: str) -> None:
        assert resolve_tool(alias).canonical == "outreach_run", alias
        assert requires_approval(alias, {}) is True, alias

    @pytest.mark.parametrize(
        "alias", ["genesis", "genesis-email", "genesis_email", "genesisEmail", "genesis.run"]
    )
    def test_genesis_aliases_share_one_policy_row(self, alias: str) -> None:
        assert resolve_tool(alias).canonical == "genesis", alias
        assert requires_approval(alias, {}) is True, alias

    def test_all_send_email_aliases_produce_identical_decisions(self) -> None:
        args = {"to": "a@b.com", "subject": "s", "body": "b"}
        decisions = {
            (evaluate(a, args).canonical, evaluate(a, args).decision, evaluate(a, args).tier)
            for a in self.SEND_EMAIL_FORMS
        }
        assert len(decisions) == 1, decisions

    def test_alias_forms_produce_identical_argument_digests(self) -> None:
        """Scope binding must not be defeatable by respelling the tool."""
        args = {"to": "a@b.com"}
        digests = {compute_args_digest(a, args) for a in self.SEND_EMAIL_FORMS}
        assert len(digests) == 1

    def test_normalization_examples(self) -> None:
        assert normalize_tool_name("sendEmail") == "send_email"
        assert normalize_tool_name("send-email") == "send_email"
        assert normalize_tool_name("Send Email") == "send_email"
        assert normalize_tool_name("site_services.send_outreach") == "site_services_send_outreach"


# ===========================================================================
# A3. No substring matching on model-supplied text
# ===========================================================================


class TestNoSubstringEvasion:
    @pytest.mark.parametrize(
        "task",
        [
            "dispatch the newsletter to 4000 people",  # avoided the word "send"
            "deliver outreach",
            "blast the list",
            "transmit messages",
            "",
            "read the docs",
        ],
    )
    def test_genesis_gates_regardless_of_task_wording(self, task: str) -> None:
        """The old gate looked for 'send'/'campaign' in this string."""
        assert requires_approval("genesis", {"task": task}) is True, task

    def test_genesis_gates_regardless_of_agent_name(self) -> None:
        for agent in ("genesis-email", "genesis-dispatch", "", "harmless-reader"):
            assert requires_approval("genesis", {"agent": agent}) is True, agent

    def test_genesis_is_classified_as_dispatch_not_by_text(self) -> None:
        d = approval_decision("genesis", {"task": "anything"})
        assert d.tier == "dispatch"
        assert d.reason == "tier:dispatch:always"


# ===========================================================================
# B. Model-controlled bypasses are dead
# ===========================================================================


class TestBypassesKilled:
    def test_dry_run_in_args_cannot_remove_approval(self) -> None:
        assert requires_approval("send_email", {"dry_run": True}) is True
        assert requires_approval("outreach.run", {"dry_run": True}) is True

    def test_draft_only_in_args_cannot_remove_approval(self) -> None:
        assert requires_approval("send_email", {"draft_only": True}) is True
        assert requires_approval("outreach.run", {"draft_only": True}) is True

    @pytest.mark.parametrize(
        "key",
        ["dry_run", "dryRun", "draft_only", "draftOnly", "simulate", "preview_only",
         "test_mode", "_approval_granted", "approval_granted", "skip_approval",
         "no_approval", "auto_approve", "bypass_approval"],
    )
    def test_no_single_arg_key_opens_the_gate(self, key: str) -> None:
        assert requires_approval("send_email", {key: True, "to": "a@b.com"}) is True

    def test_every_bypass_key_at_once_still_gates(self) -> None:
        args = {
            "dry_run": True, "draft_only": True, "_approval_granted": True,
            "skip_approval": True, "auto_approve": True, "simulate": True,
            "to": "victim@example.com",
        }
        assert requires_approval("send_email", args) is True

    def test_bypass_attempt_is_reported(self) -> None:
        d = approval_decision("send_email", {"dry_run": True, "_approval_granted": True})
        assert "dry_run" in d.bypass_attempted
        assert "_approval_granted" in d.bypass_attempted

    def test_bypass_attempt_is_logged_as_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING", logger="cato.core.approval_policy"):
            requires_approval("send_email", {"_approval_granted": True})
        assert any("bypass attempt" in r.getMessage() for r in caplog.records)

    def test_detect_bypass_ignores_falsey_simulation_flags(self) -> None:
        assert detect_bypass_attempt({"dry_run": False}) == []
        assert detect_bypass_attempt({"to": "a@b.com"}) == []

    def test_control_keys_are_stripped_from_the_approved_payload(self) -> None:
        """_approval_granted must not survive into what gets executed."""
        safe = canonical_args({"_approval_granted": True, "to": "a@b.com"})
        assert "_approval_granted" not in safe
        assert safe["to"] == "a@b.com"

    def test_execution_meaningful_flags_are_preserved(self) -> None:
        """draft_only changes what send_email DOES; dropping it would turn an
        approved draft into a live send."""
        safe = canonical_args({"draft_only": True, "to": "a@b.com"})
        assert safe["draft_only"] is True

    def test_simulation_needs_caller_context_not_args(self) -> None:
        # outreach_run is the one tool the policy marks simulation_exempt.
        assert requires_approval("outreach.run", {"dry_run": True}) is True
        ctx = ApprovalContext(actor="scheduler", simulation_authorized=True)
        assert requires_approval("outreach.run", {}, context=ctx) is False

    def test_caller_context_cannot_downgrade_a_non_exempt_tool(self) -> None:
        ctx = ApprovalContext(actor="scheduler", simulation_authorized=True)
        assert requires_approval("send_email", {}, context=ctx) is True
        assert requires_approval("genesis", {}, context=ctx) is True
        assert requires_approval("unknown_tool", {}, context=ctx) is True

    def test_context_without_authorization_does_nothing(self) -> None:
        ctx = ApprovalContext(actor="model", simulation_authorized=False)
        assert requires_approval("outreach.run", {}, context=ctx) is True


# ===========================================================================
# C. Ticket properties
# ===========================================================================


class TestTicketIdentityAndScope:
    def test_ticket_has_unique_identity(self) -> None:
        t1, _ = issue_ticket(KEY, "appr-1", "send_email", {"to": "a@b.com"})
        t2, _ = issue_ticket(KEY, "appr-1", "send_email", {"to": "a@b.com"})
        assert t1.ticket_id != t2.ticket_id
        assert t1.nonce != t2.nonce

    def test_ticket_is_bound_to_the_argument_digest(self) -> None:
        args = {"to": "a@b.com", "body": "hello"}
        ticket, token = issue_ticket(KEY, "appr-1", "send_email", args)
        assert ticket.args_digest == compute_args_digest("send_email", args)
        # Same args -> verifies.
        verify_ticket(KEY, token, "send_email", args)

    def test_changing_args_after_approval_invalidates_the_ticket(self) -> None:
        approved = {"to": "boss@example.com", "body": "quarterly update"}
        _, token = issue_ticket(KEY, "appr-1", "send_email", approved)
        tampered = {"to": "attacker@evil.example", "body": "quarterly update"}
        with pytest.raises(TicketError) as exc:
            verify_ticket(KEY, token, "send_email", tampered)
        assert str(exc.value) == "ticket_args_mismatch"

    def test_adding_an_argument_after_approval_invalidates_the_ticket(self) -> None:
        _, token = issue_ticket(KEY, "appr-1", "send_email", {"to": "a@b.com"})
        with pytest.raises(TicketError):
            verify_ticket(KEY, token, "send_email", {"to": "a@b.com", "bcc": "evil@x.com"})

    def test_ticket_for_one_tool_cannot_authorize_another(self) -> None:
        args = {"cmd": "ls"}
        _, token = issue_ticket(KEY, "appr-1", "send_email", args)
        with pytest.raises(TicketError) as exc:
            verify_ticket(KEY, token, "shell.exec", args)
        assert str(exc.value) == "ticket_tool_mismatch"

    def test_ticket_bound_to_its_approval_id(self) -> None:
        _, token = issue_ticket(KEY, "appr-1", "send_email", {})
        with pytest.raises(TicketError) as exc:
            verify_ticket(KEY, token, "send_email", {}, approval_id="appr-2")
        assert str(exc.value) == "ticket_approval_mismatch"


class TestTicketExpiry:
    def test_ticket_has_24h_ttl(self) -> None:
        ticket, _ = issue_ticket(KEY, "a", "send_email", {}, now=1_000_000.0)
        assert ticket.expires_at == pytest.approx(1_000_000.0 + 86_400)

    def test_expired_ticket_is_rejected(self) -> None:
        _, token = issue_ticket(KEY, "a", "send_email", {}, now=1_000_000.0)
        with pytest.raises(TicketError) as exc:
            verify_ticket(KEY, token, "send_email", {}, now=1_000_000.0 + 86_400 + 61)
        assert str(exc.value) == "ticket_expired"

    def test_ticket_valid_inside_the_skew_window(self) -> None:
        """60s of clock skew is tolerated, not more."""
        _, token = issue_ticket(KEY, "a", "send_email", {}, now=1_000_000.0)
        verify_ticket(KEY, token, "send_email", {}, now=1_000_000.0 + 86_400 + 30)

    def test_ticket_from_the_future_beyond_skew_is_rejected(self) -> None:
        """A rolled-forward clock must not mint an effectively immortal ticket."""
        _, token = issue_ticket(KEY, "a", "send_email", {}, now=2_000_000.0)
        with pytest.raises(TicketError) as exc:
            verify_ticket(KEY, token, "send_email", {}, now=2_000_000.0 - 61)
        assert str(exc.value) == "ticket_not_yet_valid"


class TestTicketTamperProtection:
    def test_tampered_payload_is_rejected(self) -> None:
        ticket, token = issue_ticket(KEY, "a", "send_email", {"to": "a@b.com"})
        prefix, encoded, sig = token.split(".")
        import base64

        raw = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        raw["expires_at"] = raw["expires_at"] + 10_000_000  # extend my own ticket
        forged = base64.urlsafe_b64encode(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        with pytest.raises(TicketError) as exc:
            decode_ticket(KEY, f"{prefix}.{forged}.{sig}")
        assert str(exc.value) == "ticket_signature_invalid"

    def test_forged_signature_is_rejected(self) -> None:
        _, token = issue_ticket(KEY, "a", "send_email", {})
        prefix, encoded, _ = token.split(".")
        with pytest.raises(TicketError):
            decode_ticket(KEY, f"{prefix}.{encoded}.{'0' * 64}")

    def test_ticket_signed_with_another_key_is_rejected(self) -> None:
        _, token = issue_ticket(b"\x02" * 32, "a", "send_email", {})
        with pytest.raises(TicketError) as exc:
            decode_ticket(KEY, token)
        assert str(exc.value) == "ticket_signature_invalid"

    @pytest.mark.parametrize(
        "bad", ["", None, 12345, "garbage", "cato-appr-v1.only-two-parts",
                "wrong-prefix.abc.def"],
    )
    def test_malformed_tokens_are_rejected(self, bad: object) -> None:
        with pytest.raises(TicketError):
            decode_ticket(KEY, bad)

    def test_correctly_signed_but_incomplete_ticket_is_rejected(self) -> None:
        """A signed payload missing required fields must not be trusted."""
        import base64
        import hashlib
        import hmac

        encoded = base64.urlsafe_b64encode(
            json.dumps({"ticket_id": "x"}, sort_keys=True, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        sig = hmac.new(KEY, encoded.encode("ascii"), hashlib.sha256).hexdigest()
        with pytest.raises(TicketError) as exc:
            decode_ticket(KEY, f"cato-appr-v1.{encoded}.{sig}")
        assert str(exc.value) == "ticket_incomplete"

    def test_correctly_signed_non_object_payload_is_rejected(self) -> None:
        import base64
        import hashlib
        import hmac

        encoded = base64.urlsafe_b64encode(b'"a string"').decode().rstrip("=")
        sig = hmac.new(KEY, encoded.encode("ascii"), hashlib.sha256).hexdigest()
        with pytest.raises(TicketError) as exc:
            decode_ticket(KEY, f"cato-appr-v1.{encoded}.{sig}")
        assert str(exc.value) == "ticket_undecodable"

    def test_reencoding_a_valid_ticket_roundtrips(self) -> None:
        ticket, token = issue_ticket(KEY, "a", "send_email", {"to": "x@y.com"})
        assert encode_ticket(KEY, ticket) == token
        assert decode_ticket(KEY, token).ticket_id == ticket.ticket_id


# ===========================================================================
# C2. Single-use enforcement (through the store)
# ===========================================================================


class TestStoreTicketLifecycle:
    def test_approval_creates_a_ticket_with_scope_and_expiry(
        self, store: OutboundApprovalStore
    ) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        assert row.args_digest
        assert row.canonical_tool == "send_email"
        approved, token = store.approve(row.id, resolved_by="operator")
        assert approved.status == "approved"
        assert approved.ticket_id
        assert approved.expires_at > approved.created_at
        assert token.startswith("cato-appr-v1.")

    def test_consumed_ticket_cannot_be_replayed(self, store: OutboundApprovalStore) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        store.approve(row.id)
        ticket, approved_args = store.consume(row.id)
        assert ticket.approval_id == row.id
        assert approved_args == {"to": "a@b.com"}

        with pytest.raises(TicketError) as exc:
            store.consume(row.id)
        assert str(exc.value) == "ticket_already_consumed"
        assert store.get(row.id).status == "consumed"

    def test_replay_with_a_saved_token_still_fails(self, store: OutboundApprovalStore) -> None:
        """Keeping a copy of the token does not buy a second execution."""
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        _, token = store.approve(row.id)
        store.consume(row.id, token=token)
        with pytest.raises(TicketError):
            store.consume(row.id, token=token)

    def test_expired_stored_ticket_is_rejected(self, store: OutboundApprovalStore) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        store.approve(row.id)
        with pytest.raises(TicketError) as exc:
            store.consume(row.id, now=time.time() + 86_400 + 120)
        assert str(exc.value) == "ticket_expired"
        assert store.get(row.id).status == "approved"  # not consumed

    def test_tampered_stored_row_is_rejected(self, store: OutboundApprovalStore) -> None:
        """Editing args_json in SQLite after approval must void the ticket."""
        row = store.create("sess-1", "send_email", {"to": "boss@example.com"})
        store.approve(row.id)
        store._conn.execute(
            "UPDATE outbound_approvals SET args_json = ? WHERE id = ?",
            (json.dumps({"to": "attacker@evil.example"}), row.id),
        )
        store._conn.commit()
        with pytest.raises(TicketError) as exc:
            store.consume(row.id)
        assert str(exc.value) == "ticket_args_mismatch"

    def test_tampered_stored_token_is_rejected(self, store: OutboundApprovalStore) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        store.approve(row.id)
        store._conn.execute(
            "UPDATE outbound_approvals SET ticket_token = ? WHERE id = ?",
            ("cato-appr-v1.YWJj." + "0" * 64, row.id),
        )
        store._conn.commit()
        with pytest.raises(TicketError) as exc:
            store.consume(row.id)
        assert str(exc.value) == "ticket_signature_invalid"

    def test_consuming_with_different_args_than_approved_is_rejected(
        self, store: OutboundApprovalStore
    ) -> None:
        row = store.create("sess-1", "send_email", {"to": "boss@example.com"})
        store.approve(row.id)
        with pytest.raises(TicketError) as exc:
            store.consume(row.id, args={"to": "attacker@evil.example"})
        assert str(exc.value) == "ticket_args_mismatch"

    def test_pending_approval_cannot_be_consumed(self, store: OutboundApprovalStore) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        with pytest.raises(TicketError) as exc:
            store.consume(row.id)
        assert str(exc.value) == "approval_status_pending"

    def test_denied_approval_cannot_be_consumed(self, store: OutboundApprovalStore) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        store.resolve(row.id, "denied", resolved_by="operator")
        with pytest.raises(TicketError) as exc:
            store.consume(row.id)
        assert str(exc.value) == "approval_status_denied"

    def test_unknown_approval_id_is_rejected(self, store: OutboundApprovalStore) -> None:
        with pytest.raises(TicketError) as exc:
            store.consume("does-not-exist")
        assert str(exc.value) == "approval_not_found"

    def test_double_approve_is_refused(self, store: OutboundApprovalStore) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        assert store.approve(row.id) is not None
        assert store.approve(row.id) is None

    def test_denied_then_approved_is_refused(self, store: OutboundApprovalStore) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        store.resolve(row.id, "denied")
        assert store.resolve(row.id, "approved") is None

    def test_double_deny_is_refused(self, store: OutboundApprovalStore) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        assert store.resolve(row.id, "denied") is not None
        assert store.resolve(row.id, "denied") is None

    def test_concurrent_consume_loses_the_race(
        self, store: OutboundApprovalStore, monkeypatch
    ) -> None:
        """Single-use is enforced by the DB, not just by the pre-check.

        Simulates another process consuming the row in the window between the
        status read and the UPDATE.
        """
        import cato.core.outbound_approval as mod

        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        store.approve(row.id)
        real = mod.verify_ticket

        def racing_verify(*a, **kw):
            result = real(*a, **kw)
            store._conn.execute(
                "UPDATE outbound_approvals SET status='consumed', consumed_at=1 WHERE id=?",
                (row.id,),
            )
            store._conn.commit()
            return result

        monkeypatch.setattr(mod, "verify_ticket", racing_verify)
        with pytest.raises(TicketError) as exc:
            store.consume(row.id)
        assert str(exc.value) == "ticket_already_consumed"

    def test_invalid_status_returns_none(self, store: OutboundApprovalStore) -> None:
        row = store.create("sess-1", "send_email", {"to": "a@b.com"})
        assert store.resolve(row.id, "maybe") is None

    def test_get_missing_returns_none(self, store: OutboundApprovalStore) -> None:
        assert store.get("nope") is None

    def test_list_pending_excludes_resolved(self, store: OutboundApprovalStore) -> None:
        a = store.create("s", "send_email", {"to": "a@b.com"})
        b = store.create("s", "send_email", {"to": "c@d.com"})
        store.approve(a.id)
        pending = store.list_pending()
        assert [p.id for p in pending] == [b.id]

    def test_ticket_token_of_unknown_id_is_empty(self, store: OutboundApprovalStore) -> None:
        assert store.ticket_token("nope") == ""

    def test_env_signing_key_is_used(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("CATO_APPROVAL_SIGNING_KEY", "aa" * 32)
        s = OutboundApprovalStore(db_path=tmp_path / "k.db")
        assert s._signing_key == bytes.fromhex("aa" * 32)
        s.close()

    def test_non_hex_env_signing_key_is_accepted_as_bytes(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("CATO_APPROVAL_SIGNING_KEY", "a-passphrase-not-hex")
        s = OutboundApprovalStore(db_path=tmp_path / "k2.db")
        assert s._signing_key == b"a-passphrase-not-hex"
        s.close()

    def test_signing_key_persists_across_reopen(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("CATO_APPROVAL_SIGNING_KEY", raising=False)
        db = tmp_path / "persist.db"
        s1 = OutboundApprovalStore(db_path=db)
        key1 = s1._signing_key
        s1.close()
        s2 = OutboundApprovalStore(db_path=db)
        assert s2._signing_key == key1
        s2.close()

    def test_legacy_database_migrates_in_place(self, tmp_path: Path) -> None:
        """An existing cato.db without the ticket columns must upgrade."""
        import sqlite3

        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(
            """CREATE TABLE outbound_approvals (
                   id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                   tool_name TEXT NOT NULL, args_json TEXT NOT NULL,
                   preview TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
                   created_at REAL NOT NULL, resolved_at REAL,
                   resolved_by TEXT NOT NULL DEFAULT '');
               INSERT INTO outbound_approvals
                   (id, session_id, tool_name, args_json, created_at)
               VALUES ('old1', 's', 'send_email', '{"to":"a@b.com"}', 1.0);"""
        )
        conn.commit()
        conn.close()

        s = OutboundApprovalStore(db_path=db)
        old = s.get("old1")
        assert old is not None and old.args_digest == ""
        # New rows get full ticket metadata.
        fresh = s.create("s", "send_email", {"to": "x@y.com"})
        assert fresh.args_digest
        s.close()


# ===========================================================================
# D. Redaction before persist and before display
# ===========================================================================


class TestRedaction:
    NESTED = {
        "to": "victim@example.com",
        "subject": "hi",
        "headers": {"authorization": f"Bearer {SECRET}"},
        "auth": {"nested": {"deeper": {"api_key": SECRET}}},
        "config": [{"password": SECRET}, {"safe": "value"}],
        "note": f"my key is {SECRET} ok",
    }

    def test_nested_credential_absent_from_persisted_row(
        self, store: OutboundApprovalStore
    ) -> None:
        row = store.create("sess-1", "send_email", dict(self.NESTED))
        raw = store._conn.execute(
            "SELECT args_json, preview FROM outbound_approvals WHERE id = ?", (row.id,)
        ).fetchone()
        assert SECRET not in raw["args_json"], "secret reached SQLite"
        assert SECRET not in raw["preview"], "secret reached the preview column"
        # And nothing anywhere in the whole DB file.
        blob = Path(store._db_path).read_bytes()
        assert SECRET.encode() not in blob

    def test_nested_credential_absent_from_preview(self) -> None:
        preview = build_preview("send_email", dict(self.NESTED))
        assert SECRET not in preview
        assert "[redacted]" in preview

    def test_caller_supplied_preview_is_scrubbed(self, store: OutboundApprovalStore) -> None:
        """Even a caller that hand-builds an unredacted preview cannot leak."""
        row = store.create(
            "sess-1", "send_email", {"to": "a@b.com"},
            preview=f"Authorization: Bearer {SECRET}",
        )
        assert SECRET not in row.preview
        raw = store._conn.execute(
            "SELECT preview FROM outbound_approvals WHERE id = ?", (row.id,)
        ).fetchone()
        assert SECRET not in raw["preview"]

    def test_top_level_only_redaction_would_have_missed_this(self) -> None:
        """The exact case audit_log._sanitize_inputs misses."""
        out = redact({"headers": {"authorization": f"Bearer {SECRET}"}})
        assert out["headers"]["authorization"] == "[redacted]"

    def test_redaction_reaches_into_lists(self) -> None:
        out = redact({"items": [{"token": SECRET}, {"ok": 1}]})
        assert out["items"][0]["token"] == "[redacted]"
        assert out["items"][1]["ok"] == 1

    def test_redaction_catches_secret_shaped_values_under_innocent_keys(self) -> None:
        out = redact({"note": f"here: {SECRET}"})
        assert SECRET not in out["note"]

    def test_redaction_preserves_non_sensitive_data(self) -> None:
        out = redact({"to": "a@b.com", "count": 3, "ok": True, "none": None})
        assert out == {"to": "a@b.com", "count": 3, "ok": True, "none": None}

    def test_redaction_keeps_boolean_sensitive_flags_readable(self) -> None:
        """has_token=False is useful signal and is not itself a secret."""
        assert redact({"has_token": False}) == {"has_token": False}

    def test_redaction_is_depth_bounded(self) -> None:
        deep: dict = {}
        cur = deep
        for _ in range(60):
            cur["n"] = {}
            cur = cur["n"]
        cur["value"] = SECRET
        out = redact(deep)
        assert SECRET not in json.dumps(out)

    def test_redaction_handles_non_serializable_values(self) -> None:
        out = redact({"obj": object()})
        assert isinstance(out["obj"], str)

    def test_approved_args_returned_by_consume_are_redacted(
        self, store: OutboundApprovalStore
    ) -> None:
        """Credentials must come from the vault, never replayed from a ticket."""
        row = store.create("sess-1", "send_email", dict(self.NESTED))
        store.approve(row.id)
        _, approved_args = store.consume(row.id)
        assert SECRET not in json.dumps(approved_args)
        assert approved_args["to"] == "victim@example.com"


# ===========================================================================
# E. Dispatcher sub-action routing (file / browser)
#
# These tools carry their real capability in args["action"], so tiering them by
# name alone would either gate every file read or wave through every file
# write. Tiers must agree with cato/safety.py::_TOOL_TIER.
# ===========================================================================


class TestDispatcherSubActions:
    @pytest.mark.parametrize(
        "action", ["navigate", "navigate_back", "extract", "extract_main", "screenshot",
                   "search", "snapshot", "accessibility_snapshot", "network_requests",
                   "console_messages", "wait", "wait_for", "scroll", "hover"],
    )
    def test_browser_read_actions_do_not_gate(self, action: str) -> None:
        assert requires_approval("browser", {"action": action}) is False, action

    @pytest.mark.parametrize(
        "action", ["click", "type", "fill", "key_press", "select_option",
                   "handle_dialog", "pdf", "output_to_file"],
    )
    def test_browser_reversible_actions_do_not_gate(self, action: str) -> None:
        assert requires_approval("browser", {"action": action}) is False, action

    def test_browser_eval_gates(self) -> None:
        """browser.eval runs attacker-reachable JS — IRREVERSIBLE in safety.py."""
        d = approval_decision("browser", {"action": "eval", "script": "fetch('/x')"})
        assert d.canonical == "browser_eval"
        assert d.tier == "elevated"
        assert d.decision == REQUIRE

    @pytest.mark.parametrize("action", ["read", "list", "exists", "roots"])
    def test_file_read_actions_do_not_gate(self, action: str) -> None:
        assert requires_approval("file", {"action": action, "path": "x.txt"}) is False

    @pytest.mark.parametrize("action", ["write", "append", "patch", "delete"])
    def test_file_write_actions_gate(self, action: str) -> None:
        d = approval_decision("file", {"action": action, "path": "x.txt"})
        assert d.tier == "elevated"
        assert d.decision == REQUIRE, action

    def test_read_and_write_are_different_tiers(self) -> None:
        """The whole point of the sub-action mechanism."""
        assert approval_decision("file", {"action": "read"}).tier == "read_only"
        assert approval_decision("file", {"action": "write"}).tier == "elevated"

    def test_dispatcher_without_action_fails_closed(self) -> None:
        for tool in ("browser", "file"):
            d = approval_decision(tool, {})
            assert d.tier == "critical"
            assert d.decision == REQUIRE, tool

    @pytest.mark.parametrize("bad", [{"action": ""}, {"action": "   "}, {"action": 123},
                                     {"action": None}, {"action": ["read"]}])
    def test_dispatcher_with_unreadable_action_fails_closed(self, bad: dict) -> None:
        assert requires_approval("file", bad) is True

    def test_unknown_sub_action_fails_closed(self) -> None:
        d = approval_decision("file", {"action": "chmod"})
        assert d.canonical == "file_chmod"
        assert d.reason == "unknown_tool_default_require"
        assert d.decision == REQUIRE

    def test_op_and_operation_keys_are_honoured(self) -> None:
        """Same key precedence as safety.py::_dispatcher_key."""
        assert requires_approval("file", {"op": "read"}) is False
        assert requires_approval("file", {"operation": "read"}) is False
        assert requires_approval("file", {"op": "delete"}) is True

    def test_action_key_cannot_redirect_a_non_dispatcher_tool(self) -> None:
        """Only rules marked `dispatcher` ever read args for identity."""
        for sneaky in ({"action": "read"}, {"op": "list"}, {"operation": "exists"}):
            d = approval_decision("send_email", sneaky)
            assert d.canonical == "send_email"
            assert d.decision == REQUIRE, sneaky

    def test_sub_action_is_bound_into_the_ticket(self) -> None:
        """An approval for file.read must not authorise file.delete."""
        read_args = {"action": "read", "path": "x.txt"}
        ticket, token = issue_ticket(KEY, "appr-1", "file", read_args)
        assert ticket.tool == "file_read"
        with pytest.raises(TicketError):
            verify_ticket(KEY, token, "file", {"action": "delete", "path": "x.txt"})

    def test_dispatcher_digests_differ_per_sub_action(self) -> None:
        assert compute_args_digest("file", {"action": "read"}) != compute_args_digest(
            "file", {"action": "delete"}
        )

    def test_store_records_the_resolved_sub_action(
        self, store: OutboundApprovalStore
    ) -> None:
        row = store.create("s", "file", {"action": "delete", "path": "x.txt"})
        assert row.canonical_tool == "file_delete"
        store.approve(row.id)
        ticket, _ = store.consume(row.id)
        assert ticket.tool == "file_delete"


class TestPolicyMatchesSafetyTable:
    """Where both gates classify a call, they must agree about its risk.

    This policy is deliberately NOT a mirror of safety.py::_TOOL_TIER.
    safety.py falls through to this policy for anything its own table does not
    cover (safety.py::classify_action -> _policy_tier), so duplicating a row
    here that safety.py already owns creates two sources of truth AND softens
    safety.py's "deleting a row must escalate" property — deletion would fall
    through to this policy's copy instead of escalating to UNCLASSIFIED.

    So the invariant under test is agreement, not duplication.
    """

    # Tools this policy deliberately tiers ABOVE safety.py, with the reason.
    # safety.py classifies reversibility of local effect; this policy classifies
    # external blast radius. Divergence is only ever allowed upward.
    DELIBERATE_DIVERGENCE = {
        "integration.action": "reaches Stripe/GitHub/Vercel third-party writes",
    }

    def test_policy_and_safety_agree_wherever_both_classify(self) -> None:
        from cato.safety import _POLICY_TIER_TO_RISK, _TOOL_TIER

        inverse: dict = {}
        for policy_tier, risk in _POLICY_TIER_TO_RISK.items():
            inverse.setdefault(risk, set()).add(policy_tier)

        pol = load_policy()
        mismatches = []
        checked = 0
        for name, risk in sorted(_TOOL_TIER.items()):
            if name in self.DELIBERATE_DIVERGENCE:
                continue
            base = name.split(".", 1)[0]
            if base in ("browser", "file") and "." in name:
                rule = resolve_tool(base, pol, args={"action": name.split(".", 1)[1]})
            else:
                rule = resolve_tool(name, pol)
            if not rule.known:
                continue  # safety.py owns it exclusively; nothing to disagree about
            checked += 1
            if rule.tier not in inverse.get(risk, set()):
                mismatches.append((name, risk.name, rule.tier))
        assert not mismatches, f"policy/safety.py tier drift: {mismatches}"
        assert checked >= 40, f"only {checked} rows overlapped — coverage collapsed"

    def test_deliberate_divergences_are_strictly_more_restrictive(self) -> None:
        """A documented divergence may only ever tighten, never loosen."""
        from cato.safety import _POLICY_TIER_TO_RISK, _TOOL_TIER

        pol = load_policy()
        for name in self.DELIBERATE_DIVERGENCE:
            safety_risk = _TOOL_TIER[name]
            rule = resolve_tool(name, pol)
            policy_risk = _POLICY_TIER_TO_RISK[rule.tier]
            assert policy_risk > safety_risk, (
                f"{name}: policy tier {rule.tier} ({policy_risk.name}) is not "
                f"stricter than safety.py {safety_risk.name}"
            )
            assert requires_approval(name, {}) is True, name

    def test_policy_does_not_shadow_safety_only_tools(self) -> None:
        """Regression for test_safety_failclosed's deletion-escalates property.

        A tool safety.py classifies by itself must stay UNKNOWN here, so that
        removing its safety.py row escalates it to UNCLASSIFIED instead of
        quietly landing on a duplicate row in this policy.
        """
        for safety_only in ("memory.store", "integration.setup",
                            "academic.pubmed", "academic.semantic_scholar"):
            assert resolve_tool(safety_only).known is False, safety_only

    def test_the_previously_unclassified_tools_are_now_classified(self) -> None:
        """Regression: these all resolved to unknown_tool_default_require and
        made the daemon unusable by holding every browser click for approval."""
        for name in ("browser", "file", "conduit.crawl", "conduit.monitor",
                     "web.code", "web.news", "graph.related", "integration.action"):
            assert resolve_tool(name).known is True, name

    def test_integration_action_is_not_read_only(self) -> None:
        """integration.action is a third-party WRITE; integration.status is a read.

        Re-tiered from `reversible` to `financial`: `reversible` clears without
        an approval ticket, and this tool reaches Stripe/GitHub/Vercel writes.
        """
        assert approval_decision("integration.status", {}).tier == "read_only"
        assert approval_decision("integration.action", {}).tier == "financial"
        assert requires_approval("integration.action", {}) is True


# ===========================================================================
# E2. integration.action — the third instance of the model-supplied-boolean
#     authorization bug, this one reaching live money.
# ===========================================================================


class TestIntegrationActionIsGated:
    def test_integration_action_always_requires_approval(self) -> None:
        assert requires_approval("integration.action", {}) is True

    @pytest.mark.parametrize(
        "args",
        [
            {"approved": True},
            {"approved": True, "dry_run": False},
            {"dry_run": False},
            {"approved": "true", "dry_run": "false"},
            {"integration": "stripe", "action": "create_payment_link",
             "approved": True, "dry_run": False},
        ],
    )
    def test_model_supplied_flags_are_inert(self, args: dict) -> None:
        """The exact bypass shape: none of these may clear the gate."""
        assert requires_approval("integration.action", args) is True, args

    def test_tier_is_financial_not_reversible(self) -> None:
        d = approval_decision("integration.action", {"approved": True})
        assert d.tier == "financial"
        assert d.reason == "tier:financial:always"

    def test_caller_simulation_context_cannot_downgrade_it(self) -> None:
        ctx = ApprovalContext(actor="scheduler", simulation_authorized=True)
        assert requires_approval("integration.action", {}, context=ctx) is True

    def test_integration_status_still_runs_free(self) -> None:
        """Tightening the write path must not gate the read path."""
        assert requires_approval("integration.status", {}) is False


class TestExecutionGrants:
    """Authorization that cannot be expressed as a JSON tool argument."""

    def setup_method(self) -> None:
        clear_execution_grants()

    def teardown_method(self) -> None:
        clear_execution_grants()

    def test_no_grant_means_not_authorized(self) -> None:
        assert take_execution_grant("integration.action", {"integration": "stripe"}) is False

    def test_grant_authorizes_exactly_once(self) -> None:
        args = {"integration": "stripe", "action": "create_payment_link"}
        grant_execution("integration_action", compute_args_digest("integration.action", args))
        assert take_execution_grant("integration.action", args) is True
        assert take_execution_grant("integration.action", args) is False

    def test_grant_is_bound_to_the_exact_payload(self) -> None:
        approved = {"integration": "stripe", "action": "create_payment_link",
                    "params": {"amount": 100}}
        grant_execution("integration_action", compute_args_digest("integration.action", approved))
        tampered = dict(approved, params={"amount": 999999})
        assert take_execution_grant("integration.action", tampered) is False
        assert take_execution_grant("integration.action", approved) is True

    def test_grant_for_one_tool_does_not_authorize_another(self) -> None:
        args = {"a": 1}
        grant_execution("integration_action", compute_args_digest("integration.action", args))
        assert take_execution_grant("send_email", args) is False

    def test_grant_expires(self) -> None:
        grants = ExecutionGrants(ttl=10.0)
        grants.grant("t", "d", now=1000.0)
        assert grants.take("t", "d", now=1005.0) is True
        grants.grant("t", "d", now=1000.0)
        assert grants.take("t", "d", now=1011.0) is False

    def test_consume_mints_a_grant_for_the_approved_payload(
        self, store: OutboundApprovalStore
    ) -> None:
        args = {"integration": "stripe", "action": "create_payment_link"}
        row = store.create("s", "integration.action", args)
        store.approve(row.id)
        assert take_execution_grant("integration.action", args) is False  # not yet
        _, approved_args = store.consume(row.id)
        assert take_execution_grant("integration.action", approved_args) is True
        assert take_execution_grant("integration.action", approved_args) is False

    def test_failed_consume_mints_no_grant(self, store: OutboundApprovalStore) -> None:
        args = {"integration": "stripe", "action": "create_payment_link"}
        row = store.create("s", "integration.action", args)
        # never approved
        with pytest.raises(TicketError):
            store.consume(row.id)
        assert take_execution_grant("integration.action", args) is False


class TestIntegrationToolCannotSelfAuthorize:
    """End-to-end at the tool boundary, with a fake transport.

    No network I/O occurs: cato.integrations.runtime.request_json is replaced,
    and the assertion is that it is never called.
    """

    def setup_method(self) -> None:
        clear_execution_grants()

    def teardown_method(self) -> None:
        clear_execution_grants()

    @staticmethod
    def _fake_transport(calls: list) -> object:
        def _fake_request_json(*, method, url, headers, body, body_format, timeout):
            calls.append({"method": method, "url": url})

            class _Resp:
                status = 200

                def as_dict(self) -> dict:
                    return {"status": 200, "body": {"id": "pl_fake"}}

            return _Resp()

        return _fake_request_json

    STRIPE_WRITE = {
        "integration": "stripe",
        "action": "create_payment_link",
        "params": {"line_items[0][price]": "price_fake", "line_items[0][quantity]": 1},
    }

    @pytest.mark.asyncio
    async def test_model_supplied_approved_reaches_no_live_call(self, monkeypatch) -> None:
        from cato.tools.integration_tool import IntegrationTool

        calls: list = []
        monkeypatch.setattr(
            "cato.integrations.runtime.request_json", self._fake_transport(calls)
        )
        tool = IntegrationTool()
        out = json.loads(await tool.action(
            {**self.STRIPE_WRITE, "approved": True, "dry_run": False}
        ))
        assert out["ok"] is False
        assert out["error"] == "approval_required"
        assert calls == [], "a live third-party write happened with no ticket"

    @pytest.mark.asyncio
    async def test_no_flags_at_all_plans_only(self, monkeypatch) -> None:
        from cato.tools.integration_tool import IntegrationTool

        calls: list = []
        monkeypatch.setattr(
            "cato.integrations.runtime.request_json", self._fake_transport(calls)
        )
        out = json.loads(await IntegrationTool().action(dict(self.STRIPE_WRITE)))
        assert out["dry_run"] is True
        assert calls == []

    @pytest.mark.asyncio
    async def test_a_redeemed_ticket_authorizes_the_live_call(
        self, store: OutboundApprovalStore, monkeypatch
    ) -> None:
        """The approved path must still work end to end."""
        from cato.tools.integration_tool import IntegrationTool

        calls: list = []
        monkeypatch.setattr(
            "cato.integrations.runtime.request_json", self._fake_transport(calls)
        )
        monkeypatch.setattr(
            "cato.integrations.runtime.resolve_credential_groups",
            lambda vault, groups: [
                SimpleNamespace(found=True, value="fake-key", public_dict=lambda: {})
            ],
        )

        row = store.create("s", "integration.action", dict(self.STRIPE_WRITE))
        store.approve(row.id, resolved_by="operator")
        _, approved_args = store.consume(row.id)

        out = json.loads(await IntegrationTool().action(approved_args))
        assert out["dry_run"] is False
        assert len(calls) == 1, "the approved live call did not happen"

    @pytest.mark.asyncio
    async def test_ticket_for_one_action_cannot_run_a_different_one(
        self, store: OutboundApprovalStore, monkeypatch
    ) -> None:
        from cato.tools.integration_tool import IntegrationTool

        calls: list = []
        monkeypatch.setattr(
            "cato.integrations.runtime.request_json", self._fake_transport(calls)
        )
        row = store.create("s", "integration.action", dict(self.STRIPE_WRITE))
        store.approve(row.id)
        store.consume(row.id)

        # Grant exists, but for create_payment_link — not for a refund.
        swapped = {**self.STRIPE_WRITE, "action": "create_refund"}
        out = json.loads(await IntegrationTool().action(
            {**swapped, "approved": True, "dry_run": False}
        ))
        assert out["error"] == "approval_required"
        assert calls == []

    @pytest.mark.asyncio
    async def test_trusted_python_context_authorizes(self, monkeypatch) -> None:
        """The other sanctioned source: an ApprovalContext from Python code."""
        from cato.tools.integration_tool import IntegrationTool

        calls: list = []
        monkeypatch.setattr(
            "cato.integrations.runtime.request_json", self._fake_transport(calls)
        )
        monkeypatch.setattr(
            "cato.integrations.runtime.resolve_credential_groups",
            lambda vault, groups: [
                SimpleNamespace(found=True, value="fake-key", public_dict=lambda: {})
            ],
        )
        out = json.loads(await IntegrationTool().action(
            dict(self.STRIPE_WRITE),
            context=ApprovalContext(actor="operator-cli", execution_authorized=True),
        ))
        assert out["dry_run"] is False
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_context_without_execution_authorization_does_not(self, monkeypatch) -> None:
        from cato.tools.integration_tool import IntegrationTool

        calls: list = []
        monkeypatch.setattr(
            "cato.integrations.runtime.request_json", self._fake_transport(calls)
        )
        out = json.loads(await IntegrationTool().action(
            {**self.STRIPE_WRITE, "approved": True},
            context=ApprovalContext(actor="model", simulation_authorized=True),
        ))
        assert out["error"] == "approval_required"
        assert calls == []

    @pytest.mark.asyncio
    async def test_malformed_params_rejected_before_any_call(self, monkeypatch) -> None:
        from cato.tools.integration_tool import IntegrationTool

        calls: list = []
        monkeypatch.setattr(
            "cato.integrations.runtime.request_json", self._fake_transport(calls)
        )
        out = json.loads(await IntegrationTool().action(
            {"integration": "stripe", "action": "create_payment_link",
             "params": "not-an-object", "approved": True, "dry_run": False}
        ))
        assert out["ok"] is False
        assert calls == []

    @pytest.mark.parametrize(
        "args,expected",
        [
            ({}, False),
            ({"dry_run": True}, False),
            ({"approved": False, "dry_run": True}, False),
            ({"approved": True}, True),
            ({"dry_run": False}, True),
            ({"approved": "yes"}, True),
            ({"dry_run": "off"}, True),
            ({"approved": 1}, True),
        ],
    )
    def test_live_write_request_detection(self, args: dict, expected: bool) -> None:
        """Detection only shapes the error message — it never authorizes."""
        from cato.tools.integration_tool import _requests_live_write

        assert _requests_live_write(args) is expected

    @pytest.mark.asyncio
    async def test_grant_is_single_use_at_the_tool_boundary(
        self, store: OutboundApprovalStore, monkeypatch
    ) -> None:
        from cato.tools.integration_tool import IntegrationTool

        calls: list = []
        monkeypatch.setattr(
            "cato.integrations.runtime.request_json", self._fake_transport(calls)
        )
        monkeypatch.setattr(
            "cato.integrations.runtime.resolve_credential_groups",
            lambda vault, groups: [
                SimpleNamespace(found=True, value="fake-key", public_dict=lambda: {})
            ],
        )
        row = store.create("s", "integration.action", dict(self.STRIPE_WRITE))
        store.approve(row.id)
        _, approved_args = store.consume(row.id)

        tool = IntegrationTool()
        first = json.loads(await tool.action(approved_args))
        assert first["dry_run"] is False
        # Replaying the identical approved payload must not execute again.
        second = json.loads(await tool.action(
            {**approved_args, "approved": True, "dry_run": False}
        ))
        assert second["error"] == "approval_required"
        assert len(calls) == 1


# ===========================================================================
# F. Redaction must not collide with ordinary tool arguments
# ===========================================================================


class TestRedactionDoesNotOverReach:
    def test_keyboard_key_argument_survives(self) -> None:
        """browser.key_press {"key": "Enter"} must reach the tool intact.

        A bare "key" in the sensitive-key list would make the tool press a
        literal "[redacted]". Guards against anyone adding one.
        """
        out = redact({"action": "key_press", "key": "Enter", "selector": "#search"})
        assert out["key"] == "Enter"
        assert out["action"] == "key_press"

    @pytest.mark.parametrize("value", ["Enter", "Tab", "Escape", "ArrowDown", "a"])
    def test_every_common_key_value_survives(self, value: str) -> None:
        assert redact({"key": value})["key"] == value

    def test_key_survives_the_full_approval_round_trip(
        self, store: OutboundApprovalStore
    ) -> None:
        """Through create -> approve -> consume, as the dispatch path runs it."""
        args = {"action": "key_press", "key": "Enter", "selector": "#search"}
        row = store.create("s", "browser", args)
        store.approve(row.id)
        _, approved_args = store.consume(row.id)
        assert approved_args["key"] == "Enter"

    def test_key_is_not_treated_as_sensitive(self) -> None:
        assert is_sensitive_key("key") is False
        assert is_sensitive_key("keys") is False
        assert is_sensitive_key("keyword") is False
        assert is_sensitive_key("monkey") is False

    # --- and the credentials must STILL be redacted -------------------------

    def test_api_key_is_still_redacted(self) -> None:
        assert redact({"api_key": SECRET})["api_key"] == "[redacted]"

    @pytest.mark.parametrize(
        "name", ["api_key", "apiKey", "api-key", "x-api-key", "private_key",
                 "session_key", "secret_key", "signing_key"],
    )
    def test_credential_key_variants_are_still_redacted(self, name: str) -> None:
        assert redact({name: SECRET})[name] == "[redacted]"

    def test_nested_authorization_header_is_still_redacted(self) -> None:
        out = redact({"headers": {"authorization": f"Bearer {SECRET}"}})
        assert out["headers"]["authorization"] == "[redacted]"

    def test_no_real_tool_argument_name_collides_with_redaction(self) -> None:
        """Scan every argument name Cato's tools actually read.

        This is the check that proves the redaction key list is not silently
        corrupting ordinary tool inputs anywhere in the codebase.
        """
        import pathlib
        import re

        import cato

        cato_root = pathlib.Path(cato.__file__).resolve().parent
        names: set[str] = set()
        for path in cato_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            names.update(
                m.group(1) for m in re.finditer(
                    r"(?:args|inputs|params|payload)\.get\(\s*['\"]([A-Za-z0-9_\-]+)['\"]",
                    text,
                )
            )
            names.update(
                m.group(1) for m in re.finditer(
                    r"['\"]([A-Za-z0-9_\-]+)['\"]\s*:\s*\{\s*['\"]type['\"]", text
                )
            )
        assert names, "scanner found no tool argument names — the regex broke"
        collisions = sorted(n for n in names if is_sensitive_key(n))
        assert collisions == [], (
            f"redaction would mask these real tool arguments: {collisions}"
        )


# ===========================================================================
# Cross-cutting: the digest binds tool + args, not just args
# ===========================================================================


class TestDigestBinding:
    def test_digest_is_stable_for_equal_payloads(self) -> None:
        a = compute_args_digest("send_email", {"b": 2, "a": 1})
        b = compute_args_digest("send_email", {"a": 1, "b": 2})
        assert a == b

    def test_digest_differs_across_tools(self) -> None:
        assert compute_args_digest("send_email", {}) != compute_args_digest("shell.exec", {})

    def test_digest_ignores_control_keys(self) -> None:
        """_approval_granted is stripped, so it cannot be used to grind digests."""
        assert compute_args_digest("send_email", {"to": "a"}) == compute_args_digest(
            "send_email", {"to": "a", "_approval_granted": True}
        )

    def test_digest_includes_execution_flags(self) -> None:
        assert compute_args_digest("send_email", {"draft_only": True}) != compute_args_digest(
            "send_email", {"draft_only": False}
        )
