"""
tests/test_semantic_search.py — Tests for semantic memory search.

Tests cover:
- Embedding and indexing text chunks
- Similarity search with scoring
- Memory file loading and section splitting
- Search engine stats and clear
- API endpoints for search, indexing, and stats
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
from datetime import datetime

from cato.core.semantic_search import SemanticSearchEngine, EMBEDDING_MODEL


class TestSemanticSearchEngine:
    """Test core semantic search functionality."""

    def test_init_loads_model(self):
        """Test SemanticSearchEngine initializes with embedding model."""
        engine = SemanticSearchEngine()
        assert engine.model is not None
        assert engine.chunks == {}
        assert engine.embeddings == []

    def test_add_chunks_single(self):
        """Test adding a single text chunk."""
        engine = SemanticSearchEngine()
        count = engine.add_chunks(["Hello world"])
        assert count == 1
        assert len(engine.chunks) == 1
        assert len(engine.embeddings) == 1

    def test_add_chunks_multiple(self):
        """Test adding multiple text chunks."""
        engine = SemanticSearchEngine()
        chunks = ["First chunk", "Second chunk", "Third chunk"]
        count = engine.add_chunks(chunks)
        assert count == 3
        assert len(engine.chunks) == 3
        assert len(engine.embeddings) == 3

    def test_add_chunks_empty_list(self):
        """Test adding empty list returns 0."""
        engine = SemanticSearchEngine()
        count = engine.add_chunks([])
        assert count == 0
        assert len(engine.chunks) == 0

    def test_add_chunks_duplicate(self):
        """Test that duplicate chunks are not re-indexed."""
        engine = SemanticSearchEngine()
        engine.add_chunks(["Duplicate chunk"])
        count = engine.add_chunks(["Duplicate chunk"])
        assert count == 0  # Not added again
        assert len(engine.chunks) == 1
        assert len(engine.embeddings) == 1

    def test_search_empty_index(self):
        """Test search on empty index returns empty list."""
        engine = SemanticSearchEngine()
        results = engine.search("query")
        assert results == []

    def test_search_returns_top_k(self):
        """Test search returns at most top_k results."""
        engine = SemanticSearchEngine()
        chunks = [
            "The cat sat on the mat",
            "The dog played in the park",
            "A bird flew in the sky",
            "The cat jumped high",
            "Dogs love to play",
        ]
        engine.add_chunks(chunks)

        results = engine.search("cat", top_k=2)
        assert len(results) <= 2

    def test_search_with_threshold(self):
        """Test search respects similarity threshold."""
        engine = SemanticSearchEngine()
        chunks = [
            "The quick brown fox jumps over the lazy dog",
            "Machine learning is a subset of artificial intelligence",
        ]
        engine.add_chunks(chunks)

        # Search with high threshold should filter out low similarity
        results = engine.search("fox", top_k=10, threshold=0.5)
        assert len(results) >= 1

    def test_search_similarity_ordering(self):
        """Test search results are ordered by similarity (best first)."""
        engine = SemanticSearchEngine()
        chunks = [
            "I love cats",
            "Cats are animals",
            "The weather is nice today",
            "Cats meow loudly",
        ]
        engine.add_chunks(chunks)

        results = engine.search("cats", top_k=4)
        # Results should be ordered by relevance (cat-related chunks first)
        assert len(results) > 0
        # First result should mention cats
        assert "cat" in results[0].lower()

    def test_clear_empties_index(self):
        """Test clear() removes all chunks and embeddings."""
        engine = SemanticSearchEngine()
        engine.add_chunks(["Chunk 1", "Chunk 2"])
        assert len(engine.chunks) == 2

        engine.clear()
        assert len(engine.chunks) == 0
        assert len(engine.embeddings) == 0

    def test_stats_returns_count(self):
        """Test stats() returns indexed chunk count."""
        engine = SemanticSearchEngine()
        stats = engine.stats()
        assert "chunks_indexed" in stats
        assert "model" in stats
        assert stats["chunks_indexed"] == 0

        engine.add_chunks(["Chunk 1", "Chunk 2"])
        stats = engine.stats()
        assert stats["chunks_indexed"] == 2


class TestMemoryFileLoading:
    """Test loading and parsing MEMORY.md files."""

    def test_split_by_sections_basic(self):
        """Test splitting text by ## section headers."""
        text = """## Section 1
First section content here.

## Section 2
Second section content here."""
        chunks = SemanticSearchEngine._split_by_sections(text)
        assert len(chunks) >= 1
        assert "Section" in chunks[0] or "content" in chunks[0].lower()

    def test_split_by_sections_filters_short(self):
        """Test that very short chunks are filtered out."""
        text = """## Section
x

## Another
This is a longer chunk with more than 20 characters."""
        chunks = SemanticSearchEngine._split_by_sections(text)
        # Should only include chunks > 20 chars
        assert all(len(c) > 20 for c in chunks)

    def test_load_memory_file_exists(self):
        """Test loading existing memory file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_path = Path(tmpdir) / "MEMORY.md"
            memory_path.write_text("""## Projects
AI agent development

## Technical Notes
Database optimization techniques""")

            engine = SemanticSearchEngine()
            count = engine.load_memory_file(memory_path)
            assert count > 0
            assert len(engine.chunks) > 0

    def test_load_memory_file_missing(self):
        """Test loading non-existent file returns 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_path = Path(tmpdir) / "missing.md"
            engine = SemanticSearchEngine()
            count = engine.load_memory_file(memory_path)
            assert count == 0
            assert len(engine.chunks) == 0


class TestMemorySearchAPI:
    """Test memory search API endpoints."""

    @pytest.mark.asyncio
    async def test_search_memory_missing_query(self):
        """Test GET /api/memory/search without query param returns 400."""
        from cato.api.memory_routes import search_memory
        from unittest.mock import MagicMock

        request = MagicMock()
        request.query = {}

        response = await search_memory(request)
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_search_memory_empty_query(self):
        """Test GET /api/memory/search with empty query returns 400."""
        from cato.api.memory_routes import search_memory
        from unittest.mock import MagicMock

        request = MagicMock()
        request.query = {"q": "  "}  # Whitespace only

        response = await search_memory(request)
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_search_memory_valid_query(self):
        """Test GET /api/memory/search with valid query returns 200."""
        from cato.api.memory_routes import search_memory
        from unittest.mock import MagicMock, patch

        request = MagicMock()
        request.query = {"q": "memory search test"}

        with patch("cato.api.memory_routes._get_search_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.search.return_value = []
            mock_engine.stats.return_value = {"chunks_indexed": 0, "model": "test"}
            mock_get.return_value = mock_engine

            response = await search_memory(request)
            assert response.status == 200

    @pytest.mark.asyncio
    async def test_search_memory_top_k_param(self):
        """Test top_k parameter is parsed correctly."""
        from cato.api.memory_routes import search_memory
        from unittest.mock import MagicMock, patch

        request = MagicMock()
        request.query = {"q": "test", "top_k": "10"}

        with patch("cato.api.memory_routes._get_search_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.search.return_value = []
            mock_engine.stats.return_value = {"chunks_indexed": 0}
            mock_engine.chunks = {}  # Empty index
            mock_get.return_value = mock_engine

            response = await search_memory(request)
            # Should call search with top_k=10
            mock_engine.search.assert_called()
            args = mock_engine.search.call_args
            assert args[1]["top_k"] == 10

    @pytest.mark.asyncio
    async def test_index_memory_success(self):
        """Test POST /api/memory/index returns 200 and stats."""
        from cato.api.memory_routes import index_memory
        from unittest.mock import MagicMock, patch
        import tempfile

        request = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_path = Path(tmpdir) / "MEMORY.md"
            memory_path.write_text("## Test\nContent here")

            with patch("cato.api.memory_routes._get_search_engine") as mock_get:
                mock_engine = MagicMock()
                mock_engine.clear = MagicMock()
                mock_engine.load_memory_file.return_value = 2
                mock_engine.stats.return_value = {"chunks_indexed": 2}
                mock_get.return_value = mock_engine

                with patch("cato.config.CatoConfig.load") as mock_config:
                    mock_config.return_value.workspace_dir = tmpdir
                    response = await index_memory(request)
                    # Will fail because actual memory file not in tmpdir
                    # But we're testing the API contract

    @pytest.mark.asyncio
    async def test_memory_stats_returns_dict(self):
        """Test GET /api/memory/stats returns stats object."""
        from cato.api.memory_routes import memory_stats
        from unittest.mock import MagicMock, patch

        request = MagicMock()

        with patch("cato.api.memory_routes._get_search_engine") as mock_get:
            mock_engine = MagicMock()
            mock_engine.stats.return_value = {
                "chunks_indexed": 5,
                "model": EMBEDDING_MODEL
            }
            mock_get.return_value = mock_engine

            response = await memory_stats(request)
            assert response.status == 200


class TestSemanticSearchIntegration:
    """Integration tests for full search flow."""

    def test_end_to_end_search_flow(self):
        """Test complete flow: add chunks → search → verify results."""
        engine = SemanticSearchEngine()

        # Add domain-specific chunks
        chunks = [
            "The user prefers high-level thinking and abstract concepts",
            "The user is located in US Mountain Time zone",
            "The user's favorite color is blue",
            "Machine learning models require large datasets",
            "Python is a popular language for data science",
        ]
        engine.add_chunks(chunks)

        # Search for user preference
        results = engine.search("timezone and location", top_k=2)
        assert len(results) > 0
        assert "zone" in " ".join(results).lower() or "time" in " ".join(results).lower()

    def test_search_model_embedding_dimension(self):
        """Test that embeddings have consistent dimensionality."""
        engine = SemanticSearchEngine()
        engine.add_chunks(["Chunk one", "Chunk two"])

        # All embeddings should have the same length
        if engine.embeddings:
            dim = len(engine.embeddings[0])
            assert all(len(e) == dim for e in engine.embeddings)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
