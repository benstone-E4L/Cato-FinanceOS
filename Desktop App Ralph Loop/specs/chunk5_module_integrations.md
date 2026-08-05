# Spec: Chunk 5 — Missing Module Integrations

## Acceptance Criteria
1. WhatsApp adapter has configuration UI
2. Ledger verification has "Verify" button in AuditLogView
3. Delegation tokens have CRUD UI
4. Confidence scores visible in CodingAgentView
5. Early termination shown in CodingAgentView

## Files to Modify
- `cato/ui/server.py` — Token CRUD endpoints, ledger verify endpoint
- `desktop/src/views/AuthKeysView.tsx` or new AdaptersView — WhatsApp config
- `desktop/src/views/AuditLogView.tsx` — Verify button
- `desktop/src/views/CodingAgentView.tsx` — Confidence + early termination

## Test Scenarios
- All endpoints return valid JSON
- Frontend builds
- All tests pass
