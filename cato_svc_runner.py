"""Minimal runner script for the Cato daemon — used by Task Scheduler / NSSM."""
import logging
import os
import sys
from pathlib import Path

# Repo root = directory containing this script (any Windows profile / clone).
_REPO_ROOT = Path(__file__).resolve().parent
os.chdir(_REPO_ROOT)
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "cato"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DAEMON_LOG = _DATA_DIR / "daemon_runner.log"

# Hidden/background launches on Windows can have no real stdout/stderr.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # type: ignore[assignment]
elif getattr(sys.stdout, "closed", False):
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # type: ignore[assignment]

if sys.stderr is None:
    sys.stderr = open(_DAEMON_LOG, "a", encoding="utf-8")  # type: ignore[assignment]
elif getattr(sys.stderr, "closed", False):
    sys.stderr = open(_DAEMON_LOG, "a", encoding="utf-8")  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(_DAEMON_LOG, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# Operator credentials are resolved from the encrypted vault only.
from cato.vault import VaultError
from cato.vault_bootstrap import bootstrap_launch_credentials

try:
    _vault, _boot = bootstrap_launch_credentials(
        repo_root=_REPO_ROOT,
        require_password=True,
        load_dotenv=False,
    )
    logging.info(
        "Launch credentials: vault_present=%s unlocked=%s vault_keys=%d",
        _boot.vault_present,
        _boot.vault_unlocked,
        _boot.vault_keys_total,
    )
except VaultError as _exc:
    logging.error("Vault bootstrap failed: %s", _exc)
    print(f"[CATO] ERROR: vault bootstrap failed: {_exc}")
    sys.exit(1)

from cato.cli import CatoConfig, BudgetManager, _CATO_DIR, _run_daemon, _PID_FILE, _read_live_pid

config = CatoConfig.load()
budget = BudgetManager(session_cap=config.session_cap, monthly_cap=config.monthly_cap, daily_cap=config.daily_cap)

# BH-010 — Propagate config.workspace_dir to the file/shell/python tools via
# an env var.  The tools resolve their workspace root at call time from
# `CATO_WORKSPACE_DIR` if set (see cato/tools/file.py etc).  Without this
# bridge the tools fall back to ~/.cato/workspace even when config points
# elsewhere, which silently breaks the workspace_dir setting.
if getattr(config, "workspace_dir", None):
    os.environ["CATO_WORKSPACE_DIR"] = str(config.workspace_dir)

live_pid = _read_live_pid()
if live_pid is not None and live_pid != os.getpid():
    logging.info("Cato daemon already running; runner exiting.")
    sys.exit(0)
_PID_FILE.write_text(str(os.getpid()))

try:
    _run_daemon(config, "claude", "all")
finally:
    _PID_FILE.unlink(missing_ok=True)
