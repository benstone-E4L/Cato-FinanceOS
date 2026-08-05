"""P0-1 — cato/safety.py must fail CLOSED on anything it cannot identify.

The defect this file locks down: `classify_action` used to return
`RiskTier.REVERSIBLE_WRITE` for any tool missing from `_TOOL_TIER`, and
`check_and_confirm` auto-allowed anything below the IRREVERSIBLE threshold.
Together that meant a tool nobody had ever classified — say `xero_post_bill` —
executed with no gate at all.

The contract now:
  * unknown tool  -> most restrictive tier (HIGH_STAKES) and never auto-allowed
  * removing a tool from the table makes it MORE restricted, not less
  * no non-interactive path can turn into an allow
"""

from __future__ import annotations

import pytest

from cato.safety import (
    UNCLASSIFIED_TIER,
    RiskTier,
    SafetyGuard,
    _TOOL_TIER,
    _is_interactive,
)


# Names that do not exist anywhere in Cato, the approval policy, or the
# reversibility registry. These stand in for "the tool someone adds next week".
INVENTED_TOOLS = [
    "xero_post_bill",
    "wire_transfer_send",
    "quickbooks.post_journal_entry",
    "payroll_run_now",
    "totally_new_capability_v2",
]


@pytest.fixture()
def strict_guard(tmp_path, monkeypatch):
    """A strict-mode guard whose STOP file lives in a temp dir."""
    monkeypatch.setattr(SafetyGuard, "_stop_file_path", staticmethod(lambda: tmp_path / "STOP"))
    return SafetyGuard(config={"safety_mode": "strict"})


# ---------------------------------------------------------------------------
# 1. Unknown tools classify at the top tier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool_name", INVENTED_TOOLS)
def test_invented_tool_classifies_at_most_restrictive_tier(strict_guard, tool_name):
    tier = strict_guard.classify_action(tool_name, {"amount": 100_000})
    assert tier == UNCLASSIFIED_TIER
    assert tier == RiskTier.HIGH_STAKES
    # It is genuinely the maximum, not merely "high".
    assert tier == max(RiskTier)


@pytest.mark.parametrize("tool_name", INVENTED_TOOLS)
def test_invented_tool_is_not_auto_allowed(strict_guard, tool_name, monkeypatch):
    """The whole point: no gate must wave this through.

    `input()` is replaced with a bomb so that an accidental fallthrough to the
    interactive prompt is a test failure rather than a hang.
    """
    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)
    monkeypatch.setattr(
        "builtins.input",
        lambda *_a, **_k: pytest.fail("unclassified tool reached the human prompt path"),
    )
    assert strict_guard.check_and_confirm(tool_name, {"amount": 100_000}) is False


@pytest.mark.parametrize("mode", ["strict", "permissive", "off"])
def test_unknown_tool_denied_in_every_safety_mode(tmp_path, monkeypatch, mode):
    """Even `safety_mode: off` is not consent for an unreviewed capability."""
    monkeypatch.setattr(SafetyGuard, "_stop_file_path", staticmethod(lambda: tmp_path / "STOP"))
    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)
    guard = SafetyGuard(config={"safety_mode": mode, "shell_exec_allowed": True})
    assert guard.check_and_confirm("xero_post_bill", {"amount": 1}) is False


def test_removing_a_tool_from_the_table_makes_it_more_restricted(strict_guard, monkeypatch):
    """The regression that started this: deletion must escalate, not relax.

    `memory.store` is a REVERSIBLE_WRITE that is auto-allowed. Delete its row
    and it must become HIGH_STAKES and be denied — the opposite of the old
    `.get(name, REVERSIBLE_WRITE)` behaviour, where deleting a row from the
    table changed nothing at all.
    """
    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)

    assert strict_guard.classify_action("memory.store", {}) == RiskTier.REVERSIBLE_WRITE
    assert strict_guard.check_and_confirm("memory.store", {}) is True

    patched = dict(_TOOL_TIER)
    patched.pop("memory.store")
    monkeypatch.setattr("cato.safety._TOOL_TIER", patched)

    assert strict_guard.classify_action("memory.store", {}) == RiskTier.HIGH_STAKES
    assert strict_guard.check_and_confirm("memory.store", {}) is False


# ---------------------------------------------------------------------------
# 2. Dispatcher tools (`file` / `browser`) are classified by sub-action
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("tool", "action", "expected"),
    [
        ("browser", "navigate", RiskTier.READ),
        ("browser", "screenshot", RiskTier.READ),
        ("browser", "click", RiskTier.REVERSIBLE_WRITE),
        ("browser", "eval", RiskTier.IRREVERSIBLE),
        ("file", "read", RiskTier.READ),
        ("file", "write", RiskTier.IRREVERSIBLE),
        ("file", "delete", RiskTier.IRREVERSIBLE),
    ],
)
def test_dispatcher_subactions_classify_individually(strict_guard, tool, action, expected):
    assert strict_guard.classify_action(tool, {"action": action}) == expected


def test_dispatcher_with_unknown_subaction_fails_closed(strict_guard):
    assert strict_guard.classify_action("browser", {"action": "exfiltrate"}) == RiskTier.HIGH_STAKES
    assert strict_guard.classify_action("file", {"action": "chmod777"}) == RiskTier.HIGH_STAKES


def test_dispatcher_with_no_action_fails_closed(strict_guard):
    """A `file` call with no action could be anything, so it is treated as the worst."""
    assert strict_guard.classify_action("file", {}) == RiskTier.HIGH_STAKES
    assert strict_guard.classify_action("browser", {"action": ""}) == RiskTier.HIGH_STAKES


def test_empty_and_malformed_tool_names_fail_closed(strict_guard):
    assert strict_guard.classify_action("", {}) == UNCLASSIFIED_TIER
    assert strict_guard.classify_action("   ", {}) == UNCLASSIFIED_TIER
    assert strict_guard.classify_action(None, {}) == UNCLASSIFIED_TIER  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. The approval policy is consulted, so the two engines cannot disagree
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool_name",
    ["send_email", "telegram.send", "api.payment", "vault.set", "python.execute", "flow.run"],
)
def test_policy_gated_tools_are_high_stakes(strict_guard, tool_name):
    """Anything the approval policy always gates must also be HIGH_STAKES here."""
    assert strict_guard.classify_action(tool_name, {}) == RiskTier.HIGH_STAKES


@pytest.mark.parametrize("tool_name", ["web.search", "memory.search", "github.pr_list"])
def test_read_only_tools_still_flow(strict_guard, monkeypatch, tool_name):
    """Fail-closed must not mean fail-everything — reads still pass unattended."""
    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)
    assert strict_guard.classify_action(tool_name, {}) == RiskTier.READ
    assert strict_guard.check_and_confirm(tool_name, {"q": "x"}) is True


def test_policy_lookup_failure_denies(strict_guard, monkeypatch):
    """If the policy engine cannot be reached we escalate, never relax."""
    import cato.core.approval_policy as ap

    def _boom(*_a, **_k):
        raise RuntimeError("policy file corrupt")

    monkeypatch.setattr(ap, "resolve_tool", _boom)
    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)
    assert strict_guard.classify_action("some_unlisted_tool", {}) == RiskTier.HIGH_STAKES
    assert strict_guard.check_and_confirm("some_unlisted_tool", {}) is False


# ---------------------------------------------------------------------------
# 4. Shell classification (line 78 — previously uncovered)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("echo hello", RiskTier.REVERSIBLE_WRITE),
        ("rm -rf /tmp/x", RiskTier.IRREVERSIBLE),
        ("remove-item C:/x", RiskTier.IRREVERSIBLE),
        ("git push origin main", RiskTier.HIGH_STAKES),
        ("stripe payment create", RiskTier.HIGH_STAKES),
        ("mail -s hi bob@example.com", RiskTier.HIGH_STAKES),
    ],
)
def test_shell_command_tiers(strict_guard, command, expected):
    assert strict_guard.classify_action("shell.exec", {"command": command}) == expected


def test_shell_high_stakes_beats_irreversible(strict_guard):
    """A command that is both destructive and outbound takes the HIGHER tier."""
    tier = strict_guard.classify_action("shell", {"command": "rm old.txt && git push"})
    assert tier == RiskTier.HIGH_STAKES


def test_shell_with_non_dict_inputs_does_not_crash(strict_guard):
    assert strict_guard.classify_action("shell", None) == RiskTier.REVERSIBLE_WRITE  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. STOP file and the non-interactive deny path
# ---------------------------------------------------------------------------

def test_stop_file_halts_even_a_read(tmp_path, monkeypatch):
    monkeypatch.setattr(SafetyGuard, "_stop_file_path", staticmethod(lambda: tmp_path / "STOP"))
    guard = SafetyGuard(config={"safety_mode": "strict"})
    assert guard.check_and_confirm("web.search", {"q": "x"}) is True
    (tmp_path / "STOP").write_text("halt", encoding="utf-8")
    assert guard.is_stop_requested() is True
    assert guard.check_and_confirm("web.search", {"q": "x"}) is False


def test_non_interactive_denies_anything_with_no_downstream_human_gate(
    strict_guard, monkeypatch,
):
    """t14: a headless context still denies by default.

    The exception is narrow and deliberate — see
    ``SafetyGuard._defers_to_approval_gate``. A tool that is NOT positively
    classified has no downstream gate to defer to, so it is refused right here
    exactly as before.
    """
    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)
    assert strict_guard.check_and_confirm("wire_transfer_send", {"amount": 1}) is False
    assert strict_guard.check_and_confirm("file", {"action": "no_such_action"}) is False


def test_non_interactive_defers_high_tier_only_to_the_human_approval_gate(
    strict_guard, monkeypatch,
):
    """The headless deny used to make the Telegram approval flow unreachable:
    Cato ships safety_mode=strict and runs with no TTY, so every HIGH_STAKES /
    IRREVERSIBLE tool died here and never reached the gate a human answers.

    It now defers — but ONLY for a call the approval policy guarantees will be
    held for a human. That guarantee is what this test pins: whatever
    check_and_confirm lets through in a headless context must itself require an
    approval ticket.
    """
    from cato.core.approval_policy import evaluate

    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)
    for tool, args in [
        ("file", {"action": "delete", "path": "x"}),
        ("genesis", {"agent": "genesis-research", "task": "x"}),
        ("github.issue_create", {"title": "x"}),
        ("shell", {"command": "rm -rf /"}),
    ]:
        assert strict_guard.check_and_confirm(tool, args) is True, tool
        assert evaluate(tool, args).requires_approval is True, (
            f"{tool} was let past the safety gate but nothing downstream holds it"
        )


def test_headless_deferral_is_never_a_downgrade(strict_guard, monkeypatch):
    """Exhaustive invariant, not a spot check: across every tool the safety
    table knows about, a headless allow implies an approval requirement."""
    from cato.core.approval_policy import evaluate
    from cato.safety import _TOOL_TIER

    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)
    checked = 0
    for key in _TOOL_TIER:
        tool, _, action = key.partition(".")
        args = {"action": action} if tool in ("file", "browser") else {}
        name = tool if tool in ("file", "browser") else key
        if strict_guard.check_and_confirm(name, args):
            checked += 1
            tier = strict_guard.classify_action(name, args)
            from cato.safety import RiskTier

            if tier >= RiskTier.IRREVERSIBLE:
                assert evaluate(name, args).requires_approval is True, (
                    f"{key} cleared the headless safety gate with no human gate behind it"
                )
    assert checked, "the sweep asserted nothing"


def test_interactive_yes_allows_and_no_denies(strict_guard, monkeypatch):
    monkeypatch.setattr("cato.safety._is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "y")
    assert strict_guard.check_and_confirm("file", {"action": "delete"}) is True
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "")
    assert strict_guard.check_and_confirm("file", {"action": "delete"}) is False


def test_interactive_eof_denies(strict_guard, monkeypatch):
    monkeypatch.setattr("cato.safety._is_interactive", lambda: True)

    def _eof(*_a, **_k):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    assert strict_guard.check_and_confirm("file", {"action": "delete"}) is False


def test_is_interactive_handles_missing_and_broken_stdin(monkeypatch):
    """A detached daemon must read as 'cannot ask', not raise."""
    import sys as _sys

    monkeypatch.setattr(_sys, "stdin", None)
    assert _is_interactive() is False

    class _Broken:
        def isatty(self):
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(_sys, "stdin", _Broken())
    assert _is_interactive() is False


# ---------------------------------------------------------------------------
# 6. safety_mode: off still keeps its two carve-outs
# ---------------------------------------------------------------------------

def test_off_mode_still_blocks_shell_without_optin(tmp_path, monkeypatch):
    monkeypatch.setattr(SafetyGuard, "_stop_file_path", staticmethod(lambda: tmp_path / "STOP"))
    guard = SafetyGuard(config={"safety_mode": "off"})
    assert guard.check_and_confirm("shell.exec", {"command": "rm -rf /"}) is False

    opted_in = SafetyGuard(config={"safety_mode": "off", "shell_exec_allowed": True})
    assert opted_in.check_and_confirm("shell.exec", {"command": "rm -rf /"}) is True


def test_off_mode_allows_classified_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(SafetyGuard, "_stop_file_path", staticmethod(lambda: tmp_path / "STOP"))
    guard = SafetyGuard(config={"safety_mode": "off"})
    assert guard.check_and_confirm("browser", {"action": "navigate"}) is True
    assert guard.check_and_confirm("send_email", {"to": "a@b.c"}) is True


def test_is_classified_reports_the_truth(strict_guard):
    assert strict_guard.is_classified("web.search") is True
    assert strict_guard.is_classified("shell.exec") is True
    assert strict_guard.is_classified("send_email") is True
    assert strict_guard.is_classified("browser", {"action": "click"}) is True
    assert strict_guard.is_classified("browser", {"action": "nope"}) is False
    assert strict_guard.is_classified("xero_post_bill") is False
    assert strict_guard.is_classified("") is False
