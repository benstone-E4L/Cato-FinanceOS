# Cato — Exhaustive Validation Implementation Plan

Source requirement: `CatoGensisAgentBuild.md` (this repo root). Executed via
`continuous-build-verify` in LOOP-ONLY mode; one task below = one `ralph-wiggum-loop` build + one
`truth-fix-loop` audit before advancing.

Ground truth for every task below comes from a direct source-and-test read of the current tree
(2026-08-04), cross-referenced against `PROJECT_BLACKBOX_AUDIT.md` (2026-05-22) and
`CATO_ALEX_AUDIT.md`/`CATO_KRAKEN_VERDICT.md` (2026-07-10 — these two are stale/superseded in full,
since they audit the now-removed arbitrage subsystem). Findings already confirmed FIXED in current
source (C-1 vault password, C-4 Telegram token, C-3 duplicate route, H-3 pipeline path validation,
H-4 PTY/WS auth) are **not** repeated as tasks below — only what is still open gets a task.

**Non-negotiables carried into every task:**
- No agent/tool/policy claims success without ledger evidence, a real verification/read-back, or a
  passing test — matching the existing `INTENT`/`FAILED`/`INDETERMINATE` discipline already in
  `cato/audit/ledger.py`.
- A capability that cannot be made safe gets disabled, not shipped with a known bypass.
- Real financial/deployment/destructive actions are never exercised live by any test — mocks,
  fixtures, or the sandbox mode only.

---

## Phase A — Close the confirmed-still-open security/reliability gaps

- [ ] Harden the shell tool against the Windows `cmd.exe` full-string-execution path: `cato/tools/shell.py::_run_sandbox` always routes through `create_subprocess_shell` on `sys.platform == "win32"`, so `mode="gateway"` (the default, unapproved mode) executes the *entire* command string under shell interpretation once the first token passes the allowlist — and `powershell`/`pwsh`/`cmd`/`rm` are all still in `DEFAULT_ALLOWLIST` (`shell.py:73-79`). The remaining gate, `cato/safety.py::_classify_shell`, does a plain `cmd.lower().split()` keyword-membership check, which a quoted/escaped/concatenated destructive verb can plausibly dodge. Add adversarial fuzz coverage for `_classify_shell` against quoting/escaping/concatenation variants of destructive PowerShell verbs, then add a genuine end-to-end test of `ShellTool.execute()` (mode omitted / `"gateway"`) with a command containing a destructive verb via each dodge pattern found, and fix `_classify_shell` (or the allowlist) for every variant that gets through undetected.
- [ ] Build a real `ShellTool.execute()` end-to-end test suite (currently only `_classify_shell()` and a config default are tested, in 32 lines) — cover gateway-mode allowlist enforcement, cwd clamping/workspace scoping, full-mode execution-grant consumption (single-use, cannot be replayed), and stdout/stderr truncation behavior.
- [ ] Fix the DB path split-brain: `cato/memory/contradiction_detector.py:93`, `cato/memory/decision_memory.py:64`, and `cato/monitoring/anomaly_detector.py:92` each default to a different path than `cato/ui/server.py`'s actual instantiation (`get_data_dir()/"default"/...` vs the modules' own bare `get_data_dir()/...` or `Path.home()/".cato"/...` defaults). Make each module's own default match what `server.py` actually passes, add a test asserting `server.py`'s instantiation path equals each module's own default (so a future refactor can't silently re-diverge them), and confirm no diagnostics endpoint is currently reading from the wrong (empty) file.
- [ ] Make CI run automatically: `.github/workflows/python-verify.yml` runs the full `pytest tests/ -x -q --tb=short` suite but only on `workflow_dispatch` — add `push`/`pull_request` triggers (scoped to relevant branches) so the ~1900-test suite actually gates merges instead of requiring a human to remember to fire it manually.
- [ ] Add a concurrent-redemption race test for `OutboundApprovalStore.consume()` — the code defends the single-use guarantee via `cur.rowcount == 0` → `TicketError`, but no test exercises two simultaneous `execute_approved_tool()` calls racing to consume the same `approval_id`. Add the test; fix if it reveals a real race.
- [ ] Address `SchedulerDaemon`'s missed-firing-on-crash gap (`cato/core/schedule_manager.py`): in-progress state is tracked only in-memory (`self._in_progress`), and `croniter(...).get_next()` always computes forward from current wall-clock time on restart with no catch-up/backfill of a tick missed during a crash window. Either implement a reconciliation/backfill path, or explicitly decide this is accepted behavior and add a test that documents and pins it (so it can never regress into an even worse silent-drop with no evidence trail) — do not leave it undocumented and untested either way.
- [ ] Add an SSRF-inheritance test for `conduit_crawl.py`: it has no direct IP-safety check of its own and relies entirely on delegating navigation to `browser_tool`'s guard. Prove (with a test, not a read of the code) that this delegation cannot be bypassed via a redirect chain, a raw-`urllib` side-channel (e.g. a `robots.txt` fetch), or any crawl target that never actually calls `browser_tool.navigate`. Fix any bypass found.
- [ ] Expand `cato/vault.py` test coverage beyond the current 48-line happy-path suite: add tests for corrupted-file recovery, a wrong Argon2id parameter set (regression-proofing time_cost/memory_cost/parallelism), and the canary-leak-detection path (`create_canary`/`check_canary_used`), which currently has no dedicated test at all.
- [ ] Add Telegram-adapter unit tests isolated from the WS/gateway integration tests: the long-poll loop itself, and send-path HTTP error handling, independent of `test_telegram_security.py`'s existing scope (verify what that file actually covers first — do not assume it already covers this).
- [ ] Add HTTP auth-middleware rejection tests distinct from `test_auth_security.py`'s token-*logic* unit tests: a real request to a protected route with a missing or wrong `X-Cato-Token` must return 401, tested at the HTTP-middleware layer itself (via `test_ui_server_runtime_health.py`/`test_dashboard_token_and_host.py` or a new file), not only asserted at the token-checker function level.
- [ ] Add a cross-tool consistency test asserting `cato/safety.py`'s tool-tier table and `cato/core/approval_policy.py`'s `_BUILTIN_TOOLS` table stay in sync (both docstrings already say they must be hand-kept in agreement, with no automated check today) — a tool present in one table and missing from the other should fail the test, not ship silently.

## Phase B — LangSmith trajectory-evaluation harness for the complete Cato path

- [ ] Build the LangSmith target adapter that invokes the real Cato daemon (via its actual API/CLI, not an in-process shortcut) and returns both the user-facing result and the full structured execution trajectory. Use `RoutingDecision.log_record()`/the `routing_log` persistence layer as the model-choice trace source, `LedgerQuery.by_session()`/`replay_session()` (`cato/audit/ledger.py:1132-1149`) as the ground-truth action trajectory (already redacted and ordered), and `cato/tools/genesis.py`'s AP2 envelope/response pair as the Cato→Genesis boundary snapshot — these are the natural integration points; there is currently zero LangSmith code anywhere in this repo, confirmed by a repo-wide search.
- [ ] Build deterministic trajectory evaluators that fail when: the wrong skill loads, the wrong model is selected, the wrong Genesis agent is selected, an unknown tool does not fail closed, a tool bypasses the approval-policy gate, approval is missing/expired/replayed/altered, intent and executed payload differ, a protected operation lacks ledger evidence, a ledger failure does not stop execution, Genesis runs without an allowlisted identity, Genesis claims success without completion evidence, Cato retries a non-idempotent action, a restart produces duplicate execution, or secrets enter prompts/traces/logs/approvals.
- [ ] Test the harness against ordinary, ambiguous, malicious, and failure-producing requests, and build the chaos-test suite: Genesis endpoint unavailable, Anthropic unavailable, invalid credentials, approval interface unavailable, ledger unavailable, process crash before execution, process crash after execution but before confirmation, network timeout, corrupt state, wrong Windows account, missing environment variables, budget exceeded, model-router failure. Each chaos scenario must assert Cato's actual documented behavior for that failure (e.g. INDETERMINATE not FAILED for an ambiguous-outcome crash) rather than merely that it "doesn't crash."

## Phase C — Evidence and reporting

- [ ] Generate `docs/validation/coverage-report.json` and `docs/validation/known-limitations.json` for the Cato side: which subsystems (model routing, skill routing, agent routing, policy engine, approvals, tool dispatch, ledger, recovery, security, API/CLI/daemon) are fully tested vs. partially tested, every fix applied in Phase A with its regression test, and every remaining known gap with a reason — ready to feed the joint Part 7 independent-validation handoff once Genesis's side is also GREEN.
