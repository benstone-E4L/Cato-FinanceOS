"""t26 HIGH-2 — the dashboard must not hand its token to anonymous callers.

`GET /` injects `window.__CATO_TOKEN__ = "<64 hex>"` into the HTML, and that
token unlocks every /api/* route including /api/coding-agent/*, which spawns
claude/codex/gemini subprocesses. `/` used to be token-exempt, so an
unauthenticated `curl http://127.0.0.1:8080/` returned the token in the body.

Aggravating: the server did not validate the Host header. CORS is restrictive,
but DNS rebinding bypasses CORS entirely — once a hostile name resolves to
127.0.0.1 the browser treats the response as same-origin and never consults the
CORS whitelist. Pinning Host is the actual control.

No test in this file prints the token; they assert on its ABSENCE, or on a
length/prefix property.
"""

from __future__ import annotations

import re

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from cato.ui import server as server_module
from cato.ui.server import create_ui_app

#: 64-char lowercase hex — the shape of the daemon token in the page body.
_TOKEN_SHAPE = re.compile(r"\b[0-9a-f]{64}\b")


@pytest.fixture()
async def client():
    app = await create_ui_app(gateway=None)
    async with TestClient(TestServer(app)) as c:
        yield c


def _assert_no_token(body: str) -> None:
    """Fail if the response body contains the daemon token (never printed)."""
    assert server_module._DAEMON_TOKEN not in body, (
        "response body contains the daemon token verbatim"
    )
    assert not _TOKEN_SHAPE.search(body), (
        "response body contains a 64-char hex string shaped like the daemon token"
    )


# ---------------------------------------------------------------------------
# 1. Unauthenticated GET / must not disclose the token
# ---------------------------------------------------------------------------

class TestTokenNotDisclosed:
    async def test_unauthenticated_root_is_rejected(self, client):
        resp = await client.get("/")
        assert resp.status == 401
        _assert_no_token(await resp.text())

    async def test_root_with_wrong_token_is_rejected(self, client):
        resp = await client.get("/", headers={"X-Cato-Token": "0" * 64})
        assert resp.status == 401
        _assert_no_token(await resp.text())

    async def test_root_with_bogus_handoff_is_rejected(self, client):
        resp = await client.get("/?handoff=not-a-real-ticket")
        assert resp.status == 401
        _assert_no_token(await resp.text())

    async def test_root_is_not_in_the_token_exempt_list(self):
        assert "/" not in server_module._TOKEN_EXEMPT_PATHS

    async def test_health_stays_public_and_carries_no_token(self, client):
        """doctor/watchdog probe /health unauthenticated — that must still work."""
        resp = await client.get("/health")
        assert resp.status == 200
        _assert_no_token(await resp.text())


# ---------------------------------------------------------------------------
# 2. Authenticated entry paths still work
# ---------------------------------------------------------------------------

class TestAuthenticatedEntry:
    async def test_root_with_the_daemon_token_serves_the_dashboard(self, client):
        resp = await client.get("/", headers={"X-Cato-Token": server_module._DAEMON_TOKEN})
        assert resp.status == 200
        body = await resp.text()
        assert "window.__CATO_TOKEN__" in body
        # The page must carry a working credential without us printing it.
        assert len(server_module._DAEMON_TOKEN) == 64
        assert server_module._DAEMON_TOKEN in body
        assert resp.headers["Cache-Control"].startswith("no-store")
        assert resp.headers["Referrer-Policy"] == "no-referrer"

    async def test_handoff_requires_the_token(self, client):
        resp = await client.post("/api/dashboard/handoff")
        assert resp.status == 401

    async def test_handoff_ticket_admits_the_browser_once(self, client):
        minted = await client.post(
            "/api/dashboard/handoff",
            headers={"X-Cato-Token": server_module._DAEMON_TOKEN},
        )
        assert minted.status == 200
        payload = await minted.json()
        ticket = payload["handoff"]
        assert payload["expires_in"] == pytest.approx(60.0)
        assert ticket != server_module._DAEMON_TOKEN
        # A ticket is not a token: it must not open the API.
        api = await client.get("/api/skills", headers={"X-Cato-Token": ticket})
        assert api.status == 401

        first = await client.get(f"/?handoff={ticket}")
        assert first.status == 200
        assert "window.__CATO_TOKEN__" in await first.text()

        # Single use — the same ticket must not work twice.
        second = await client.get(f"/?handoff={ticket}")
        assert second.status == 401
        _assert_no_token(await second.text())

    async def test_expired_ticket_is_refused(self, client, monkeypatch):
        minted = await client.post(
            "/api/dashboard/handoff",
            headers={"X-Cato-Token": server_module._DAEMON_TOKEN},
        )
        ticket = (await minted.json())["handoff"]

        import time as _time

        real_monotonic = _time.monotonic
        monkeypatch.setattr(
            server_module.time, "monotonic", lambda: real_monotonic() + 61.0
        )
        resp = await client.get(f"/?handoff={ticket}")
        assert resp.status == 401
        _assert_no_token(await resp.text())


# ---------------------------------------------------------------------------
# 3. Host header validation — the DNS-rebinding control
# ---------------------------------------------------------------------------

class TestHostValidation:
    @pytest.mark.parametrize(
        "host",
        ["evil.com", "evil.com:8080", "cato.attacker.test", "127.0.0.1.nip.io",
         "localhost.evil.com", "0.0.0.0", "[::ffff:127.0.0.1]", ""],
    )
    async def test_foreign_host_is_rejected(self, client, host):
        resp = await client.get("/health", headers={"Host": host})
        assert resp.status == 421, f"Host {host!r} was accepted"
        _assert_no_token(await resp.text())

    async def test_foreign_host_is_rejected_before_the_handler_runs(self, client):
        """Even with a valid token, a rebound Host must not reach a handler."""
        resp = await client.get(
            "/",
            headers={"Host": "evil.com", "X-Cato-Token": server_module._DAEMON_TOKEN},
        )
        assert resp.status == 421
        _assert_no_token(await resp.text())

    @pytest.mark.parametrize(
        "host",
        ["127.0.0.1", "127.0.0.1:8080", "localhost", "localhost:8080",
         "[::1]", "[::1]:8080", "tauri.localhost", "LOCALHOST:8080"],
    )
    async def test_loopback_and_tauri_hosts_are_accepted(self, client, host):
        resp = await client.get("/health", headers={"Host": host})
        assert resp.status == 200

    async def test_tauri_desktop_path_still_works(self, client):
        """Tauri: Origin tauri://localhost, Host 127.0.0.1, token from disk."""
        resp = await client.get(
            "/api/skills",
            headers={
                "Host": "127.0.0.1:8080",
                "Origin": "tauri://localhost",
                "X-Cato-Token": server_module._DAEMON_TOKEN,
            },
        )
        assert resp.status == 200
        assert resp.headers["Access-Control-Allow-Origin"] == "tauri://localhost"

    async def test_host_middleware_is_outermost(self):
        app = await create_ui_app(gateway=None)
        assert app.middlewares[0] is server_module.host_validation_middleware


# ---------------------------------------------------------------------------
# 4. The Host predicate itself
# ---------------------------------------------------------------------------

class TestHostPredicate:
    @pytest.mark.parametrize(
        "host,expected",
        [
            ("127.0.0.1", True),
            ("127.0.0.1:8080", True),
            ("localhost", True),
            ("localhost:65535", True),
            ("[::1]", True),
            ("[::1]:8080", True),
            ("tauri.localhost", True),
            ("Tauri.Localhost:8080", True),
            ("", False),
            ("evil.com", False),
            ("127.0.0.1.evil.com", False),
            ("localhost.evil.com", False),
            ("evil.com:80", False),
            ("127.0.0.2", False),
            ("192.168.1.10", False),
            ("[2001:db8::1]", False),
            ("[bad", False),
        ],
    )
    def test_predicate(self, host, expected):
        assert server_module._host_header_allowed(host) is expected


# ---------------------------------------------------------------------------
# 5. `cato dashboard` — the operator's browser entry path
# ---------------------------------------------------------------------------

class TestDashboardCommand:
    def test_opens_browser_with_a_ticket_and_never_prints_the_token(self, tmp_path):
        from unittest.mock import patch

        from click.testing import CliRunner

        from cato import cli as cli_mod

        token_file = tmp_path / "daemon.token"
        token_file.write_text("a" * 64, encoding="utf-8")
        opened: list[str] = []

        with (
            patch.object(cli_mod, "_CATO_DIR", tmp_path),
            patch.object(cli_mod, "_discover_http_port", return_value=8080),
            patch.object(cli_mod, "_request_dashboard_handoff", return_value="ticket-123") as ex,
            patch("webbrowser.open", side_effect=lambda u: opened.append(u) or True),
        ):
            result = CliRunner().invoke(cli_mod.main, ["dashboard"])

        assert result.exit_code == 0, result.output
        ex.assert_called_once_with(8080, "a" * 64)
        assert opened == ["http://127.0.0.1:8080/?handoff=ticket-123"]
        # The ticket is single-use and short-lived, but the token must never
        # reach the terminal or the shell history.
        assert "a" * 64 not in result.output
        assert "ticket-123" not in result.output

    def test_fails_loudly_when_the_daemon_is_not_running(self, tmp_path):
        from unittest.mock import patch

        from click.testing import CliRunner

        from cato import cli as cli_mod

        (tmp_path / "daemon.token").write_text("b" * 64, encoding="utf-8")

        with (
            patch.object(cli_mod, "_CATO_DIR", tmp_path),
            patch.object(cli_mod, "_discover_http_port", return_value=8080),
            patch.object(
                cli_mod, "_request_dashboard_handoff", side_effect=OSError("connection refused")
            ),
            patch("webbrowser.open") as opener,
        ):
            result = CliRunner().invoke(cli_mod.main, ["dashboard"])

        assert result.exit_code == 1
        assert "Could not obtain a dashboard ticket" in result.output
        opener.assert_not_called()
        assert "b" * 64 not in result.output

    def test_missing_token_file_fails_closed(self, tmp_path):
        from unittest.mock import patch

        from click.testing import CliRunner

        from cato import cli as cli_mod

        with patch.object(cli_mod, "_CATO_DIR", tmp_path), patch("webbrowser.open") as opener:
            result = CliRunner().invoke(cli_mod.main, ["dashboard"])

        assert result.exit_code == 1
        assert "Cannot read the daemon token" in result.output
        opener.assert_not_called()
