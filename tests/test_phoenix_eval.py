"""
tests/test_phoenix_eval.py — CHUNK_4_ASK_E4L's 10-question eval gate.

No live LLM or Phoenix call is made here — grading logic is exercised
directly against a scripted fake LLM, and the Phoenix-unreachable fallback
path is proven by simply not setting PHOENIX_ENDPOINT (the common case).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cato.core.ask_e4l import AskE4LAnswer
from cato.core.memory import MemorySystem
from cato.core.phoenix_eval import (
    DEFAULT_EVAL_QUESTIONS,
    EvalQuestion,
    _grade,
    run_phoenix_eval,
)
from cato.core.vault_ingest import ingest_vault


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def memory(tmp_path: Path) -> MemorySystem:
    mem = MemorySystem(agent_id="phoenix-eval-test", memory_dir=tmp_path / "memdb")
    yield mem
    mem.close()


def test_default_question_set_has_at_least_one_refusal_question() -> None:
    assert len(DEFAULT_EVAL_QUESTIONS) == 10
    assert any(q.expects_refusal for q in DEFAULT_EVAL_QUESTIONS)
    assert any(not q.expects_refusal for q in DEFAULT_EVAL_QUESTIONS)


async def test_eval_passes_bar_with_correct_answers_and_logs_locally(
    tmp_path: Path, memory: MemorySystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PHOENIX_ENDPOINT", raising=False)
    vault_root = tmp_path / "vault"
    _write(vault_root, "knowledge/facts.md", "# The Sky\n\nThe sky is blue during the day.\n")
    _write(vault_root, "knowledge/other.md", "# Water\n\nWater is wet.\n")
    ingest_vault(memory, vault_root)

    questions = (
        EvalQuestion("What color is the sky?", expected_keywords=("blue",)),
        EvalQuestion("What is a fact about water?", expected_keywords=("wet",)),
        EvalQuestion("What is the capital of a made-up country?", expects_refusal=True),
    )

    async def fake_llm(prompt: str) -> str:
        if "sky" in prompt.lower():
            return "The sky is blue. [knowledge/facts.md#the-sky]"
        return "Water is wet. [knowledge/other.md#water]"

    log_path = tmp_path / "eval-log.md"
    report = await run_phoenix_eval(
        memory, vault_root, llm_complete=fake_llm, questions=questions, log_path=log_path
    )

    assert report.total == 3
    assert report.correct_count == 3
    assert report.confidently_wrong_count == 0
    assert report.passes_bar is True
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "Phoenix eval run" in log_text
    assert "phoenix_reachable: False" in log_text


async def test_confidently_wrong_answer_is_flagged_and_fails_the_bar(
    tmp_path: Path, memory: MemorySystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PHOENIX_ENDPOINT", raising=False)
    vault_root = tmp_path / "vault"
    _write(vault_root, "knowledge/facts.md", "# The Sky\n\nThe sky is blue during the day.\n")
    _write(vault_root, "knowledge/other.md", "# Water\n\nWater is wet.\n")
    ingest_vault(memory, vault_root)

    questions = (
        EvalQuestion("What color is the sky?", expected_keywords=("blue",)),
    )

    async def wrong_llm(prompt: str) -> str:
        return "The sky is green. [knowledge/facts.md#the-sky]"

    report = await run_phoenix_eval(
        memory, vault_root, llm_complete=wrong_llm, questions=questions,
        log_path=tmp_path / "eval-log.md",
    )

    assert report.confidently_wrong_count == 1
    assert report.passes_bar is False


def test_grade_treats_an_answer_when_refusal_was_expected_as_confidently_wrong() -> None:
    """Direct unit test of the grading function: if an eval question is
    marked expects_refusal but the engine answered anyway (e.g. a borderline
    retrieval match), that must grade as confidently wrong, not correct."""
    eq = EvalQuestion("Some borderline question", expects_refusal=True)
    answer = AskE4LAnswer(
        question=eq.question, refused=False, text="Here's a confident answer.",
    )
    result = _grade(eq, answer)
    assert result.correct is False
    assert result.confidently_wrong is True


def test_grade_refusal_when_expected_is_correct() -> None:
    eq = EvalQuestion("Some out-of-scope question", expects_refusal=True)
    answer = AskE4LAnswer(question=eq.question, refused=True, text="No vault answer found.")
    result = _grade(eq, answer)
    assert result.correct is True
    assert result.confidently_wrong is False


def test_grade_refusal_when_answer_was_expected_is_incorrect_but_not_confidently_wrong() -> None:
    """A refusal on a question that should have been answerable is a miss —
    not "confidently wrong" (the system declined rather than stating a
    wrong fact)."""
    eq = EvalQuestion("Answerable question", expected_keywords=("blue",))
    answer = AskE4LAnswer(question=eq.question, refused=True, text="No vault answer found.")
    result = _grade(eq, answer)
    assert result.correct is False
    assert result.confidently_wrong is False
