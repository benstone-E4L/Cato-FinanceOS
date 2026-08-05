"""
tests/test_t21_operator_subprocess_surfaces.py — t21 regression pins.

Covers the four ungated subprocess surfaces triaged in t21:

  1. cato/orchestrator/cli_invoker.py    — coding-agent fan-out
  2. cato/orchestrator/cli_process_pool.py — warm pool behind the same fan-out
  3. cato/api/pty_routes.py              — interactive operator terminal
  4. cato/gateway.py                     — `git clone` for skill install

None of the four is model-reachable, so none is routed through
``guarded_action``. What IS pinned here is the hardening that keeps them
operator-only and auditable:

  * both subprocess WebSockets FAIL CLOSED when the app has no daemon_token
    (they used to skip authentication entirely in that case);
  * the PTY CLI allowlist is enforced at the spawn helper as well as the
    route, and an empty allowlist refuses everything;
  * `git clone` cannot be talked into executing code by the URL
    (`ext::` transport, `--upload-pack=` argument injection, LFS smudge);
  * operator actions that spawn a process or write a credential land in the
    action ledger, and are REFUSED when they cannot be recorded.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from cato.api.pty_routes import ALLOWED_CLIS
from cato.api.pty_routes import register_routes as register_pty_routes
from cato.api.websocket_handler import _task_store
from cato.api.websocket_handler import register_routes as register_coding_routes
from cato.config import CatoConfig
from cato.gateway import Gateway
from cato.orchestrator.pty_session import build_pty_cmd

# Imported lazily inside the tests that need them. These names do not exist on
# the pre-fix revision, and a module-level import of them would make the whole
# file fail to COLLECT there — which proves nothing about behaviour. Collection
# must succeed against the pre-fix tree so the behavioural assertions below are
# what fails. See scripts/t21_before_after_evidence.py.
try:  # pragma: no cover — exercised by the BEFORE run of the evidence script
    from cato.orchestrator.pty_session import ALLOWED_PTY_CLIS
except ImportError:  # pragma: no cover
    ALLOWED_PTY_CLIS = None  # type: ignore[assignment]

TOKEN = "t21" + "0" * 61
WRONG = "f" * 64


def _make_gateway(tmp_path: Path) -> Gateway:
    cfg = CatoConfig()
    cfg.workspace_dir = str(tmp_path / "workspace")
    cfg.agent_name = "t21-agent"
    budget = MagicMock()
    budget.format_footer.return_value = ""
    return Gateway(config=cfg, budget=budget, vault=MagicMock())


# ---------------------------------------------------------------------------
# 1/2. Coding-agent fan-out WebSocket — fail closed
# ---------------------------------------------------------------------------

class TestCodingAgentWsFailsClosed(AioHTTPTestCase):
    """No daemon_token on the app must mean NO connection, not no checking."""

    async def get_application(self) -> web.Application:
        app = web.Application()
        # Deliberately no app["daemon_token"] — the pre-fix code read this as
        # "authentication is not configured, so let everyone in".
        register_coding_routes(app)
        return app

    async def test_unauthenticated_app_refuses_and_spawns_nothing(self):
        task_id = "t21-no-token"
        _task_store[task_id] = {
            "task": "spawn something", "prompt": "spawn something",
            "enabled_models": ["claude"],
        }

        def _explode(*_a, **_kw):
            raise AssertionError("a CLI subprocess was invoked on the refused path")

        try:
            with patch("cato.api.websocket_handler.invoke_claude_api", side_effect=_explode):
                async with self.client.ws_connect(f"/ws/coding-agent/{task_id}") as ws:
                    msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                    while msg.type is web.WSMsgType.TEXT:
                        assert json.loads(msg.data.strip())["event"] == "error"
                        msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                    assert msg.type is web.WSMsgType.CLOSE
                    assert ws.close_code == 4401
        finally:
            _task_store.pop(task_id, None)


class TestCodingAgentWsRejectsWrongToken(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        app = web.Application()
        app["daemon_token"] = TOKEN
        register_coding_routes(app)
        return app

    async def test_wrong_token_is_refused(self):
        task_id = "t21-wrong-token"
        _task_store[task_id] = {
            "task": "spawn something", "prompt": "spawn something",
            "enabled_models": ["claude"],
        }
        try:
            async with self.client.ws_connect(
                f"/ws/coding-agent/{task_id}?token={WRONG}"
            ) as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                while msg.type is web.WSMsgType.TEXT:
                    msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                assert ws.close_code == 4401
        finally:
            _task_store.pop(task_id, None)


# ---------------------------------------------------------------------------
# 3. PTY terminal
# ---------------------------------------------------------------------------

class TestPtyWsFailsClosed(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        app = web.Application()
        # No daemon_token, same as above.
        register_pty_routes(app)
        return app

    async def test_unauthenticated_app_refuses_before_streaming(self):
        session = MagicMock()
        session.session_id = "t21-pty"
        with patch("cato.api.pty_routes.get_session", return_value=session):
            async with self.client.ws_connect("/ws/pty/t21-pty") as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                while msg.type is web.WSMsgType.TEXT:
                    msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                assert ws.close_code == 4401
        session.write.assert_not_called()


class TestPtyAllowlist:
    def test_route_and_spawn_share_one_allowlist(self):
        assert ALLOWED_PTY_CLIS is not None, "pty_session has no spawn-side allowlist"
        assert ALLOWED_CLIS is ALLOWED_PTY_CLIS
        assert ALLOWED_PTY_CLIS  # non-empty, or nothing may spawn

    @pytest.mark.parametrize("name", ["bash", "cmd.exe", "python", "cursor", "", "CLAUDE; rm -rf /"])
    def test_spawn_helper_refuses_anything_off_the_allowlist(self, name):
        with pytest.raises(ValueError):
            build_pty_cmd(name)

    def test_empty_allowlist_refuses_everything(self):
        """Fail closed: an empty allowlist must not mean 'no restriction'."""
        assert ALLOWED_PTY_CLIS is not None, "pty_session has no spawn-side allowlist"
        with patch("cato.orchestrator.pty_session.ALLOWED_PTY_CLIS", frozenset()):
            with pytest.raises(ValueError):
                build_pty_cmd("claude")

    def test_spawn_helper_does_not_resolve_arbitrary_path_executables(self):
        """The helper must reject before it ever reaches shutil.which()."""
        with patch("cato.orchestrator.pty_session._resolve_cli") as resolver:
            with pytest.raises(ValueError):
                build_pty_cmd("bash")
        resolver.assert_not_called()


class TestPtyRouteAllowlist(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        app = web.Application()
        app["daemon_token"] = TOKEN
        register_pty_routes(app)
        return app

    async def test_unknown_cli_rejected(self):
        resp = await self.client.post("/api/pty/sessions", json={"cli": "bash"})
        assert resp.status in (400, 503)

    async def test_empty_allowlist_rejects_a_known_cli(self):
        with patch("cato.api.pty_routes.ALLOWED_CLIS", frozenset()), \
             patch("cato.api.pty_routes.pty_available", return_value=True), \
             patch("cato.api.pty_routes.create_session") as create:
            resp = await self.client.post("/api/pty/sessions", json={"cli": "claude"})
        assert resp.status == 400
        create.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Skill install — `git clone` is a code-execution primitive
# ---------------------------------------------------------------------------

class TestSkillSourceValidation:
    @pytest.mark.parametrize("url", [
        "ext::sh -c 'touch /tmp/pwned'",       # git remote helper that runs a command
        "ext::sh",
        "--upload-pack=/tmp/evil.sh",          # argument injection (no `--` pre-fix)
        "--config=core.hooksPath=/tmp",
        "-u/tmp/evil",
        "file:///etc",
        "ssh://host/repo.git",
        "git://host/repo.git",
        "git@github.com:org/repo.git",         # scp-style, not a URL
        "/local/path/repo",
        "https://host/repo\next::sh -c id",
        "",
    ])
    def test_dangerous_sources_are_refused(self, url):
        from cato.gateway import _skill_source_problem

        assert _skill_source_problem(url) is not None

    @pytest.mark.parametrize("url", [
        "https://github.com/org/repo",
        "https://github.com/org/repo.git",
        "http://example.com/skill",
        "https://example.com/raw/SKILL.md",
    ])
    def test_ordinary_https_sources_are_allowed(self, url):
        from cato.gateway import _skill_source_problem

        assert _skill_source_problem(url) is None


class TestInstallSkillFromUrlHardening:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", [
        "ext::sh -c 'touch /tmp/pwned'",
        "--upload-pack=/tmp/evil.sh",
        "file:///etc/passwd",
        "git@github.com:org/repo.git",
    ])
    async def test_refused_urls_never_reach_a_subprocess(self, tmp_path, url):
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)

        async def _explode(*_a, **_kw):
            raise AssertionError(f"git was executed for a refused url: {url!r}")

        with patch.object(gw, "_skills_dir", return_value=skills_root), \
             patch("asyncio.create_subprocess_exec", new=_explode):
            assert await gw._install_skill_from_url(url) is None

    @pytest.mark.asyncio
    async def test_clone_argv_cannot_be_turned_into_code_execution(self, tmp_path):
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)
        seen: dict = {}

        async def fake_exec(*args, **kwargs):
            seen["argv"] = list(args)
            seen["env"] = kwargs.get("env") or {}
            proc = MagicMock()
            proc.returncode = 0
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch.object(gw, "_skills_dir", return_value=skills_root), \
             patch("asyncio.create_subprocess_exec", new=fake_exec), \
             patch.object(gw, "_list_skills", return_value=[]):
            await gw._install_skill_from_url("https://example.com/org/my-skill")

        argv = seen["argv"]
        assert argv[0] == "git"
        # End-of-options marker immediately before the URL: a URL that looks
        # like an option can no longer be parsed as one.
        assert "--" in argv
        assert argv[argv.index("--") + 1] == "https://example.com/org/my-skill"
        # Command-executing transports off.
        assert "protocol.ext.allow=never" in argv
        assert "protocol.file.allow=never" in argv
        # Submodules are not fetched, so no submodule URL is followed.
        assert "--no-recurse-submodules" in argv
        # LFS smudge filters cannot run at checkout.
        assert "filter.lfs.smudge=" in argv
        assert seen["env"].get("GIT_LFS_SKIP_SMUDGE") == "1"
        assert seen["env"].get("GIT_TERMINAL_PROMPT") == "0"

    def test_clone_config_and_env_constants_are_not_empty(self):
        """Fail closed: emptying these silently would re-open the RCE paths."""
        from cato.gateway import _GIT_CLONE_CONFIG, _GIT_CLONE_ENV

        assert "protocol.ext.allow=never" in _GIT_CLONE_CONFIG
        assert _GIT_CLONE_ENV["GIT_LFS_SKIP_SMUDGE"] == "1"

    @pytest.mark.asyncio
    async def test_empty_slug_is_refused_without_touching_the_skills_dir(self, tmp_path):
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)
        (skills_root / "keep.txt").write_text("keep", encoding="utf-8")

        async def _explode(*_a, **_kw):
            raise AssertionError("git was executed for an empty slug")

        with patch.object(gw, "_skills_dir", return_value=skills_root), \
             patch("asyncio.create_subprocess_exec", new=_explode):
            assert await gw._install_skill_from_url("https://example.com/---") is None
        assert (skills_root / "keep.txt").exists()


# ---------------------------------------------------------------------------
# Operator ledger — an unledgered operator action is invisible to an audit
# ---------------------------------------------------------------------------

class TestOperatorLedger:
    @pytest.mark.asyncio
    async def test_action_records_intent_then_confirmed(self, tmp_path):
        from cato.audit.ledger import EntryKind, LedgerMiddleware
        from cato.core import operator_ledger

        ledger = LedgerMiddleware(db_path=tmp_path / "ledger.db")
        ran: list[str] = []

        async def _work() -> str:
            ran.append("yes")
            return "done"

        with patch.object(operator_ledger, "get_operator_ledger", return_value=ledger):
            out = await operator_ledger.record_operator_action(
                tool_name="skill.install",
                tool_input={"url": "https://example.com/x"},
                session_id="gateway-ws",
                run=_work,
            )

        assert out == "done" and ran == ["yes"]
        records = ledger._conn.execute(
            "SELECT entry_kind FROM ledger_records ORDER BY seq"
        ).fetchall()
        kinds = [r["entry_kind"] for r in records]
        assert kinds[0] == EntryKind.INTENT.value
        assert EntryKind.CONFIRMED.value in kinds
        ledger.close()

    @pytest.mark.asyncio
    async def test_unavailable_ledger_refuses_the_action(self):
        from cato.core import operator_ledger

        async def _work() -> str:
            raise AssertionError("the action ran without a ledger record")

        with patch.object(operator_ledger, "get_operator_ledger", return_value=None):
            with pytest.raises(operator_ledger.OperatorLedgerUnavailable):
                await operator_ledger.record_operator_action(
                    tool_name="pty.session.create",
                    tool_input={"cli": "claude"},
                    session_id="s",
                    run=_work,
                )

    @pytest.mark.asyncio
    async def test_skill_install_over_ws_is_ledgered(self, tmp_path):
        from cato.core import operator_ledger

        gw = _make_gateway(tmp_path)
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()
        calls: list[str] = []

        async def fake_record(*, tool_name, tool_input, session_id, run, **kw):
            calls.append(tool_name)
            return await run()

        with patch("cato.gateway.record_operator_action", new=fake_record), \
             patch.object(gw, "_install_skill_from_url",
                          new=AsyncMock(return_value={"dir": "x", "name": "x"})):
            await gw._handle_ws_message(
                ws, json.dumps({"type": "skill_install", "url": "https://example.com/x"})
            )

        assert calls == ["skill.install"]

    @pytest.mark.asyncio
    async def test_vault_write_over_ws_is_ledgered_without_the_value(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()
        recorded: list[dict] = []

        async def fake_record(*, tool_name, tool_input, session_id, run, **kw):
            recorded.append({"tool": tool_name, "input": tool_input})
            return await run()

        with patch("cato.gateway.record_operator_action", new=fake_record):
            await gw._handle_ws_message(ws, json.dumps({
                "type": "set_vault_key",
                "vault_key": "TELEGRAM_BOT_TOKEN",
                "value": "super-secret-value",
            }))

        assert recorded and recorded[0]["tool"] == "vault.set"
        assert recorded[0]["input"] == {"vault_key": "TELEGRAM_BOT_TOKEN"}
        assert "super-secret-value" not in json.dumps(recorded)
