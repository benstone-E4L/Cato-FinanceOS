# CHUNK_1_HYGIENE: Clean up Cato's repo-hygiene debt (CI branch scope, dead code, unused dependency, WhatsApp removal) before any other chunk lands on main

## Summary

This chunk fixes the cheap, high-value, no-live-credential issues the architecture-cartographer
audit found on top of the master spec's own Phase A list: CI silently not running on `main`,
3,991 LOC of confirmed-dead code (`Genesis_meta_agent.py`), an unused pip dependency (`mcp`), and
a duplicate WhatsApp implementation Ben has decided to remove entirely (no WhatsApp support at
all — see `.ralph/guardrails.md` "RESOLVED: No WhatsApp"). None of this touches live secrets or
the daemon, so it can and must land first — it makes every subsequent chunk's merges to `main`
actually CI-checked. It hands off a clean, CI-protected `main` to Chunk 2 (vault + daemon), which
is the first chunk that touches live credentials.

## Acceptance Criteria

- [ ] `.github/workflows/ci.yml` runs the pytest suite on `push`/`pull_request` to both
      `main` and `e4l-runtime-hardening` (do not remove the existing branch, add `main`).
- [ ] `Genesis_meta_agent.py` is deleted from the repo root; a `git grep` for
      `Genesis_meta_agent` returns zero hits anywhere else in the repo (imports, docs, scripts).
- [ ] `mcp>=1.22.0` is removed from `pyproject.toml`'s `dependencies` list; `pip install -e .`
      still succeeds and `python -m cato --help` still runs (confirms nothing imports `mcp`).
- [ ] `cato/adapters/whatsapp.py` (Twilio) and `cato/channels/whatsapp.py` (Meta Cloud API) are
      both deleted, along with every call site that registers or routes to either — grep for
      `whatsapp` (case-insensitive) across `cato/cli.py`, `cato/ui/server.py`,
      `cato/api/whatsapp_routes.py`, and any desktop view that surfaces a WhatsApp toggle/status,
      and remove each reference found; do not assume this list is exhaustive without grepping.
      `twilio` is removed from `pyproject.toml`'s dependencies if nothing else in the repo imports
      it (grep-confirm first).
- [ ] `python -m cato --help` and the existing test suite still pass with WhatsApp fully removed —
      this is a deletion of an unused-by-anyone-yet feature, not a behavior change for a live user.
- [ ] A trivial commit pushed to `main` produces a visible GitHub Actions run (manual proof step,
      documented in progress.md — do not fabricate this if push access isn't available in this
      environment; note it as a manual follow-up instead).
- [ ] All tests pass with zero failures.

## Endpoints / Interfaces

No HTTP endpoints — internal service layer only (CI config + dead-code removal + dependency list).

## Database Changes

No schema changes in this chunk.

## Test Scenarios

- **Happy path**: `ruff check cato/ && pytest` passes with `Genesis_meta_agent.py` gone and `mcp`
  removed from `pyproject.toml`.
- **Edge case**: confirm no test file, script, or doc under active maintenance imports
  `Genesis_meta_agent` (the ~50 stale root-level planning docs are out of scope — do not edit them
  in this chunk; only code and CI config are in scope).
- **Failure case**: if removing `mcp` breaks an import somewhere the audit missed, that import is
  itself dead code masking a real dependency — do not silently re-add `mcp`; report it as a
  guardrails.md finding and block on it rather than guessing.
- **Integration**: a CI-green `main` branch is the precondition Chunk 2 depends on — Chunk 2's own
  validation gate assumes CI is already catching regressions on `main`.

## Dependencies

- **Requires**: None (first chunk).
- **Blocks**: CHUNK_2_VAULT (vault/secret work should land on a CI-protected `main`).

## Completion Promise

<promise>CHUNK COMPLETE: CHUNK_1_HYGIENE</promise>
