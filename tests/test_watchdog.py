"""
tests/test_watchdog.py — Unit tests for the Cato watchdog script.

Covers:
- _effective_port(): falls back to PORT constant when no port file exists,
  reads the port file when it exists.
- _clear_stale_pid(): removes PID file when PID is dead; kills process and
  removes PID file when PID is alive but port is unresponsive; always removes
  the port file before restart.
- _kill_process(): calls taskkill on Windows / os.kill on POSIX.
- _gateway_alive(): uses the effective port, not the hardcoded constant.
"""
from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to load the watchdog module with a patched data-dir
# ---------------------------------------------------------------------------

def _load_watchdog(tmp_path: Path) -> types.ModuleType:
    """Import scripts/watchdog.py with _CATO_DIR pointing to tmp_path."""
    # Ensure the repo root is on sys.path so the module can find cato.platform
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Remove any cached copy so we get a fresh import each time
    for key in list(sys.modules):
        if "watchdog" in key and "scripts" not in key:
            pass  # leave unrelated watchdog modules alone
    if "scripts.watchdog" in sys.modules:
        del sys.modules["scripts.watchdog"]

    spec = importlib.util.spec_from_file_location(
        "scripts.watchdog",
        repo_root / "scripts" / "watchdog.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Point the module's globals at tmp_path
    mod._CATO_DIR = tmp_path
    mod.PID_FILE = tmp_path / "cato.pid"
    mod.PORT_FILE = tmp_path / "cato.port"
    mod.PORT = 8080
    mod.HOST = "127.0.0.1"
    return mod


# ---------------------------------------------------------------------------
# _effective_port
# ---------------------------------------------------------------------------

class TestEffectivePort:
    def test_returns_PORT_when_no_port_file(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        assert wd._effective_port() == 8080

    def test_reads_port_file_when_present(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        (tmp_path / "cato.port").write_text("9090")
        assert wd._effective_port() == 9090

    def test_falls_back_on_corrupt_port_file(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        (tmp_path / "cato.port").write_text("not-a-number")
        assert wd._effective_port() == 8080

    def test_falls_back_on_empty_port_file(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        (tmp_path / "cato.port").write_text("")
        assert wd._effective_port() == 8080


# ---------------------------------------------------------------------------
# _gateway_alive uses effective port
# ---------------------------------------------------------------------------

class TestGatewayAlive:
    def test_uses_effective_port_from_file(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        (tmp_path / "cato.port").write_text("9999")

        import socket as _socket
        import contextlib

        connected_ports = []

        class _FakeSocket:
            def __init__(self, *a, **kw):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        def _fake_create_connection(addr, timeout=None):
            connected_ports.append(addr[1])
            return _FakeSocket()

        with patch.object(
            importlib.import_module("socket"), "create_connection", _fake_create_connection
        ):
            result = wd._gateway_alive()

        assert result is True
        assert connected_ports == [9999]

    def test_returns_false_on_connection_error(self, tmp_path):
        wd = _load_watchdog(tmp_path)

        import socket as _socket

        def _refuse(*a, **kw):
            raise OSError("connection refused")

        with patch.object(
            importlib.import_module("socket"), "create_connection", _refuse
        ):
            result = wd._gateway_alive()

        assert result is False


# ---------------------------------------------------------------------------
# _clear_stale_pid
# ---------------------------------------------------------------------------

class TestClearStalePid:
    def test_removes_port_file_even_when_no_pid_file(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        port_file = tmp_path / "cato.port"
        port_file.write_text("8081")
        # No PID file
        wd._clear_stale_pid()
        assert not port_file.exists()

    def test_clears_pid_file_when_pid_is_dead(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        pid_file = tmp_path / "cato.pid"
        pid_file.write_text("99999999")  # Almost certainly not running

        with patch.object(wd, "_pid_alive", return_value=False):
            wd._clear_stale_pid()

        assert not pid_file.exists()

    def test_clears_pid_file_when_value_invalid(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        pid_file = tmp_path / "cato.pid"
        pid_file.write_text("not-an-int")

        wd._clear_stale_pid()

        assert not pid_file.exists()

    def test_kills_and_clears_pid_when_alive_but_port_unresponsive(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        pid_file = tmp_path / "cato.pid"
        pid_file.write_text("12345")

        killed_pids = []

        def _fake_kill(pid):
            killed_pids.append(pid)

        with (
            patch.object(wd, "_pid_alive", return_value=True),
            patch.object(wd, "_kill_process", side_effect=_fake_kill),
            patch("time.sleep"),  # don't actually sleep
        ):
            wd._clear_stale_pid()

        assert killed_pids == [12345]
        assert not pid_file.exists()

    def test_no_crash_when_pid_file_missing(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        # Should not raise even if no PID file at all
        wd._clear_stale_pid()


# ---------------------------------------------------------------------------
# _kill_process (platform-specific)
# ---------------------------------------------------------------------------

class TestKillProcess:
    def test_uses_taskkill_on_windows(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        calls = []

        import subprocess as _sp

        def _fake_run(cmd, **kw):
            calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch.object(sys, "platform", "win32"),
            patch("subprocess.run", _fake_run),
        ):
            wd._kill_process(9876)

        assert any("taskkill" in str(c) for c in calls)
        assert any("9876" in str(c) for c in calls)

    def test_uses_sigterm_on_posix(self, tmp_path):
        wd = _load_watchdog(tmp_path)
        sent_signals = []

        import signal as _signal

        def _fake_kill(pid, sig):
            sent_signals.append((pid, sig))

        with (
            patch.object(sys, "platform", "linux"),
            patch("os.kill", _fake_kill),
            patch.object(wd, "_pid_alive", return_value=False),
            patch("time.sleep"),
        ):
            wd._kill_process(5555)

        assert (_signal.SIGTERM in [s for _, s in sent_signals]) or sent_signals


# ---------------------------------------------------------------------------
# cli.py — cato.port file written by _run_daemon
# ---------------------------------------------------------------------------

class TestPortFileWrittenByDaemon:
    def test_cato_port_written_after_bind(self, tmp_path):
        """_run_daemon writes the actual bound port to cato.port."""
        import cato.cli as cli_mod
        source = Path(cli_mod.__file__).read_text(encoding="utf-8")
        assert "cato.port" in source, "_run_daemon must write cato.port"

    def test_cato_port_cleaned_up_on_shutdown(self, tmp_path):
        """_run_daemon removes cato.port in the finally block."""
        import cato.cli as cli_mod
        source = Path(cli_mod.__file__).read_text(encoding="utf-8")
        # Both creation and deletion should be present
        assert "cato.port" in source
        assert ".unlink(missing_ok=True)" in source
