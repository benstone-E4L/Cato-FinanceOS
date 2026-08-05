"""
tests/test_conduit_monitor.py — Tests for ConduitMonitor (fingerprint + check_changed).

Verifies:
- Fingerprint SHA-256 computation and normalization
- PAGE_MUTATION event logged when content changes
- No PAGE_MUTATION logged when content is unchanged
"""
import asyncio
import hashlib
import re
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Import conduit_monitor standalone
# ---------------------------------------------------------------------------

_MON_PATH = Path(__file__).parent.parent / "cato" / "tools" / "conduit_monitor.py"
_mon_src = _MON_PATH.read_text(encoding="utf-8")

_mon_mod = types.ModuleType("conduit_monitor_standalone")
_mon_mod.__file__ = str(_MON_PATH)
exec(compile(_mon_src, str(_MON_PATH), "exec"), _mon_mod.__dict__)

ConduitMonitor = _mon_mod.ConduitMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockAuditLog:
    def __init__(self):
        self.entries = []

    def log(self, session_id, action_type, tool_name, inputs, outputs, cost_cents=0, error=""):
        self.entries.append({
            "session_id": session_id,
            "action_type": action_type,
            "tool_name": tool_name,
            "inputs": inputs,
            "outputs": outputs,
        })
        return len(self.entries)


def make_mock_browser(body_text="Hello world", url="https://example.com", title="Page"):
    page = MagicMock()
    page.url = url
    page.title = AsyncMock(return_value=title)

    async def mock_evaluate(script, *args, **kwargs):
        return body_text

    page.evaluate = AsyncMock(side_effect=mock_evaluate)

    browser = MagicMock()
    browser._page = page
    browser._navigate = AsyncMock(return_value={"url": url, "title": title, "text": body_text})
    return browser


# ---------------------------------------------------------------------------
# Tests: normalize_text
# ---------------------------------------------------------------------------

class TestNormalizeText(unittest.TestCase):

    def setUp(self):
        browser = make_mock_browser()
        audit = MockAuditLog()
        self.monitor = ConduitMonitor(browser, audit, "sess-norm")

    def test_strips_iso_timestamps(self):
        text = "Updated at 2026-03-05T12:34:56Z and also 2025-01-01T00:00:00+05:30"
        result = self.monitor._normalize_text(text)
        self.assertNotIn("2026-03-05", result)
        self.assertNotIn("2025-01-01", result)

    def test_strips_unix_timestamps(self):
        text = "Token expires at 1741234567890 timestamp"
        result = self.monitor._normalize_text(text)
        # 13-digit unix ts should be stripped
        self.assertNotIn("1741234567890", result)

    def test_strips_hex_nonces(self):
        text = "Session nonce: a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        result = self.monitor._normalize_text(text)
        self.assertNotIn("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2", result)

    def test_normalizes_whitespace(self):
        text = "Hello    world\n\n  foo  \t bar"
        result = self.monitor._normalize_text(text)
        self.assertNotIn("    ", result)
        self.assertNotIn("\n\n", result)

    def test_stable_content_unchanged(self):
        text = "The quick brown fox jumps over the lazy dog."
        result1 = self.monitor._normalize_text(text)
        result2 = self.monitor._normalize_text(text)
        self.assertEqual(result1, result2)


# ---------------------------------------------------------------------------
# Tests: fingerprint
# ---------------------------------------------------------------------------

class TestConduitMonitorFingerprint(unittest.IsolatedAsyncioTestCase):

    async def test_fingerprint_returns_sha256_hash(self):
        browser = make_mock_browser("Stable page content")
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-fp")

        result = await monitor.fingerprint("https://example.com")

        self.assertIn("fingerprint", result)
        # SHA-256 hex digest is 64 chars
        self.assertEqual(len(result["fingerprint"]), 64)
        # Must be valid hex
        int(result["fingerprint"], 16)

    async def test_fingerprint_includes_url_title_timestamp(self):
        browser = make_mock_browser("Content", url="https://test.com", title="My Title")
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-fp")

        result = await monitor.fingerprint("https://test.com")

        self.assertEqual(result["url"], "https://test.com")
        self.assertEqual(result["title"], "My Title")
        self.assertIn("timestamp", result)
        self.assertIn("char_count", result)

    async def test_fingerprint_logs_to_audit(self):
        browser = make_mock_browser("Content")
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-fp")

        await monitor.fingerprint("https://example.com")

        fp_entries = [e for e in audit.entries if e["tool_name"] == "browser.fingerprint"]
        self.assertEqual(len(fp_entries), 1)
        self.assertEqual(fp_entries[0]["inputs"]["url"], "https://example.com")

    async def test_fingerprint_is_deterministic_for_same_content(self):
        browser = make_mock_browser("Stable content")
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-fp")

        fp1 = await monitor.fingerprint("https://example.com")
        fp2 = await monitor.fingerprint("https://example.com")

        self.assertEqual(fp1["fingerprint"], fp2["fingerprint"])

    async def test_fingerprint_differs_for_different_content(self):
        # First fingerprint
        browser1 = make_mock_browser("Content A")
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser1, audit, "sess-fp")
        fp1 = await monitor.fingerprint("https://example.com")

        # Second fingerprint with different content
        browser2 = make_mock_browser("Content B")
        monitor2 = ConduitMonitor(browser2, audit, "sess-fp")
        fp2 = await monitor2.fingerprint("https://example.com")

        self.assertNotEqual(fp1["fingerprint"], fp2["fingerprint"])

    async def test_fingerprint_ignores_timestamps_in_content(self):
        """Two pages with same content but different timestamps should have same fingerprint."""
        content_with_ts1 = "Main content 2026-03-05T12:00:00Z footer"
        content_with_ts2 = "Main content 2026-03-06T08:30:00Z footer"

        browser1 = make_mock_browser(content_with_ts1)
        browser2 = make_mock_browser(content_with_ts2)
        audit = MockAuditLog()

        monitor1 = ConduitMonitor(browser1, audit, "sess-fp")
        monitor2 = ConduitMonitor(browser2, audit, "sess-fp")

        fp1 = await monitor1.fingerprint("https://example.com")
        fp2 = await monitor2.fingerprint("https://example.com")

        # Same semantic content — fingerprints should match
        self.assertEqual(fp1["fingerprint"], fp2["fingerprint"])


# ---------------------------------------------------------------------------
# Tests: check_changed
# ---------------------------------------------------------------------------

class TestConduitMonitorCheckChanged(unittest.IsolatedAsyncioTestCase):

    async def test_check_changed_returns_false_when_content_same(self):
        content = "Stable page content here"
        browser = make_mock_browser(content)
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-cc")

        # Get the actual fingerprint first
        fp_data = await monitor.fingerprint("https://example.com")
        fp = fp_data["fingerprint"]

        # Now check again with same browser (same content)
        result = await monitor.check_changed("https://example.com", fp)

        self.assertFalse(result["changed"])

    async def test_check_changed_returns_true_when_content_differs(self):
        content_a = "Original content"
        browser = make_mock_browser(content_a)
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-cc")

        # Compute fingerprint of content_a
        normalized = monitor._normalize_text(content_a)
        fp_a = hashlib.sha256(normalized.encode()).hexdigest()

        # Switch browser to different content
        content_b = "Completely different content"
        browser2 = make_mock_browser(content_b)
        monitor2 = ConduitMonitor(browser2, audit, "sess-cc")

        result = await monitor2.check_changed("https://example.com", fp_a)

        self.assertTrue(result["changed"])

    async def test_check_changed_logs_page_mutation_event_on_change(self):
        browser = make_mock_browser("New content")
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-cc")

        # Use a fingerprint that won't match (old content)
        old_fp = hashlib.sha256("Old content".encode()).hexdigest()

        result = await monitor.check_changed("https://example.com", old_fp)

        # Should have logged a PAGE_MUTATION event
        mutation_entries = [e for e in audit.entries if e["action_type"] == "PAGE_MUTATION"]
        self.assertEqual(len(mutation_entries), 1)

    async def test_check_changed_does_not_log_mutation_when_unchanged(self):
        content = "Same content"
        browser = make_mock_browser(content)
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-cc")

        # Compute the actual fingerprint
        normalized = monitor._normalize_text(content)
        current_fp = hashlib.sha256(normalized.encode()).hexdigest()

        result = await monitor.check_changed("https://example.com", current_fp)

        mutation_entries = [e for e in audit.entries if e["action_type"] == "PAGE_MUTATION"]
        self.assertEqual(len(mutation_entries), 0)

    async def test_check_changed_mutation_event_contains_fingerprints(self):
        browser = make_mock_browser("Updated content")
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-cc")

        old_fp = "a" * 64  # fake old fingerprint

        await monitor.check_changed("https://example.com", old_fp)

        mutation_entries = [e for e in audit.entries if e["action_type"] == "PAGE_MUTATION"]
        if mutation_entries:
            entry = mutation_entries[0]
            self.assertIn("prev_fingerprint", entry["inputs"])
            self.assertIn("new_fingerprint", entry["outputs"])
            self.assertEqual(entry["inputs"]["prev_fingerprint"], old_fp)

    async def test_check_changed_returns_both_fingerprints(self):
        old_fp = "deadbeef" * 8  # 64 char fake hash
        content = "Some new content"
        browser = make_mock_browser(content)
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-cc")

        result = await monitor.check_changed("https://example.com", old_fp)

        self.assertIn("prev_fingerprint", result)
        self.assertIn("new_fingerprint", result)
        self.assertEqual(result["prev_fingerprint"], old_fp)
        self.assertIsNotNone(result["new_fingerprint"])
        self.assertEqual(len(result["new_fingerprint"]), 64)

    async def test_check_changed_also_logs_fingerprint_event(self):
        """check_changed calls fingerprint() internally, so both audit entries appear."""
        content = "Page content"
        browser = make_mock_browser(content)
        audit = MockAuditLog()
        monitor = ConduitMonitor(browser, audit, "sess-cc")

        old_fp = "x" * 64
        await monitor.check_changed("https://example.com", old_fp)

        fp_entries = [e for e in audit.entries if e["tool_name"] == "browser.fingerprint"]
        self.assertGreater(len(fp_entries), 0)


if __name__ == "__main__":
    unittest.main()
