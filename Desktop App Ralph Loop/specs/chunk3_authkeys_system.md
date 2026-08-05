# Spec: Chunk 3 — AuthKeys & System View Fixes

## Acceptance Criteria
1. AuthKeysView fetches live data from /api/cli/status (no hardcoded statuses)
2. Both AuthKeysView and SystemView have per-backend restart buttons
3. Both views show consistent data from the same endpoint

## Files to Modify
- `desktop/src/views/AuthKeysView.tsx` — Replace CLI_BACKENDS with live fetch
- `desktop/src/views/SystemView.tsx` — Add restart buttons

## Test Scenarios
- `npm run build` succeeds
- AuthKeysView shows same warm/cold status as SystemView
- Restart button calls POST /api/cli/{name}/restart
