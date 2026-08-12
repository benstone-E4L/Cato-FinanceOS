# CHUNK_6_WORK_INBOX: Make Work Inbox Cato's default landing page and reorganize the 23-view sidebar into the master spec's 9-item nav

## Summary

Phase D, part 2 — the UX centerpiece of this workstream. Per master spec §10, Work Inbox stops
being one view among 23 and becomes Cato's default landing page; the sidebar reorganizes into the
9-item nav (Work Inbox, Waiting/Follow-ups, Approvals, Calendar, Company Tasks, Finance, Ask E4L,
Activity/Automations, Settings/Diagnostics), absorbing/demoting the existing 23 views per §10's
table. This chunk's acceptance bar is intentionally narrower than the full §10/Phase-F acceptance
test: it only needs Work Inbox live with FinanceOS status cards rendering (via Chunk 5's view) —
NOT the one-correlated-card cross-system correlation across Gmail/Slack/Monday/FinanceOS, which is
Phase F's job in a separate, out-of-scope workstream (the Coordination Ledger doesn't exist yet).

## Acceptance Criteria

- [ ] Launching Cato opens Work Inbox by default (not Chat, not Dashboard, not any other view).
- [ ] The sidebar is reorganized into exactly the 9 items from §10's table: Work Inbox,
      Waiting/Follow-ups, Approvals, Calendar, Company Tasks, Finance, Ask E4L,
      Activity/Automations, Settings/Diagnostics.
- [ ] Existing views are absorbed/demoted per §10's table, not preserved as a parallel surface:
      Inbox/Chat-as-landing/Alerts/Dashboard → Work Inbox; Chat/Memory search → Ask E4L;
      AuditLog/Cron/Sessions/Replay/Logs/Usage/Budget → Activity/Automations;
      Settings/Config/Identity/AuthKeys/Skills/System/Diagnostics/Nodes/Flows/CodingAgent/
      InteractiveCLI → Settings/Diagnostics (operator/debug tier only — this absorption target is
      the ONLY place the legacy 23-view surface may still exist post-chunk, per the do-not-build
      list).
- [ ] Work Inbox renders FinanceOS status cards sourced from Chunk 5's Finance view/client (finance
      status only — not Gmail/Slack/Monday correlation, which is out of scope for this chunk).
- [ ] Killing the FinanceOS API produces a stale-marked state on any FinanceOS-sourced card in Work
      Inbox, with no crash — reusing Chunk 5's stale-state behavior, not reimplementing it.
- [ ] Card state groups render in the fixed order the spec defines: Needs Me, Waiting, Approvals,
      Due Soon, FYI/Summarized, Resolved (even if some groups are empty in this chunk's scope,
      since full cross-system population is Phase F's job).
- [ ] Approvals nav item deep-links non-finance approvals locally and finance approvals to
      Airtable/FinanceOS externally — it never duplicates a finance approval action inside Cato.
- [ ] All tests pass with zero failures.

## Endpoints / Interfaces

No new external HTTP endpoints — this chunk is UI/navigation restructuring inside the existing
Tauri app, consuming Chunk 4 (Ask E4L) and Chunk 5 (Finance) as already-built nav targets.

## Database Changes

No schema changes in this chunk. If Work Inbox needs local card state before the Coordination
Ledger exists (Phase F), store it in Cato's existing local SQLite state store as disposable UI
state, not a new authoritative table — Cato is explicitly not an authority for cross-system state
per the master spec's §6 Source-of-Truth Matrix.

## Test Scenarios

- **Happy path**: launching Cato opens Work Inbox; the sidebar shows exactly the 9 nav items; a
  FinanceOS status card renders live data sourced from Chunk 5.
- **Edge case**: FinanceOS API killed mid-session — the Work Inbox card sourced from it flips to
  stale-marked without a UI crash or a stuck loading state.
- **Failure case**: navigating to any of the legacy 23 view routes that were absorbed must not
  404 or dead-end silently — it either redirects into the corresponding new nav item or is only
  reachable from the Settings/Diagnostics operator/debug tier, per the do-not-build constraint
  that the legacy dashboard survives only as a debug-tier absorption target.
- **Integration**: this chunk is the last in this workstream. It hands off a working Work-Inbox-
  as-home Cato build to the (separate, out-of-scope) Phase E/F workstreams, which add the
  Coordination Ledger and true one-correlated-card cross-system rendering on top of this
  navigation shell.

## Dependencies

- **Requires**: CHUNK_4_ASK_E4L, CHUNK_5_FINANCE_VIEW.
- **Blocks**: None within this workstream (Phase E/F are separate, out-of-scope workstreams).

## Completion Promise

<promise>CHUNK COMPLETE: CHUNK_6_WORK_INBOX</promise>
