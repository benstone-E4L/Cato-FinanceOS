"""Negative proofs for Cato's direct-Anthropic-only execution contract."""

from datetime import date

import pytest

from cato.anthropic_client import CallResult
from cato.gateway import _direct_compaction_call
from cato.model_policy import (
    MODEL_REGISTRY,
    Provider,
    TaskDescriptor,
    TaskType,
    route,
)
from cato.router import ModelRouter


class _AnthropicStub:
    def __init__(self) -> None:
        self.models: list[str] = []

    async def call(self, decision, messages, **kwargs):
        self.models.append(decision.model_id)
        return CallResult(
            model_id=decision.model_id,
            message={"content": [{"type": "text", "text": "direct"}]},
            stop_reason="end_turn",
        )

    async def close(self) -> None:
        return None


class _ForbiddenOpenAI:
    def has_credentials(self) -> bool:
        return True

    async def call(self, *args, **kwargs):
        raise AssertionError("OpenAI must never be called by complete_message")

    async def close(self) -> None:
        return None


@pytest.mark.parametrize(
    ("task_type", "when", "escalation"),
    [
        (TaskType.DOCUMENT_CLASSIFICATION, date(2026, 8, 20), 0),
        (TaskType.AUDIT_SYNTHESIS, date(2026, 8, 20), 0),
        (TaskType.GENERAL_TOOL_USE, date(2026, 8, 20), 1),
        (TaskType.RECONCILIATION_ANALYSIS, date(2026, 9, 1), 0),
        (TaskType.SESSION_COMPACTION, date(2026, 9, 1), 0),
    ],
)
def test_policy_never_selects_non_anthropic(task_type, when, escalation):
    decision = route(
        TaskDescriptor(
            task_type=task_type,
            input_tokens=100,
            max_output_tokens=1_024,
            cost_ceiling_usd=100.0,
            escalation_level=escalation,
        ),
        when=when,
        available_providers=frozenset(Provider),
    )
    assert decision.provider is Provider.ANTHROPIC
    assert MODEL_REGISTRY[decision.model_id].provider is Provider.ANTHROPIC
    assert decision.model_id.startswith("claude-")


@pytest.mark.asyncio
async def test_credential_bearing_openai_client_is_never_called():
    anthropic = _AnthropicStub()
    router = ModelRouter(
        vault=None,
        anthropic_client=anthropic,
        openai_client=_ForbiddenOpenAI(),
    )

    for task_type in (
        TaskType.DOCUMENT_CLASSIFICATION,
        TaskType.AUDIT_SYNTHESIS,
        TaskType.GENERAL_TOOL_USE,
    ):
        model, message, decision = await router.complete_message(
            [{"role": "user", "content": "Ask E4L request"}],
            TaskDescriptor(
                task_type=task_type,
                input_tokens=10,
                max_output_tokens=512,
                cost_ceiling_usd=100.0,
            ),
            when=date(2026, 9, 1),
        )
        assert decision.provider is Provider.ANTHROPIC
        assert model.startswith("claude-")
        assert message["content"] == "direct"

    assert anthropic.models
    assert all(model.startswith("claude-") for model in anthropic.models)


@pytest.mark.asyncio
async def test_compaction_uses_policy_path_and_never_legacy_complete():
    class _Router:
        async def complete(self, *args, **kwargs):
            raise AssertionError("legacy multi-provider complete() must not be called")

        async def complete_message(self, messages, descriptor, **kwargs):
            assert descriptor.task_type is TaskType.SESSION_COMPACTION
            assert kwargs["system"] == "summarize faithfully"
            assert messages == [{"role": "user", "content": "transcript"}]
            decision = route(descriptor, when=date(2026, 9, 1))
            assert decision.provider is Provider.ANTHROPIC
            return decision.model_id, {"content": "summary"}, decision

    result = await _direct_compaction_call(
        _Router(),
        system_prompt="summarize faithfully",
        user_prompt="transcript",
        session_id="ask-e4l",
    )
    assert result == "summary"
