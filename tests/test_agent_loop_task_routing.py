"""
Regression test for CHUNK_2_VAULT: agent_loop.py's planning-turn task-type
classification.

Before this fix, every planning turn hardcoded ``TaskType.GENERAL_TOOL_USE``
regardless of the actual message content, so model_policy.py's per-task-type
tier table could never route a chat turn to anything other than the
GENERAL_TOOL_USE -> SONNET row. These tests assert:

  1. ``_classify_task_type`` still returns ``GENERAL_TOOL_USE`` for the
     general/default case (no behavior change for the common path).
  2. A message matching a more specific, unambiguous pattern classifies to a
     *different* ``TaskType``.
  3. That different ``TaskType`` actually routes to a different
     :class:`~cato.model_policy.ModelTier` than ``GENERAL_TOOL_USE`` does —
     i.e. the routing *decision*, not just the label, changes.
"""

from __future__ import annotations

from cato.agent_loop import _classify_task_type
from cato.model_policy import (
    TASK_BASE_TIER,
    ModelTier,
    TaskDescriptor,
    TaskType,
    route,
)


def test_classify_task_type_defaults_to_general_tool_use() -> None:
    """Unmatched / tool-using turns keep the pre-fix default (no regression)."""
    assert _classify_task_type("what's on my calendar today?", False) is (
        TaskType.GENERAL_TOOL_USE
    )
    # Even a phrase that would otherwise match must not override an actual
    # tool-using turn — tool calls stay on the general/tool-capable tier.
    assert _classify_task_type("classify this document", True) is (
        TaskType.GENERAL_TOOL_USE
    )


def test_classify_task_type_detects_document_classification() -> None:
    """A message that is clearly a classification ask is no longer forced
    onto GENERAL_TOOL_USE."""
    task_type = _classify_task_type(
        "Please classify this document as an invoice or a receipt.", False
    )
    assert task_type is TaskType.DOCUMENT_CLASSIFICATION
    assert task_type is not TaskType.GENERAL_TOOL_USE


def test_classify_task_type_detects_draft_correspondence() -> None:
    task_type = _classify_task_type(
        "Draft a reply to this vendor email confirming receipt.", False
    )
    assert task_type is TaskType.DRAFT_CORRESPONDENCE
    assert task_type is not TaskType.GENERAL_TOOL_USE


def test_routing_decision_changes_for_reclassified_task_type() -> None:
    """The actual bug this chunk fixes: the hardcoded task type meant every
    turn produced the same routed tier. Prove a reclassified turn now
    produces a *different* routed tier than the old hardcoded constant did.
    """
    general_tier = TASK_BASE_TIER[TaskType.GENERAL_TOOL_USE]
    classification_tier = TASK_BASE_TIER[TaskType.DOCUMENT_CLASSIFICATION]
    assert classification_tier != general_tier, (
        "fixture assumption broken: DOCUMENT_CLASSIFICATION and "
        "GENERAL_TOOL_USE must map to different tiers for this regression "
        "test to be meaningful"
    )

    message = "Please classify this document as an invoice or a receipt."
    task_type = _classify_task_type(message, False)
    assert task_type is TaskType.DOCUMENT_CLASSIFICATION

    old_decision = route(
        TaskDescriptor.build(task_type=TaskType.GENERAL_TOOL_USE)
    )
    new_decision = route(TaskDescriptor.build(task_type=task_type))

    assert old_decision.tier is ModelTier.SONNET
    assert new_decision.tier is ModelTier.HAIKU
    assert new_decision.tier != old_decision.tier
