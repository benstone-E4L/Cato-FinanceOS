"""
cato/core/ask_e4l.py — CHUNK_4_ASK_E4L: the Retrieval Contract answer engine.

Ask-E4L is a chat surface (inside Cato's existing desktop/Telegram UI —
CHUNK_6 wires it into the reorganized nav) built on top of Chunk 3's vault
index. This module implements every deterministic rule from the master
spec's Retrieval Contract:

  * citations in ``{vault-relative-path}#{heading-anchor}`` format
  * superseded chunks excluded by default, retrievable on explicit request
  * a hard refusal path when nothing indexed clears the retrieval threshold
    — the LLM is never invoked in that case, so it cannot guess
  * a staleness flag when the index predates the vault tree's latest change

Genuine semantic judgment — "do these two ACTIVE notes actually disagree on
a fact?" — is not something deterministic code can decide from text alone,
so that one step (and only that step) is delegated to an LLM via an
injectable ``llm_complete`` callable, per CLAUDE.md's "model for judgment
only" doctrine. The model is instructed to emit a structured
``[CONTRADICTION: id_a | id_b]`` marker when (and only when) it finds a real
conflict between two retrieved active chunks; this module parses that
marker deterministically rather than trusting free-form prose — the model
still cannot silently avoid flagging a contradiction it found, because the
instruction is explicit and the caller checks for the marker, not for the
model's own summary of whether it found one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import aiohttp

from ..tools.genesis import AP2_ENVELOPE_VERSION, build_envelope
from .vault_ingest import index_is_stale

# Genesis authenticates /retrieval/query exactly the way it authenticates /agents/{slug}/run:
# a signed AP2 envelope verified against trusted_ap2_clients.json (scope `retrieval.query`).
# Retrieval has no agent slug, so the envelope's `agent` names the ROUTE, `task` carries the
# query text, and `params` carries the retrieval scope. Genesis mirrors this constant in
# runtime/request_auth.py:RETRIEVAL_ENVELOPE_AGENT — the two must not drift.
RETRIEVAL_ENVELOPE_AGENT = "retrieval.query"

# Below this hybrid BM25+semantic score, a retrieved chunk is not trusted
# enough to ground an answer. Conservative on purpose: false refusals are
# recoverable (the operator rephrases); a confidently-wrong answer is not.
RETRIEVAL_SCORE_THRESHOLD = 0.12

REFUSAL_TEXT = (
    "No vault answer found. Nothing indexed from the E4L knowledge vault "
    "cleared the retrieval threshold for this question — I'm not going to "
    "guess."
)

_CONTRADICTION_MARKER_RE_TEXT = "[CONTRADICTION:"

# Second-layer refusal marker. The retrieval-threshold gate above only
# catches the *zero relevant chunks* case; at real vault scale a topically-
# adjacent chunk (e.g. a Gmail OAuth setup note, for "what's my Gmail
# password") can clear the score threshold without actually answering the
# question. Rather than trust the model's free-form prose ("I don't have
# that information..."), the model is instructed to emit this exact marker
# when the retrieved excerpts don't genuinely ground an answer — parsed
# deterministically here, same pattern as the contradiction marker, so a
# model can't get credit for a mushy non-answer that doesn't emit it.
NO_GROUNDED_ANSWER_MARKER = "NO_GROUNDED_ANSWER"
REMOTE_RETRIEVAL_CONTRACT_VERSION = "1"
REMOTE_RETRIEVAL_MAX_CHUNKS = 20
REMOTE_RETRIEVAL_MAX_CONTENT_BYTES = 16_384
REMOTE_RETRIEVAL_MAX_TOTAL_CONTENT_BYTES = 65_536
REMOTE_RETRIEVAL_MAX_CITATION_BYTES = 2_048


@dataclass(frozen=True)
class Citation:
    vault_path: str
    heading_anchor: str
    canonical_id: str

    def formatted(self) -> str:
        """``{vault-relative-path}#{heading-anchor}`` — the exact citation format."""
        return f"{self.vault_path}#{self.heading_anchor}"


@dataclass
class RetrievedChunk:
    canonical_id: str
    content: str
    score: float
    metadata: dict

    @property
    def citation(self) -> Citation:
        vault_path, _, rest = self.canonical_id.partition("#")
        heading_anchor, _, _index = rest.partition("@")
        return Citation(
            vault_path=vault_path,
            heading_anchor=heading_anchor,
            canonical_id=self.canonical_id,
        )

    @property
    def is_active(self) -> bool:
        return self.metadata.get("status") == "active"


@dataclass
class AskE4LAnswer:
    question: str
    refused: bool
    text: str
    citations: list[Citation] = field(default_factory=list)
    contradiction: bool = False
    contradiction_citations: list[Citation] = field(default_factory=list)
    stale: bool = False
    retrieved: list[RetrievedChunk] = field(default_factory=list)
    superseded_available: bool = False
    source: str = "local_fallback"
    authoritative: bool = False
    authority_note: str = (
        "Local Cato retrieval is a derived convenience index, not current-state authority."
    )


LLMComplete = Callable[[str], Awaitable[str]]
RemoteTransport = Callable[
    [str, dict[str, Any], dict[str, str], float],
    Awaitable[tuple[int, dict[str, Any]]],
]


@dataclass
class RemoteRetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    stale: bool = False
    available: bool = False
    reason: str = ""
    contract_version: str = REMOTE_RETRIEVAL_CONTRACT_VERSION


class GenesisRetrievalClient:
    """Versioned read-only boundary to Genesis's derived retrieval route.

    The remote index is not promoted to canonical authority here.  It becomes
    usable only when every returned chunk includes the source content needed
    for grounded synthesis; citation-only metadata cannot support an answer.
    """

    def __init__(self, config: Any, vault: Any, transport: RemoteTransport | None = None) -> None:
        self._config = config
        self._vault = vault
        self._transport = transport or self._http_transport

    @staticmethod
    async def _http_transport(
        url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float,
    ) -> tuple[int, dict[str, Any]]:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                try:
                    body = await response.json(content_type=None)
                except Exception:
                    body = {}
                return response.status, body if isinstance(body, dict) else {}

    async def retrieve(
        self, question: str, *, top_k: int, include_history: bool,
    ) -> RemoteRetrievalResult:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            return RemoteRetrievalResult(reason="remote retrieval top_k is invalid")
        accepted_top_k = min(top_k, REMOTE_RETRIEVAL_MAX_CHUNKS)
        if not bool(getattr(self._config, "genesis_enabled", False)):
            return RemoteRetrievalResult(reason="genesis retrieval disabled")

        endpoint = str(getattr(self._config, "genesis_endpoint", "")).rstrip("/")
        if not endpoint:
            return RemoteRetrievalResult(reason="genesis endpoint unavailable")
        timeout_s = min(max(float(getattr(self._config, "genesis_timeout_s", 30.0)), 1.0), 60.0)

        # Every scope field below is signed, so it must be JSON-canonical on the wire and in the
        # signed payload alike — `bool(include_history)` matters, because Genesis normalizes the
        # wire body through a pydantic model before comparing and a truthy `1` would not match a
        # signed `1` once normalized to `true`.
        scope = {
            "top_k": accepted_top_k,
            "entity_filter": None,
            "include_superseded": bool(include_history),
            "domain_hint": "vault",
            "requesting_principal": None,
        }
        try:
            envelope = build_envelope(self._vault, RETRIEVAL_ENVELOPE_AGENT, question, scope)
        except Exception as exc:
            return RemoteRetrievalResult(
                reason=f"genesis request signing unavailable: {type(exc).__name__}"
            )

        # Wire shape mirrors the agent-run path: the signed envelope, plus the unsigned execution
        # fields the route actually reads. Genesis re-derives (task, params) from those unsigned
        # fields and refuses unless they equal the signed payload, so the signature binds the
        # query text and the retrieval scope, not merely the fact that Cato sent something.
        payload = {**envelope, "query": question, **scope}
        headers = {
            "Content-Type": "application/json",
            "X-AP2-Version": str(AP2_ENVELOPE_VERSION),
            "X-AP2-Pubkey": envelope["pubkey"],
            "X-E4L-Retrieval-Contract": REMOTE_RETRIEVAL_CONTRACT_VERSION,
        }
        try:
            status, body = await self._transport(
                f"{endpoint}/retrieval/query", payload, headers, timeout_s,
            )
        except Exception as exc:
            return RemoteRetrievalResult(reason=f"remote retrieval unavailable: {type(exc).__name__}")
        if status != 200:
            return RemoteRetrievalResult(reason=f"remote retrieval HTTP {status}")
        if body.get("refusal"):
            return RemoteRetrievalResult(
                available=True,
                stale=bool(body.get("stale")),
                reason=str(body.get("reason") or "remote refusal"),
            )

        raw_chunks = body.get("chunks")
        if not isinstance(raw_chunks, list):
            return RemoteRetrievalResult(reason="remote retrieval contract missing chunks")
        if len(raw_chunks) > accepted_top_k:
            return RemoteRetrievalResult(reason="remote retrieval exceeded the requested chunk limit")
        chunks: list[RetrievedChunk] = []
        total_content_bytes = 0
        for raw in raw_chunks:
            if not isinstance(raw, dict):
                return RemoteRetrievalResult(reason="remote retrieval returned an invalid chunk")
            content = raw.get("content")
            citation = raw.get("citation")
            if not isinstance(content, str) or not content.strip() or not isinstance(citation, str):
                return RemoteRetrievalResult(
                    reason="remote retrieval content/authority contract is not yet proven"
                )
            content_bytes = len(content.encode("utf-8"))
            citation_bytes = len(citation.encode("utf-8"))
            total_content_bytes += content_bytes
            if (
                content_bytes > REMOTE_RETRIEVAL_MAX_CONTENT_BYTES
                or total_content_bytes > REMOTE_RETRIEVAL_MAX_TOTAL_CONTENT_BYTES
                or citation_bytes > REMOTE_RETRIEVAL_MAX_CITATION_BYTES
            ):
                return RemoteRetrievalResult(reason="remote retrieval response exceeded safe size limits")
            score = raw.get("score")
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
                or not 0.0 <= float(score) <= 1.0
            ):
                return RemoteRetrievalResult(reason="remote retrieval returned an invalid score")
            canonical_id = citation if "@" in citation else f"{citation}@0"
            chunks.append(RetrievedChunk(
                canonical_id=canonical_id,
                content=content,
                score=float(score),
                metadata={
                    "status": raw.get("status"),
                    "entity": raw.get("entity"),
                    "source": raw.get("source", "vault"),
                    "content_sha256": raw.get("content_sha256"),
                },
            ))
        return RemoteRetrievalResult(
            chunks=chunks,
            stale=bool(body.get("stale")),
            available=True,
        )


def _find_contradiction_candidates(
    chunks: list[RetrievedChunk],
) -> list[tuple[RetrievedChunk, RetrievedChunk]]:
    """Pre-filter pairs worth asking the model to judge for real disagreement.

    A pair is a *candidate* — not a confirmed contradiction — when both
    chunks are ``status: active``, come from different source files, and
    share the same declared ``entity`` (same topic, so an actual conflict is
    plausible). Real disagreement detection happens in the model step;
    this is only what gets shown to it.
    """
    active = [c for c in chunks if c.is_active]
    candidates: list[tuple[RetrievedChunk, RetrievedChunk]] = []
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            a_path = a.canonical_id.split("#", 1)[0]
            b_path = b.canonical_id.split("#", 1)[0]
            if a_path == b_path:
                continue
            a_entity = a.metadata.get("entity")
            b_entity = b.metadata.get("entity")
            if a_entity and b_entity and a_entity == b_entity:
                candidates.append((a, b))
    return candidates


def _build_grounded_prompt(
    question: str,
    chunks: list[RetrievedChunk],
    contradiction_candidates: list[tuple[RetrievedChunk, RetrievedChunk]],
) -> str:
    excerpts = "\n\n".join(
        f"[{c.canonical_id}] (status={c.metadata.get('status', 'unknown')})\n{c.content}"
        for c in chunks
    )
    contradiction_note = ""
    if contradiction_candidates:
        pairs = ", ".join(
            f"{a.canonical_id} vs {b.canonical_id}" for a, b in contradiction_candidates
        )
        contradiction_note = (
            "\n\nThe following excerpt pairs are on the same topic and BOTH "
            f"still marked active — check whether they actually disagree: {pairs}. "
            "If they truly conflict, do NOT average or silently prefer one. "
            "Quote both and emit a line in exactly this form for each conflicting "
            "pair: [CONTRADICTION: <canonical_id_a> | <canonical_id_b>]"
        )
    return (
        "Answer the question using ONLY the excerpts below. Cite every claim "
        "as {vault-relative-path}#{heading-anchor} (the bracketed id before "
        "each excerpt, without the @index suffix). Do not use outside "
        "knowledge. If, and only if, none of the excerpts actually contain "
        f"information that answers this specific question, respond with "
        f"exactly the single line {NO_GROUNDED_ANSWER_MARKER} and nothing "
        "else — do not guess, do not explain, do not use outside "
        "knowledge to fill the gap.\n\n"
        f"Question: {question}\n\n"
        f"Excerpts:\n{excerpts}"
        f"{contradiction_note}"
    )


def _parse_contradiction_markers(
    answer_text: str, candidates: list[tuple[RetrievedChunk, RetrievedChunk]]
) -> list[tuple[RetrievedChunk, RetrievedChunk]]:
    """Return only the candidate pairs the model actually flagged."""
    if _CONTRADICTION_MARKER_RE_TEXT not in answer_text:
        return []
    flagged: list[tuple[RetrievedChunk, RetrievedChunk]] = []
    for a, b in candidates:
        if a.canonical_id in answer_text and b.canonical_id in answer_text:
            flagged.append((a, b))
    return flagged


async def answer_question(
    memory: Any,
    vault_root: Optional[Path],
    question: str,
    *,
    llm_complete: LLMComplete,
    top_k: int = 6,
    score_threshold: float = RETRIEVAL_SCORE_THRESHOLD,
    include_history: bool = False,
) -> AskE4LAnswer:
    """Answer *question* against the vault index, enforcing the full
    Retrieval Contract (citations, superseded exclusion, refusal,
    contradiction surfacing, staleness).

    ``llm_complete`` is required and injectable — production callers pass a
    real router-backed callable; tests pass a deterministic fake so the
    control flow (refusal gate, citation formatting, contradiction-marker
    parsing, staleness) is fully testable without a live API call.
    """
    raw = memory.search_vault_chunks(
        question, top_k=top_k, include_superseded=include_history
    )
    retrieved = [
        RetrievedChunk(
            canonical_id=r["canonical_id"],
            content=r["content"],
            score=r["score"],
            metadata=r["metadata"],
        )
        for r in raw
    ]

    above_threshold = [r for r in retrieved if r.score >= score_threshold]

    if not above_threshold:
        # Refusal path — the LLM is never invoked to guess.
        return AskE4LAnswer(
            question=question,
            refused=True,
            text=REFUSAL_TEXT,
            retrieved=retrieved,
        )

    stale = bool(index_is_stale(memory, vault_root)) if vault_root is not None else False

    superseded_available = False
    if not include_history:
        # Cheap check: does explicit-history retrieval turn up anything this
        # default query excluded? Only needed to set the UI/answer hint.
        history = memory.search_vault_chunks(
            question, top_k=top_k, include_superseded=True
        )
        superseded_available = any(
            h["canonical_id"] not in {c.canonical_id for c in above_threshold}
            and h.get("metadata", {}).get("status") == "superseded"
            for h in history
        )

    contradiction_candidates = _find_contradiction_candidates(above_threshold)
    prompt = _build_grounded_prompt(question, above_threshold, contradiction_candidates)
    answer_text = await llm_complete(prompt)

    if answer_text.strip() == NO_GROUNDED_ANSWER_MARKER:
        # Second-layer refusal: chunks cleared the retrieval-score threshold
        # (so the fast zero-chunks gate above didn't fire), but the model
        # determined none of them actually answer the question and emitted
        # the marker instead of guessing. Same refusal shape as the
        # zero-chunks path so downstream consumers don't need a third branch.
        return AskE4LAnswer(
            question=question,
            refused=True,
            text=REFUSAL_TEXT,
            stale=stale,
            retrieved=retrieved,
        )

    flagged = _parse_contradiction_markers(answer_text, contradiction_candidates)
    contradiction_citations: list[Citation] = []
    for a, b in flagged:
        contradiction_citations.extend([a.citation, b.citation])

    return AskE4LAnswer(
        question=question,
        refused=False,
        text=answer_text,
        citations=[c.citation for c in above_threshold],
        contradiction=bool(flagged),
        contradiction_citations=contradiction_citations,
        stale=stale,
        retrieved=retrieved,
        superseded_available=superseded_available,
    )


async def answer_question_master(
    memory: Any,
    vault_root: Optional[Path],
    question: str,
    *,
    llm_complete: LLMComplete,
    remote_client: GenesisRetrievalClient,
    top_k: int = 6,
    score_threshold: float = RETRIEVAL_SCORE_THRESHOLD,
    include_history: bool = False,
) -> AskE4LAnswer:
    """Prefer the versioned Genesis retrieval boundary, then label fallback.

    Neither remote nor local derived indexes are declared current-state
    authority by this client.  Remote results must first prove the content
    contract; otherwise the existing local path remains available but is
    visibly marked as a non-authoritative fallback.
    """
    remote = await remote_client.retrieve(
        question, top_k=top_k, include_history=include_history,
    )
    if remote.available and remote.chunks:
        rows = [
            {
                "canonical_id": chunk.canonical_id,
                "content": chunk.content,
                "score": chunk.score,
                "metadata": chunk.metadata,
            }
            for chunk in remote.chunks
        ]

        class _RemoteMemory:
            def search_vault_chunks(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
                return rows

        result = await answer_question(
            _RemoteMemory(),
            None,
            question,
            llm_complete=llm_complete,
            top_k=top_k,
            score_threshold=score_threshold,
            include_history=include_history,
        )
        result.stale = remote.stale
        result.source = "genesis_master_retrieval"
        result.authoritative = False
        result.authority_note = (
            "Genesis retrieval is a derived index response; verify cited source files "
            "before treating it as current-state authority."
        )
        return result

    result = await answer_question(
        memory,
        vault_root,
        question,
        llm_complete=llm_complete,
        top_k=top_k,
        score_threshold=score_threshold,
        include_history=include_history,
    )
    result.source = "local_fallback"
    result.authoritative = False
    reason = remote.reason or "remote retrieval returned no usable grounded content"
    result.authority_note = (
        f"Non-authoritative local fallback ({reason}). Verify cited source files and "
        "refresh the canonical system before relying on current-state claims."
    )
    return result
