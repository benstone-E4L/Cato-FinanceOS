"""
tests/test_retrieval.py — Tests for Skill 4: QMD Hybrid Search Retrieval Layer.

Min 20 tests covering:
- HybridRetriever.search() with mocked memory
- Deduplication logic for URLs and chunk_ids
- LOW_CONFIDENCE_RETRIEVAL warning emission
- Graceful fallback when CrossEncoder unavailable
- federated_search behavior
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.core.retrieval import HybridRetriever, _LOW_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_memory(chunks: list[str] | None = None):
    """Return a mock MemorySystem with asearch returning given chunks."""
    mem = MagicMock()
    mem.asearch = AsyncMock(return_value=chunks or [])
    return mem


def _make_results(*texts: str, source: str = "memory", base_score: float = 0.8) -> list[dict]:
    results = []
    for i, text in enumerate(texts):
        results.append({
            "text": text,
            "source": source,
            "score": base_score - i * 0.05,
            "url": f"http://example.com/{i}" if source == "web" else None,
            "chunk_id": f"mem-{i}" if source == "memory" else None,
            "rerank_score": None,
        })
    return results


# ---------------------------------------------------------------------------
# HybridRetriever.search()
# ---------------------------------------------------------------------------

class TestHybridRetrieverSearch:
    @pytest.mark.asyncio
    async def test_search_returns_list(self):
        """search() returns a list of dicts."""
        mem = _make_mock_memory(["chunk one", "chunk two"])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        results = await r.search("test query", top_k=5)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_result_structure(self):
        """Each result has required keys."""
        mem = _make_mock_memory(["hello world"])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        results = await r.search("hello", top_k=5)
        assert len(results) >= 1
        item = results[0]
        assert "text" in item
        assert "source" in item
        assert "score" in item
        assert "url" in item
        assert "chunk_id" in item

    @pytest.mark.asyncio
    async def test_search_memory_source_label(self):
        """Memory results have source='memory'."""
        mem = _make_mock_memory(["memory result"])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        results = await r.search("query", top_k=5)
        assert all(item["source"] == "memory" for item in results)

    @pytest.mark.asyncio
    async def test_search_empty_memory(self):
        """search() returns empty list when memory is empty."""
        mem = _make_mock_memory([])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        results = await r.search("query", top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self):
        """search() returns at most top_k results."""
        mem = _make_mock_memory([f"chunk {i}" for i in range(20)])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        results = await r.search("query", top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_search_calls_memory_asearch(self):
        """search() calls memory.asearch with the right query."""
        mem = _make_mock_memory(["result"])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        await r.search("my query", top_k=5)
        mem.asearch.assert_called_once()
        call_args = mem.asearch.call_args
        assert "my query" in call_args[0] or call_args[1].get("query") == "my query"

    @pytest.mark.asyncio
    async def test_search_memory_exception_returns_empty(self):
        """If memory.asearch raises, search() returns empty list gracefully."""
        mem = MagicMock()
        mem.asearch = AsyncMock(side_effect=RuntimeError("db error"))
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        results = await r.search("query", top_k=5)
        assert results == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_dedup_by_url(self):
        """Duplicate URLs are removed — first occurrence wins."""
        candidates = [
            {"text": "a", "source": "web", "score": 0.9, "url": "http://ex.com/1", "chunk_id": None, "rerank_score": None},
            {"text": "b", "source": "web", "score": 0.8, "url": "http://ex.com/1", "chunk_id": None, "rerank_score": None},
            {"text": "c", "source": "web", "score": 0.7, "url": "http://ex.com/2", "chunk_id": None, "rerank_score": None},
        ]
        unique = HybridRetriever._deduplicate(candidates)
        assert len(unique) == 2
        assert unique[0]["text"] == "a"  # first occurrence wins

    def test_dedup_by_chunk_id(self):
        """Duplicate chunk_ids are removed."""
        candidates = [
            {"text": "x", "source": "memory", "score": 0.8, "url": None, "chunk_id": "mem-1", "rerank_score": None},
            {"text": "y", "source": "memory", "score": 0.6, "url": None, "chunk_id": "mem-1", "rerank_score": None},
        ]
        unique = HybridRetriever._deduplicate(candidates)
        assert len(unique) == 1
        assert unique[0]["text"] == "x"

    def test_dedup_no_duplicates(self):
        """Non-duplicate list is unchanged."""
        candidates = [
            {"text": "a", "source": "web", "score": 0.9, "url": "http://ex.com/1", "chunk_id": None, "rerank_score": None},
            {"text": "b", "source": "memory", "score": 0.8, "url": None, "chunk_id": "mem-1", "rerank_score": None},
        ]
        unique = HybridRetriever._deduplicate(candidates)
        assert len(unique) == 2

    def test_dedup_empty_list(self):
        """Deduplication of empty list returns empty."""
        assert HybridRetriever._deduplicate([]) == []

    def test_dedup_mixed_sources(self):
        """URL dedup and chunk_id dedup work together."""
        candidates = [
            {"text": "web1", "source": "web", "score": 0.9, "url": "http://x.com", "chunk_id": None, "rerank_score": None},
            {"text": "web1-dup", "source": "web", "score": 0.8, "url": "http://x.com", "chunk_id": None, "rerank_score": None},
            {"text": "mem1", "source": "memory", "score": 0.7, "url": None, "chunk_id": "c1", "rerank_score": None},
            {"text": "mem1-dup", "source": "memory", "score": 0.6, "url": None, "chunk_id": "c1", "rerank_score": None},
        ]
        unique = HybridRetriever._deduplicate(candidates)
        assert len(unique) == 2


# ---------------------------------------------------------------------------
# LOW_CONFIDENCE_RETRIEVAL warning
# ---------------------------------------------------------------------------

class TestLowConfidenceWarning:
    @pytest.mark.asyncio
    async def test_low_confidence_warning_emitted(self, caplog):
        """LOW_CONFIDENCE_RETRIEVAL warning logged when top score < 0.3."""
        mem = _make_mock_memory(["low-conf result"])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        # Force very low score by patching _fetch_memory result
        low_score_result = [{"text": "x", "source": "memory", "score": 0.1, "url": None, "chunk_id": "c0", "rerank_score": None}]
        with patch.object(r, "_fetch_memory", AsyncMock(return_value=low_score_result)):
            with caplog.at_level(logging.WARNING, logger="cato.core.retrieval"):
                await r.search("obscure query", top_k=5)
        assert "LOW_CONFIDENCE_RETRIEVAL" in caplog.text

    @pytest.mark.asyncio
    async def test_no_warning_for_high_confidence(self, caplog):
        """No LOW_CONFIDENCE_RETRIEVAL warning when score >= 0.3."""
        mem = _make_mock_memory(["high confidence"])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        high_score = [{"text": "x", "source": "memory", "score": 0.8, "url": None, "chunk_id": "c0", "rerank_score": None}]
        with patch.object(r, "_fetch_memory", AsyncMock(return_value=high_score)):
            with caplog.at_level(logging.WARNING, logger="cato.core.retrieval"):
                await r.search("query", top_k=5)
        assert "LOW_CONFIDENCE_RETRIEVAL" not in caplog.text

    @pytest.mark.asyncio
    async def test_warning_threshold_boundary(self, caplog):
        """Score exactly at threshold (0.3) does NOT emit a warning."""
        mem = _make_mock_memory([])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        boundary = [{"text": "x", "source": "memory", "score": _LOW_CONFIDENCE_THRESHOLD, "url": None, "chunk_id": "c0", "rerank_score": None}]
        with patch.object(r, "_fetch_memory", AsyncMock(return_value=boundary)):
            with caplog.at_level(logging.WARNING, logger="cato.core.retrieval"):
                await r.search("query", top_k=5)
        assert "LOW_CONFIDENCE_RETRIEVAL" not in caplog.text


# ---------------------------------------------------------------------------
# CrossEncoder fallback
# ---------------------------------------------------------------------------

class TestCrossEncoderFallback:
    def test_rerank_without_crossencoder_uses_score_sort(self):
        """Rerank falls back to score sorting when CrossEncoder unavailable."""
        mem = _make_mock_memory()
        r = HybridRetriever(memory=mem, rerank_enabled=True)
        r._cross_encoder = None  # Force unavailable

        candidates = [
            {"text": "low", "source": "memory", "score": 0.3, "url": None, "chunk_id": "c1", "rerank_score": None},
            {"text": "high", "source": "memory", "score": 0.9, "url": None, "chunk_id": "c2", "rerank_score": None},
            {"text": "mid", "source": "memory", "score": 0.6, "url": None, "chunk_id": "c3", "rerank_score": None},
        ]

        # Patch _get_cross_encoder to return None
        with patch.object(r, "_get_cross_encoder", return_value=None):
            ranked = r.rerank("query", candidates, top_k=3)

        assert ranked[0]["text"] == "high"
        assert ranked[-1]["text"] == "low"

    def test_rerank_adds_rerank_score_when_encoder_available(self):
        """Rerank adds rerank_score to each result when encoder works."""
        mem = _make_mock_memory()
        r = HybridRetriever(memory=mem, rerank_enabled=True)

        mock_encoder = MagicMock()
        mock_encoder.predict = MagicMock(return_value=[0.9, 0.2])

        candidates = [
            {"text": "a", "source": "memory", "score": 0.5, "url": None, "chunk_id": "c1", "rerank_score": None},
            {"text": "b", "source": "memory", "score": 0.5, "url": None, "chunk_id": "c2", "rerank_score": None},
        ]

        with patch.object(r, "_get_cross_encoder", return_value=mock_encoder):
            ranked = r.rerank("query", candidates, top_k=2)

        assert ranked[0]["rerank_score"] is not None

    def test_rerank_empty_candidates(self):
        """Rerank with empty candidates returns empty list."""
        mem = _make_mock_memory()
        r = HybridRetriever(memory=mem, rerank_enabled=True)
        result = r.rerank("query", [], top_k=5)
        assert result == []


# ---------------------------------------------------------------------------
# Federated search
# ---------------------------------------------------------------------------

class TestFederatedSearch:
    @pytest.mark.asyncio
    async def test_federated_without_web_tool(self):
        """federated_search works with memory-only (no web tool)."""
        mem = _make_mock_memory(["federated result"])
        r = HybridRetriever(memory=mem, rerank_enabled=False)
        results = await r.federated_search("query", top_k=5)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_federated_deduplicates_results(self):
        """federated_search deduplicates before returning."""
        mem = _make_mock_memory(["chunk"])
        r = HybridRetriever(memory=mem, rerank_enabled=False)

        # Two copies of same result
        dup_result = [
            {"text": "dup", "source": "memory", "score": 0.8, "url": None, "chunk_id": "mem-0", "rerank_score": None},
            {"text": "dup", "source": "memory", "score": 0.8, "url": None, "chunk_id": "mem-0", "rerank_score": None},
        ]
        with patch.object(r, "_fetch_memory", AsyncMock(return_value=dup_result)):
            results = await r.federated_search("query", top_k=10)

        assert len(results) == 1
