"""
Cato Gateway Watchdog
=====================
Polls port 8080 (or CATO_PORT env var) every 30 seconds.
If the gateway is down, clears the stale PID file and restarts `cato start`.

Run continuously:  python scripts/watchdog.py
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def _read_port_from_env() -> int:
    """Return the configured port from env, defaulting to 8080."""
    return int(os.environ.get("CATO_PORT", "8080"))


PORT: int = _read_port_from_env()
HOST: str = os.environ.get("CATO_HOST", "127.0.0.1")
POLL_INTERVAL: int = int(os.environ.get("CATO_WATCHDOG_INTERVAL", "30"))  # seconds
STARTUP_GRACE: int = int(os.environ.get("CATO_WATCHDOG_GRACE", "20"))     # seconds after restart (20s for Windows cold start)

# Resolve cato data dir the same way the CLI does
try:
    from cato.platform import get_data_dir
    _CATO_DIR = Path(get_data_dir())
except Exception:
    _CATO_DIR = Path(os.environ.get("APPDATA", Path.home())) / "cato"

PID_FILE: Path = _CATO_DIR / "cato.pid"
PORT_FILE: Path = _CATO_DIR / "cato.port"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_CATO_DIR / "watchdog.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("cato.watchdog")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _effective_port() -> int:
    """Return the port the daemon actually bound to.

    Reads cato.port (written by the daemon at startup) when available,
    falling back to the configured PORT constant.  This ensures the watchdog
    checks the right port even when the daemon fell back to an alternate port.
    """
    try:
        if PORT_FILE.exists():
            p = int(PORT_FILE.read_text().strip())
            if p != PORT:
                log.debug("Reading actual port from %s: %d (configured: %d)", PORT_FILE, p, PORT)
            return p
    except (ValueError, OSError):
        pass
    return PORT


def _gateway_alive() -> bool:
    """Return True if the gateway is accepting TCP connections on HOST:effective_port."""
    check_port = _effective_port()
    try:
        with socket.create_connection((HOST, check_port), timeout=3):
            return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    """Return True if a process with this PID exists.

    Uses the shared platform probe: on Windows ``os.kill(pid, 0)`` is
    CTRL_C_EVENT, not a liveness check, and reported live daemons as dead —
    which made the watchdog kill and restart a healthy process.
    """
    try:
        from cato.platform import pid_alive as _pid_alive_impl
    except Exception:  # pragma: no cover - watchdog must never die on import
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    return _pid_alive_impl(pid)


def _kill_process(pid: int) -> None:
    """Terminate a process by PID, escalating to SIGKILL on Unix if needed."""
    import signal as _signal
    try:
        if sys.platform == "win32":
            import subprocess as _sp
            _sp.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
            log.info("Killed stale process PID %s via taskkill", pid)
        else:
            os.kill(pid, _signal.SIGTERM)
            # Give the process a moment to exit cleanly before SIGKILL
            for _ in range(5):
                time.sleep(1)
                if not _pid_alive(pid):
                    break
            else:
                os.kill(pid, _signal.SIGKILL)
            log.info("Killed stale process PID %s", pid)
    except OSError as exc:
        log.warning("Could not kill PID %s: %s", pid, exc)


def _clear_stale_pid() -> None:
    # Always remove the port file before restart so the watchdog does not
    # keep polling a stale port from the previous daemon instance.
    PORT_FILE.unlink(missing_ok=True)

    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            pid = None

        if pid is None or not _pid_alive(pid):
            PID_FILE.unlink(missing_ok=True)
            log.info("Cleared stale PID file (pid=%s)", pid)
        else:
            # Process is alive but not serving the port — kill it so the
            # new daemon can bind to the canonical port (8080) rather than
            # falling back to 8081+ and becoming invisible to the watchdog.
            log.warning(
                "PID %s is alive but port %s is not responding — killing stale process",
                pid, PORT,
            )
            _kill_process(pid)
            PID_FILE.unlink(missing_ok=True)
            log.info("Cleared PID file after killing stale process (pid=%s)", pid)
            # Brief pause to let the OS fully release the port before the new daemon starts
            time.sleep(2)


def _start_gateway() -> None:
    """Launch the Cato daemon as a detached background process.

    Prefer the compiled Cato backend so restart does not depend on the Python
    service runner. Fall back to the CLI only if the bundled binary is missing.
    """
    log.info("Starting cato gateway...")

    _REPO = Path(__file__).resolve().parent.parent
    cato_exe = _REPO / "desktop" / "src-tauri" / "target" / "release" / "binaries" / "cato.exe"

    try:
        if cato_exe.exists():
            cmd = [str(cato_exe), "start", "--channel", "webchat"]
            log.info("Using compiled backend: %s", " ".join(cmd))
        else:
            cmd = ["cato", "start", "--channel", "webchat"]
            log.info("Using cato CLI fallback (compiled backend not found)")

        if sys.platform == "win32":
            subprocess.Popen(
                cmd,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
                cwd=str(_REPO),
            )
        else:
            subprocess.Popen(
                cmd,
                start_new_session=True,
                close_fds=True,
                cwd=str(_REPO),
            )
        log.info("Daemon launched — waiting %ss for startup...", STARTUP_GRACE)
        time.sleep(STARTUP_GRACE)
    except FileNotFoundError as exc:
        log.error("Launch failed — executable not found: %s", exc)
    except Exception as exc:
        log.error("Failed to start gateway: %s", exc)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run() -> None:
    log.info("Watchdog started — monitoring %s:%s every %ss", HOST, PORT, POLL_INTERVAL)
    consecutive_failures = 0

    while True:
        if _gateway_alive():
            if consecutive_failures > 0:
                log.info("Gateway recovered after %s failed poll(s)", consecutive_failures)
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            log.warning("Gateway DOWN (failure #%s) — attempting restart", consecutive_failures)
            _clear_stale_pid()
            _start_gateway()

            if _gateway_alive():
                log.info("Gateway successfully restarted on %s:%s", HOST, PORT)
                consecutive_failures = 0
            else:
                log.error("Gateway still unreachable after restart attempt")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cato gateway watchdog")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override HTTP port to monitor (defaults to CATO_PORT env or 8080).",
    )
    args = parser.parse_args()

    if args.port is not None:
        PORT = args.port  # type: ignore[assignment]

    run()
