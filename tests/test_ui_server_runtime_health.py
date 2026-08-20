from __future__ import annotations

import re

from aiohttp.test_utils import AioHTTPTestCase

from cato.ui.server import _redact_log_text, create_ui_app


class TestHeartbeatAuth(AioHTTPTestCase):
    async def get_application(self):
        return await create_ui_app(gateway=None)

    async def test_local_heartbeat_post_is_allowed_without_token(self):
        resp = await self.client.post(
            "/api/heartbeat",
            json={"agent_name": "Cato", "uptime_seconds": 12},
        )

        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"

    async def test_health_exposes_immutable_full_source_identity(self):
        response = await self.client.get("/health")
        payload = await response.json()

        assert response.status == 200
        assert re.fullmatch(r"[0-9a-f]{40}", payload["source_sha"])


def test_log_redaction_masks_obvious_secret_values():
    text = "token=abc123 password: hunter2 api_key='sk-live-secretvalue'"

    redacted = _redact_log_text(text)

    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert "sk-live-secretvalue" not in redacted
    assert "[redacted]" in redacted
