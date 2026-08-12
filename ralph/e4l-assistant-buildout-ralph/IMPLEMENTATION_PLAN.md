# IMPLEMENTATION_PLAN.md

## Chunk Order

1. CHUNK_1_HYGIENE — repo hygiene: CI branch scope, dead-code removal, unused-dependency check, WhatsApp removal.
2. CHUNK_2_VAULT — encrypted credential vault stand-up + live routed model-call proof (requires Ben's manual token/password rotation first).
3. CHUNK_3_VAULT_INDEX — ingest the E4L vault into Cato's memory engine per the Retrieval Contract.
4. CHUNK_4_ASK_E4L — wire Ask-E4L chat to the Retrieval Contract and pass the 10-question Phoenix eval bar.
5. CHUNK_5_FINANCE_VIEW — read-only Finance nav view consuming FinanceOS's control-room API, with stale-state fallback.
6. CHUNK_6_WORK_INBOX — Work Inbox as default landing page + reorganized 9-item nav.

---

## Chunk 1: CHUNK_1_HYGIENE

### Tasks (in order)

1. `.github/workflows/ci.yml` — add `main` to both the `push.branches` and `pull_request.branches`
   lists, keeping the existing `e4l-runtime-hardening` entry (do not remove it).
2. Delete `Genesis_meta_agent.py` from the repo root. Grep-confirm zero remaining Python/test
   references to `Genesis_meta_agent` anywhere in `cato/` or `tests/` before deleting (docs under
   the ~50 stale root-level planning-doc set, e.g. `docs/genesis_marketplace_plan.md`, are prose
   mentions only and are out of scope — do not edit them).
3. `mcp>=1.22.0` dependency in `pyproject.toml`: grep-confirm real usage before touching it. If
   real (non-dead) usage is found — do NOT blindly delete per the spec's own failure-case
   instruction; document the finding in `.ralph/guardrails.md` and treat this specific sub-task as
   BLOCKED rather than guessing at a packaging redesign. Do not silently re-add/keep it disguised
   as something else and do not silently delete a working feature either.
4. Remove WhatsApp support entirely (Ben's decision, guardrails.md "RESOLVED: No WhatsApp"):
   - Delete `cato/adapters/whatsapp.py`, `cato/channels/whatsapp.py`,
     `cato/api/whatsapp_routes.py`, `tests/test_whatsapp.py`.
   - Grep-confirm and remove every call site (imports, registrations, routes, config fields, UI
     panels, doctor checks, integration-registry catalog entries) across `cato/cli.py`,
     `cato/ui/server.py`, `cato/ui/dashboard.html`, `cato/ui/settings_panel.html`,
     `cato/api/routes.py`, `cato/api/integration_routes.py`, `cato/integrations/registry.py`,
     `cato/gateway.py`, `cato/adapters/__init__.py`, `cato/config.py`, `cato/doctor.py`,
     `cato/vault_bootstrap.py`, `cato/agent_loop.py`, `cato/mcp/runtime.py` — do not assume this
     list is exhaustive without grepping first.
   - Update the affected tests (`tests/test_integrations.py`, `tests/test_start_channel.py`,
     `tests/test_port_fallback_integration.py`) so the suite reflects "no WhatsApp" rather than
     failing or silently asserting a now-removed capability.
   - Remove `twilio` from `pyproject.toml` only if it is currently listed there (grep-confirm
     first — it may not be a declared dependency at all).
5. Run the validation gate (`ruff check cato/ && pytest`) and fix any regressions caused by the
   above deletions until it is clean. Do not fabricate a passing result.

### Validation
- Command: `ruff check cato/ && pytest`
- Expected: exit 0, zero ERROR/FAIL/Traceback lines in output, all tests green (task 3's `mcp`
  sub-item may remain a documented BLOCKED finding rather than a code change — that does not
  count as a validation failure).

### Manual Follow-up (cannot be produced by this workstream)
- "A trivial commit pushed to `main` produces a visible GitHub Actions run" — requires actual
  push access to `origin/main` and is gated by this repo's own audit pipeline
  (`/HKO-truth-audit` → `Kraken`, both must approve before any `git push`). Document as a manual
  follow-up rather than fabricating a GitHub Actions run.

### Promise
<promise>CHUNK COMPLETE: CHUNK_1_HYGIENE</promise>

---

## Chunk 2: CHUNK_2_VAULT

### Tasks (in order)

1. **Manual operator step — do not perform, only wait on:** Ben rotates the Telegram bot token and
   chooses a new `CATO_VAULT_PASSWORD`. Ralph must never invent, generate, or silently choose
   either value. This task blocks all subsequent tasks in this chunk.
2. Once rotated values exist in the environment, run `cato/vault_bootstrap.py`'s migration path to
   create `vault.enc` at `~/.cato/` using the rotated `CATO_VAULT_PASSWORD`.
3. Migrate all secrets currently in `Cato\.env` (`CATO_VAULT_PASSWORD`, `ANTHROPIC_API_KEY`,
   `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `CATODESKTOP_BOT_TOKEN`,
   `GITHUB_FOXFIREPOETS_TOKEN`, `OPENAI_API_KEY`, `SWARMSYNC_VERIFYAPI_KEY`) into `vault.enc`;
   leave only non-secret config in `.env` (`GMAIL_ADDRESS`, `GMAIL_REDIRECT_URI`,
   `TELEGRAM_CHAT_ID`, `CATODESKTOP_BOT_USERNAME`) or remove `.env` entirely.
4. Verify `cato doctor` reports the vault initialized and no live secrets remaining in `.env`.
5. Fix the hardcoded `GENERAL_TOOL_USE` task-type assignment in `agent_loop.py` (confirmed
   ~line 2012, verify current line number first — it has drifted before) so `model_policy.py`/
   `router.py` receive and route on the real task type.
6. Add a regression test asserting the routing decision changes for a task type other than the one
   the hardcoded bug previously forced.
7. Start the daemon (`python -m cato`) reading credentials from `vault.enc` and prove one live
   model call, logging the routed tier/model as evidence (not just "it responded").

### Validation
- Command: `ruff check cato/ && pytest`
- Expected: exit 0, all tests green, plus the live daemon-start + model-call proof documented in
  progress.md (not just unit tests).

### Promise
<promise>CHUNK COMPLETE: CHUNK_2_VAULT</promise>

---

## Chunk 3: CHUNK_3_VAULT_INDEX

### Tasks (in order)

1. Build an ingestion job that walks `C:\Users\Work\Desktop\vault\`'s markdown tree and produces
   chunk records with canonical IDs `{vault-relative-path}#{heading-path}@{chunk-index}` plus
   `content_sha256`, stable across re-indexes of unchanged content.
2. Parse each chunk's YAML frontmatter (`entity`, `type`, `status`, `updated`, `supersedes`) and
   store it as filterable metadata on the corresponding `kg_nodes` row.
3. Exclude `status: superseded` chunks from default retrieval; add a filter flag to retrieve them
   on explicit request.
4. Record `index_updated_at` and a staleness-detection function comparing it against the vault
   tree's latest git commit/mtime.
5. Make ingestion idempotent/re-runnable: re-indexing after an edit updates only the changed
   file's chunks; ingestion never writes to the vault itself.
6. Add tests: fixture-vault happy path (correct IDs/hashes/metadata), superseded-note exclusion,
   malformed-frontmatter graceful degradation (warns, does not abort the run).

### Validation
- Command: `ruff check cato/ && pytest`
- Expected: exit 0, all tests green.

### Promise
<promise>CHUNK COMPLETE: CHUNK_3_VAULT_INDEX</promise>

---

## Chunk 4: CHUNK_4_ASK_E4L

### Tasks (in order)

1. Implement citation formatting `{vault-relative-path}#{heading-anchor}` in Ask-E4L answers.
2. Enforce superseded-chunk exclusion by default, with explicit-history retrieval surfaced and
   labeled superseded.
3. Implement contradiction surfacing: two `status: active` notes disagreeing are both returned,
   flagged, never averaged.
4. Implement the refusal path: zero chunks above the retrieval threshold returns a structured "no
   vault answer found" response without invoking the LLM.
5. Implement a staleness flag on answers when `index_updated_at` predates the vault tree's latest
   known change.
6. Build and run a 10-question Phoenix eval set (real E4L knowledge questions, including at least
   one out-of-scope question to test the refusal path); log results locally
   (`.ralph/context-log.md` or a dedicated eval log) if Phoenix is unreachable.
7. Confirm the eval bar: ≥8/10 correct+cited, 0 confidently-wrong.

### Validation
- Command: `ruff check cato/ && pytest`
- Expected: exit 0, all tests green, plus the Phoenix eval log/results attached as evidence.

### Promise
<promise>CHUNK COMPLETE: CHUNK_4_ASK_E4L</promise>

---

## Chunk 5: CHUNK_5_FINANCE_VIEW

### Tasks (in order)

1. Extend `cato/integrations/financeos_client.py` (do not rewrite) to call
   `/api/v1/control-room` and the integrations-health endpoint.
2. Build a read-only Finance nav view rendering close status, exceptions/HOLDs, integration
   health, and write-gate state — no write-back controls to FinanceOS.
3. Implement the stale-marked fallback state for when FinanceOS is unreachable or the
   capability-token mint endpoint (O2O-FOS-1) is not yet live — no crash, no blank screen.
4. Add tests for: live-data happy path, auth-failure-treated-as-stale-not-"no data" edge case, and
   fully-unreachable failure case (no unhandled exception, no write attempted).

### Validation
- Command: `ruff check cato/ && pytest`
- Expected: exit 0, all tests green.

### Promise
<promise>CHUNK COMPLETE: CHUNK_5_FINANCE_VIEW</promise>

---

## Chunk 6: CHUNK_6_WORK_INBOX

### Tasks (in order)

1. Make Work Inbox Cato's default landing page on launch.
2. Reorganize the sidebar into the 9 items: Work Inbox, Waiting/Follow-ups, Approvals, Calendar,
   Company Tasks, Finance, Ask E4L, Activity/Automations, Settings/Diagnostics.
3. Absorb/demote the legacy 23 views per §10's table (Inbox/Chat-as-landing/Alerts/Dashboard →
   Work Inbox; Chat/Memory search → Ask E4L; AuditLog/Cron/Sessions/Replay/Logs/Usage/Budget →
   Activity/Automations; Settings/Config/Identity/AuthKeys/Skills/System/Diagnostics/Nodes/Flows/
   CodingAgent/InteractiveCLI → Settings/Diagnostics operator/debug tier) — no parallel surface.
4. Render FinanceOS status cards in Work Inbox sourced from Chunk 5's Finance client/view.
5. Confirm killing the FinanceOS API flips the card to stale-marked with no crash.
6. Implement the fixed card-group render order: Needs Me, Waiting, Approvals, Due Soon,
   FYI/Summarized, Resolved (groups may be empty).
7. Wire the Approvals nav item to deep-link non-finance approvals locally and finance approvals to
   Airtable/FinanceOS externally, never duplicating a finance approval action in Cato.
8. Add tests for: default-landing-page, 9-item sidebar, FinanceOS-card stale fallback, and no
   404/dead-end on any absorbed legacy route.

### Validation
- Command: `ruff check cato/ && pytest`
- Expected: exit 0, all tests green.

### Promise
<promise>CHUNK COMPLETE: CHUNK_6_WORK_INBOX</promise>
