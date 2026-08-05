"""
tests/test_web_search.py — Tests for SKILL 6: Web-Search-Plus.

Covers:
- Query classifier
- SearchResult dataclass
- Confidence scoring (heuristic + cross-engine agreement)
- Rate-limit cooldown logic
- Provider fallback chain (mocked aiohttp)
- DDG API, arXiv XML parsing
- Vault key lookup
- search() orchestration
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# classify_query
# ---------------------------------------------------------------------------

class TestClassifyQuery:
    def test_code_github(self):
        from cato.tools.web_search import classify_query
        assert classify_query("github asyncio library") == "code"

    def test_code_stackoverflow(self):
        from cato.tools.web_search import classify_query
        assert classify_query("stackoverflow Python error") == "code"

    def test_code_api_docs(self):
        from cato.tools.web_search import classify_query
        assert classify_query("Python api function docs") == "code"

    def test_academic_arxiv(self):
        from cato.tools.web_search import classify_query
        assert classify_query("arxiv paper on transformers") == "academic"

    def test_academic_doi(self):
        from cato.tools.web_search import classify_query
        assert classify_query("doi:10.1234/paper cite journal") == "academic"

    def test_news_today(self):
        from cato.tools.web_search import classify_query
        assert classify_query("latest AI news today breaking") == "news"

    def test_news_announced(self):
        from cato.tools.web_search import classify_query
        assert classify_query("OpenAI announced new model") == "news"

    def test_general_fallback(self):
        from cato.tools.web_search import classify_query
        assert classify_query("how to make pasta carbonara") == "general"

    def test_code_takes_priority_over_general(self):
        from cato.tools.web_search import classify_query
        # "function" keyword → code
        assert classify_query("what is a function in mathematics") == "code"

    def test_empty_query_is_general(self):
        from cato.tools.web_search import classify_query
        assert classify_query("") == "general"


# ---------------------------------------------------------------------------
# SearchResult dataclass
# ---------------------------------------------------------------------------

class TestSearchResult:
    def test_fields_set_correctly(self):
        from cato.tools.web_search import SearchResult
        r = SearchResult(
            title="Test",
            url="https://example.com",
            snippet="A snippet",
            source_engine="ddg_api",
            confidence=0.85,
            rank=0,
            published_date="2024-01-01",
        )
        assert r.title == "Test"
        assert r.url == "https://example.com"
        assert r.source_engine == "ddg_api"
        assert r.confidence == 0.85
        assert r.rank == 0

    def test_default_published_date(self):
        from cato.tools.web_search import SearchResult
        r = SearchResult(
            title="", url="", snippet="", source_engine="", confidence=0.5, rank=0
        )
        assert r.published_date == ""


# ---------------------------------------------------------------------------
# Heuristic confidence scoring
# ---------------------------------------------------------------------------

class TestHeuristicConfidence:
    def setup_method(self):
        from cato.tools.web_search import WebSearchTool
        self.tool = WebSearchTool()

    def test_rank_zero_high_confidence(self):
        c = self.tool._heuristic_confidence("test", "https://example.com", 0, "test snippet")
        assert c >= 0.80

    def test_rank_nine_lower_confidence(self):
        c = self.tool._heuristic_confidence("test", "https://example.com", 9, "snippet")
        assert c <= 0.50

    def test_edu_domain_bonus(self):
        c_edu = self.tool._heuristic_confidence("test", "https://mit.edu/page", 0, "snippet")
        c_com = self.tool._heuristic_confidence("test", "https://example.com/page", 0, "snippet")
        assert c_edu > c_com

    def test_gov_domain_bonus(self):
        c_gov = self.tool._heuristic_confidence("test", "https://cdc.gov/data", 0, "snippet")
        c_com = self.tool._heuristic_confidence("test", "https://example.com", 0, "snippet")
        assert c_gov > c_com

    def test_org_domain_small_bonus(self):
        c_org = self.tool._heuristic_confidence("test", "https://python.org/docs", 0, "snippet")
        c_com = self.tool._heuristic_confidence("test", "https://example.com", 0, "snippet")
        assert c_org > c_com

    def test_freshness_bonus_2024(self):
        c_fresh = self.tool._heuristic_confidence("query", "https://x.com", 5, "Released in 2024!")
        c_stale = self.tool._heuristic_confidence("query", "https://x.com", 5, "Released in 2010!")
        assert c_fresh >= c_stale

    def test_keyword_overlap_bonus(self):
        c_match = self.tool._heuristic_confidence("python async", "https://x.com", 5, "python async tutorial")
        c_no_match = self.tool._heuristic_confidence("python async", "https://x.com", 5, "java sync code")
        assert c_match > c_no_match

    def test_confidence_capped_at_1(self):
        # Many bonuses combined should not exceed 1.0
        c = self.tool._heuristic_confidence(
            "test query words many terms",
            "https://university.edu/research",
            0,
            "test query words many terms released in 2024 with test",
        )
        assert c <= 1.0

    def test_confidence_floor_above_zero(self):
        c = self.tool._heuristic_confidence("xyz", "https://x.com", 9, "")
        assert c >= 0.0


# ---------------------------------------------------------------------------
# Cross-engine agreement
# ---------------------------------------------------------------------------

class TestCrossEngineAgreement:
    def setup_method(self):
        from cato.tools.web_search import WebSearchTool
        self.tool = WebSearchTool()

    def test_single_engine_no_boost(self):
        from cato.tools.web_search import SearchResult
        results = [
            SearchResult("A", "https://a.com", "", "brave", 0.70, 0),
            SearchResult("B", "https://b.com", "", "brave", 0.70, 0),
        ]
        boosted = self.tool._cross_engine_agreement(results)
        # Only appears once each, no boost
        assert all(r.confidence == 0.70 for r in boosted)

    def test_two_engines_boost(self):
        from cato.tools.web_search import SearchResult
        results = [
            SearchResult("A", "https://a.com/", "", "brave", 0.70, 0),
            SearchResult("A", "https://a.com", "", "ddg_api", 0.70, 0),
        ]
        boosted = self.tool._cross_engine_agreement(results)
        # Both should be boosted (same normalised URL)
        assert all(r.confidence > 0.70 for r in boosted)

    def test_different_urls_no_cross_boost(self):
        from cato.tools.web_search import SearchResult
        results = [
            SearchResult("A", "https://a.com", "", "brave", 0.70, 0),
            SearchResult("B", "https://b.com", "", "ddg_api", 0.70, 0),
        ]
        boosted = self.tool._cross_engine_agreement(results)
        assert all(r.confidence == 0.70 for r in boosted)

    def test_trailing_slash_normalised(self):
        from cato.tools.web_search import SearchResult
        r1 = SearchResult("A", "https://a.com/page/", "", "brave", 0.70, 0)
        r2 = SearchResult("A", "https://a.com/page", "", "ddg_api", 0.70, 0)
        boosted = self.tool._cross_engine_agreement([r1, r2])
        assert all(r.confidence > 0.70 for r in boosted)


# ---------------------------------------------------------------------------
# Rate-limit logic
# ---------------------------------------------------------------------------

class TestRateLimit:
    def setup_method(self):
        from cato.tools.web_search import WebSearchTool
        self.tool = WebSearchTool()

    def test_not_rate_limited_initially(self):
        assert not self.tool._is_rate_limited("brave")

    def test_mark_rate_limited(self):
        self.tool._mark_rate_limited("brave", cooldown=60.0)
        assert self.tool._is_rate_limited("brave")

    def test_rate_limit_expires(self):
        self.tool._mark_rate_limited("exa", cooldown=0.001)
        time.sleep(0.01)
        assert not self.tool._is_rate_limited("exa")

    @pytest.mark.asyncio
    async def test_rate_limited_provider_skipped_in_search(self):
        from cato.tools.web_search import WebSearchTool, SearchResult
        tool = WebSearchTool()
        tool._mark_rate_limited("brave", cooldown=9999)
        tool._mark_rate_limited("searxng", cooldown=9999)

        # Only ddg_api is available; mock it
        mock_results = [
            SearchResult("DDG result", "https://ddg.com", "snippet", "ddg_api", 0.7, 0)
        ]

        with patch.object(tool, "_search_ddg_api", new=AsyncMock(return_value=mock_results)):
            with patch.object(tool, "_search_brave", new=AsyncMock(return_value=[])):
                results = await tool.search("hello", query_type="general")

        # Should still return DDG results
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Vault key lookup
# ---------------------------------------------------------------------------

class TestVaultLookup:
    def test_vault_get_returns_key(self):
        from cato.tools.web_search import WebSearchTool
        vault = MagicMock()
        vault.get.return_value = "test-key-123"
        tool = WebSearchTool(vault=vault)
        assert tool._vault_get("brave_api_key") == "test-key-123"
        vault.get.assert_called_once_with("brave_api_key")

    def test_vault_get_no_vault_returns_none(self):
        from cato.tools.web_search import WebSearchTool
        tool = WebSearchTool(vault=None)
        assert tool._vault_get("anything") is None

    def test_vault_get_exception_returns_none(self):
        from cato.tools.web_search import WebSearchTool
        vault = MagicMock()
        vault.get.side_effect = Exception("vault locked")
        tool = WebSearchTool(vault=vault)
        assert tool._vault_get("brave_api_key") is None


# ---------------------------------------------------------------------------
# DDG API parsing
# ---------------------------------------------------------------------------

class TestDDGApiParsing:
    @pytest.mark.asyncio
    async def test_ddg_api_parses_abstract(self):
        from cato.tools.web_search import WebSearchTool
        tool = WebSearchTool()
        mock_resp_data = {
            "Heading": "Python",
            "AbstractText": "A programming language",
            "AbstractURL": "https://python.org",
            "RelatedTopics": [],
        }
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_resp_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            results = await tool._search_ddg_api("Python")

        assert len(results) >= 1
        assert results[0].url == "https://python.org"
        assert "programming" in results[0].snippet

    @pytest.mark.asyncio
    async def test_ddg_api_429_raises_rate_limit_error(self):
        from cato.tools.web_search import WebSearchTool, _RateLimitError
        tool = WebSearchTool()
        mock_resp = AsyncMock()
        mock_resp.status = 429
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(_RateLimitError):
                await tool._search_ddg_api("test")

    @pytest.mark.asyncio
    async def test_ddg_api_related_topics(self):
        from cato.tools.web_search import WebSearchTool
        tool = WebSearchTool()
        mock_resp_data = {
            "Heading": "",
            "AbstractText": "",
            "AbstractURL": "",
            "RelatedTopics": [
                {"Text": "Topic 1 text", "FirstURL": "https://a.com"},
                {"Text": "Topic 2 text", "FirstURL": "https://b.com"},
            ],
        }
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_resp_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            results = await tool._search_ddg_api("anything")

        assert len(results) == 2
        assert results[0].url == "https://a.com"


# ---------------------------------------------------------------------------
# arXiv XML parsing
# ---------------------------------------------------------------------------

class TestArXivParsing:
    @pytest.mark.asyncio
    async def test_arxiv_parses_entries(self):
        from cato.tools.web_search import WebSearchTool
        tool = WebSearchTool()
        xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001</id>
    <title>Attention Is All You Need</title>
    <summary>A transformer architecture paper.</summary>
    <published>2023-01-01T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.00002</id>
    <title>BERT Pre-training</title>
    <summary>Bidirectional encoder representations.</summary>
    <published>2023-02-01T00:00:00Z</published>
  </entry>
</feed>"""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=xml_text)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            results = await tool._search_arxiv("transformers")

        assert len(results) == 2
        assert "Attention" in results[0].title
        assert results[0].source_engine == "arxiv"

    @pytest.mark.asyncio
    async def test_arxiv_bad_xml_returns_empty(self):
        from cato.tools.web_search import WebSearchTool
        tool = WebSearchTool()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="<not valid xml [[")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            results = await tool._search_arxiv("anything")
        assert results == []


# ---------------------------------------------------------------------------
# search() orchestration
# ---------------------------------------------------------------------------

class TestSearchOrchestration:
    @pytest.mark.asyncio
    async def test_search_returns_sorted_by_confidence(self):
        from cato.tools.web_search import WebSearchTool, SearchResult
        tool = WebSearchTool()

        mock_results = [
            SearchResult("Low", "https://low.com", "", "ddg_api", 0.40, 3),
            SearchResult("High", "https://high.com", "", "ddg_api", 0.90, 0),
            SearchResult("Mid", "https://mid.com", "", "ddg_api", 0.65, 1),
        ]

        with patch.object(tool, "_search_ddg_api", new=AsyncMock(return_value=mock_results)):
            results = await tool.search("test", query_type="general")

        # Should be sorted descending by confidence
        confidences = [r.confidence for r in results]
        assert confidences == sorted(confidences, reverse=True)

    @pytest.mark.asyncio
    async def test_search_respects_max_results(self):
        from cato.tools.web_search import WebSearchTool, SearchResult
        tool = WebSearchTool()

        many_results = [
            SearchResult(f"Title {i}", f"https://r{i}.com", "", "ddg_api", 0.5, i)
            for i in range(20)
        ]

        with patch.object(tool, "_search_ddg_api", new=AsyncMock(return_value=many_results)):
            results = await tool.search("test", query_type="general", max_results=5)

        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_search_fallback_to_ddg_when_all_fail(self):
        from cato.tools.web_search import WebSearchTool, SearchResult
        tool = WebSearchTool()
        fallback_result = [SearchResult("DDG", "https://ddg.com", "", "ddg_api", 0.6, 0)]

        async def always_fail(query):
            return []

        with patch.object(tool, "_search_brave", new=AsyncMock(return_value=[])):
            with patch.object(tool, "_search_searxng_default", new=AsyncMock(return_value=[])):
                with patch.object(tool, "_search_ddg_api", new=AsyncMock(return_value=fallback_result)):
                    results = await tool.search("test", query_type="general")

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_deep_adds_perplexity(self):
        from cato.tools.web_search import WebSearchTool, SearchResult
        tool = WebSearchTool()
        perplexity_called = []

        async def mock_perplexity(q):
            perplexity_called.append(q)
            return [SearchResult("Perplexity", "https://p.ai", "", "perplexity", 0.8, 0)]

        with patch.object(tool, "_search_perplexity", new=mock_perplexity):
            with patch.object(tool, "_search_ddg_api", new=AsyncMock(return_value=[])):
                await tool.search("test", query_type="general", depth="deep")

        # Perplexity should have been called for deep mode
        assert len(perplexity_called) >= 1

    @pytest.mark.asyncio
    async def test_search_code_type_uses_code_chain(self):
        from cato.tools.web_search import WebSearchTool, SearchResult
        tool = WebSearchTool()
        exa_called = []

        async def mock_exa(q):
            exa_called.append(q)
            return [SearchResult("Exa", "https://exa.ai", "", "exa", 0.9, 0)]

        with patch.object(tool, "_search_exa", new=mock_exa):
            await tool.search("Python asyncio", query_type="code")

        assert len(exa_called) == 1

    @pytest.mark.asyncio
    async def test_search_no_aiohttp_returns_empty(self):
        """If aiohttp is missing, all providers should return empty list gracefully."""
        from cato.tools.web_search import WebSearchTool
        tool = WebSearchTool()
        with patch("builtins.__import__", side_effect=lambda n, *a, **kw: (_ for _ in ()).throw(ImportError()) if n == "aiohttp" else __import__(n, *a, **kw)):
            # Should not raise
            results = await tool._search_ddg_api("test")
        assert results == []
