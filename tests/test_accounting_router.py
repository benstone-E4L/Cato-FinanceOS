"""tests/test_accounting_router.py — Task 3: Cato routing matrix loader.

Reproduces the Genesis-side S1-S10 expected-agent outcomes
(``Genesis Agents/tests/test_accounting_orchestration.py`` /
``accounting/tests/ORCHESTRATION_SCENARIOS.yaml``) from the CATO side,
without the caller naming the agent, using Cato's own ported router
(``cato/accounting_router.py``) and version-pinned matrix copy
(``cato/accounting/CATO_GENESIS_ROUTING_MATRIX.yaml``).

Also covers the two acceptance criteria the Genesis-side suite does not:
ambiguous-prompt -> NEED_CLARIFICATION, and genesis-finance (or any
money-domain stub) can never be a routing target.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cato.accounting_router import (
    ENTITY_KEYS,
    FORBIDDEN_SLUGS,
    ONE_HAT_SLUG,
    SPECIALIST_SLUGS,
    NeedClarification,
    load_routing_matrix,
    route_question,
)
from cato.tools.genesis import MONEY_DOMAIN_AGENTS

# Genesis Agents repo is a sibling checkout on this machine; the scenario
# fixture is read directly from there (read-only) so this test proves
# reproduction against the SAME source-of-truth prompts/expectations the
# execution plan's acceptance criterion names, without duplicating that
# fixture into the Cato repo (which would drift). If the sibling repo is not
# present (e.g. a fresh clone of Cato alone), these parametrized cases are
# skipped rather than failing the whole suite.
_GENESIS_AGENTS_ROOT = Path(r"C:\Users\Work\Desktop\vault\projects\My Github\Genesis Agents")
_SCENARIOS_PATH = _GENESIS_AGENTS_ROOT / "accounting" / "tests" / "ORCHESTRATION_SCENARIOS.yaml"

if _SCENARIOS_PATH.is_file():
    _SCENARIOS = yaml.safe_load(_SCENARIOS_PATH.read_text(encoding="utf-8"))["scenarios"]
else:
    _SCENARIOS = []

_SCENARIO_IDS = [s["id"] for s in _SCENARIOS]


class TestMatrixLoads:
    def test_matrix_loads_and_checks_schema_version(self):
        matrix = load_routing_matrix()
        assert matrix["dispatch_contract"]["pattern"] == "one_agent_one_job"
        assert matrix["_meta"]["last_verified"]

    def test_specialist_slugs_is_the_14_and_matches_genesis_fail_closed_set(self):
        assert len(SPECIALIST_SLUGS) == 14
        assert ONE_HAT_SLUG not in SPECIALIST_SLUGS
        assert SPECIALIST_SLUGS.isdisjoint(MONEY_DOMAIN_AGENTS)

    def test_forbidden_slugs_include_money_domain_and_one_hat_and_entities(self):
        assert MONEY_DOMAIN_AGENTS <= FORBIDDEN_SLUGS
        assert ONE_HAT_SLUG in FORBIDDEN_SLUGS
        assert set(ENTITY_KEYS) <= FORBIDDEN_SLUGS


@pytest.mark.skipif(not _SCENARIOS, reason="Genesis Agents sibling checkout not present on this machine")
@pytest.mark.parametrize("scenario", _SCENARIOS, ids=_SCENARIO_IDS)
def test_router_reproduces_s1_s10_expected_agents_without_naming_them(scenario: dict):
    prompt = scenario["prompt"]
    assert "genesis-e4l-" not in prompt.lower(), "test fixture prompt must not name a slug"
    decision = route_question(prompt)
    assert set(decision.agents) == set(scenario["expect_agents"])
    if scenario.get("expect_entities"):
        assert set(decision.entities) == set(scenario["expect_entities"])
    chosen = set(decision.agents) | set(decision.then_fanout)
    assert chosen <= SPECIALIST_SLUGS
    assert chosen.isdisjoint(FORBIDDEN_SLUGS)
    assert not chosen.intersection(MONEY_DOMAIN_AGENTS)


@pytest.mark.skipif(not _SCENARIOS, reason="Genesis Agents sibling checkout not present on this machine")
def test_genesis_finance_never_selected_for_any_scenario():
    for scenario in _SCENARIOS:
        decision = route_question(scenario["prompt"])
        chosen = set(decision.agents) | set(decision.then_fanout)
        assert "genesis-finance" not in chosen
        assert chosen.isdisjoint(MONEY_DOMAIN_AGENTS)


class TestAmbiguity:
    @pytest.mark.parametrize("prompt", [
        "What is the weather today?",
        "Tell me a joke.",
        "hi",
        "Give me the numbers.",
        "",
        "   ",
    ])
    def test_low_signal_prompt_raises_need_clarification(self, prompt):
        with pytest.raises(NeedClarification) as excinfo:
            route_question(prompt)
        assert excinfo.value.candidates  # carries something for the caller to show the operator

    def test_need_clarification_carries_scored_candidates(self):
        with pytest.raises(NeedClarification) as excinfo:
            route_question("random unrelated text about nothing accounting related")
        assert all(isinstance(rid, str) and isinstance(score, int) for rid, score in excinfo.value.candidates)


class TestFanout:
    @pytest.mark.skipif(not _SCENARIOS, reason="Genesis Agents sibling checkout not present on this machine")
    def test_s2_close_exposes_fanout_for_parallel_dispatch(self):
        decision = route_question("Close July for all E4L entities.")
        assert "genesis-e4l-close" in decision.agents
        assert len(decision.then_fanout) > 1
        assert set(decision.then_fanout) <= SPECIALIST_SLUGS
        # parallel_dispatch merges agents + fanout with no duplicates
        assert set(decision.parallel_dispatch) == set(decision.agents) | set(decision.then_fanout)
        assert len(decision.parallel_dispatch) == len(set(decision.parallel_dispatch))
