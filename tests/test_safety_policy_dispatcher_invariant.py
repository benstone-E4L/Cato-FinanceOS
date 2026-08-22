"""
tests/test_safety_policy_dispatcher_invariant.py — the safety/policy boundary.

`cato/safety.py::_policy_tier` forwards the call's `inputs` into
`approval_policy.resolve_tool`, so the two gates resolve one call to one policy
row. That forwarding is only safe because of an invariant that, until this
module existed, nothing enforced:

    Of the policy rows that CONSUME `args`, every one except `genesis` is
    intercepted by `cato.safety._DISPATCHER_TOOLS` before `_policy_tier` is
    ever reached.

Today `file` and `browser` are the only `dispatcher: true` rows and both are in
`_DISPATCHER_TOOLS`, so the invariant holds — but it holds as an emergent
agreement between two independently-maintained sets, one of which lives in a
YAML file an operator can edit. Add a dispatcher row to
`docs/approval-policy.yaml` without touching `safety.py` and args-forwarding
silently starts lowering that tool's SafetyGuard classification.

BOTH SIDES ARE READ FROM SOURCE. Nothing here restates a set by hand — a
hardcoded expectation is precisely the thing that drifts. `test_drift_is_caught`
proves the check has teeth by running it against a synthetic drifted policy.

`genesis` is the single deliberate exemption: it consumes args and is NOT
intercepted, because its sub-capability resolution is reviewed separately in
`_resolve_genesis_rule` / tests/test_genesis_subaction_tiering.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from cato.core.approval_policy import GENESIS_CANONICAL, load_policy
from cato.safety import RiskTier, SafetyGuard, _DISPATCHER_TOOLS, _policy_tier

# Names `classify_action` routes to `_classify_shell`, which reads the command
# out of args by design. Not part of the dispatcher invariant; pinned below so
# that an accidental removal of shell classification is still noticed.
_SHELL_NAMES = ("shell", "shell.exec", "shell.run")

#: Args a hostile caller might attach hoping to redirect a policy row. Drawn
#: from every key any resolver in the codebase reads: the generic dispatcher
#: keys, the unsandboxed-root escape, and the genesis operation channel.
PROBE_ARGS: tuple[dict[str, Any], ...] = (
    {},
    {"action": "read"},
    {"action": "navigate"},
    {"action": "delete"},
    {"action": "eval"},
    {"op": "write"},
    {"operation": "get_trial_balance"},
    {"root": "absolute"},
    {"action": "read", "root": "absolute"},
    {"agent": "genesis-e4l-fs-integrity", "params": {"operation": "get_trial_balance"}},
)


def args_consuming_canonicals(policy: Any) -> set[str]:
    """Policy rows that read `args`, derived from the policy itself.

    Two sources, both authoritative: the `dispatcher` flag on each row, and the
    one canonical id `resolve_tool` special-cases by name.
    """
    return {c for c, r in policy.tools.items() if r.dispatcher} | {GENESIS_CANONICAL}


def unintercepted_args_consumers(policy: Any, intercepted: frozenset[str]) -> set[str]:
    """Args-consuming rows that reach `_policy_tier` — must be `genesis` alone."""
    return args_consuming_canonicals(policy) - set(intercepted) - {GENESIS_CANONICAL}


@pytest.fixture
def policy() -> Any:
    """The EFFECTIVE policy: built-ins merged with docs/approval-policy.yaml."""
    return load_policy(reload=True)


# ===========================================================================
# Invariant A — the structural one (FINDING 9)
# ===========================================================================


class TestDispatcherInterceptionInvariant:
    def test_every_args_consuming_row_except_genesis_is_intercepted(self, policy: Any) -> None:
        """The invariant `_policy_tier`'s args-forwarding depends on.

        If this fails, a policy row gained `dispatcher: true` without being
        added to `cato.safety._DISPATCHER_TOOLS`, and SafetyGuard has begun
        tiering it by a sub-action nobody reviewed. Fix by adding the tool to
        `_DISPATCHER_TOOLS` and tiering its sub-actions in `_TOOL_TIER`.
        """
        leaked = unintercepted_args_consumers(policy, _DISPATCHER_TOOLS)
        assert leaked == set(), (
            f"policy rows consume args but are not intercepted by safety.py: "
            f"{sorted(leaked)}"
        )

    def test_genesis_is_the_only_exemption_and_it_is_deliberate(self, policy: Any) -> None:
        """A second exemption must be a conscious edit to this test."""
        consumers = args_consuming_canonicals(policy)
        assert GENESIS_CANONICAL in consumers
        assert consumers - set(_DISPATCHER_TOOLS) == {GENESIS_CANONICAL}

    def test_interception_set_is_not_stale(self, policy: Any) -> None:
        """The reverse direction: `_DISPATCHER_TOOLS` naming a row that is no
        longer a dispatcher means safety.py is tiering by a sub-action the
        policy has stopped recognising."""
        stale = set(_DISPATCHER_TOOLS) - args_consuming_canonicals(policy)
        assert stale == set(), f"_DISPATCHER_TOOLS names non-dispatcher rows: {sorted(stale)}"

    def test_corpus_is_not_vacuous(self, policy: Any) -> None:
        assert args_consuming_canonicals(policy) >= {"file", "browser", GENESIS_CANONICAL}
        assert _DISPATCHER_TOOLS, "empty interception set would make the check vacuous"

    def test_drift_is_caught(self, policy: Any) -> None:
        """Proof the check has teeth: simulate the exact drift it guards.

        A new `dispatcher: true` row added to the policy without a matching
        `safety.py` edit must be reported, not silently tolerated.
        """
        from cato.core.approval_policy import ToolRule

        drifted = load_policy(reload=True)
        drifted.tools["xero_ledger"] = ToolRule(
            canonical="xero_ledger", tier="financial", dispatcher=True,
        )
        leaked = unintercepted_args_consumers(drifted, _DISPATCHER_TOOLS)
        assert leaked == {"xero_ledger"}

        # ...and is silent once safety.py is updated to match.
        repaired = unintercepted_args_consumers(
            drifted, frozenset(_DISPATCHER_TOOLS | {"xero_ledger"})
        )
        assert repaired == set()


# ===========================================================================
# Invariant B — the behaviour Invariant A protects
# ===========================================================================


class TestArgsAreInertForNonDispatchers:
    """Args must not move the tier of any row that does not consume them.

    This is the safety-layer mirror of the policy engine's own guarantee that
    "adding `action` to a non-dispatcher call cannot redirect its policy row".
    Every identity the policy can be addressed by is probed — canonical ids and
    aliases alike — because `_policy_tier` receives the raw model-supplied name.
    """

    @staticmethod
    def _probe_identities(policy: Any) -> list[str]:
        exempt = args_consuming_canonicals(policy)
        return sorted(
            name for name in set(policy.tools) | set(policy.aliases)
            if policy.aliases.get(name, name) not in exempt
        )

    def test_probe_set_is_substantial(self, policy: Any) -> None:
        assert len(self._probe_identities(policy)) > 50

    def test_no_args_change_the_policy_tier(self, policy: Any) -> None:
        violations = []
        for name in self._probe_identities(policy):
            base = _policy_tier(name, None)
            for args in PROBE_ARGS:
                got = _policy_tier(name, args)
                if got is not base:
                    violations.append((name, args, base.name, got.name))
        assert violations == [], f"args redirected a non-dispatcher row: {violations[:5]}"

    def test_no_args_change_the_safety_classification(self, policy: Any) -> None:
        guard = SafetyGuard(config={"safety_mode": "strict"})
        violations = []
        for name in self._probe_identities(policy):
            if name in _SHELL_NAMES:
                continue
            base = guard.classify_action(name, {})
            for args in PROBE_ARGS:
                got = guard.classify_action(name, args)
                if got is not base:
                    violations.append((name, args, base.name, got.name))
        assert violations == [], f"args moved a SafetyGuard classification: {violations[:5]}"

    @pytest.mark.parametrize("name", _SHELL_NAMES)
    def test_shell_names_are_args_sensitive_by_design(self, name: str) -> None:
        """Excluded from the sweep above deliberately, not by oversight."""
        guard = SafetyGuard(config={"safety_mode": "strict"})
        benign = guard.classify_action(name, {"command": "echo hi"})
        destructive = guard.classify_action(name, {"command": "rm -rf /"})
        assert destructive > benign


# ===========================================================================
# Invariant C — every spelling of a dispatcher is INTERCEPTED, not merely
# answered the same way by a second code path
# ===========================================================================


class TestSpellingVariantsAreIntercepted:
    """`_DISPATCHER_TOOLS` is matched on the alias-resolved canonical name.

    It used to be matched on the RAW name, so `File` / `BROWSER` / `"file "`
    escaped interception and were classified by `_policy_tier` instead. Both
    paths reached the same answer, but only because both happened to consult
    the same policy — and "that variant can never be dispatched anyway" rested
    on `agent_loop._TOOL_REGISTRY` staying an exact lowercase dict lookup
    (`_TOOL_REGISTRY.get(call.name)`, agent_loop.py:1376). That is an unenforced
    property of an unrelated module. These tests pin that the classifier no
    longer depends on it.
    """

    VARIANTS = {
        "file": ["file", "File", "FILE", "file ", " file"],
        "browser": ["browser", "Browser", "BROWSER", "browser ", " browser"],
    }
    # Sub-actions that are REAL for one dispatcher and not the other. This
    # asymmetry is why probing `browser` with `action=read` shows no divergence:
    # `browser.read` does not exist, so it fails closed on both paths.
    REAL = {"file": "read", "browser": "navigate"}
    NOT_REAL = {"file": "navigate", "browser": "read"}

    @pytest.mark.parametrize("tool", sorted(VARIANTS))
    def test_every_spelling_matches_the_canonical_spelling(self, tool: str) -> None:
        guard = SafetyGuard(config={"safety_mode": "strict"})
        for action in (self.REAL[tool], self.NOT_REAL[tool], "chmod", "eval", "delete"):
            args = {"action": action}
            expected = guard.classify_action(tool, args)
            for variant in self.VARIANTS[tool]:
                assert guard.classify_action(variant, args) is expected, (variant, action)

    @pytest.mark.parametrize("tool", sorted(VARIANTS))
    def test_real_sub_action_is_tiered_under_every_spelling(self, tool: str) -> None:
        """The case that actually diverged before the fix."""
        guard = SafetyGuard(config={"safety_mode": "strict"})
        args = {"action": self.REAL[tool]}
        for variant in self.VARIANTS[tool]:
            assert guard.classify_action(variant, args) is RiskTier.READ, variant

    @pytest.mark.parametrize("tool", sorted(VARIANTS))
    def test_unreal_sub_action_fails_closed_under_every_spelling(self, tool: str) -> None:
        guard = SafetyGuard(config={"safety_mode": "strict"})
        for action in (self.NOT_REAL[tool], "chmod", "not_a_real_action"):
            for variant in self.VARIANTS[tool]:
                assert guard.classify_action(variant, {"action": action}) is RiskTier.HIGH_STAKES, (
                    variant, action,
                )

    @pytest.mark.parametrize("tool", sorted(VARIANTS))
    def test_no_readable_action_fails_closed_under_every_spelling(self, tool: str) -> None:
        guard = SafetyGuard(config={"safety_mode": "strict"})
        for variant in self.VARIANTS[tool]:
            for args in ({}, {"action": ""}, {"action": 7}, {"action": None}):
                assert guard.classify_action(variant, args) is RiskTier.HIGH_STAKES, (variant, args)

    @pytest.mark.parametrize("tool", sorted(VARIANTS))
    def test_variants_never_reach_the_policy_fallback(
        self, tool: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PATH proof, not just result proof.

        Detonate `_policy_tier`. A dispatcher spelling that still classifies
        was intercepted; one that reaches the fallback raises. This is what
        distinguishes the fix from the previous "both paths agree" situation.
        """
        import cato.safety as safety_mod

        def _detonate(*_a: Any, **_k: Any) -> RiskTier:
            raise AssertionError("reached _policy_tier: variant was NOT intercepted")

        monkeypatch.setattr(safety_mod, "_policy_tier", _detonate)
        guard = SafetyGuard(config={"safety_mode": "strict"})
        for variant in self.VARIANTS[tool]:
            for action in (self.REAL[tool], self.NOT_REAL[tool], "chmod"):
                guard.classify_action(variant, {"action": action})
            guard.classify_action(variant, {})

    @pytest.mark.parametrize("tool", sorted(VARIANTS))
    def test_is_classified_agrees_across_spellings(self, tool: str) -> None:
        guard = SafetyGuard(config={"safety_mode": "strict"})
        for action in (self.REAL[tool], self.NOT_REAL[tool], "chmod"):
            args = {"action": action}
            expected = guard.is_classified(tool, args)
            for variant in self.VARIANTS[tool]:
                assert guard.is_classified(variant, args) is expected, (variant, action)

    def test_shell_aliases_are_deliberately_not_canonicalised(self) -> None:
        """`bash`/`exec` alias to shell_exec but must NOT enter _classify_shell.

        Routing them there would let a benign command string lower them below
        the flat HIGH_STAKES they get today. Pinned so the canonicalisation
        added for dispatchers is never extended to the shell branch by reflex.
        """
        guard = SafetyGuard(config={"safety_mode": "strict"})
        for name in ("bash", "exec", "shellExec"):
            assert guard.classify_action(name, {"command": "echo hi"}) is RiskTier.HIGH_STAKES, name

    def test_genesis_is_still_the_one_capability_args_move_at_the_fallback(self) -> None:
        """After the fix, `genesis` is the only reason `_policy_tier` reads args."""
        guard = SafetyGuard(config={"safety_mode": "strict"})
        read = {"agent": "genesis-e4l-fs-integrity",
                "task": "prose", "params": {"operation": "get_trial_balance"}}
        write = {"agent": "genesis-e4l-ap",
                 "task": "prose", "params": {"operation": "create_draft_bill"}}
        assert guard.classify_action("genesis", read) is RiskTier.READ
        assert guard.classify_action("genesis", write) is RiskTier.HIGH_STAKES
