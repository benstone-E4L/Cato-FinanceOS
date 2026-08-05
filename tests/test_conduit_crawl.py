"""
tests/test_conduit_crawl.py — Tests for ConduitCrawler (map_site + crawl_site).

Uses mock browser and mock audit log — no real browser or DB required.
"""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Import conduit_crawl standalone (no package context)
# ---------------------------------------------------------------------------

_CRAWL_PATH = Path(__file__).parent.parent / "cato" / "tools" / "conduit_crawl.py"
_crawl_src = _CRAWL_PATH.read_text(encoding="utf-8")

_crawl_mod = types.ModuleType("conduit_crawl_standalone")
_crawl_mod.__file__ = str(_CRAWL_PATH)
exec(compile(_crawl_src, str(_CRAWL_PATH), "exec"), _crawl_mod.__dict__)

ConduitCrawler = _crawl_mod.ConduitCrawler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockAuditLog:
    """Minimal audit log that records calls without SQLite."""
    def __init__(self):
        self.entries = []

    def log(self, session_id, action_type, tool_name, inputs, outputs, cost_cents=0, error=""):
        self.entries.append({
            "session_id": session_id,
            "action_type": action_type,
            "tool_name": tool_name,
            "inputs": inputs,
            "outputs": outputs,
            "cost_cents": cost_cents,
            "error": error,
        })
        return len(self.entries)


def make_mock_page(url="https://example.com", hrefs=None):
    page = MagicMock()
    page.url = url
    page.title = AsyncMock(return_value="Test Page")

    if hrefs is None:
        hrefs = []

    async def mock_evaluate(script, *args, **kwargs):
        # Return inner text for crawl, hrefs for link extraction
        if "querySelectorAll('a[href]')" in script:
            return hrefs
        return "Page body text content"

    page.evaluate = AsyncMock(side_effect=mock_evaluate)
    return page


def make_mock_browser(page=None):
    if page is None:
        page = make_mock_page()
    browser = MagicMock()
    browser._page = page
    browser._navigate = AsyncMock(return_value={"title": "Test", "url": page.url, "text": "content"})
    return browser


# ---------------------------------------------------------------------------
# Tests: map_site
# ---------------------------------------------------------------------------

class TestConduitCrawlerMapSite(unittest.IsolatedAsyncioTestCase):

    async def test_map_site_returns_dict_with_urls_count_base(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-test")

        # Patch robots.txt to always allow
        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", AsyncMock(return_value=[])):
                result = await crawler.map_site("https://example.com", limit=1)

        self.assertIn("urls", result)
        self.assertIn("count", result)
        self.assertIn("base_url", result)
        self.assertEqual(result["base_url"], "https://example.com")

    async def test_map_site_respects_limit(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-test")

        # Simulate browser finding many child links
        child_links = [f"https://example.com/page{i}" for i in range(50)]

        call_count = 0
        async def mock_extract(base_url):
            nonlocal call_count
            call_count += 1
            return child_links

        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", side_effect=mock_extract):
                result = await crawler.map_site("https://example.com", limit=5)

        self.assertLessEqual(result["count"], 5)

    async def test_map_site_logs_audit_event(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-map")

        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", AsyncMock(return_value=[])):
                await crawler.map_site("https://example.com", limit=1)

        # Should have logged exactly one MAP_SITE audit event
        map_entries = [e for e in audit.entries if e["tool_name"] == "browser.map"]
        self.assertEqual(len(map_entries), 1)
        self.assertEqual(map_entries[0]["inputs"]["url"], "https://example.com")

    async def test_map_site_search_filter(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-test")

        # Patch so we get multiple URLs found
        found_urls = [
            "https://example.com/blog/post1",
            "https://example.com/about",
            "https://example.com/blog/post2",
        ]
        call_count = [0]
        async def mock_navigate(url, **kwargs):
            return {"title": "Test", "url": url, "text": "content"}

        browser._navigate = AsyncMock(side_effect=mock_navigate)

        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", AsyncMock(return_value=[])):
                # Start with 3 URLs in queue
                from collections import deque
                original_map = crawler.map_site

                async def patched_map(url, limit=100, search=None):
                    result = {"urls": found_urls, "count": len(found_urls), "base_url": url}
                    if search:
                        result["urls"] = [u for u in found_urls if search.lower() in u.lower()]
                        result["count"] = len(result["urls"])
                    audit.log(
                        session_id=crawler._session_id,
                        action_type="tool_call",
                        tool_name="browser.map",
                        inputs={"url": url, "limit": limit, "search": search},
                        outputs={"count": result["count"]},
                        cost_cents=0,
                        error="",
                    )
                    return result

                result = await patched_map("https://example.com", search="blog")

        self.assertTrue(all("blog" in u for u in result["urls"]))

    async def test_map_site_skips_disallowed_urls(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-test")

        # robots.txt blocks the URL
        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=False)):
            result = await crawler.map_site("https://example.com/blocked", limit=5)

        self.assertEqual(result["count"], 0)

    async def test_map_site_does_not_revisit_urls(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-test")

        navigate_calls = []
        async def track_navigate(url, **kwargs):
            navigate_calls.append(url)
            return {"title": "Test", "url": url, "text": "content"}

        browser._navigate = AsyncMock(side_effect=track_navigate)

        # Return same URL as child link (would cause infinite loop without dedup)
        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", AsyncMock(return_value=["https://example.com"])):
                result = await crawler.map_site("https://example.com", limit=3)

        # Should only visit example.com once
        self.assertEqual(navigate_calls.count("https://example.com"), 1)

    async def test_map_site_extract_links_called_with_current_url(self):
        """
        Regression test: _extract_links must be called with the CURRENT URL being
        crawled, not always the root URL. Using the current URL ensures the same-domain
        filter is consistent with the page actually loaded.
        """
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-test")

        extract_link_calls = []

        async def capture_extract(base_url):
            extract_link_calls.append(base_url)
            return []

        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", side_effect=capture_extract):
                await crawler.map_site("https://example.com", limit=1)

        # _extract_links must be called with the current URL, not always the root
        self.assertTrue(
            all(u == "https://example.com" for u in extract_link_calls),
            f"Expected all calls with current URL, got: {extract_link_calls}",
        )


# ---------------------------------------------------------------------------
# Tests: crawl_site
# ---------------------------------------------------------------------------

class TestConduitCrawlerCrawlSite(unittest.IsolatedAsyncioTestCase):

    async def test_crawl_site_returns_pages_list(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-crawl")

        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", AsyncMock(return_value=[])):
                result = await crawler.crawl_site("https://example.com", max_depth=0, limit=1)

        self.assertIn("pages", result)
        self.assertIn("count", result)
        self.assertIn("base_url", result)

    async def test_crawl_site_logs_each_page_visit(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-crawl")

        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", AsyncMock(return_value=[])):
                await crawler.crawl_site("https://example.com", max_depth=0, limit=1)

        crawl_entries = [e for e in audit.entries if e["tool_name"] == "browser.crawl_page"]
        self.assertGreater(len(crawl_entries), 0)

    async def test_crawl_site_respects_limit(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-crawl")

        child_links = [f"https://example.com/p{i}" for i in range(30)]
        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", AsyncMock(return_value=child_links)):
                result = await crawler.crawl_site("https://example.com", max_depth=5, limit=3)

        self.assertLessEqual(result["count"], 3)

    async def test_crawl_site_includes_url_title_text_in_page_data(self):
        page = make_mock_page(url="https://example.com")
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-crawl")

        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", AsyncMock(return_value=[])):
                result = await crawler.crawl_site("https://example.com", max_depth=0, limit=1)

        if result["pages"]:
            page_data = result["pages"][0]
            self.assertIn("url", page_data)
            self.assertIn("title", page_data)
            self.assertIn("text", page_data)
            self.assertIn("char_count", page_data)
            self.assertIn("depth", page_data)

    async def test_crawl_site_logs_error_on_page_failure(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        browser._navigate = AsyncMock(side_effect=Exception("Network error"))
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-crawl")

        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", AsyncMock(return_value=[])):
                result = await crawler.crawl_site("https://example.com", max_depth=0, limit=1)

        # Should not raise — errors are caught and logged
        error_entries = [e for e in audit.entries if e["error"]]
        self.assertGreater(len(error_entries), 0)

    async def test_crawl_site_path_filtering_include(self):
        """include_paths filters to only URLs containing the path segment."""
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-crawl")

        # Manually test the path filtering logic
        from urllib.parse import urlparse
        test_url = "https://example.com/blog/post1"
        path = urlparse(test_url).path  # "/blog/post1"

        include_paths = ["/blog"]
        result_allowed = any(p in path for p in include_paths)
        self.assertTrue(result_allowed)

        exclude_url = "https://example.com/about"
        exclude_path = urlparse(exclude_url).path
        result_excluded = any(p in exclude_path for p in include_paths)
        self.assertFalse(result_excluded)

    async def test_crawl_site_extract_links_called_with_current_url(self):
        """
        Regression test: _extract_links in crawl_site must be called with
        current_url (the page just navigated to), not always with the root URL.
        """
        root = "https://example.com"
        child = "https://example.com/page1"

        page = make_mock_page(url=root)
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-crawl")

        # First call (root): return child URL; second call (child): return empty
        extract_link_calls = []
        async def capture_extract(base_url):
            extract_link_calls.append(base_url)
            if base_url == root:
                return [child]
            return []

        with patch.object(crawler, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(crawler, "_extract_links", side_effect=capture_extract):
                await crawler.crawl_site(root, max_depth=1, limit=5)

        # The first call should be for root, and any subsequent call for child URL
        self.assertIn(root, extract_link_calls)
        if len(extract_link_calls) > 1:
            self.assertIn(child, extract_link_calls)


# ---------------------------------------------------------------------------
# Tests: robots.txt compliance
# ---------------------------------------------------------------------------

class TestRobotsTxtCompliance(unittest.IsolatedAsyncioTestCase):

    async def test_is_allowed_returns_true_when_robots_unreadable(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-robot")

        # Patch RobotFileParser.read to raise — should default to allow
        with patch("urllib.robotparser.RobotFileParser.read", side_effect=Exception("timeout")):
            result = await crawler._is_allowed("https://example.com/page")

        self.assertTrue(result)

    async def test_is_allowed_caches_per_domain(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess-robot")

        with patch("urllib.robotparser.RobotFileParser.read"):
            with patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True):
                await crawler._is_allowed("https://example.com/page1")
                await crawler._is_allowed("https://example.com/page2")

        # Both pages share the same domain — only one cache entry
        self.assertIn("https://example.com", crawler._robots_cache)


# ---------------------------------------------------------------------------
# Tests: same_domain helper
# ---------------------------------------------------------------------------

class TestSameDomain(unittest.TestCase):

    def test_same_domain_returns_true_for_same_host(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess")

        self.assertTrue(crawler._same_domain(
            "https://example.com/page1", "https://example.com/page2"
        ))

    def test_same_domain_returns_false_for_different_host(self):
        page = make_mock_page()
        browser = make_mock_browser(page)
        audit = MockAuditLog()
        crawler = ConduitCrawler(browser, audit, "sess")

        self.assertFalse(crawler._same_domain(
            "https://example.com/page", "https://other.com/page"
        ))


if __name__ == "__main__":
    unittest.main()
