"""
cato/core/retrieval.py — QMD Hybrid Search Retrieval Layer.

Combines memory (BM25+semantic) with optional web search, deduplicates,
and reranks results using a CrossEncoder model.

Each result dict schema:
    {
        "text": str,
        "source": "memory" | "web" | "session",
        "score": float,
        "url": str | None,
        "chunk_id": str | None,
        "rerank_score": float | None,   # set after reranking
    }
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_LOW_CONFIDENCE_THRESHOLD = 0.3
_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class HybridRetriever:
    """
    QMD hybrid retrieval: memory + optional web search + CrossEncoder reranking.

    Usage::

        retriever = HybridRetriever(memory=mem)
        results = await retriever.search("Python async patterns", top_k=5)
    """

    def __init__(
        self,
        memory: Any,
        web_search_tool: Optional[Any] = None,
        rerank_enabled: bool = True,
        rerank_threshold: int = 5,
    ) -> None:
        self._memory = memory
        self._web_search_tool = web_search_tool
        self._rerank_enabled = rerank_enabled
        self._rerank_threshold = rerank_threshold
        self._cross_encoder: Optional[Any] = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Lazy CrossEncoder loader
    # ------------------------------------------------------------------

    def _get_cross_encoder(self) -> Optional[Any]:
        if self._cross_encoder is not None:
            return self._cross_encoder
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import]
            self._cross_encoder = CrossEncoder(_CROSS_ENCODER_MODEL)
            logger.info("CrossEncoder loaded: %s", _CROSS_ENCODER_MODEL)
        except Exception as exc:
            logger.warning(
                "CrossEncoder not available (%s) — reranking will fall back to original scores", exc
            )
            self._cross_encoder = None
        return self._cross_encoder

    # ------------------------------------------------------------------
    # Core search
    # ------------------------------------------------------------------

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Search memory (and optionally web), deduplicate, and rerank.

        Returns at most *top_k* result dicts.
        """
        memory_results = await self._fetch_memory(query, top_k=top_k * 2)
        candidates = memory_results

        # Rerank when candidate set is large enough
        if self._rerank_enabled and len(candidates) > self._rerank_threshold:
            candidates = self.rerank(query, candidates, top_k=top_k)
        else:
            candidates = candidates[:top_k]

        # Emit low-confidence warning
        if candidates and candidates[0].get("score", 0) < _LOW_CONFIDENCE_THRESHOLD:
            logger.warning(
                "LOW_CONFIDENCE_RETRIEVAL: top score=%.3f for query=%r",
                candidates[0].get("score", 0),
                query,
            )

        return candidates

    # ------------------------------------------------------------------
    # Federated search (memory + web in parallel)
    # ------------------------------------------------------------------

    async def federated_search(self, query: str, top_k: int = 10) -> list[dict]:
        """
        Run memory and web search in parallel, merge, deduplicate, rerank.
        """
        tasks: list[asyncio.coroutines] = [self._fetch_memory(query, top_k=top_k)]
        if self._web_search_tool is not None:
            tasks.append(self._fetch_web(query, top_k=top_k))

        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        all_candidates: list[dict] = []
        for result in gathered:
            if isinstance(result, Exception):
                logger.warning("Federated search source error: %s", result)
                continue
            if isinstance(result, list):
                all_candidates.extend(result)

        # Deduplicate
        all_candidates = self._deduplicate(all_candidates)

        # Rerank
        if self._rerank_enabled and len(all_candidates) > self._rerank_threshold:
            all_candidates = self.rerank(query, all_candidates, top_k=top_k)
        else:
            all_candidates = all_candidates[:top_k]

        # Emit low-confidence warning
        if all_candidates and all_candidates[0].get("score", 0) < _LOW_CONFIDENCE_THRESHOLD:
            logger.warning(
                "LOW_CONFIDENCE_RETRIEVAL: top score=%.3f for federated query=%r",
                all_candidates[0].get("score", 0),
                query,
            )

        return all_candidates

    # ------------------------------------------------------------------
    # Reranking
    # ------------------------------------------------------------------

    def rerank(self, query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
        """
        Rerank *candidates* using a CrossEncoder.

        Falls back to score-sorted ordering if CrossEncoder unavailable.
        """
        if not candidates:
            return []

        encoder = self._get_cross_encoder()
        if encoder is None:
            # Fallback: sort by existing score
            return sorted(candidates, key=lambda r: r.get("score", 0.0), reverse=True)[:top_k]

        try:
            pairs = [(query, r.get("text", "")) for r in candidates]
            scores = encoder.predict(pairs)
            for r, s in zip(candidates, scores):
                r["rerank_score"] = float(s)
            ranked = sorted(candidates, key=lambda r: r.get("rerank_score", 0.0), reverse=True)
            return ranked[:top_k]
        except Exception as exc:
            logger.warning("CrossEncoder predict failed: %s — using original ordering", exc)
            return sorted(candidates, key=lambda r: r.get("score", 0.0), reverse=True)[:top_k]

    # ------------------------------------------------------------------
    # Internal fetchers
    # ------------------------------------------------------------------

    async def _fetch_memory(self, query: str, top_k: int) -> list[dict]:
        """Fetch results from the MemorySystem."""
        try:
            raw = await self._memory.asearch(query, top_k=top_k)
        except Exception as exc:
            logger.warning("Memory search failed: %s", exc)
            return []

        results: list[dict] = []
        for i, text in enumerate(raw):
            results.append({
                "text": text,
                "source": "memory",
                "score": max(0.0, 1.0 - i * 0.05),  # proxy score based on rank
                "url": None,
                "chunk_id": f"mem-{i}",
                "rerank_score": None,
            })
        return results

    async def _fetch_web(self, query: str, top_k: int) -> list[dict]:
        """Fetch results from the web search tool."""
        try:
            raw = await self._web_search_tool.search(query=query, max_results=top_k)
        except Exception as exc:
            logger.warning("Web search failed: %s", exc)
            return []

        results: list[dict] = []
        for r in raw:
            results.append({
                "text": getattr(r, "snippet", str(r)),
                "source": "web",
                "score": getattr(r, "confidence", 0.5),
                "url": getattr(r, "url", None),
                "chunk_id": None,
                "rerank_score": None,
            })
        return results

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(candidates: list[dict]) -> list[dict]:
        """
        Remove duplicates by URL (for web results) or chunk_id (for memory).
        First occurrence wins.
        """
        seen_urls: set[str] = set()
        seen_chunks: set[str] = set()
        unique: list[dict] = []

        for r in candidates:
            url = r.get("url")
            chunk_id = r.get("chunk_id")

            if url is not None:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
            elif chunk_id is not None:
                if chunk_id in seen_chunks:
                    continue
                seen_chunks.add(chunk_id)

            unique.append(r)

        return unique
