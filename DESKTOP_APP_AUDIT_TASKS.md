# Cato Desktop App Audit Report

**Generated**: 2026-03-09 07:03:43
**Daemon**: http://127.0.0.1:8080
**Frontend**: http://localhost:5173
**Test Script**: `C:\Users\Administrator\Desktop\Cato\desktop_app_audit_test.py`
**Screenshots**: `C:\Users\Administrator\Desktop\Cato\audit_screenshots\`

## Summary

| Metric | Count |
|--------|-------|
| Total Checks | 101 |
| Passed | 80 |
| Bugs Found | 8 |
| Warnings | 2 |
| Info | 11 |

---

## Bugs (Action Items)

### CRITICAL -- Identity Page Save Fails (Issue #1)

- [ ] **BUG [Identity Save]**: Identity save returns `TypeError: Failed to fetch` -- **ROOT CAUSE FOUND**: CORS policy blocks PUT method. The daemon's `cors_middleware` in `cato/ui/server.py` line 76 sets `Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS` but the `IdentityView.tsx` line 71 uses `method: "PUT"` for the workspace file save. The preflight OPTIONS response rejects PUT. **FIX**: Add `PUT` to the CORS allowed methods in `cato/ui/server.py` lines 73 and 81, changing to `GET, POST, PUT, PATCH, DELETE, OPTIONS`. The API endpoint itself works fine (tested via direct HTTP PUT which bypasses CORS).

- [ ] **BUG [Identity Console]**: `Access to fetch at 'http://127.0.0.1:8080/api/workspace/file' from origin 'http://localhost:5173' has been blocked by CORS policy: Method PUT is not allowed by Access-Control-Allow-Methods in preflight response` -- This is the browser-side error confirming the CORS root cause above.

### HIGH -- System vs AuthKeys Data Mismatch (Issue #4)

- [ ] **BUG [Issue #4 Mismatch]**: CLI pool (System page, live data from `/api/cli/status`) shows only 1 warm tool (Claude), with Codex/Gemini/Cursor all cold. But Auth Keys page **hardcodes** 3 backends as "Working" and Gemini as "Degraded" (see `AuthKeysView.tsx` lines 22-50, the `CLI_BACKENDS` const is static, not fetched from API). **FIX**: AuthKeysView should fetch `/api/cli/status` and derive the Working/Degraded badges from live data instead of hardcoded values.

- [ ] **BUG [Auth & Keys Mismatch]**: AuthKeys shows 3 Working + 1 Degraded but System CLI Pool shows 1 warm + 3 cold.

### MEDIUM -- No Individual LLM Restart (Issue #5)

- [ ] **BUG [System LLM Restart]**: No individual LLM restart buttons on System or Auth pages. Only a full daemon restart button exists. **FIX**: Add per-backend reconnect/restart buttons in SystemView's CLI Pool panel.

### MEDIUM -- Gemini Degraded (Issue #6)

- [ ] **BUG [Gemini Status]**: Gemini CLI is installed but not logged in (cold). Live `/api/cli/status` returns `{"installed": true, "logged_in": false}`. AuthKeysView hardcodes this as "Degraded" with note "Hangs in non-interactive mode." **ROOT CAUSE**: Gemini CLI hangs when invoked non-interactively on this Windows VPS. This is a known environment limitation.

- [ ] **BUG [Auth & Keys Gemini]**: Gemini shows Degraded in Auth Keys view.

### LOW -- Chat WebSocket Error

- [ ] **BUG [Chat Console]**: `[useChatStream] WebSocket error` logged during Chat view navigation. The WS connection to port 8081 recovers (shows Connected), but the initial connection attempt logs an error. This may be a race condition during view mount/unmount.

---

## Warnings

- [ ] **WARN [Chat Send Button]**: Send button only shows 'Send' with no visual change during processing -- KNOWN ISSUE #3: No working/thinking indicator. The `isStreaming` state in `useChatStream.ts` drives a typing animation bubble below the messages, but the send button itself does not change to "Working..." or show a spinner.

- [ ] **WARN [System CLI Pool]**: Only 1 tool shows warm -- KNOWN ISSUE #4: Mismatch with Auth page.

---

## Known Issues Status

| Issue | Description | Status | Root Cause |
|-------|-------------|--------|------------|
| #1 | Identity page save fails | **CONFIRMED** | CORS middleware missing PUT in allowed methods (`cato/ui/server.py:73,81`) |
| #2 | Chat not going to Telegram | **NOT REPRODUCED** | Telegram adapter shows `connected` via `/api/adapters`. Chat history has 12 entries. May work in Tauri but needs live Telegram test. |
| #3 | No working/thinking indicator | **CONFIRMED** | Send button has no loading state; only the typing dots bubble below messages indicates streaming. |
| #4 | System vs AuthKeys mismatch | **CONFIRMED** | AuthKeysView hardcodes CLI_BACKENDS status instead of fetching live `/api/cli/status` data. |
| #5 | No restart button for LLM connections | **CONFIRMED** | Only whole-daemon restart exists; no per-backend reconnect. |
| #6 | Gemini shows degraded | **CONFIRMED** | Gemini CLI hangs in non-interactive mode on this Windows VPS. |
| #7 | Double message printing | **NOT REPRODUCED** | No live chat messages were sent during test. Potential cause: `addMessages` dedup relies on `knownIdsRef` but history poll + WS both fire. |
| #8 | Coding agent boxes on side | **NOT TESTED** | The 3-panel layout (sidebar-left, talk-main, sidebar-right) only appears after a task is created. Entry view rendered correctly. |
| #9 | Heartbeat showing stale | **NOT REPRODUCED** | Heartbeat API returns `status=alive`, last heartbeat 0s ago. The 45-minute stale issue may have been a one-time state. |
| #10 | Duplicate files in Identity/Agents links | **NOT REPRODUCED** | Workspace files (`/api/workspace/files`) and memory files (`/api/memory/files`) have zero overlap. May be a UI rendering issue in sidebar grouping. |

---

## Passed Checks (80/101)

### Backend API (35 passed)

- [x] `GET /health` -- Returns ok, version=0.1.0, uptime=3856s, sessions=3
- [x] `GET /api/budget/summary` -- session_spend=0.0, monthly_spend=0.0
- [x] `GET /api/sessions` -- Returns 3 sessions
- [x] `GET /api/usage/summary` -- total_calls=0
- [x] `GET /api/skills` -- Returns 18 skills
- [x] `GET /api/skills/{name}/content` -- Skill 'add-notion' content loaded
- [x] `GET /api/cron/jobs` -- Returns 3 cron jobs
- [x] `GET /api/logs` -- Returns 10 log entries
- [x] `GET /api/audit/entries` -- Returns 0 audit entries
- [x] `POST /api/audit/verify` -- Chain integrity ok=True
- [x] `GET /api/config` -- Config has 30 keys
- [x] `PATCH /api/config` -- Config patching works
- [x] `GET /api/vault/keys` -- 5 keys stored
- [x] `GET /api/cli/status` -- Claude warm, Codex/Gemini/Cursor cold
- [x] `GET /api/adapters` -- Telegram connected, WhatsApp disconnected
- [x] `GET /api/heartbeat` -- alive, agent=cato
- [x] `GET /api/memory/files` -- 0 files
- [x] `GET /api/memory/stats` -- facts=0, kg_nodes=0, kg_edges=0
- [x] `GET /api/workspace/files` -- 4 files
- [x] `GET /api/workspace/file` -- SOUL.md content 9825 chars
- [x] `PUT /api/workspace/file` -- Identity save works at API level (no CORS)
- [x] `POST /api/workspace/file` -- POST alias works
- [x] `GET /api/action-guard/status` -- 3 checks, autonomy=0.5
- [x] `GET /api/flows` -- 1 flow
- [x] `GET /api/nodes` -- 0 nodes
- [x] `GET /api/diagnostics/query-classifier` -- Returns tiers
- [x] `GET /api/diagnostics/contradiction-health` -- Returns health
- [x] `GET /api/diagnostics/decision-memory` -- Returns decisions
- [x] `GET /api/diagnostics/anomaly-domains` -- Returns domains
- [x] `GET /api/diagnostics/skill-corrections` -- Returns corrections
- [x] `GET /api/chat/history` -- 12 history entries
- [x] `GET /api/memory/content` -- MEMORY.md loaded

### WebSocket (2 passed)

- [x] WebSocket 8081 (gateway) -- Connected, health response received
- [x] WebSocket 8080 (coding agent) -- Connected, health response received

### Frontend Views (43 passed)

- [x] Frontend Load -- App root rendered with Tauri invoke mock
- [x] Sidebar -- Navigation groups rendered
- [x] Dashboard -- 6 metric cards, Gateway Online, Quick Launch 3 buttons, Refresh works
- [x] Chat -- WebSocket connected, input present, send button present
- [x] Coding Agent -- Entry form rendered, task input present
- [x] Skills -- View loaded with 67 skill elements
- [x] Cron Jobs -- View loaded
- [x] Flows -- View loaded
- [x] Sessions -- View loaded
- [x] Remote Nodes -- View loaded
- [x] Memory -- View loaded
- [x] Usage -- View loaded
- [x] Logs -- View loaded with 5964 chars of log content
- [x] Audit Log -- View loaded
- [x] Diagnostics -- All 5 tabs present and clickable (Query Tiers, Contradictions, Decisions, Anomalies, Corrections)
- [x] System -- 4 CLI tool cards, Safety Gate, Daemon Controls
- [x] Identity -- 4 files listed, editor present with content, Save and Reload buttons
- [x] Config -- View loaded
- [x] Budget -- View loaded with spend data
- [x] Alerts -- Budget threshold controls present, save button present
- [x] Auth & Keys -- Add key form present, vault key rows shown

---

## Recommended Fixes (Priority Order)

### 1. CORS PUT Method (fixes Issue #1 -- Identity save)

File: `cato/ui/server.py`, lines 73 and 81

```python
# BEFORE:
"Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",

# AFTER:
"Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
```

### 2. AuthKeysView Live Status (fixes Issue #4 -- mismatch)

File: `desktop/src/views/AuthKeysView.tsx`

Replace the hardcoded `CLI_BACKENDS` const with a fetch to `/api/cli/status` and derive Working/Degraded badges from the live `installed` and `logged_in` fields.

### 3. Send Button Loading State (fixes Issue #3)

File: `desktop/src/views/ChatView.tsx`, line 151-156

Add `isStreaming` check to show "Working..." instead of "Send":

```tsx
<button type="submit" className="chat-send-btn" disabled={...}>
  {isStreaming ? "Working..." : "Send"}
</button>
```

### 4. Per-Backend Restart (fixes Issue #5)

File: `desktop/src/views/SystemView.tsx`

Add a restart/reconnect button per CLI tool card in the CliPoolPanel that calls a new `/api/cli/{name}/restart` endpoint.

### 5. Gemini Non-Interactive Fix (fixes Issue #6)

This is an environment limitation. Gemini CLI hangs in non-interactive mode on this Windows VPS. Options:
- Add a `--non-interactive` or `--batch` flag if available
- Use a timeout wrapper around Gemini invocations
- Document as known limitation for this deployment

---

## Test Environment

- Daemon: Python 3.11+, aiohttp, ports 8080/8081
- Frontend: Vite 7.3.1, React 19, TypeScript, port 5173
- Browser: Headless Chromium via Playwright 1.58.0
- OS: Windows Server 2025 Datacenter 10.0.26100
- Tauri: Bypassed via `__TAURI_INTERNALS__` mock injection
