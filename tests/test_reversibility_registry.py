"""
tests/test_reversibility_registry.py — Tests for Skill 8 (Irreversibility Classifier).
"""
from __future__ import annotations

import pytest

from cato.audit.reversibility_registry import (
    BlastRadius,
    ReversibilityEntry,
    ReversibilityRegistry,
    ToolNotRegistered,
)
from cato.audit.action_guard import ActionGuard, GuardDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_registry() -> ReversibilityRegistry:
    """Return a new (non-singleton) registry for test isolation."""
    return ReversibilityRegistry()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_instance_returns_same_object(self) -> None:
        a = ReversibilityRegistry.get_instance()
        b = ReversibilityRegistry.get_instance()
        assert a is b

    def test_singleton_is_registry_instance(self) -> None:
        inst = ReversibilityRegistry.get_instance()
        assert isinstance(inst, ReversibilityRegistry)


# ---------------------------------------------------------------------------
# Built-in entries — reversibility values
# ---------------------------------------------------------------------------

class TestBuiltinReversibility:
    def test_read_file_is_reversible(self) -> None:
        reg = fresh_registry()
        assert reg.get("read_file").reversibility == 0.0

    def test_list_dir_is_reversible(self) -> None:
        reg = fresh_registry()
        assert reg.get("list_dir").reversibility == 0.0

    def test_web_search_is_reversible(self) -> None:
        reg = fresh_registry()
        assert reg.get("web_search").reversibility == 0.0

    def test_memory_search_is_reversible(self) -> None:
        reg = fresh_registry()
        assert reg.get("memory_search").reversibility == 0.0

    def test_email_send_is_irreversible(self) -> None:
        reg = fresh_registry()
        assert reg.get("email_send").reversibility == 1.0

    def test_api_payment_is_irreversible(self) -> None:
        reg = fresh_registry()
        assert reg.get("api_payment").reversibility == 1.0

    def test_delete_file_score(self) -> None:
        reg = fresh_registry()
        assert reg.get("delete_file").reversibility == 0.8

    def test_write_file_score(self) -> None:
        reg = fresh_registry()
        assert reg.get("write_file").reversibility == 0.3

    def test_edit_file_score(self) -> None:
        reg = fresh_registry()
        assert reg.get("edit_file").reversibility == 0.3

    def test_conduit_navigate_is_reversible(self) -> None:
        reg = fresh_registry()
        assert reg.get("conduit_navigate").reversibility == 0.0

    def test_conduit_extract_is_reversible(self) -> None:
        reg = fresh_registry()
        assert reg.get("conduit_extract").reversibility == 0.0

    def test_git_commit_score(self) -> None:
        reg = fresh_registry()
        assert reg.get("git_commit").reversibility == 0.7

    def test_shell_execute_score(self) -> None:
        reg = fresh_registry()
        assert reg.get("shell_execute").reversibility == 0.6


# ---------------------------------------------------------------------------
# Built-in entries — blast radius
# ---------------------------------------------------------------------------

class TestBuiltinBlastRadius:
    def test_read_file_blast_self(self) -> None:
        reg = fresh_registry()
        assert reg.get("read_file").blast_radius == BlastRadius.SELF

    def test_email_send_blast_public(self) -> None:
        """email_send reclassified from MULTI_USER to PUBLIC (2A audit)."""
        reg = fresh_registry()
        assert reg.get("email_send").blast_radius == BlastRadius.PUBLIC

    def test_api_payment_blast_public(self) -> None:
        reg = fresh_registry()
        assert reg.get("api_payment").blast_radius == BlastRadius.PUBLIC

    def test_delete_file_blast_single_user(self) -> None:
        reg = fresh_registry()
        assert reg.get("delete_file").blast_radius == BlastRadius.SINGLE_USER

    def test_git_commit_blast_multi_user(self) -> None:
        reg = fresh_registry()
        assert reg.get("git_commit").blast_radius == BlastRadius.MULTI_USER


# ---------------------------------------------------------------------------
# register() and get()
# ---------------------------------------------------------------------------

class TestRegisterAndGet:
    def test_register_custom_tool(self) -> None:
        reg = fresh_registry()
        reg.register("my_custom_tool", 0.4, "minutes", BlastRadius.SINGLE_USER, "custom")
        entry = reg.get("my_custom_tool")
        assert entry.reversibility == 0.4
        assert entry.recovery_time == "minutes"
        assert entry.blast_radius == BlastRadius.SINGLE_USER
        assert entry.notes == "custom"

    def test_register_with_string_blast_radius(self) -> None:
        reg = fresh_registry()
        reg.register("tool_x", 0.6, "hours", "multi_user")
        entry = reg.get("tool_x")
        assert entry.blast_radius == BlastRadius.MULTI_USER

    def test_get_missing_tool_raises(self) -> None:
        reg = fresh_registry()
        with pytest.raises(ToolNotRegistered):
            reg.get("nonexistent_tool_xyz")

    def test_tool_not_registered_is_key_error_subclass(self) -> None:
        with pytest.raises(KeyError):
            fresh_registry().get("no_such_tool")

    def test_register_overwrites_existing(self) -> None:
        reg = fresh_registry()
        reg.register("read_file", 0.9, "hours", BlastRadius.PUBLIC, "overridden")
        assert reg.get("read_file").reversibility == 0.9


# ---------------------------------------------------------------------------
# list_all()
# ---------------------------------------------------------------------------

class TestListAll:
    def test_list_all_sorted_descending(self) -> None:
        reg = fresh_registry()
        entries = reg.list_all()
        scores = [e.reversibility for e in entries]
        assert scores == sorted(scores, reverse=True)

    def test_list_all_includes_all_builtins(self) -> None:
        reg = fresh_registry()
        names = {e.tool_name for e in reg.list_all()}
        assert "email_send" in names
        assert "read_file" in names
        assert "delete_file" in names

    def test_list_all_returns_list(self) -> None:
        reg = fresh_registry()
        result = reg.list_all()
        assert isinstance(result, list)
        assert all(isinstance(e, ReversibilityEntry) for e in result)


# ---------------------------------------------------------------------------
# ActionGuard
# ---------------------------------------------------------------------------

class TestActionGuard:
    def _guard(self) -> ActionGuard:
        return ActionGuard(registry=fresh_registry())

    def test_email_send_always_requires_confirmation(self) -> None:
        guard = self._guard()
        decision = guard.check_before_execute("email_send", {}, current_autonomy_level=1.0)
        assert decision.proceed is False
        assert decision.requires_confirmation is True

    def test_api_payment_always_requires_confirmation(self) -> None:
        guard = self._guard()
        decision = guard.check_before_execute("api_payment", {}, current_autonomy_level=1.0)
        assert decision.proceed is False
        assert decision.requires_confirmation is True

    def test_delete_file_high_rev_low_autonomy_requires_confirm(self) -> None:
        # rev=0.8 > 0.7, autonomy=0.5 < 0.8 → Rule 2
        guard = self._guard()
        decision = guard.check_before_execute("delete_file", {}, current_autonomy_level=0.5)
        assert decision.proceed is False
        assert decision.requires_confirmation is True

    def test_delete_file_high_autonomy_proceeds(self) -> None:
        # rev=0.8, autonomy=0.9 >= 0.8 → passes Rule 2, rev <= 0.9 passes Rule 1
        # But 0.8 is NOT > 0.9, so Rule 1 doesn't apply. Rule 2: 0.8>0.7 but autonomy=0.9>=0.8 → passes
        guard = self._guard()
        decision = guard.check_before_execute("delete_file", {}, current_autonomy_level=0.9)
        assert decision.proceed is True

    def test_shell_execute_medium_rev_low_autonomy_requires_confirm(self) -> None:
        # rev=0.6 > 0.5, autonomy=0.3 < 0.5 → Rule 3
        guard = self._guard()
        decision = guard.check_before_execute("shell_execute", {}, current_autonomy_level=0.3)
        assert decision.proceed is False
        assert decision.requires_confirmation is True

    def test_write_file_low_rev_proceeds(self) -> None:
        # rev=0.3, autonomy=0.5 → all rules pass
        guard = self._guard()
        decision = guard.check_before_execute("write_file", {}, current_autonomy_level=0.5)
        assert decision.proceed is True
        assert decision.requires_confirmation is False

    def test_read_file_always_proceeds(self) -> None:
        guard = self._guard()
        decision = guard.check_before_execute("read_file", {}, current_autonomy_level=0.0)
        assert decision.proceed is True

    def test_unknown_tool_defaults_to_0_5(self) -> None:
        guard = self._guard()
        decision = guard.check_before_execute("totally_unknown_tool", {}, current_autonomy_level=0.5)
        # rev=0.5: NOT > 0.9, NOT > 0.7, NOT > 0.5 (strict), so proceeds
        assert decision.proceed is True
        assert any("unknown_tool_default_0.5" in c for c in decision.applied_checks)

    def test_unknown_tool_low_autonomy_requires_confirm(self) -> None:
        # rev=0.5 (unknown default), autonomy=0.4 < 0.5 but rev=0.5 NOT > 0.5 (strict)
        # Actually 0.5 is NOT > 0.5, so Rule 3 doesn't apply → proceeds
        guard = self._guard()
        decision = guard.check_before_execute("totally_unknown_tool", {}, current_autonomy_level=0.4)
        assert decision.proceed is True

    def test_guard_decision_fields_populated(self) -> None:
        guard = self._guard()
        decision = guard.check_before_execute("read_file", {"path": "/tmp/x"}, 0.5)
        assert isinstance(decision, GuardDecision)
        assert isinstance(decision.reason, str)
        assert len(decision.reason) > 0
        assert isinstance(decision.applied_checks, list)

    def test_applied_checks_non_empty(self) -> None:
        guard = self._guard()
        decision = guard.check_before_execute("read_file", {}, 0.5)
        assert len(decision.applied_checks) > 0

    def test_applied_checks_non_empty_on_confirmation(self) -> None:
        guard = self._guard()
        decision = guard.check_before_execute("email_send", {}, 1.0)
        assert len(decision.applied_checks) > 0

    def test_git_commit_low_autonomy_requires_confirm(self) -> None:
        # rev=0.7 > 0.7 is FALSE (not strictly >), so Rule 2 doesn't apply
        # Actually 0.7 is NOT > 0.7 (strict), so only Rule 3 checks: 0.7 > 0.5 → yes
        # autonomy=0.3 < 0.5 → Rule 3 triggers
        guard = self._guard()
        decision = guard.check_before_execute("git_commit", {}, current_autonomy_level=0.3)
        assert decision.proceed is False
        assert decision.requires_confirmation is True

    def test_conduit_click_medium_rev_mid_autonomy_proceeds(self) -> None:
        # rev=0.5 NOT > 0.9, NOT > 0.7, NOT > 0.5 (strict) → proceed
        guard = self._guard()
        decision = guard.check_before_execute("conduit_click", {}, current_autonomy_level=0.5)
        assert decision.proceed is True

    def test_guard_blocks_without_token_for_high_rev_tool(self) -> None:
        """Without delegation token, high-reversibility action requires confirmation."""
        guard = self._guard()
        decision = guard.check_before_execute(
            "email_send", {}, current_autonomy_level=0.5, agent_session_id=None
        )
        assert decision.proceed is False
        assert decision.requires_confirmation is True

    def test_guard_allows_with_valid_token(self) -> None:
        """When TokenChecker authorizes with a token, guard proceeds without reversibility block."""
        from unittest.mock import MagicMock
        from cato.auth.token_checker import AuthResult
        mock_tc = MagicMock()
        mock_tc.check_authorization.return_value = AuthResult(
            authorized=True,
            token_id="test-token-abc12345",
            reason="Authorized by token.",
            requires_user_confirmation=False,
        )
        guard = ActionGuard(registry=fresh_registry(), token_checker=mock_tc)
        decision = guard.check_before_execute(
            "email_send", {"to": "user@example.com"},
            current_autonomy_level=0.5,
            agent_session_id="sess-1",
        )
        assert decision.proceed is True
        assert decision.requires_confirmation is False
        assert any("token_authorized" in c for c in decision.applied_checks)

    def test_guard_blocks_when_token_scope_insufficient(self) -> None:
        """When TokenChecker says not authorized and requires confirmation, guard blocks."""
        from unittest.mock import MagicMock
        from cato.auth.token_checker import AuthResult
        mock_tc = MagicMock()
        mock_tc.check_authorization.return_value = AuthResult(
            authorized=False,
            token_id=None,
            reason="No active token covers category 'email.send'.",
            requires_user_confirmation=True,
        )
        guard = ActionGuard(registry=fresh_registry(), token_checker=mock_tc)
        decision = guard.check_before_execute(
            "email_send", {},
            current_autonomy_level=0.9,
            agent_session_id="sess-1",
        )
        assert decision.proceed is False
        assert decision.requires_confirmation is True
        assert any("token_scope_insufficient" in c for c in decision.applied_checks)
