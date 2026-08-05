"""
cato/core/semantic_search.py — Vector embeddings and semantic search.

Uses sentence-transformers to embed text chunks and perform similarity search.
All vectors are stored in memory (no persistent vector DB).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

try:
    from sentence_transformers import SentenceTransformer, util
except ImportError:
    SentenceTransformer = None
    util = None

logger = logging.getLogger(__name__)

# Model identifier for embeddings
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast, lightweight, ~22MB


class SemanticSearchEngine:
    """
    Embed and search over memory chunks using sentence-transformers.

    Maintains an in-memory vector store keyed by chunk text.
    No persistent storage — vectors are computed on demand or batch-loaded.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL) -> None:
        """Initialize the embedding model."""
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers not installed: pip install sentence-transformers")

        try:
            self.model = SentenceTransformer(model_name)
            logger.info(f"Loaded embedding model: {model_name}")
        except Exception as e:
            logger.error(f"Failed to load embedding model {model_name}: {e}")
            raise

        # In-memory vector store: chunk_text -> embedding (list of floats)
        self.chunks: dict[str, list[float]] = {}
        self.embeddings: list[list[float]] = []

    def add_chunks(self, chunks: list[str]) -> int:
        """
        Embed and store a batch of text chunks.

        Args:
            chunks: List of text strings to embed.

        Returns:
            Number of NEW chunks added (duplicates are skipped).
        """
        if not chunks:
            return 0

        try:
            embeddings = self.model.encode(chunks, convert_to_tensor=False)

            added = 0
            for chunk, embedding in zip(chunks, embeddings):
                if chunk not in self.chunks:
                    self.chunks[chunk] = embedding
                    self.embeddings.append(embedding)
                    added += 1

            logger.debug(f"Added {added} new chunks to search index")
            return added
        except Exception as e:
            logger.error(f"Error embedding chunks: {e}")
            return 0

    def search(self, query: str, top_k: int = 4, threshold: float = 0.3) -> list[str]:
        """
        Search for the most similar chunks to a query.

        Args:
            query: Search query string.
            top_k: Number of results to return.
            threshold: Minimum similarity score (0-1). Results below this are excluded.

        Returns:
            List of chunk texts ranked by similarity (highest first).
        """
        if not self.chunks:
            logger.debug("Search index is empty")
            return []

        try:
            query_embedding = self.model.encode(query, convert_to_tensor=False)

            # Compute similarity scores using cosine similarity
            similarities = util.cos_sim(query_embedding, self.embeddings)[0]

            # Sort by similarity (descending)
            sorted_pairs = sorted(
                zip(self.chunks.keys(), similarities),
                key=lambda x: x[1],
                reverse=True
            )

            # Filter by threshold and limit to top_k
            results = [
                chunk for chunk, score in sorted_pairs
                if score >= threshold
            ][:top_k]

            logger.debug(f"Search query '{query}' returned {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"Error during search: {e}")
            return []

    def load_memory_file(self, memory_path: Path) -> int:
        """
        Load and index a MEMORY.md file.

        Splits the file into logical chunks (by ## sections) and embeds them.

        Args:
            memory_path: Path to MEMORY.md file.

        Returns:
            Number of chunks loaded and indexed.
        """
        if not memory_path.exists():
            logger.debug(f"Memory file not found: {memory_path}")
            return 0

        try:
            content = memory_path.read_text(encoding="utf-8", errors="replace")
            chunks = self._split_by_sections(content)
            return self.add_chunks(chunks)
        except Exception as e:
            logger.error(f"Error loading memory file {memory_path}: {e}")
            return 0

    @staticmethod
    def _split_by_sections(text: str) -> list[str]:
        """
        Split text by ## section headers.

        Returns non-empty chunks (minimum 20 characters).
        """
        chunks = []
        current = []

        for line in text.split("\n"):
            if line.startswith("## ") and current:
                chunk = "\n".join(current).strip()
                if len(chunk) > 20:
                    chunks.append(chunk)
                current = [line]
            else:
                current.append(line)

        if current:
            chunk = "\n".join(current).strip()
            if len(chunk) > 20:
                chunks.append(chunk)

        return chunks

    def clear(self) -> None:
        """Clear all indexed chunks and embeddings."""
        self.chunks.clear()
        self.embeddings.clear()
        logger.debug("Search index cleared")

    def stats(self) -> dict:
        """Return indexing statistics."""
        return {
            "chunks_indexed": len(self.chunks),
            "model": EMBEDDING_MODEL,
        }
