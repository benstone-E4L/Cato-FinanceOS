"""
Cato Windows Service — installs the Cato daemon as a persistent background service.

Install:  python cato_service.py install
Start:    python cato_service.py start
Stop:     python cato_service.py stop
Remove:   python cato_service.py remove
"""

import sys
import os
import threading
from pathlib import Path

import servicemanager
import win32event
import win32service
import win32serviceutil

# Repo root = directory containing this script (any Windows profile / clone path).
_REPO_ROOT = Path(__file__).resolve().parent
os.chdir(_REPO_ROOT)
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Vault password must be set in the environment before installing/starting the service.
# Example: set CATO_VAULT_PASSWORD=your-strong-password
_vault_pw = os.environ.get("CATO_VAULT_PASSWORD")
if not _vault_pw:
    print("[CATO] ERROR: CATO_VAULT_PASSWORD environment variable is not set.")
    print("[CATO] Set it before running: set CATO_VAULT_PASSWORD=<your-strong-password>")
    sys.exit(1)


class CatoDaemonService(win32serviceutil.ServiceFramework):
    _svc_name_ = "CatoDaemon"
    _svc_display_name_ = "Cato AI Daemon"
    _svc_description_ = (
        "Cato privacy-focused AI agent daemon — HTTP 8080, WS 8081, Telegram bot"
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._thread = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self._thread:
            self._thread.join(timeout=10)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self._thread = threading.Thread(target=self._run_daemon, daemon=True)
        self._thread.start()
        # Wait until stop signal
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)

    def _run_daemon(self):
        import asyncio
        import logging

        from cato.platform import get_data_dir

        log_path = get_data_dir() / "cato_service.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            filename=str(log_path),
        )

        from cato.vault import VaultError
        from cato.vault_bootstrap import bootstrap_launch_credentials

        try:
            _vault, _boot = bootstrap_launch_credentials(
                repo_root=_REPO_ROOT,
                require_password=True,
                load_dotenv=True,
            )
            logging.info(
                "Launch credentials: vault_present=%s unlocked=%s vault_keys=%d "
                "applied_from_vault=%s filled_from_dotenv=%s",
                _boot.vault_present,
                _boot.vault_unlocked,
                _boot.vault_keys_total,
                list(_boot.applied_from_vault),
                list(_boot.filled_from_dotenv),
            )
        except VaultError as exc:
            logging.error("Vault bootstrap failed: %s", exc)
            return

        from cato.cli import CatoConfig, BudgetManager, _run_daemon, _PID_FILE

        config = CatoConfig.load()
        budget = BudgetManager(session_cap=config.session_cap, monthly_cap=config.monthly_cap)

        if _PID_FILE.exists():
            _PID_FILE.unlink(missing_ok=True)
        import os as _os
        _PID_FILE.write_text(str(_os.getpid()))

        try:
            _run_daemon(config, "claude", "all")
        finally:
            _PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(CatoDaemonService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(CatoDaemonService)
