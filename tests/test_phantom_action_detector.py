"""tests/test_phantom_action_detector.py — regression cover for the
"phantom action" continuation re-prompt in ``cato/agent_loop.py``.

The detector exists so a turn that *commits* to doing something but emits no
``tool_call`` gets re-prompted once instead of shipping narration as the final
answer.  It used to be a bare substring test over hints including ``"i can "``,
matched anywhere in the answer.  That fired on ordinary description:

    user:  "who is your best genesis agent?"
    turn1: 'I don't have a ranking of "best" - the genesis agents I can
            dispatch are specialized, not competitive with each other.'

Turn 1 was correct and complete.  ``"i can "`` matched, the re-prompt fired,
turn 2 abandoned the question and returned a gate error, and because
``final_text`` keeps only the last turn the correct answer was destroyed.

Both failure directions are covered here, because both are real:

  * FALSE POSITIVE — description classified as a commitment.  Cost: a correct
    answer is thrown away (the bug above).
  * FALSE NEGATIVE — a commitment classified as description.  Cost: the model
    narrates an action it never performed and that narration ships as the
    final answer.  Every string in :class:`TestAdverbsBetweenCommitmentAndVerb`
    and :class:`TestCommitmentShapesFoundByAudit` is one an adversarial audit
    found the first version of this detector missing.

These tests exercise :func:`cato.agent_loop._is_phantom_action` itself — the
same callable the planning loop invokes — plus a structural check that the loop
still calls it and still honours the ``force`` / one-shot guards around it.
"""

from __future__ import annotations

import inspect

import pytest

from cato.agent_loop import _is_phantom_action

# The exact turn-1 answer from the observed failure.
DESCRIPTIVE_ANSWER = (
    'I don\'t have a ranking of "best" - the genesis agents I can dispatch '
    "are specialized, not competitive with each other."
)

# A genuine narrated-but-unexecuted action.
NARRATED_ACTION = "Let me pull the current cash balance for you."


class TestTheObservedRegression:
    def test_descriptive_clause_does_not_trigger_continuation(self) -> None:
        """NEGATIVE: the exact sentence that broke, with no tool calls."""
        assert _is_phantom_action(DESCRIPTIVE_ANSWER, "who is your best genesis agent?") is False

    def test_narrated_action_still_triggers_continuation(self) -> None:
        """POSITIVE: the true positive the detector exists for."""
        assert _is_phantom_action(NARRATED_ACTION, "what is my cash balance?") is True

    def test_negative_case_holds_regardless_of_user_message(self) -> None:
        """The descriptive clause is not an action even when the user *did*
        ask for work — the fix must not depend on classifying the request."""
        assert _is_phantom_action(DESCRIPTIVE_ANSWER, "close July for all E4L entities") is False


class TestDescriptionIsNotCommitment:
    """Capability modals and embedded clauses describe; they do not commit.

    This is the constraint that outranks every widening below: if catching a
    commitment shape would reintroduce a hit here, the commitment shape stays
    uncaught.
    """

    @pytest.mark.parametrize(
        "text",
        [
            # Capability modals — description, never a commitment.
            "I can dispatch genesis-e4l-cash for that question.",
            "I could pull the ledger.",
            "I'm able to dispatch six specialists.",
            # Capability modal framed as an offer awaiting consent.  Executing
            # an offer would act without the user having said yes.
            "I can pull that for you if you want.",
            "I can pull the trial balance if that would help.",
            # Conditional that genuinely governs the commitment clause.
            "If you'd like, I'll pull the trial balance.",
            "Unless you object, I'll pull the ledger.",
            # Commissive marker embedded in a relative clause, not heading one.
            "The tools I will use depend on the question.",
            "The report I'll send later is not ready yet.",
            # Commissive marker with a non-action complement.
            "Let me know if you want me to pull the balance.",
            "Let me explain how the routing works.",
            "I'll be honest: the ledger data is stale.",
            "I'll gladly explain how the gates work.",
            "Let's start with the basics of accrual accounting.",
            # Explaining is not tool use, however it is phrased.
            "Let me walk you through the entity structure.",
            "Let me summarize the key points.",
            # Explicit refusal.
            "I will not run anything without your approval.",
            "I'll certainly not run it without approval.",
            # No first-person construction at all.
            "Your cash balance is $12,340 as of yesterday.",
            "",
        ],
    )
    def test_does_not_fire(self, text: str) -> None:
        assert _is_phantom_action(text, "who is your best genesis agent?") is False


class TestCommitmentStillCaught:
    @pytest.mark.parametrize(
        "text",
        [
            "Let me pull the current cash balance for you.",
            "Let me pull the cash balance.",
            "I'll pull the ledger.",
            "I'll check Xero for the July trial balance.",
            "Sure — I'm going to dispatch genesis-e4l-cash now.",
            "First, I'll start by pulling the bank feed.",
            "**Let me now run the reconciliation.**",
            "Okay. I'll take a look at your Xero ledger.",
            "I'll go ahead and query the invoices.",
            "1. Let me search the transcripts.",
            "Let's pull the trial balance for NES Health LLC.",
            "I’ll fetch the invoice list.",  # typographic apostrophe
            "I am going to reconcile the Stripe payouts.",
            "Here's my plan. I'll dispatch genesis-e4l-cash and report back.",
        ],
    )
    def test_fires(self, text: str) -> None:
        assert _is_phantom_action(text, "what is my cash balance?") is True


class TestAdverbsBetweenCommitmentAndVerb:
    """Audit finding 1: manner/stance adverbs are an open class, so a closed
    filler list that aborts on the first unknown token turns every one of
    these into a false negative."""

    @pytest.mark.parametrize(
        "text",
        [
            "I'll certainly pull the ledger.",
            "I'll definitely pull the ledger.",
            "I'll gladly pull the ledger.",
            "I'll surely dispatch genesis-e4l-cash.",
            "I'll happily go and check the ledger.",
        ],
    )
    def test_fires(self, text: str) -> None:
        assert _is_phantom_action(text, "what is my cash balance?") is True


class TestCommitmentShapesFoundByAudit:
    """Audit findings 2-4: elided apostrophe, phrase/verb path asymmetry, and
    an over-broad conditional test."""

    @pytest.mark.parametrize(
        "text",
        [
            # finding 2 — "Im"/"gonna"/adverb inside the construction
            "Im going to pull the balance now.",
            "I'm gonna pull the balance.",
            "I'm now going to run the reconciliation.",
            # finding 3 — action *phrases* must be reachable across fillers,
            # exactly like single-word action verbs are
            "I'll just double check this and get back to you.",
            "I'll go ahead and take a look at this.",
            # finding 4 — "should"/"once" in a clause that does not govern the
            # commitment must not suppress it
            "You should know, I'll pull the trial balance now.",
        ],
    )
    def test_fires(self, text: str) -> None:
        assert _is_phantom_action(text, "what is my cash balance?") is True


class TestUserAskedForDescriptionOnly:
    """Narrow use of the user's own message: when the user explicitly asked
    for description *only*, narration is the correct behaviour and must not be
    escalated into execution."""

    @pytest.mark.parametrize(
        "user_message",
        [
            "just explain how it works, don't run anything",
            "walk me through it without running any tools",
            "dry-run only please",
        ],
    )
    def test_suppressed(self, user_message: str) -> None:
        assert _is_phantom_action(NARRATED_ACTION, user_message) is False

    def test_not_suppressed_for_an_ordinary_request(self) -> None:
        assert _is_phantom_action(NARRATED_ACTION, "how much cash do we have?") is True


class TestDetectorWiredIntoPlanningLoop:
    """The predicate is only useful if the loop actually calls it, and the
    surrounding guards must survive the rewrite."""

    def test_planning_loop_calls_the_real_predicate(self) -> None:
        import cato.agent_loop as al

        source = inspect.getsource(al.AgentLoop._run_inner)
        assert "_is_phantom_action(text, message)" in source
        # The old substring detector must be gone, not merely bypassed.
        assert "_ACTION_HINTS" not in source

    def test_guards_around_the_detector_are_intact(self) -> None:
        import cato.agent_loop as al

        source = inspect.getsource(al.AgentLoop._run_inner)
        # force (final-answer-now) still short-circuits the re-prompt.
        assert "not force" in source
        # one-shot guard + its per-invocation reset.
        assert 'getattr(self, "_continuation_retried", False)' in source
        assert "self._continuation_retried = True" in source
        assert "self._continuation_retried = False" in source
        # a turn with text and no tool calls still ends the loop.
        assert "final_text = text" in source
