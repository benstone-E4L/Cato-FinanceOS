from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_desktop_versions_match_canonical_package_version() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "sync_version.py"), "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "PASS" in completed.stdout
