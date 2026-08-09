"""
tests/test_ask_e4l.py — CHUNK_4_ASK_E4L

No live LLM call is made anywhere in this file — the answer-synthesis step
is driven through an injected fake `llm_complete` callable, exactly like
test_model_policy.py drives the Anthropic client through a fake transport.
This isolates and proves the deterministic control flow the Retrieval
Contract actually requires: the refusal gate never invokes the LLM,
citations are formatted correctly, superseded chunks are excluded by
default, and contradiction markers are parsed rather than trusted as prose.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from cato.core.ask_e4l import NO_GROUNDED_ANSWER_MARKER, REFUSAL_TEXT, answer_question
from cato.core.memory import MemorySystem
from cato.core.vault_ingest import ingest_vault


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _add_distractors(root: Path) -> None:
    """A couple of unrelated notes so BM25 has a non-degenerate corpus to
    rank against (a single-document corpus makes BM25's idf term degenerate
    — real vaults always have many documents; these keep fixtures realistic)."""
    _write(root, "noise/coffee.md", "# Coffee\n\nWe like coffee at the office on Fridays.\n")
    _write(root, "noise/weather.md", "# Weather\n\nIt rained yesterday in the city.\n")


@pytest.fixture()
def memory(tmp_path: Path) -> MemorySystem:
    mem = MemorySystem(agent_id="ask-e4l-test", memory_dir=tmp_path / "memdb")
    yield mem
    mem.close()


class _FakeLLM:
    """Records every prompt it was called with; returns a canned answer."""

    def __init__(self, response: str = "Canned answer.") -> None:
        self.calls: list[str] = []
        self.response = response

    async def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response


# ---------------------------------------------------------------------------
# Refusal path
# ---------------------------------------------------------------------------

async def test_refusal_path_never_calls_the_llm(tmp_path: Path, memory: MemorySystem) -> None:
    vault_root = tmp_path / "vault"
    _write(vault_root, "knowledge/note.md", "# Coffee\n\nWe like coffee at the office.\n")
    ingest_vault(memory, vault_root)

    fake_llm = _FakeLLM()
    result = await answer_question(
        memory, vault_root,
        "What is the capital of a country that has never been mentioned anywhere?",
        llm_complete=fake_llm,
    )

    assert result.refused is True
    assert result.text == REFUSAL_TEXT
    assert result.citations == []
    assert fake_llm.calls == []  # never invoked — the whole point of the gate


async def test_second_layer_refusal_when_chunks_cross_threshold_but_dont_ground_an_answer(
    tmp_path: Path, memory: MemorySystem
) -> None:
    """Real-vault-scale finding: a topically-adjacent chunk (e.g. a Gmail
    OAuth setup note, for "what's my Gmail password") can clear the
    retrieval-score threshold without actually answering the question — the
    zero-chunks fast gate never fires. The model is instructed to emit
    NO_GROUNDED_ANSWER instead of guessing in that case; this must still
    produce a real refusal, not a "confidently wrong" answer with citations
    pointing at content that doesn't actually support it."""
    vault_root = tmp_path / "vault"
    _write(
        vault_root,
        "knowledge/gmail-setup.md",
        "# Gmail OAuth Setup\n\nGmail is authenticated via OAuth tokens stored "
        "in the vault, not a plaintext password.\n",
    )
    _add_distractors(vault_root)
    ingest_vault(memory, vault_root)

    fake_llm = _FakeLLM(NO_GROUNDED_ANSWER_MARKER)
    result = await answer_question(
        memory, vault_root, "What is my personal Gmail account password?", llm_complete=fake_llm
    )

    assert len(fake_llm.calls) == 1  # retrieval did cross threshold, so the LLM WAS invoked
    assert result.refused is True
    assert result.text == REFUSAL_TEXT
    assert result.citations == []
    assert result.contradiction is False


# ---------------------------------------------------------------------------
# Happy path: citations
# ---------------------------------------------------------------------------

async def test_happy_path_citation_format(tmp_path: Path, memory: MemorySystem) -> None:
    vault_root = tmp_path / "vault"
    _write(
        vault_root,
        "knowledge/finance/entity-structure.md",
        "---\nentity: E4L\ntype: decision\nstatus: active\n---\n\n"
        "# The Entity Map\n\nE4L Inc. is the parent entity for all E4L operations.\n",
    )
    _add_distractors(vault_root)
    ingest_vault(memory, vault_root)

    fake_llm = _FakeLLM("E4L Inc. is the parent entity. [knowledge/finance/entity-structure.md#the-entity-map]")
    result = await answer_question(
        memory, vault_root, "What is the parent entity for E4L?", llm_complete=fake_llm
    )

    assert result.refused is False
    assert len(fake_llm.calls) == 1
    assert "the-entity-map" in fake_llm.calls[0]  # prompt grounded the model in real excerpts
    assert result.citations
    for c in result.citations:
        formatted = c.formatted()
        assert "@" not in formatted  # citation drops the internal @index suffix
        assert formatted == "knowledge/finance/entity-structure.md#the-entity-map"


# ---------------------------------------------------------------------------
# Superseded exclusion
# ---------------------------------------------------------------------------

async def test_superseded_excluded_by_default_and_flagged_available(
    tmp_path: Path, memory: MemorySystem
) -> None:
    vault_root = tmp_path / "vault"
    _write(
        vault_root,
        "decisions/old.md",
        "---\ntype: decision\nstatus: superseded\n---\n\n# XPO Timing\n\nWe planned Q1 liquidation.\n",
    )
    _write(
        vault_root,
        "decisions/new.md",
        "---\ntype: decision\nstatus: active\n---\n\n# XPO Timing Revised\n\nWe now plan Q3 liquidation.\n",
    )
    _add_distractors(vault_root)
    ingest_vault(memory, vault_root)

    fake_llm = _FakeLLM("We plan Q3 liquidation.")
    result = await answer_question(
        memory, vault_root, "When is the XPO liquidation planned?", llm_complete=fake_llm
    )

    assert result.refused is False
    assert all(c.vault_path == "decisions/new.md" for c in result.citations)
    # No superseded excerpt reached the prompt.
    assert "old.md" not in fake_llm.calls[0]

    history_llm = _FakeLLM("Q1 was the old plan; Q3 is current.")
    history_result = await answer_question(
        memory, vault_root, "When is the XPO liquidation planned?",
        llm_complete=history_llm, include_history=True,
    )
    assert any(c.vault_path == "decisions/old.md" for c in history_result.citations)


# ---------------------------------------------------------------------------
# Contradiction surfacing
# ---------------------------------------------------------------------------

async def test_contradiction_flagged_when_model_emits_marker(
    tmp_path: Path, memory: MemorySystem
) -> None:
    vault_root = tmp_path / "vault"
    _write(
        vault_root,
        "decisions/a.md",
        "---\nentity: E4L\ntype: decision\nstatus: active\n---\n\n"
        "# Royalty Rate\n\nThe royalty rate is 5 percent per the 2016 agreement terms.\n",
    )
    _write(
        vault_root,
        "decisions/b.md",
        "---\nentity: E4L\ntype: decision\nstatus: active\n---\n\n"
        "# Royalty Rate Restated\n\nThe royalty rate is 8 percent per the latest review.\n",
    )
    _add_distractors(vault_root)
    ingest_vault(memory, vault_root)

    id_a = "decisions/a.md#royalty-rate@0"
    id_b = "decisions/b.md#royalty-rate-restated@0"
    fake_llm = _FakeLLM(
        f"These sources disagree on the royalty rate (5% vs 8%). "
        f"[CONTRADICTION: {id_a} | {id_b}]"
    )
    result = await answer_question(
        memory, vault_root, "What is the E4L royalty rate?", llm_complete=fake_llm
    )

    assert result.refused is False
    assert result.contradiction is True
    cited_ids = {c.canonical_id for c in result.contradiction_citations}
    assert cited_ids == {id_a, id_b}


async def test_no_contradiction_flag_without_the_marker(
    tmp_path: Path, memory: MemorySystem
) -> None:
    vault_root = tmp_path / "vault"
    _write(
        vault_root,
        "decisions/a.md",
        "---\nentity: E4L\ntype: decision\nstatus: active\n---\n\n"
        "# Royalty Rate\n\nThe royalty rate is 5 percent.\n",
    )
    _write(
        vault_root,
        "decisions/b.md",
        "---\nentity: E4L\ntype: decision\nstatus: active\n---\n\n"
        "# Royalty Rate Again\n\nThe royalty rate is 5 percent, confirmed.\n",
    )
    _add_distractors(vault_root)
    ingest_vault(memory, vault_root)

    # Model reviewed the candidate pair and found no real conflict — no marker.
    fake_llm = _FakeLLM("Both sources agree: the royalty rate is 5 percent.")
    result = await answer_question(
        memory, vault_root, "What is the E4L royalty rate?", llm_complete=fake_llm
    )

    assert result.contradiction is False
    assert result.contradiction_citations == []


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------

async def test_staleness_flag_propagates(tmp_path: Path, memory: MemorySystem) -> None:
    vault_root = tmp_path / "vault"
    path = _write(vault_root, "knowledge/note.md", "# Topic\n\nOriginal fact.\n")
    _add_distractors(vault_root)
    ingest_vault(memory, vault_root)

    fake_llm = _FakeLLM("Original fact.")
    fresh = await answer_question(memory, vault_root, "What is the topic?", llm_complete=fake_llm)
    assert fresh.stale is False

    future = time.time() + 5
    import os
    path.write_text("# Topic\n\nChanged fact, not yet re-indexed.\n", encoding="utf-8")
    os.utime(path, (future, future))

    stale_result = await answer_question(
        memory, vault_root, "What is the topic?", llm_complete=_FakeLLM("Original fact.")
    )
    assert stale_result.stale is True
