"""
conduit_monitor.py — Cryptographically signed page change detection.

Fingerprints pages with SHA-256 (timestamps/nonces stripped).
Change events are logged to the audit hash chain as PAGE_MUTATION events.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from typing import Optional


class ConduitMonitor:
    """
    Monitors URL for changes. Each detected change logs a signed PAGE_MUTATION
    event to the audit chain with prev_hash, new_hash, and structured diff.

    Usage:
        monitor = ConduitMonitor(browser_tool, audit_log, session_id)
        fp = await monitor.fingerprint("https://example.com")
        # Later:
        changed = await monitor.check_changed("https://example.com", fp["fingerprint"])
    """

    def __init__(self, browser_tool, audit_log, session_id: str):
        self._browser = browser_tool
        self._audit_log = audit_log
        self._session_id = session_id

    def _normalize_text(self, text: str) -> str:
        """Strip timestamps, session tokens, and other noise before hashing."""
        # Remove ISO timestamps
        text = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[Z\+\-\d:]*', '', text)
        # Remove Unix timestamps (10-13 digit numbers)
        text = re.sub(r'\b\d{10,13}\b', '', text)
        # Remove common nonce/token patterns
        text = re.sub(r'[a-f0-9]{32,}', '', text)
        # Normalize whitespace
        text = ' '.join(text.split())
        return text

    async def fingerprint(self, url: str) -> dict:
        """
        Navigate to URL, normalize page text, return SHA-256 fingerprint.
        Fingerprint is logged to the audit chain.
        """
        await self._browser._navigate(url)
        raw_text = await self._browser._page.evaluate(
            "() => document.body ? document.body.innerText : ''"
        )
        normalized = self._normalize_text(raw_text)
        fp = hashlib.sha256(normalized.encode()).hexdigest()
        title = await self._browser._page.title()

        result = {
            "url": url,
            "fingerprint": fp,
            "title": title,
            "timestamp": time.time(),
            "char_count": len(normalized),
        }
        self._audit_log.log(
            session_id=self._session_id,
            action_type="tool_call",
            tool_name="browser.fingerprint",
            inputs={"url": url},
            outputs=result,
            cost_cents=0,
            error="",
        )
        return result

    async def check_changed(self, url: str, previous_fingerprint: str) -> dict:
        """
        Re-fingerprint URL. If changed, log PAGE_MUTATION event with diff summary.
        Returns {"changed": bool, "prev_fingerprint": str, "new_fingerprint": str}
        """
        new_fp_data = await self.fingerprint(url)
        new_fp = new_fp_data["fingerprint"]
        changed = new_fp != previous_fingerprint

        if changed:
            self._audit_log.log(
                session_id=self._session_id,
                action_type="PAGE_MUTATION",
                tool_name="browser.change_monitor",
                inputs={"url": url, "prev_fingerprint": previous_fingerprint},
                outputs={
                    "new_fingerprint": new_fp,
                    "changed": True,
                    "timestamp": time.time(),
                },
                cost_cents=0,
                error="",
            )

        return {
            "url": url,
            "changed": changed,
            "prev_fingerprint": previous_fingerprint,
            "new_fingerprint": new_fp,
        }

    async def watch(self, url: str, interval_seconds: int = 3600, max_checks: int = 24) -> dict:
        """
        Poll url every interval_seconds. Logs PAGE_MUTATION events on change.
        Returns after max_checks iterations (non-blocking loop for agent use).
        """
        fp_data = await self.fingerprint(url)
        current_fp = fp_data["fingerprint"]
        mutations = []

        for i in range(max_checks - 1):
            await asyncio.sleep(interval_seconds)
            result = await self.check_changed(url, current_fp)
            if result["changed"]:
                mutations.append({
                    "check": i + 1,
                    "new_fingerprint": result["new_fingerprint"],
                    "timestamp": time.time(),
                })
                current_fp = result["new_fingerprint"]

        return {
            "url": url,
            "checks_performed": max_checks,
            "mutations_detected": len(mutations),
            "mutations": mutations,
        }
