# Spec: Chunk 2 — Chat System Fixes

## Acceptance Criteria
1. Send button shows "Working..." during streaming, "Send" otherwise
2. Messages don't appear twice (WS + history poll dedup works)
3. No React state updates on unmounted component warnings

## Files to Modify
- `desktop/src/views/ChatView.tsx` — Send button text
- `desktop/src/hooks/useChatStream.ts` — Dedup logic, mount guard

## Test Scenarios
- `npm run build` succeeds with zero errors
- Send button disabled while streaming
- Same message from WS and history poll appears only once
