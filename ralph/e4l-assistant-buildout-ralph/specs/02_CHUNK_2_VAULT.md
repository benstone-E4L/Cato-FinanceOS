# CHUNK_2_VAULT: Stand up Cato's encrypted credential vault and prove the daemon makes one live, correctly-routed model call using it

## Summary

This is the security-hardening chunk — the analogue of an "auth chunk" for a project with no web
login. Per the master spec's Phase A and confirmed live by the audit (P0): `Cato\.env` currently
holds live plaintext secrets including `CATO_VAULT_PASSWORD` itself, and `vault.enc` has never
been created on this host. `cato/vault.py` (AES-256-GCM/Argon2id) and `cato/vault_bootstrap.py`
(precedence: env > vault.enc > plaintext .env fallback) already exist and are unit-tested (per
`proof-artifacts/truth-audit-gate/VERDICT.md`, 24 passed) — this chunk executes them live, not
builds them from scratch. It also fixes the hardcoded `GENERAL_TOOL_USE` routing bug (confirmed
at `agent_loop.py:2012`, not the spec's stated line 1943 — line numbers drifted) so the live model
call this chunk proves is actually tier-routed, not just hardcoded to one model. This chunk must
land before any chunk that starts the daemon or touches live credentials (Chunks 3-6 all assume a
running daemon and an initialized vault).

## Acceptance Criteria

- [ ] **Manual operator step (document, do not fabricate):** Ben rotates the Telegram bot token
      (predecessor-repo token, owed since the 2026-08-06 audit) and chooses a new
      `CATO_VAULT_PASSWORD` — both are human actions outside this chunk's code-writing scope; the
      chunk's job is to make the tooling ready to receive the rotated values, not to invent them.
- [ ] `vault.enc` is created at `~/.cato/` via `cato/vault_bootstrap.py`'s migration path, using
      the rotated `CATO_VAULT_PASSWORD`.
- [ ] All secrets currently live in `Cato\.env` (`CATO_VAULT_PASSWORD`, `ANTHROPIC_API_KEY`,
      `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `CATODESKTOP_BOT_TOKEN`,
      `GITHUB_FOXFIREPOETS_TOKEN`, `OPENAI_API_KEY`, `SWARMSYNC_VERIFYAPI_KEY`) are migrated into
      `vault.enc`; `.env` retains only non-secret config (`GMAIL_ADDRESS`, `GMAIL_REDIRECT_URI`,
      `TELEGRAM_CHAT_ID`, `CATODESKTOP_BOT_USERNAME`) or is removed entirely.
- [ ] `cato doctor` reports the vault initialized and no live secrets remaining in `.env`.
- [ ] `agent_loop.py`'s hardcoded `GENERAL_TOOL_USE` task-type assignment (confirmed at line 2012)
      is fixed so `model_policy.py`/`router.py`'s tier logic actually receives and routes on the
      real task type instead of the hardcoded constant.
- [ ] The Cato daemon starts (`python -m cato`) reading credentials from `vault.enc`, and makes one
      live model call, with the call's routed tier/model logged as proof (not just "it responded").
- [ ] All tests pass with zero failures.

## Endpoints / Interfaces

No HTTP endpoints — internal service layer only (vault, bootstrap, daemon startup, model routing).

## Database Changes

No schema changes in this chunk. `vault.enc` is a new encrypted file at `~/.cato/`, not a database
table.

## Test Scenarios

- **Happy path**: with `CATO_VAULT_PASSWORD` set in the environment (rotated value) and
  `vault.enc` populated, `python -m cato` starts, unlocks the vault, and completes one live model
  call routed through the fixed tier logic.
- **Edge case**: `CATO_VAULT_PASSWORD` unset — `vault_bootstrap.py` must fail closed with a clear
  error, not silently fall back to plaintext `.env` secrets that may no longer exist.
- **Failure case**: a task type other than the one the hardcoded bug previously forced must now
  route to a different tier than before — write a regression test asserting the routing decision
  is no longer constant regardless of input task type.
- **Integration**: Chunks 3-6 all assume the daemon starts successfully off `vault.enc` — this
  chunk's daemon-start proof is their shared precondition.

## Dependencies

- **Requires**: CHUNK_1_HYGIENE (CI-protected `main`).
- **Blocks**: CHUNK_3_VAULT_INDEX, CHUNK_4_ASK_E4L, CHUNK_5_FINANCE_VIEW, CHUNK_6_WORK_INBOX (all
  require a running daemon with an initialized vault).

## Completion Promise

<promise>CHUNK COMPLETE: CHUNK_2_VAULT</promise>
