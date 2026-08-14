"""
cato/platform.py — Windows compatibility layer for CATO.

Provides cross-platform path handling, safe Unicode printing,
signal handler setup, and the canonical data directory.

Usage::

    from cato.platform import IS_WINDOWS, safe_path, safe_print, get_data_dir
    from cato.platform import setup_signal_handlers

    data_dir = get_data_dir()          # %APPDATA%/cato on Windows, ~/.cato on POSIX
    p = safe_path("~/some/path")       # always a resolved Path
    safe_print("Hello \u2713")         # safe on cp1252 terminals
    setup_signal_handlers(my_shutdown) # SIGINT + Windows SIGBREAK, SIGTERM on POSIX
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

IS_WINDOWS: bool = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------

def get_data_dir() -> Path:
    """
    Return the canonical Cato data directory.

    - Windows: %APPDATA%/cato  (e.g. C:/Users/Alice/AppData/Roaming/cato)
    - POSIX:   ~/.cato

    The directory is created if it does not exist.
    """
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata) / "cato"
        else:
            # Fallback if APPDATA is somehow unset
            base = Path.home() / "AppData" / "Roaming" / "cato"
    else:
        base = Path.home() / ".cato"

    base.mkdir(parents=True, exist_ok=True)
    return base


def get_legacy_data_dirs() -> tuple[Path, ...]:
    """Return existing non-canonical Cato roots for read-only discovery.

    This deliberately performs no copying, moving, merging, or deletion.  It
    gives doctor/migration tooling a safe way to report a legacy Windows
    ``~/.cato`` tree without letting runtime components silently write there.
    """
    canonical = get_data_dir().resolve()
    candidates = (Path.home() / ".cato",)
    return tuple(
        path for path in candidates
        if path.exists() and path.resolve() != canonical
    )


def _readonly_table_count(db_path: Path, table: str) -> int:
    """Row count for *table*, or 0. Opens read-only; never creates or alters.

    Discovery must not be able to damage the thing it discovered — the legacy
    root may hold the only copy of some records.
    """
    import sqlite3

    try:
        conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    except Exception:
        return 0
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
        ).fetchone()
        if not exists:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception:
        return 0
    finally:
        conn.close()


def get_legacy_data_inventory() -> tuple[dict[str, object], ...]:
    """Inventory meaningful legacy state without reading content or mutating it."""
    inventories: list[dict[str, object]] = []
    for root in get_legacy_data_dirs():
        present: list[str] = []
        counts: dict[str, int] = {}
        # store.key / conduit_identity.key are key material. A stranded copy in
        # a non-canonical root is the split-brain the audit flagged: keys and
        # the records they protect sitting in different trust domains. Names
        # only — never read or move key bytes from here.
        for filename in (
            "config.yaml", "cato.db", "vault.enc",
            "store.key", "conduit_identity.key",
        ):
            if (root / filename).is_file():
                present.append(filename)
        # A stranded cato.db is the one entry whose MERE PRESENCE understates
        # the problem. On the audited machine `~/.cato/cato.db` holds 11
        # audit_log rows on a NEWER schema (inputs_digest / outputs_digest /
        # schema_version) than the canonical %APPDATA% audit_log, which has
        # none of those columns and 0 rows. Every verification surface —
        # `cato verify-ledger`, `cato audit`, `cato receipt`, `cato replay`,
        # GET /api/audit/* — reads get_data_dir()/cato.db only, so those rows
        # are invisible to all of them and nothing raised an alarm.
        # Reporting "cato.db exists" is not enough; report what is inside it.
        # Strictly read-only (mode=ro), counts only, never content.
        legacy_db = root / "cato.db"
        if legacy_db.is_file():
            for table in ("ledger_records", "audit_log"):
                count = _readonly_table_count(legacy_db, table)
                if count:
                    label = f"cato.db:{table}"
                    present.append(label)
                    counts[label] = count
        for dirname in ("skills", "agents", "workspace"):
            path = root / dirname
            try:
                count = sum(1 for _ in path.iterdir()) if path.is_dir() else 0
            except OSError:
                count = -1
            if count != 0:
                present.append(dirname)
                counts[dirname] = count
        if present:
            inventories.append(
                {"root": str(root), "present": tuple(present), "counts": counts}
            )
    return tuple(inventories)


# ---------------------------------------------------------------------------
# Path normalisation
# ---------------------------------------------------------------------------

def safe_path(p: "str | Path") -> Path:
    """
    Normalize any path string or Path to a valid, expanded, resolved Path.

    Handles:
    - ~ expansion
    - Backslash / forward-slash normalisation on Windows
    - Relative path resolution against cwd
    """
    path = Path(str(p))
    # Expand ~ and ~user
    path = path.expanduser()
    # On Windows, Path handles backslash natively; on POSIX we normalise
    # any accidental backslashes coming from config files written on Windows.
    if not IS_WINDOWS:
        path = Path(str(path).replace("\\", "/"))
    return path.resolve()


# ---------------------------------------------------------------------------
# Safe Unicode printing
# ---------------------------------------------------------------------------

def safe_print(text: str) -> None:
    """
    Print *text* to stdout with Unicode fallback for Windows cp1252 terminals.

    On cp1252 terminals (common on Windows), characters outside the
    Windows-1252 range are replaced with '?' rather than crashing.
    On all other platforms this is equivalent to print().
    """
    if IS_WINDOWS:
        try:
            encoding = sys.stdout.encoding or "cp1252"
            encoded = text.encode(encoding, errors="replace").decode(encoding)
            print(encoded)
        except (UnicodeEncodeError, LookupError):
            # Last-resort ASCII fallback
            print(text.encode("ascii", errors="replace").decode("ascii"))
    else:
        print(text)


# ---------------------------------------------------------------------------
# Process liveness / termination
# ---------------------------------------------------------------------------

#: GetExitCodeProcess returns this while the process is still running.
_WIN_STILL_ACTIVE = 259
#: PROCESS_QUERY_LIMITED_INFORMATION — enough to call GetExitCodeProcess and
#: obtainable for processes owned by other users at the same integrity level.
_WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WIN_ERROR_ACCESS_DENIED = 5
_WIN_ERROR_INVALID_PARAMETER = 87


def _win_pid_alive(pid: int) -> bool:
    """Windows liveness probe via OpenProcess + GetExitCodeProcess.

    ``os.kill(pid, 0)`` cannot be used here: on Windows ``signal.CTRL_C_EVENT``
    is 0, so CPython routes signal 0 to ``GenerateConsoleCtrlEvent``, which
    needs a console *process-group* id and fails with ERROR_INVALID_PARAMETER
    (87) for an ordinary pid. The resulting OSError made every live daemon look
    dead.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        _WIN_PROCESS_QUERY_LIMITED_INFORMATION, False, wintypes.DWORD(pid)
    )
    if not handle:
        err = ctypes.get_last_error()
        # ERROR_ACCESS_DENIED means the process exists but is not ours to
        # inspect — fail closed and call it alive. Anything else (notably
        # ERROR_INVALID_PARAMETER for an unknown pid) means it is gone.
        return err == _WIN_ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True  # fail closed: we hold a handle, so something is there
        return code.value == _WIN_STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _posix_is_zombie(pid: int) -> bool:
    """True when */proc/<pid>* exists but the process is a zombie (state ``Z``).

    Zombies still answer ``os.kill(pid, 0)``, so a stop that only checks that
    probe never reports success after SIGKILL until some other process reaps
    the child. For daemon lifecycle that is a false "still running".
    """
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            # Format: pid (comm) state ... — comm may contain spaces/parens.
            data = fh.read()
    except (FileNotFoundError, PermissionError, OSError):
        return False
    rparen = data.rfind(")")
    if rparen < 0 or rparen + 2 >= len(data):
        return False
    state = data[rparen + 2 : rparen + 3]
    return state == "Z"


def pid_alive(pid: int) -> bool:
    """Return True when *pid* currently refers to a live process.

    Fails closed: when liveness cannot be determined the pid is reported alive,
    because acting on a false "dead" answer is what lets a second daemon start
    against the same hash-chained ledger.

    POSIX zombies are treated as **not** alive — they cannot run code, and
    treating them as live breaks ``terminate_pid`` / ``cato stop`` after a
    successful SIGKILL when the caller is not the parent that will wait().
    """
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            return _win_pid_alive(pid)
        except OSError as exc:  # pragma: no cover - ctypes/DLL loading failure
            logger.warning("Windows liveness probe failed for pid %s: %s", pid, exc)
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    if _posix_is_zombie(pid):
        return False
    return True


def terminate_pid(pid: int, *, timeout: float = 10.0, poll_interval: float = 0.2) -> bool:
    """Terminate *pid* and wait for it to actually exit.

    Returns True when the process is gone by the deadline. SIGTERM is not
    deliverable on Windows, so the Windows path uses ``taskkill``: a graceful
    request first, escalating to ``/F`` when the process ignores it.
    """
    if pid <= 0:
        return False
    if not pid_alive(pid):
        return True

    deadline = time.monotonic() + max(timeout, 0.0)
    graceful_deadline = time.monotonic() + max(timeout, 0.0) / 2

    if IS_WINDOWS:
        _run_taskkill(pid, force=False)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except OSError as exc:
            logger.warning("SIGTERM to pid %s failed: %s", pid, exc)

    escalated = False
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        if not escalated and time.monotonic() >= graceful_deadline:
            escalated = True
            if IS_WINDOWS:
                _run_taskkill(pid, force=True)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
        time.sleep(poll_interval)

    return not pid_alive(pid)


def _run_taskkill(pid: int, *, force: bool) -> None:
    """Invoke taskkill for *pid*, tree-killing children with ``/T``."""
    cmd = ["taskkill", "/T", "/PID", str(pid)]
    if force:
        cmd.insert(1, "/F")
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("taskkill %s for pid %s failed: %s", "/F" if force else "", pid, exc)


# ---------------------------------------------------------------------------
# Signal handlers
# ---------------------------------------------------------------------------

def setup_signal_handlers(shutdown_fn: Callable[[], None]) -> None:
    """
    Register *shutdown_fn* as the handler for graceful shutdown signals.

    - SIGINT   (Ctrl-C)     — registered on all platforms.
    - SIGBREAK (Ctrl-Break) — registered on Windows for process-group shutdown.
    - SIGTERM              — registered on POSIX only.
    - atexit               — registered on all platforms as a final safety net.

    The shutdown function is called at most once (idempotent guard).
    """
    _called: list[bool] = [False]

    def _handler(signum: int, frame: object) -> None:  # noqa: ARG001
        if not _called[0]:
            _called[0] = True
            logger.info("Signal %s received — initiating shutdown", signum)
            try:
                shutdown_fn()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error during signal shutdown: %s", exc)
        sys.exit(0)

    def _atexit_handler() -> None:
        if not _called[0]:
            _called[0] = True
            try:
                shutdown_fn()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error during atexit shutdown: %s", exc)

    # SIGINT is available everywhere
    signal.signal(signal.SIGINT, _handler)

    if IS_WINDOWS:
        # CREATE_NEW_PROCESS_GROUP ignores Ctrl-C by default, while Ctrl-Break
        # is deliverable to that exact group. Register it so asyncio.run can
        # unwind pending tasks and execute daemon-owned cleanup blocks.
        sigbreak = getattr(signal, "SIGBREAK", None)
        if sigbreak is not None:
            try:
                signal.signal(sigbreak, _handler)
            except (OSError, ValueError) as exc:
                logger.debug("Could not register SIGBREAK: %s", exc)
    else:
        # SIGTERM is POSIX-only.
        try:
            signal.signal(signal.SIGTERM, _handler)
        except (OSError, ValueError) as exc:
            logger.debug("Could not register SIGTERM: %s", exc)

    atexit.register(_atexit_handler)
    logger.debug(
        "Signal handlers registered (SIGINT%s + atexit)",
        "+SIGBREAK" if IS_WINDOWS else "+SIGTERM",
    )
