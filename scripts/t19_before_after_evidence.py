#!/usr/bin/env python
"""
scripts/t19_before_after_evidence.py — reproducible BEFORE/AFTER proof for t19.

An unreproducible number is not evidence. This script re-derives the result
from the repository itself instead of asking you to trust pasted output:

  BEFORE — check out the pre-fix revision of the three files that carried the
           defect, run the t19 regression tests against them, and require them
           to FAIL. A green BEFORE run means the tests do not actually pin the
           defect, and this script exits non-zero saying so.
  AFTER  — restore the working-tree versions and require the same tests to PASS.

The files are restored in a ``finally`` block, and the script refuses to run at
all if the working tree has uncommitted changes to them, so an interrupted run
cannot leave you with pre-fix code on disk.

Usage:
    .venv/Scripts/python.exe scripts/t19_before_after_evidence.py
    .venv/Scripts/python.exe scripts/t19_before_after_evidence.py --base <rev>

No network calls. No daemon. No real shell command is executed through the
scheduler — the tests fail the run if one ever is.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The pre-fix revision. bb0bc95 is the HEAD the t19 audit was performed against.
DEFAULT_BASE = "bb0bc95"

#: The files whose pre-fix content reintroduces the bypass.
#:
#: t22 NOTE: ``cato/adapters/telegram.py`` was a third defect file here — its
#: /arbitrage command had a fail-OPEN operator allowlist. That whole command
#: surface was deleted with the arbitrage subsystem in t22, so there is no
#: longer a working-tree version of it to compare against, and its proof test
#: (tests/test_arbitrage_integration.py::test_arbitrage_command_empty_allowlist_denies)
#: went with it. The remaining two files still carry the scheduler half of the
#: t19 defect and are still proven here. The equivalent fail-open-on-empty
#: allowlist fix is still pinned for the surfaces that survived — see
#: cato/tools/genesis.py and cato/api/ws_auth.py.
DEFECT_FILES = [
    "cato/core/scheduled_dispatch.py",
    "cato/tools/shell.py",
]

#: Tests that must FAIL before the fix and PASS after it.
PROOF_TESTS = [
    "tests/test_scheduled_dispatch_gates.py",
]


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def run_tests() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", *PROOF_TESTS],
        cwd=REPO,
    )
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE, help="pre-fix revision")
    args = ap.parse_args()

    dirty = git("status", "--porcelain", "--", *DEFECT_FILES)
    if dirty:
        print(
            "REFUSING TO RUN: uncommitted changes in the files this script "
            f"overwrites and restores:\n{dirty}\n"
            "Commit or stash them first — otherwise an interrupted run loses them.",
            file=sys.stderr,
        )
        return 2

    base = git("rev-parse", "--short", args.base)
    head = git("rev-parse", "--short", "HEAD")
    print(f"=== t19 before/after evidence: base={base} head={head} ===\n")

    try:
        print(f"--- BEFORE: restoring pre-fix {', '.join(DEFECT_FILES)} from {base} ---")
        git("checkout", args.base, "--", *DEFECT_FILES)
        before_rc = run_tests()
        print(f"\nBEFORE exit code: {before_rc} (expected NON-ZERO — the defect is live)\n")
    finally:
        git("checkout", "HEAD", "--", *DEFECT_FILES)

    print("--- AFTER: working-tree (fixed) files restored ---")
    after_rc = run_tests()
    print(f"\nAFTER exit code: {after_rc} (expected 0)\n")

    ok = before_rc != 0 and after_rc == 0
    print("=" * 70)
    if ok:
        print("EVIDENCE HOLDS: the regression tests fail on the pre-fix code and "
              "pass on the fixed code.")
    else:
        if before_rc == 0:
            print("EVIDENCE FAILS: the tests PASSED against the pre-fix code, so "
                  "they do not pin the defect. Fix the tests, not this script.")
        if after_rc != 0:
            print("EVIDENCE FAILS: the tests do not pass against the current code.")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
