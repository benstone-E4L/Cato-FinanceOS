#!/usr/bin/env python
"""
scripts/t20_before_after_evidence.py — reproducible BEFORE/AFTER proof for t20.

An unreproducible number is not evidence. This script re-derives the result from
the repository itself instead of asking you to trust pasted output:

  BEFORE — check out the pre-fix revision of every source file that carried the
           Clawflows step bypass, run the t20 regression tests against them, and
           require them to FAIL. A green BEFORE run means the tests do not
           actually pin the defect, and this script exits non-zero saying so.
  AFTER  — restore the working-tree versions and require the same tests to PASS.

Only SOURCE files are swapped; the tests are always the new ones. The files are
restored in a ``finally`` block, and the script refuses to run at all if the
working tree has uncommitted changes to them, so an interrupted run cannot leave
you with pre-fix code on disk.

Usage:
    .venv/Scripts/python.exe scripts/t20_before_after_evidence.py
    .venv/Scripts/python.exe scripts/t20_before_after_evidence.py --base <rev>

No network calls. No daemon. No real shell command, file write, email or Genesis
dispatch happens through a flow — the tests fail the run if one ever does.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The pre-fix revision. 4f6c992 is the HEAD the t20 audit was performed against.
DEFAULT_BASE = "4f6c992"

#: The source files whose pre-fix content reintroduces the bypass. All of them
#: are swapped together so BEFORE is a coherent pre-fix tree rather than a
#: half-applied one that fails for the wrong reason.
DEFECT_FILES = [
    "cato/orchestrator/clawflows.py",
    "cato/agent_loop.py",
    "cato/tools/__init__.py",
    "cato/gateway.py",
    "cato/core/scheduled_dispatch.py",
    "cato/ui/server.py",
    "cato/cli.py",
    "cato/replay.py",
]

#: Tests that must FAIL before the fix and PASS after it.
PROOF_TESTS = [
    "tests/test_flow_engine_gates.py",
    "tests/test_flow_routes_gates.py",
    "tests/test_replay_live_gates.py",
]

#: Tests that must PASS in BOTH states — proof the fix did not simply delete
#: the behaviour the suite already pinned.
NO_REGRESSION_TESTS = [
    "tests/test_clawflows.py",
    "tests/test_scheduled_dispatch_gates.py",
]


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def run_tests(paths: list[str]) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", *paths],
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
    print(f"=== t20 before/after evidence: base={base} head={head} ===\n")

    try:
        print(f"--- BEFORE: restoring {len(DEFECT_FILES)} pre-fix source files from {base} ---")
        git("checkout", args.base, "--", *DEFECT_FILES)
        before_rc = run_tests(PROOF_TESTS)
        print(f"\nBEFORE exit code: {before_rc} (expected NON-ZERO — the bypass is live)\n")
    finally:
        git("checkout", "HEAD", "--", *DEFECT_FILES)

    print("--- AFTER: working-tree (fixed) source files restored ---")
    after_rc = run_tests(PROOF_TESTS)
    print(f"\nAFTER exit code: {after_rc} (expected 0)\n")

    print("--- NO REGRESSION: the pre-existing flow and scheduler suites ---")
    regress_rc = run_tests(NO_REGRESSION_TESTS)
    print(f"\nNO-REGRESSION exit code: {regress_rc} (expected 0)\n")

    ok = before_rc != 0 and after_rc == 0 and regress_rc == 0
    print("=" * 70)
    if ok:
        print("EVIDENCE HOLDS: the regression tests fail on the pre-fix code, pass "
              "on the fixed code, and the pre-existing suites still pass.")
    else:
        if before_rc == 0:
            print("EVIDENCE FAILS: the tests PASSED against the pre-fix code, so "
                  "they do not pin the defect. Fix the tests, not this script.")
        if after_rc != 0:
            print("EVIDENCE FAILS: the tests do not pass against the current code.")
        if regress_rc != 0:
            print("EVIDENCE FAILS: the fix regressed a pre-existing suite.")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
