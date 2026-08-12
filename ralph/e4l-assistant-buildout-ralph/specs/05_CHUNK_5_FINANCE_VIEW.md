# CHUNK_5_FINANCE_VIEW: Add a read-only Finance nav view in Cato that consumes FinanceOS's control-room API and degrades to a stale-marked state without crashing when it's unavailable

## Summary

Phase D, part 1. This chunk builds a new Finance view in Cato's UI that consumes FinanceOS's
`/api/v1/control-room` and integrations-health endpoints (read-only — close status, exceptions/
HOLDs, integration health, write-gate state; per SPEC-financeos-autonomous-operating-layer's
contract). Per the audit (P1, `financeos_client.py` verify-blocked, `VERDICT.md` item O2O-FOS-1),
FinanceOS's capability-token mint endpoint does not exist yet — this chunk's acceptance test must
therefore pass under BOTH conditions: FinanceOS reachable (real data renders) and FinanceOS not
yet available (stale-marked state renders, no crash). It hands off a working Finance nav item to
Chunk 6, which folds it into the reorganized 9-item sidebar.

## Acceptance Criteria

- [ ] `cato/integrations/financeos_client.py` (already unit-tested per the audit, 18 passed) is
      used as-is or extended — not rewritten — to call `/api/v1/control-room` and the
      integrations-health endpoint.
- [ ] A new Finance nav view renders close status, exceptions/HOLDs, integration health, and
      write-gate state, read-only, with no controls that write back to FinanceOS from Cato.
- [ ] When FinanceOS is reachable, the view renders live data.
- [ ] When FinanceOS is unreachable OR the capability-token mint endpoint is still absent
      (O2O-FOS-1, confirmed open at chunk-authoring time), the view renders the last-known state
      marked stale — no crash, no blank screen, no silent failure.
- [ ] No code path in this chunk ever writes to FinanceOS or to Xero — Cato remains read-only
      against FinanceOS by construction (this is a hard boundary, not a preference).
- [ ] All tests pass with zero failures.

## Endpoints / Interfaces

| Method | Path (external, FinanceOS-owned) | Description |
|--------|------|-------------|
| GET | `/api/v1/control-room` | Close status, exceptions/HOLDs, write-gate state (read-only) |
| GET | `/api/v1/control-room/integrations-health` | Per-integration health (read-only) |

No new HTTP endpoints are exposed BY Cato in this chunk — it is a consumer only.

## Database Changes

No schema changes in this chunk. If a local cache of last-known FinanceOS state is needed for the
stale-state fallback, store it in Cato's existing local SQLite state store, not a new database.

## Test Scenarios

- **Happy path**: FinanceOS `/api/v1/control-room` returns 200 with real data — the Finance view
  renders it without a staleness flag.
- **Edge case**: FinanceOS returns a valid response but the capability-token mint endpoint isn't
  live yet — the client fails closed on auth, and the view falls back to the stale-marked state
  rather than treating an auth failure as "no data."
- **Failure case**: FinanceOS is fully unreachable (connection refused/timeout) — the view renders
  last-known state marked stale, with no unhandled exception and no Cato-side write attempted.
- **Integration**: Chunk 6's nav reorg deep-links the Finance nav item to this view; finance
  approvals in Chunk 6's Approvals nav item deep-link to Airtable/FinanceOS directly, never
  duplicating write actions in Cato.

## Dependencies

- **Requires**: CHUNK_2_VAULT (running daemon with vault-sourced credentials, including whatever
  FinanceOS client credentials exist).
- **Blocks**: CHUNK_6_WORK_INBOX (nav reorg needs a working Finance view to link to).

## Completion Promise

<promise>CHUNK COMPLETE: CHUNK_5_FINANCE_VIEW</promise>
