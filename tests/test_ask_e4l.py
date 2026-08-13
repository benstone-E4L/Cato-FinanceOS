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
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from cato.core.ask_e4l import (
    NO_GROUNDED_ANSWER_MARKER,
    REFUSAL_TEXT,
    REMOTE_RETRIEVAL_CONTRACT_VERSION,
    REMOTE_RETRIEVAL_MAX_CONTENT_BYTES,
    REMOTE_RETRIEVAL_MAX_TOTAL_CONTENT_BYTES,
    GenesisRetrievalClient,
    answer_question,
    answer_question_master,
)
from cato.core.memory import MemorySystem
from cato.core.vault_ingest import ingest_vault


class _SigningVault:
    """In-memory stand-in for the real vault, sufficient for AP2 keypair persistence.

    Genesis authenticates /retrieval/query with a signed AP2 envelope, so the retrieval client
    now needs a vault it can read/write the Ed25519 keypair through — not just a GATEWAY_API_KEY
    reader. Keys are generated on first use by cato.vault_crypto and stay in this dict.
    """

    def __init__(self, **seed: str) -> None:
        self._data: dict[str, str] = dict(seed)

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


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


async def test_master_client_uses_versioned_auth_and_propagates_freshness(
    tmp_path: Path, memory: MemorySystem,
) -> None:
    captured = {}

    async def transport(url, payload, headers, timeout_s):
        captured.update(url=url, payload=payload, headers=headers, timeout_s=timeout_s)
        return 200, {
            "chunks": [{
                "citation": "knowledge/entity.md#entity-map",
                "content": "E4L is the current operating entity.",
                "content_sha256": "abc",
                "score": 0.9,
                "status": "active",
                "entity": "E4L",
            }],
            "stale": True,
            "refusal": False,
        }

    config = SimpleNamespace(
        genesis_enabled=True,
        genesis_endpoint="https://genesis.invalid",
        genesis_timeout_s=5,
    )
    vault = _SigningVault(GATEWAY_API_KEY="gateway-test-key")
    client = GenesisRetrievalClient(config, vault, transport=transport)
    result = await answer_question_master(
        memory,
        tmp_path / "unused-local-vault",
        "What is the operating entity?",
        llm_complete=_FakeLLM("E4L is the operating entity."),
        remote_client=client,
    )

    assert captured["url"] == "https://genesis.invalid/retrieval/query"
    # The shared gateway key is no longer sent or needed: Genesis authenticates retrieval the
    # same way it authenticates an agent run, via the signed AP2 envelope.
    assert "X-Agent-Api-Key" not in captured["headers"]
    assert captured["headers"]["X-AP2-Version"] == "1"
    assert captured["headers"]["X-AP2-Pubkey"] == captured["payload"]["pubkey"]
    assert captured["headers"]["X-E4L-Retrieval-Contract"] == REMOTE_RETRIEVAL_CONTRACT_VERSION
    assert captured["payload"]["domain_hint"] == "vault"
    assert result.source == "genesis_master_retrieval"
    assert result.authoritative is False
    assert result.stale is True
    assert result.citations[0].formatted() == "knowledge/entity.md#entity-map"


async def test_missing_remote_content_falls_back_with_non_authority_warning(
    tmp_path: Path, memory: MemorySystem,
) -> None:
    vault_root = tmp_path / "vault"
    _write(vault_root, "knowledge/entity.md", "# Entity Map\n\nE4L is the operating entity.\n")
    _add_distractors(vault_root)
    ingest_vault(memory, vault_root)

    async def citation_only_transport(*_args):
        return 200, {
            "chunks": [{
                "citation": "knowledge/entity.md#entity-map",
                "content_sha256": "abc",
                "score": 0.9,
                "status": "active",
            }],
            "stale": False,
        }

    config = SimpleNamespace(
        genesis_enabled=True,
        genesis_endpoint="https://genesis.invalid",
        genesis_timeout_s=5,
    )
    vault = _SigningVault(GATEWAY_API_KEY="gateway-test-key")
    result = await answer_question_master(
        memory,
        vault_root,
        "What is the operating entity?",
        llm_complete=_FakeLLM("E4L is the operating entity."),
        remote_client=GenesisRetrievalClient(config, vault, transport=citation_only_transport),
    )

    assert result.source == "local_fallback"
    assert result.authoritative is False
    assert "content/authority contract is not yet proven" in result.authority_note


@pytest.mark.parametrize("score", ["0.9", None, True, float("nan"), float("inf"), -0.1, 1.1])
async def test_master_client_rejects_malformed_or_nonfinite_remote_scores(score) -> None:
    async def transport(*_args):
        return 200, {
            "chunks": [{
                "citation": "remote/hostile.md#claim",
                "content": "REMOTE_SENTINEL must never reach synthesis.",
                "score": score,
            }],
        }

    config = SimpleNamespace(
        genesis_enabled=True,
        genesis_endpoint="https://genesis.invalid",
        genesis_timeout_s=5,
    )
    client = GenesisRetrievalClient(
        config,
        _SigningVault(GATEWAY_API_KEY="gateway-test-key"),
        transport=transport,
    )

    remote = await client.retrieve("question", top_k=1, include_history=False)

    assert remote.available is False
    assert remote.chunks == []
    assert remote.reason == "remote retrieval returned an invalid score"


@pytest.mark.parametrize("chunks,top_k,reason", [
    (
        [{"citation": "remote/hostile.md#claim", "content": "x" * (REMOTE_RETRIEVAL_MAX_CONTENT_BYTES + 1), "score": 0.9}],
        1,
        "remote retrieval response exceeded safe size limits",
    ),
    (
        [
            {"citation": f"remote/{index}.md#claim", "content": "x" * (REMOTE_RETRIEVAL_MAX_TOTAL_CONTENT_BYTES // 5), "score": 0.9}
            for index in range(6)
        ],
        6,
        "remote retrieval response exceeded safe size limits",
    ),
    (
        [
            {"citation": f"remote/{index}.md#claim", "content": "REMOTE_SENTINEL", "score": 0.9}
            for index in range(3)
        ],
        2,
        "remote retrieval exceeded the requested chunk limit",
    ),
])
async def test_master_client_rejects_oversize_or_excess_remote_chunks(
    chunks, top_k, reason,
) -> None:
    async def transport(*_args):
        return 200, {"chunks": chunks}

    config = SimpleNamespace(
        genesis_enabled=True,
        genesis_endpoint="https://genesis.invalid",
        genesis_timeout_s=5,
    )
    client = GenesisRetrievalClient(
        config,
        _SigningVault(GATEWAY_API_KEY="gateway-test-key"),
        transport=transport,
    )

    remote = await client.retrieve("question", top_k=top_k, include_history=False)

    assert remote.available is False
    assert remote.chunks == []
    assert remote.reason == reason


async def test_invalid_remote_payload_falls_back_without_remote_content_in_prompt(
    tmp_path: Path, memory: MemorySystem,
) -> None:
    vault_root = tmp_path / "vault"
    _write(vault_root, "knowledge/entity.md", "# Entity\n\nThe local entity is E4L.\n")
    _add_distractors(vault_root)
    ingest_vault(memory, vault_root)

    async def transport(*_args):
        return 200, {"chunks": [{
            "citation": "remote/hostile.md#claim",
            "content": "REMOTE_SENTINEL must never reach synthesis.",
            "score": math.nan,
        }]}

    config = SimpleNamespace(
        genesis_enabled=True,
        genesis_endpoint="https://genesis.invalid",
        genesis_timeout_s=5,
    )
    fake_llm = _FakeLLM("The local entity is E4L.")
    result = await answer_question_master(
        memory,
        vault_root,
        "What is the local entity?",
        llm_complete=fake_llm,
        remote_client=GenesisRetrievalClient(
            config,
            _SigningVault(GATEWAY_API_KEY="gateway-test-key"),
            transport=transport,
        ),
        top_k=1,
    )

    assert result.source == "local_fallback"
    assert result.authoritative is False
    assert all("REMOTE_SENTINEL" not in prompt for prompt in fake_llm.calls)


# ---------------------------------------------------------------------------
# JOB 1 — retrieval authenticates via a signed AP2 envelope, same as agent runs
# ---------------------------------------------------------------------------

async def _capture_retrieval_request(vault, *, question="What is the E4L entity map?", top_k=3):
    captured: dict = {}

    async def transport(url, payload, headers, timeout_s):
        captured.update(url=url, payload=payload, headers=headers)
        return 200, {"chunks": [], "refusal": True, "reason": "no vault answer found above threshold"}

    config = SimpleNamespace(
        genesis_enabled=True,
        genesis_endpoint="https://genesis.invalid",
        genesis_timeout_s=5,
    )
    client = GenesisRetrievalClient(config, vault, transport=transport)
    await client.retrieve(question, top_k=top_k, include_history=False)
    return captured


async def test_retrieval_request_is_a_signed_ap2_envelope_binding_the_query() -> None:
    """The signature must cover the query text and the retrieval scope.

    Genesis re-derives (task, params) from the UNSIGNED wire fields and refuses unless they equal
    the signed payload, so this asserts the exact bytes Genesis will check: a signature that
    verified but covered a different query would be theatre.
    """
    import base64
    import json

    from cato import vault_crypto
    from cato.core.ask_e4l import RETRIEVAL_ENVELOPE_AGENT

    vault = _SigningVault()
    question = "What is the E4L entity map?"
    captured = await _capture_retrieval_request(vault, question=question, top_k=3)
    payload = captured["payload"]

    assert payload["payload"]["agent"] == RETRIEVAL_ENVELOPE_AGENT
    assert payload["payload"]["task"] == question
    assert payload["payload"]["params"] == {
        "top_k": 3,
        "entity_filter": None,
        "include_superseded": False,
        "domain_hint": "vault",
        "requesting_principal": None,
    }
    # Unsigned wire fields must equal the signed params, field for field.
    for key, value in payload["payload"]["params"].items():
        assert payload[key] == value
    assert payload["query"] == question

    signed_bytes = json.dumps(
        {
            "payload": payload["payload"],
            "nonce": payload["nonce"],
            "timestamp": payload["timestamp"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert vault_crypto.verify(
        base64.b64decode(payload["pubkey"]),
        signed_bytes,
        base64.b64decode(payload["signature"]),
    )
    assert payload["pubkey"] == vault_crypto.public_key_b64(vault)


async def test_retrieval_no_longer_depends_on_the_shared_gateway_key() -> None:
    """A vault with no GATEWAY_API_KEY at all must still be able to retrieve — AP2 is the single
    authentication path now, so the shared key must not be a hidden prerequisite."""
    captured = await _capture_retrieval_request(_SigningVault())

    assert "X-Agent-Api-Key" not in captured["headers"]
    assert captured["headers"]["X-AP2-Version"] == "1"


async def test_every_retrieval_request_uses_a_fresh_nonce() -> None:
    """Genesis consumes the nonce atomically, so a reused nonce is a self-inflicted 401."""
    vault = _SigningVault()
    first = await _capture_retrieval_request(vault)
    second = await _capture_retrieval_request(vault)

    assert first["payload"]["nonce"] != second["payload"]["nonce"]
    assert first["payload"]["pubkey"] == second["payload"]["pubkey"]  # stable identity


async def test_unsignable_vault_degrades_instead_of_sending_an_unsigned_request() -> None:
    """If the keypair cannot be produced, the client must refuse to call rather than fall back to
    an unauthenticated request — fails closed."""

    class _BrokenVault:
        def get(self, _key):
            raise RuntimeError("vault locked")

    async def transport(*_args):
        raise AssertionError("must never reach the network without a signature")

    config = SimpleNamespace(
        genesis_enabled=True, genesis_endpoint="https://genesis.invalid", genesis_timeout_s=5,
    )
    client = GenesisRetrievalClient(config, _BrokenVault(), transport=transport)

    result = await client.retrieve("anything", top_k=3, include_history=False)

    assert result.available is False
    assert result.reason == "genesis request signing unavailable: RuntimeError"
