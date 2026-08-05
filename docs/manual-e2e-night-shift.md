# Manual E2E — Night-shift (dry run only)

Use this checklist to confirm Cato blocks live outreach and surfaces approvals. **Do not enable live sends overnight.**

## 1. Install assets

Run `scripts/install_night_shift_assets.ps1`, then restart the daemon.

## 2. Policy and status

```text
cato night-shift status
```

Expect:

- `live_outreach_allowed`: false
- `G1 proven`: false
- Ledger: VALID (or empty chain)

Or open `GET http://localhost:8080/api/night-shift/status` (with auth token if enabled).

## 3. Draft email (no send)

In chat or agent session, invoke tool `send_email` with `draft_only: true`. Expect JSON `mode: draft_only` and no approval hold.

## 4. Live send blocked by policy

`send_email` with `draft_only: false` while G1 is false should return `policy_blocked` **before** approval queue.

## 5. Approval queue (after G1 only in production)

With G1 still false, skip real live send tests. To test the queue in a dev copy:

1. Set `gates.g1_manual_loop_proven: true` in `%APPDATA%\cato\night-shift-policy.yaml` **only on a test machine**.
2. Keep `live_outreach_enabled: false` in config.
3. Retry `send_email` without `draft_only` — expect `approval_required` and Telegram buttons or `GET /api/outbound/approvals`.

## 6. Flow dry run

```text
POST /api/flows/conduitscore-revenue-loop/run
```

With `dry_run: true` in the flow YAML, run should complete or no-op steps without sends.

## 7. Digest

Telegram: `/digest` or wait for `night-shift-digest` schedule at 08:00.

## 8. Ledger

```text
cato verify-ledger
```

## Sign-off

Operator completes `docs/loop-proof-card.md` rows 1–6 before flipping G1 or `live_outreach_enabled`.
