"""t26 CRITICAL-1 — daemon lifecycle must be correct on this platform.

The original ``_pid_alive`` used ``os.kill(pid, 0)``. On Windows
``signal.CTRL_C_EVENT == 0``, so CPython routed that to
``GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)``, which needs a console
process-group id and fails with ERROR_INVALID_PARAMETER (87) for an ordinary
pid. The OSError fell through to ``return False``, so:

  * ``cato stop`` reported "Cato is not running." and orphaned the daemon,
  * ``_read_live_pid`` then deleted cato.pid AND cato.port,
  * the next ``cato start`` saw nothing and launched a SECOND daemon which
    port-shifted to 8081 and appended to the SAME hash-chained ledger.

These tests pin the whole chain, not just the probe.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cato import platform as cato_platform
from cato.cli import main


@pytest.fixture()
def live_child():
    """A real, live child process on this platform."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give the interpreter a moment to actually exist.
    for _ in range(50):
        if cato_platform.pid_alive(proc.pid):
            break
        time.sleep(0.05)
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# The liveness probe itself
# ---------------------------------------------------------------------------

class TestPidAlive:
    def test_own_process_is_alive(self):
        assert cato_platform.pid_alive(os.getpid()) is True

    def test_live_child_process_is_alive(self, live_child):
        """The exact case the old probe got wrong on Windows."""
        assert cato_platform.pid_alive(live_child.pid) is True

    def test_exited_child_process_is_not_alive(self, live_child):
        live_child.kill()
        live_child.wait(timeout=10)
        # Windows keeps the pid reserved only while a handle is open; poll until
        # the kernel reports the exit code, with a hard bound.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and cato_platform.pid_alive(live_child.pid):
            time.sleep(0.1)
        assert cato_platform.pid_alive(live_child.pid) is False

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX zombie semantics")
    def test_zombie_child_is_not_reported_alive(self, live_child):
        """SIGKILL without wait() leaves a zombie; stop must still succeed.

        Regression for CI: terminate_pid returned False because os.kill(pid, 0)
        succeeds for zombies until the parent reaps them.
        """
        os.kill(live_child.pid, 9)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            # Wait until /proc shows zombie or the pid vanishes.
            if not cato_platform.pid_alive(live_child.pid):
                break
            time.sleep(0.05)
        assert cato_platform.pid_alive(live_child.pid) is False
        # Reap so the fixture teardown is clean.
        live_child.wait(timeout=10)

    def test_nonexistent_pid_is_not_alive(self):
        assert cato_platform.pid_alive(999_999_999) is False

    def test_nonpositive_pids_are_not_alive(self):
        assert cato_platform.pid_alive(0) is False
        assert cato_platform.pid_alive(-1) is False

    def test_cli_probe_delegates_to_platform(self, live_child):
        """cato.cli._pid_alive must give the same answer as the platform probe."""
        from cato.cli import _pid_alive

        assert _pid_alive(live_child.pid) is True
        assert _pid_alive(999_999_999) is False

    def test_doctor_probe_agrees_with_platform(self, live_child):
        """doctor must not print STALE PID for a process that is alive."""
        from cato.doctor import DoctorReport

        assert DoctorReport._pid_alive(live_child.pid) is True

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only regression")
    def test_probe_never_calls_os_kill_on_windows(self, live_child):
        """os.kill(pid, 0) must not be on the Windows liveness path at all.

        Signal 0 is CTRL_C_EVENT there, so the call either raises OSError (the
        observed failure: GetLastError 87, live daemon reported dead) or
        actually delivers a console Ctrl-C to a process group. Both are wrong;
        a liveness probe must have no side effects.
        """
        with patch("os.kill", side_effect=AssertionError("os.kill used as a probe")):
            assert cato_platform.pid_alive(live_child.pid) is True
            assert cato_platform.pid_alive(999_999_999) is False


# ---------------------------------------------------------------------------
# terminate_pid — stop must actually stop
# ---------------------------------------------------------------------------

class TestTerminatePid:
    def test_terminates_a_live_process(self, live_child):
        assert cato_platform.terminate_pid(live_child.pid, timeout=15.0) is True
        assert cato_platform.pid_alive(live_child.pid) is False

    def test_already_dead_process_reports_success(self, live_child):
        live_child.kill()
        live_child.wait(timeout=10)
        assert cato_platform.terminate_pid(live_child.pid, timeout=5.0) is True

    def test_refuses_nonpositive_pid(self):
        assert cato_platform.terminate_pid(0) is False


# ---------------------------------------------------------------------------
# _read_live_pid must not delete state for a live daemon
# ---------------------------------------------------------------------------

class TestReadLivePid:
    def test_preserves_pid_and_port_files_when_process_is_alive(self, tmp_path, live_child):
        from cato import cli as cli_mod

        pid_file = tmp_path / "cato.pid"
        port_file = tmp_path / "cato.port"
        pid_file.write_text(str(live_child.pid), encoding="utf-8")
        port_file.write_text("8080", encoding="utf-8")

        with patch.object(cli_mod, "_PID_FILE", pid_file), patch.object(cli_mod, "_PORT_FILE", port_file):
            found = cli_mod._read_live_pid()

        assert found == live_child.pid
        assert pid_file.exists(), "pid file deleted while the daemon was alive"
        assert port_file.exists(), "port file deleted while the daemon was alive"

    def test_removes_files_only_for_a_genuinely_dead_pid(self, tmp_path):
        from cato import cli as cli_mod

        pid_file = tmp_path / "cato.pid"
        port_file = tmp_path / "cato.port"
        pid_file.write_text("999999999", encoding="utf-8")
        port_file.write_text("8080", encoding="utf-8")

        with patch.object(cli_mod, "_PID_FILE", pid_file), patch.object(cli_mod, "_PORT_FILE", port_file):
            assert cli_mod._read_live_pid() is None

        assert not pid_file.exists()
        assert not port_file.exists()


# ---------------------------------------------------------------------------
# cato stop
# ---------------------------------------------------------------------------

class TestCmdStop:
    def test_stop_terminates_a_live_process_and_clears_files(self, tmp_path, live_child):
        from cato import cli as cli_mod

        pid_file = tmp_path / "cato.pid"
        port_file = tmp_path / "cato.port"
        pid_file.write_text(str(live_child.pid), encoding="utf-8")
        port_file.write_text("8080", encoding="utf-8")

        with patch.object(cli_mod, "_PID_FILE", pid_file), patch.object(cli_mod, "_PORT_FILE", port_file):
            result = CliRunner().invoke(main, ["stop"])

        assert result.exit_code == 0, result.output
        assert "is not running" not in result.output
        assert f"PID {live_child.pid}) stopped" in result.output
        assert cato_platform.pid_alive(live_child.pid) is False
        assert not pid_file.exists()
        assert not port_file.exists()

    def test_stop_keeps_files_when_termination_fails(self, tmp_path, live_child):
        """A daemon we could not kill must stay discoverable to 'cato start'."""
        from cato import cli as cli_mod

        pid_file = tmp_path / "cato.pid"
        port_file = tmp_path / "cato.port"
        pid_file.write_text(str(live_child.pid), encoding="utf-8")
        port_file.write_text("8080", encoding="utf-8")

        with (
            patch.object(cli_mod, "_PID_FILE", pid_file),
            patch.object(cli_mod, "_PORT_FILE", port_file),
            patch.object(cli_mod, "terminate_pid", return_value=False),
        ):
            result = CliRunner().invoke(main, ["stop"])

        assert result.exit_code == 1
        assert "still running" in result.output
        assert pid_file.exists(), "pid file deleted for a daemon that is still alive"
        assert port_file.exists(), "port file deleted for a daemon that is still alive"


# ---------------------------------------------------------------------------
# cato start must refuse a duplicate
# ---------------------------------------------------------------------------

class TestCmdStartRefusesDuplicate:
    def test_refuses_when_pid_file_points_at_a_live_process(self, tmp_path, live_child):
        from cato import cli as cli_mod

        pid_file = tmp_path / "cato.pid"
        port_file = tmp_path / "cato.port"
        pid_file.write_text(str(live_child.pid), encoding="utf-8")
        port_file.write_text("8080", encoding="utf-8")

        with (
            patch.object(cli_mod, "_PID_FILE", pid_file),
            patch.object(cli_mod, "_PORT_FILE", port_file),
            patch.object(cli_mod, "_run_daemon") as run_daemon,
        ):
            result = CliRunner().invoke(main, ["start", "--channel", "webchat"])

        assert result.exit_code == 1
        assert "already running" in result.output
        run_daemon.assert_not_called()
        assert pid_file.read_text(encoding="utf-8").strip() == str(live_child.pid)

    def test_refuses_when_health_answers_but_pid_file_is_gone(self, tmp_path):
        """The exact state 'cato doctor' used to recommend manufacturing."""
        from cato import cli as cli_mod

        pid_file = tmp_path / "cato.pid"
        port_file = tmp_path / "cato.port"

        with (
            patch.object(cli_mod, "_PID_FILE", pid_file),
            patch.object(cli_mod, "_PORT_FILE", port_file),
            patch.object(cli_mod, "_daemon_health_responding", return_value=True),
            patch.object(cli_mod, "_run_daemon") as run_daemon,
        ):
            result = CliRunner().invoke(main, ["start", "--channel", "webchat"])

        assert result.exit_code == 1
        assert "Refusing to start a second daemon" in result.output
        run_daemon.assert_not_called()
        assert not pid_file.exists()

    def test_starts_when_nothing_is_running(self, tmp_path, monkeypatch):
        from cato import cli as cli_mod
        from cato.vault_bootstrap import BootstrapReport

        pid_file = tmp_path / "cato.pid"
        port_file = tmp_path / "cato.port"
        monkeypatch.setenv("CATO_VAULT_PASSWORD", "unit-test-vault-pw")
        boot = BootstrapReport(
            vault_path=tmp_path / "vault.enc",
            vault_present=False,
            vault_unlocked=False,
            vault_keys_total=0,
            applied_from_vault=(),
            filled_from_dotenv=(),
        )

        with (
            patch.object(cli_mod, "_PID_FILE", pid_file),
            patch.object(cli_mod, "_PORT_FILE", port_file),
            patch.object(cli_mod, "_daemon_health_responding", return_value=False),
            patch.object(cli_mod, "setup_signal_handlers"),
            patch.object(cli_mod, "_run_daemon") as run_daemon,
            patch(
                "cato.vault_bootstrap.bootstrap_launch_credentials",
                return_value=(None, boot),
            ),
        ):
            result = CliRunner().invoke(main, ["start", "--channel", "webchat"])

        assert result.exit_code == 0, result.output
        run_daemon.assert_called_once()


# ---------------------------------------------------------------------------
# The daemon must never silently take a second port
# ---------------------------------------------------------------------------

class TestPortShiftIsDisabledForTheDaemon:
    @pytest.mark.asyncio
    async def test_bind_without_shift_retries_the_same_port_and_then_fails(self):
        from cato.cli import _bind_http_site_with_fallback

        attempted: list[int] = []

        class _FailingSite:
            def __init__(self, runner, host, port):
                attempted.append(port)

            async def start(self):
                raise OSError(10048, "address in use")

        with patch("aiohttp.web.TCPSite", _FailingSite):
            with pytest.raises(OSError):
                await _bind_http_site_with_fallback(
                    object(), "127.0.0.1", 8080,
                    max_attempts=3, retry_delay=0.0, allow_port_shift=False,
                )

        assert attempted == [8080, 8080, 8080], "daemon must never shift to another port"

    def test_run_daemon_disables_port_shift(self):
        """Pin the wiring: _run_daemon must not accept a fallback port."""
        source = Path(__import__("cato.cli", fromlist=["cli"]).__file__).read_text(encoding="utf-8")
        run_daemon_src = source.split("def _run_daemon(", 1)[1]
        assert "allow_port_shift=False" in run_daemon_src
