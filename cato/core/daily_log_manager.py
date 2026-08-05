"""
cato/core/daily_log_manager.py — Daily log file management.

Auto-creates YYYY-MM-DD.md files and manages log archival for long-term memory.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _workspace_dir() -> Path:
    """Get the workspace directory."""
    from cato.config import CatoConfig
    config = CatoConfig.load()
    if config.workspace_dir:
        return Path(config.workspace_dir).expanduser()
    return Path.home() / ".cato" / "workspace"


def get_todays_log_path() -> Path:
    """Get the path for today's log file (YYYY-MM-DD.md)."""
    workspace = _workspace_dir()
    workspace.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    return workspace / f"{today}.md"


def create_daily_log() -> Path:
    """
    Create today's daily log file if it doesn't exist.

    Returns the path to today's log file (created or existing).
    """
    log_path = get_todays_log_path()

    if log_path.exists():
        return log_path

    # Load previous day's log for context
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_path = log_path.parent / f"{yesterday}.md"

    previous_context = ""
    if yesterday_path.exists():
        try:
            previous_log = yesterday_path.read_text()
            # Extract incomplete tasks from previous log
            lines = previous_log.split("\n")
            incomplete_tasks = [line for line in lines if "- [ ]" in line]
            if incomplete_tasks:
                previous_context = "\n## Carried Over From Yesterday\n" + "\n".join(incomplete_tasks)
        except Exception as e:
            logger.warning(f"Could not read previous log: {e}")

    # Create today's log with template
    today_date = datetime.now().strftime("%Y-%m-%d")
    content = f"""# Daily Log - {today_date}

## Tasks
- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Notes
(Add notes and observations here)

## Completed
(Track what you completed today){previous_context}
"""

    log_path.write_text(content, encoding="utf-8")
    logger.info(f"Created daily log: {log_path}")
    return log_path


def get_daily_log_content(date: Optional[str] = None) -> Optional[str]:
    """
    Read a daily log file.

    Args:
        date: Date in YYYY-MM-DD format. If None, returns today's log.

    Returns:
        Log content or None if file doesn't exist.
    """
    workspace = _workspace_dir()

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    log_path = workspace / f"{date}.md"

    if not log_path.exists():
        return None

    try:
        return log_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Error reading daily log {date}: {e}")
        return None


def archive_old_logs(days_threshold: int = 30) -> int:
    """
    Compress logs older than days_threshold days.

    Args:
        days_threshold: Days before archival (default: 30)

    Returns:
        Number of logs archived.
    """
    import gzip
    import shutil

    workspace = _workspace_dir()
    archive_dir = workspace / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    cutoff_date = datetime.now() - timedelta(days=days_threshold)
    archived_count = 0

    for log_file in workspace.glob("????-??-??.md"):
        try:
            # Parse date from filename
            date_str = log_file.stem
            log_date = datetime.strptime(date_str, "%Y-%m-%d")

            if log_date < cutoff_date:
                # Compress and move to archive
                archive_path = archive_dir / f"{date_str}.md.gz"

                with open(log_file, "rb") as f_in:
                    with gzip.open(archive_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)

                log_file.unlink()  # Delete original
                logger.info(f"Archived log: {date_str} → {archive_path}")
                archived_count += 1
        except Exception as e:
            logger.warning(f"Error archiving log {log_file}: {e}")

    return archived_count


def list_recent_logs(days: int = 7) -> list[str]:
    """
    List recent log files.

    Args:
        days: Number of recent days to include

    Returns:
        List of log filenames in descending date order.
    """
    workspace = _workspace_dir()
    cutoff_date = datetime.now() - timedelta(days=days)

    logs = []
    for log_file in sorted(workspace.glob("????-??-??.md"), reverse=True):
        try:
            date_str = log_file.stem
            log_date = datetime.strptime(date_str, "%Y-%m-%d")

            if log_date >= cutoff_date:
                logs.append(date_str)
        except Exception:
            pass

    return logs
