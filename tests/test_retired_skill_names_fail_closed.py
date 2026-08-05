"""
tests/test_retired_skill_names_fail_closed.py — t22: deleting a capability must
make its name MORE restricted, never less.

WHY THIS FILE EXISTS
--------------------
Nine authorization bypasses have been fixed in this codebase, and several came
from a tool name resolving to something more permissive than intended. Deleting
a subsystem is exactly the situation where that happens by accident: the code
goes, and the leftover policy row / token-checker category quietly keeps
granting the old tier to a name that now means nothing — or, worse, the removal
of a row is assumed to be a denial when the resolver actually defaults to
"allow".

The arbitrage subsystem was removed in t22. Its five gate identities were:

    arbitrage.pulse         reversible
    arbitrage.preflight     read_only
    arbitrage.cycle         reversible
    arbitrage.cycle.write   financial
    arbitrage-gbp-scan /
    arbitrage-reconcile     reversible (aliases of arbitrage.cycle)

This file pins that all of them now resolve UNKNOWN and are refused at the
highest tier, by every gate independently. No network, no daemon, no subprocess.
"""
from __future__ import annotations

import pytest

#: Every gate identity the arbitrage subsystem owned, plus the alias names.
RETIRED_SKILLS = [
    "arbitrage.pulse",
    "arbitrage-twice-daily",
    "arbitrage.preflight",
    "arbitrage.cycle",
    "arbitrage.cycle.write",
    "arbitrage-gbp-scan",
    "arbitrage-reconcile",
]


# =============================================================================
# 1. The approval policy
# =============================================================================


class TestApprovalPolicyRefusesRetiredNames:
    @pytest.mark.parametrize("skill", RETIRED_SKILLS)
    def test_retired_name_resolves_to_the_highest_tier(self, skill):
        """An unmapped name must land in `critical`, not in a default-allow bucket.

        This is the load-bearing assertion. `arbitrage.cycle` used to be
        `reversible` (runs unattended) and `arbitrage.preflight` used to be
        `read_only` (never gated). If removing their rows had left them
        resolving to anything at or below their old tier, the deletion would
        have been a silent no-op for authorization purposes.
        """
        from cato.core.approval_policy import load_policy, resolve_tool

        policy = load_policy(reload=True)
        resolved = resolve_tool(skill, policy=policy)

        assert resolved.tier == "critical", (
            f"{skill!r} resolves to tier {resolved.tier!r}; a retired name must "
            "fall to the highest tier, not to whatever it used to be"
        )

    @pytest.mark.parametrize("skill", RETIRED_SKILLS)
    def test_retired_name_has_no_alias_or_rule(self, skill):
        """No leftover row may remain. A stale row is how a name gets resurrected."""
        from cato.core.approval_policy import load_policy, normalize_tool_name

        policy = load_policy(reload=True)
        norm = normalize_tool_name(skill)

        assert norm not in policy.aliases, f"stale alias for {skill!r}"
        assert norm not in policy.tools, f"stale tool rule for {skill!r}"

    @pytest.mark.parametrize("skill", RETIRED_SKILLS)
    def test_retired_name_requires_approval(self, skill):
        """The end-to-end policy verdict, not just the tier lookup."""
        from cato.core.approval_policy import REQUIRE, evaluate, load_policy

        decision = evaluate(skill, {}, policy=load_policy(reload=True))
        assert decision.decision == REQUIRE, (
            f"{skill!r} evaluated to {decision.decision!r}; a retired name must "
            "always require an approval ticket"
        )

    def test_a_live_skill_is_still_not_critical(self):
        """Control: the tier check above must be able to fail.

        Without this, `test_retired_name_resolves_to_the_highest_tier` would
        also pass if the resolver had been broken into returning "critical"
        for everything, which would brick the scheduler rather than harden it.
        """
        from cato.core.approval_policy import load_policy, resolve_tool

        policy = load_policy(reload=True)
        assert resolve_tool("site_services.pulse", policy=policy).tier == "reversible"
        assert resolve_tool("night_shift.digest", policy=policy).tier == "reversible"


# =============================================================================
# 2. The token / authorization gate
# =============================================================================


class TestTokenCheckerRefusesRetiredNames:
    @pytest.mark.parametrize("skill", RETIRED_SKILLS)
    def test_retired_name_has_no_category_and_is_denied(self, skill, tmp_path):
        """No mapped category => authorized=False, confirmation required.

        `arbitrage.cycle` and `arbitrage.cycle.write` were mapped to `api.call`
        and were in `_DEFAULT_ALLOWED_TOOLS`, i.e. they passed this gate with
        no delegation token at all. Both entries are gone.
        """
        from cato.auth.token_checker import (
            _DEFAULT_ALLOWED_TOOLS,
            _TOOL_CATEGORY_MAP,
            TokenChecker,
        )

        assert skill not in _TOOL_CATEGORY_MAP, f"stale category map entry for {skill!r}"
        assert skill not in _DEFAULT_ALLOWED_TOOLS, f"stale allowlist entry for {skill!r}"

        checker = TokenChecker(db_path=tmp_path / "tokens.db")
        result = checker.check_authorization(skill, {}, "sess-t22")

        assert result.authorized is False
        assert result.requires_user_confirmation is True
        assert "no mapped category" in result.reason

    def test_a_live_skill_still_passes_this_gate(self, tmp_path):
        """Control: the gate must still authorize the skills that survived."""
        from cato.auth.token_checker import TokenChecker

        checker = TokenChecker(db_path=tmp_path / "tokens.db")
        result = checker.check_authorization("site_services.pulse", {}, "sess-t22")
        assert result.authorized is True


# =============================================================================
# 3. The scheduler
# =============================================================================


class TestSchedulerHasNoArbitrageBranch:
    @pytest.mark.asyncio
    async def test_a_retired_skill_reaches_no_arbitrage_code(self, tmp_path, monkeypatch):
        """A cron job naming `arbitrage.cycle` cannot reach a removed module.

        The dispatcher has no arbitrage branch left, so the job falls through
        to the generic ingest path: it queues a prompt for the agent loop,
        which re-runs this same gate chain per tool call and finds no
        arbitrage tool registered. Nothing is dispatched at the engine, and
        nothing is importable that could be.
        """
        import importlib

        from tests.scheduler_gate_harness import build_scheduler_gate_env

        for gone in ("cato.core.arbitrage_cycle", "cato.core.arbitrage_pulse"):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(gone)

        env = build_scheduler_gate_env(tmp_path, monkeypatch)

        from cato.core.scheduled_dispatch import dispatch_scheduled_skill

        result = await dispatch_scheduled_skill(
            env.gateway,
            skill="arbitrage.cycle",
            args={"approved": True, "action": "kill_switch_on"},
            session_id="cron-t22",
            budget_cap_cents=100,
        )

        # It is handled as an unknown skill name, not as a privileged one.
        assert result["action"] == "ingest"
        assert env.gateway.sent == [], "no engine output may be produced"
        assert len(env.gateway.ingested) == 1
        prompt = env.gateway.ingested[0][1]
        assert "approved" not in prompt, "the self-authorization flag must be stripped"

    def test_the_unified_arbitrage_integration_is_gone(self):
        """The HTTP surface the skill drove must be unreachable too.

        Leaving the integration registered would keep every write action
        (kill switch, dispatch, outreach) callable through the generic
        `integration.action` tool even with the skill removed.
        """
        from cato.integrations import get_integration
        from cato.integrations.registry import _INTEGRATIONS, list_integrations

        assert get_integration("unified_arbitrage") is None
        assert "unified_arbitrage" not in _INTEGRATIONS
        assert not [k for k in _INTEGRATIONS if "arbitrage" in k.lower()]
        assert not [
            d for d in list_integrations()
            if "arbitrage" in (d.category or "").lower()
        ]


# =============================================================================
# 4. The secret-in-a-command-string defect this deletion resolved
# =============================================================================


def test_no_source_file_interpolates_a_secret_into_a_shell_command():
    """cato/core/arbitrage_pulse.py:72 put a vault secret in an argv string.

    It built `powershell ... -Secret "<vault value>"` and handed that to
    `asyncio.create_subprocess_shell`, which makes the secret readable in any
    local process listing for the lifetime of the pulse. The file is gone; this
    pins that no replacement grows back.
    """
    import re
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    # A secret-shaped local name interpolated into an f-string that is also a
    # command line. Deliberately broad: false positives are cheap here.
    pattern = re.compile(
        r"\{\s*\w*(secret|token|password|api_key|credential|passwd)\w*\s*[\}\[:!]",
        re.IGNORECASE,
    )

    offenders: list[str] = []
    for path in (repo / "cato").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "create_subprocess_shell" not in text and "shell=True" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or not pattern.search(line):
                continue
            offenders.append(f"{path.relative_to(repo)}:{lineno}")

    assert offenders == [], (
        "a secret-shaped value is interpolated into a command string in a module "
        f"that spawns a shell: {offenders}"
    )
