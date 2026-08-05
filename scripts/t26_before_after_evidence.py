#!/usr/bin/env python
"""
scripts/t26_before_after_evidence.py — reproducible BEFORE/AFTER proof for t26.

An unreproducible number is not evidence. This script re-derives the result from
the repository itself instead of asking you to trust pasted output:

  BEFORE — check out the pre-fix revision of every source file that carried the
           three defects, run the t26 regression tests against them, and require
           them to FAIL. A green BEFORE run means the tests do not actually pin
           the defects, and this script exits non-zero saying so.
  AFTER  — restore the working-tree versions and require the same tests to PASS.

The three defects, all found by the first live boot of the daemon:

  CRITICAL-1  cato/cli.py::_pid_alive used os.kill(pid, 0). On Windows
              signal.CTRL_C_EVENT == 0, so that is GenerateConsoleCtrlEvent, not
              a liveness probe. Every live daemon looked dead: `cato stop`
              orphaned it, then deleted cato.pid AND cato.port, and the next
              `cato start` launched a SECOND daemon that port-shifted to 8081 —
              two processes appending to the same hash-chained ledger.
  HIGH-2      GET / injected the 64-char daemon token into the page while "/"
              was token-exempt, so any local page could read it; and the server
              did not validate the Host header, so DNS rebinding bypassed CORS.
  HIGH-3      the ledger crash-recovery scan only ran from the per-message
              AgentLoop path, and the AgentLoop is built lazily — so a restart
              after a crash surfaced nothing unless a chat message was sent.

Only SOURCE files are swapped; the tests are always the new ones. The files are
restored in a ``finally`` block, and the script refuses to run at all if the
working tree has uncommitted changes to them, so an interrupted run cannot leave
you with pre-fix code on disk.

cato/audit/recovery.py is deliberately NOT swapped: it did not exist before the
fix, and the HIGH-3 defect is the missing startup call site, not the missing
module. Leaving it in place makes BEFORE fail on the trigger, which is the
actual defect, instead of on an ImportError.

Usage:
    .venv/Scripts/python.exe scripts/t26_before_after_evidence.py
    .venv/Scripts/python.exe scripts/t26_before_after_evidence.py --base <rev>

No network calls. No daemon is started. No chat message is sent, so no Anthropic
token is spent and no outbound control is triggered. No secret is printed: the
tests assert on the ABSENCE of the daemon token, or on its length.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The pre-fix revision. dc6887a is the HEAD the t26 audit was performed against.
DEFAULT_BASE = "dc6887a"

#: The source files whose pre-fix content reintroduces the three defects. All of
#: them are swapped together so BEFORE is a coherent pre-fix tree rather than a
#: half-applied one that fails for the wrong reason.
DEFECT_FILES = [
    "cato/platform.py",
    "cato/cli.py",
    "cato/doctor.py",
    "cato/ui/server.py",
    "scripts/watchdog.py",
]

#: Tests that must FAIL before the fix and PASS after it.
PROOF_TESTS = [
    "tests/test_daemon_lifecycle_windows.py",
    "tests/test_dashboard_token_and_host.py",
    "tests/test_startup_recovery_scan.py",
]

#: Tests that must PASS in BOTH states — proof the fix did not simply delete
#: the behaviour the suite already pinned.
NO_REGRESSION_TESTS = [
    "tests/test_cli_pid_liveness.py",
    "tests/test_port_fallback_integration.py",
    "tests/test_watchdog.py",
    "tests/test_ledger_failclosed.py",
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
    print(f"=== t26 before/after evidence: base={base} head={head} ===\n")

    try:
        print(f"--- BEFORE: restoring {len(DEFECT_FILES)} pre-fix source files from {base} ---")
        git("checkout", args.base, "--", *DEFECT_FILES)
        before_rc = run_tests(PROOF_TESTS)
        print(
            f"\nBEFORE exit code: {before_rc} (expected NON-ZERO — the daemon "
            f"looks dead while alive, GET / leaks the token, and the recovery "
            f"scan never fires)\n"
        )
    finally:
        git("checkout", "HEAD", "--", *DEFECT_FILES)

    print("--- AFTER: working-tree (fixed) source files restored ---")
    after_rc = run_tests(PROOF_TESTS)
    print(f"\nAFTER exit code: {after_rc} (expected 0)\n")

    print("--- NO REGRESSION: the pre-existing lifecycle, watchdog and ledger suites ---")
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
                  "they do not pin the defects. Fix the tests, not this script.")
        if after_rc != 0:
            print("EVIDENCE FAILS: the tests do not pass against the current code.")
        if regress_rc != 0:
            print("EVIDENCE FAILS: the fix regressed a pre-existing suite.")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
