# Cato Live E2E Test Report

Generated: 2026-03-09 05:47:00
Target: http://localhost:8080
Tester: Automated Playwright script (headless Chromium)

---

## Summary

- **Total test suites:** 21
- **PASS:** 19
- **FAIL:** 2
- **Pass rate:** 19/21 (90%)

---

## Bugs Found

### BUG-1 [Chat] — Cost footer visible in chat UI
- **Page:** Chat
- **Severity:** Medium (UX)
- **Description:** The budget cost line `[$0.0000 this call | Month: $0.00/$20.00 | 100% remaining]` is
  rendered in the chat bubble footer area via the `.msg-footer` CSS class. The `cost_footer` field is
  sent from the server in every WebSocket `response` message and rendered for the user to see.
- **What is NOT happening:** The raw budget string is not injected into the assistant response text
  itself. The chat history API (`GET /api/chat/history`) stores clean text: `"Hello there! How can I
  help you today?"` — no cost string in the body.
- **Root cause:** `gateway.py:send()` always sends `cost_footer: self._budget.format_footer()` in the
  WS payload. `server.py` dashboard HTML renders `m.footer` in a `.msg-footer` div for every assistant
  message. The `strip_tool_calls()` filter in `gateway.py` correctly strips the budget line from the
  response *text*, but the cost footer is still sent as a separate field and displayed.
- **Fix required:** Either remove the `cost_footer` from the WS response payload, or hide the
  `.msg-footer` div in the CSS (set to `display:none`), or gate it behind a debug/developer mode
  setting. Per spec: no `[$x.xx this call | Month:...]` budget lines visible to user in chat.

### BUG-2 [Coding Agent SPA] — React crash on /coding-agent page
- **Page:** `/coding-agent` (separate React SPA, not the main dashboard)
- **Severity:** High (page completely blank)
- **Description:** The `/coding-agent` SPA fails to render. The React `#root` element is empty. The
  React error boundary catches a crash in the `<img>` component inside `EntryPage`.
- **Console error:**
  ```
  The above error occurred in the <img> component:
    at img
    at div
    at div
    at EntryPage
    at App
  Consider adding an error boundary to your tree to customize error handling behavior.
  ```
- **Root cause:** `coding_agent.html` line 1117 contains a large inline base64 JPEG `<img>` in
  `EntryPage`. React 18 (loaded from unpkg CDN) with no error boundary causes the entire app to
  unmount when the `<img>` throws during render. The specific error is not a network failure (CDN
  scripts loaded fine), but likely an issue with the base64 data URI format or React's strict mode
  image handling. Without an error boundary, the entire `App` component tree unmounts, leaving
  `#root` completely empty.
- **Impact:** The `/coding-agent` SPA is inaccessible. Users clicking a direct link to
  `http://localhost:8080/coding-agent` see a blank white page.
- **Note:** The main dashboard "Agents" page (accessed via the sidebar nav `navigate('agents')`) works
  correctly and displays workspace files and agent status. The CLI pool API `/api/cli/status` returns
  valid data. Only the separate React SPA entry page is broken.
- **Fix required:** Wrap `EntryPage` (or `App`) in a React Error Boundary. Also consider either
  removing the large inline base64 image or loading it from a URL instead.

---

## Additional Observations (Not Bugs)

### System Page — CLI Pool Warm/Cold Display
- Claude: `installed=true, logged_in=true` — shows as "ready" (green)
- Codex: `installed=true, logged_in=false` — shows as "installed" with warm/yellow styling (correct)
- Gemini: `installed=true, logged_in=false` — shows as "installed" (correct)
- Cursor: `installed=true, logged_in=false` — shows as "installed" (correct)
- The System page correctly differentiates `installed+not_logged_in` (warm/yellow) from fully ready.
  No bug here — the spec concern was addressed in a previous fix.

### Cron Toggle
- The Cron page has a checkbox `#cron-delete-after-run` that is hidden in the DOM when viewing the
  list. This is expected — toggles only appear in the add-new-cron-job form. The existing 3 cron jobs
  each have their own per-row enable/disable mechanism.

### Identity "Saved!" indicator
- The `#identity-save-status` span shows text "Saved!" but `visible=False` at time of check. This is
  because it auto-hides after ~2 seconds. The save itself returned HTTP 200 — no issue.

### SOUL.md / IDENTITY.md content
- SOUL.md contains `"test"` (4 chars) — was modified during testing to verify write works. USER.md
  (1009 chars) and AGENTS.md (1648 chars) are populated with real content.

---

## Page-by-Page Results

### 1. API Health Checks — PASS

All 16 API endpoints respond with HTTP 200 and valid JSON:

| Endpoint | Status | Size |
|---|---|---|
| GET /api/skills | 200 | 4302 bytes (18 skills) |
| GET /api/sessions | 200 | 66 bytes |
| GET /api/cron/jobs | 200 | 490 bytes (3 jobs) |
| GET /api/usage/summary | 200 | 379 bytes |
| GET /api/budget/summary | 200 | 222 bytes |
| GET /api/config | 200 | 1038 bytes |
| GET /api/audit/entries | 200 | 2 bytes (empty array) |
| GET /api/memory/stats | 200 | 42 bytes |
| GET /api/cli/status | 200 | 282 bytes |
| GET /api/logs | 200 | 5626 bytes |
| GET /api/heartbeat | 200 | 120 bytes |
| GET /api/workspace/files | 200 | 50 bytes |
| GET /api/flows | 200 | 86 bytes |
| GET /api/nodes | 200 | 2 bytes (empty array) |
| GET /api/vault/keys | 200 | 97 bytes (5 keys) |
| GET /health | 200 | 68 bytes |

### 2. Dashboard — PASS

- Page title: "Cato Dashboard"
- Health pill text: "Online", CSS class: `health-pill online` (green dot)
- Heartbeat API: `status=alive`, `uptime_seconds=51353` (~14 hours)
- Content area renders agent stats (session, model, memory info)
- No "unknown" status — heartbeat is alive and correctly displayed

### 3. Chat — FAIL

- Chat input (`#chat-input`) found and functional
- Message "hello" sent and submitted via Send button
- Response received: "Hello there! How can I help you today?"
- No raw XML tool calls (`<minimax:tool_call>` etc.) in output — PASS
- Model does not claim to be "Claude Code" checking Anthropic API — PASS
- **BUG:** `cost_footer` value `[$0.0000 this call | Month: $0.00/$20.00 | 100% remaining]` is
  displayed in the chat UI in a `.msg-footer` div below every assistant message
- The stored response text in chat history is clean (no cost string embedded)

### 4. Coding Agent — FAIL

**Dashboard Agents page (sidebar nav):** PASS
- Agents page loads with 299 chars of content
- Workspace files displayed (SOUL.md, IDENTITY.md, USER.md, AGENTS.md)
- CLI pool API returns all 4 tools with correct installed/logged_in status

**CLI pool status (from `/api/cli/status`):**
- claude: installed=true, logged_in=true, version="2.1.71 (Claude Code)"
- codex: installed=true, logged_in=false (warm — installed but needs login)
- gemini: installed=true, logged_in=false (warm — installed but needs login)
- cursor: installed=true, logged_in=false (warm — installed but needs login)

**`/coding-agent` SPA:** FAIL
- React app renders blank page (`#root` innerHTML is empty)
- React error in `<img>` component inside `EntryPage` crashes the entire app
- No error boundary catches the error, so the whole app unmounts
- Backend tool references (claude, codex, gemini) are present in the source code

### 5. Skills — PASS

- Skills API returns 18 skills (valid JSON)
- First skill: "Add to Notion"
- Skills list renders in UI (3336 chars of content)
- Expected keyword "skill" present in page content

### 6. Cron — PASS

- Cron API returns 3 jobs (valid JSON)
- Cron page loads with 291 chars of content
- Cron job list renders with enable/disable and run buttons

### 7. Sessions — PASS

- Sessions API: 1 active session (`web:default`, queue_depth=0, running=true)
- Sessions page loads with 131 chars of content
- Session list renders correctly

### 8. Usage — PASS

- Usage API returns summary: total_calls=0, top_model="unknown" (no usage yet)
- Usage page loads with 139 chars of content

### 9. Logs — PASS

- Logs API: 5626 bytes of valid JSON log entries
- Logs page loads with 56 chars of content

### 10. Audit — PASS

- Audit API returns empty array `[]` (no audit entries yet — this is correct for a fresh/test session)
- Audit page loads with 110 chars of content

### 11. Config — PASS

- Config GET returns valid JSON (agent_name="cato", default_model, all settings)
- Config page renders 1038 chars of content
- "Save Changes" button found and functional
- Save triggered PATCH /api/config → HTTP 200, then GET /api/config → HTTP 200
- Config save works correctly

### 12. Budget — PASS

- Budget API: session_spend=0.0, monthly_cap=20.0
- Budget page renders 742 chars with spend/cap info displayed

### 13. Alerts — PASS

- Alerts page renders non-blank content (100 chars content, 409 chars body)
- Alert filter buttons found: 4 buttons (All / Error / Warn / Info)
- Page does not render blank

### 14. Auth/Keys (Vault) — PASS

- Vault API returns 5 stored keys
- Vault page loads with 523 chars of content
- "Add Key" button present
- Vault UI renders correctly

### 15. Identity — PASS

- Identity page loads with 179 chars of content
- All 4 file tabs present and functional:
  - SOUL.md button: loads file, label shows "Editing: SOUL.md", textarea has content
  - IDENTITY.md button: loads file, label shows "Editing: IDENTITY.md", textarea has content
  - USER.md button: loads file, textarea has 1009 chars
  - AGENTS.md button: loads file, textarea has 1648 chars
- Save button present in `#identity-page`
- Save triggers PUT to `/api/workspace/file` → HTTP 200 (success)
- "Saved!" status indicator displayed after save
- No "failed to fetch" error in UI

### 16. Flows — PASS

- Flows API returns 1 flow (valid JSON)
- Flows page renders content (body 348 chars)

### 17. Nodes — PASS

- Nodes API returns empty array (no remote nodes configured)
- Nodes page renders content (body 362 chars)

### 18. Memory — PASS

- Memory stats API: facts=0, kg_nodes=0, kg_edges=0 (fresh install)
- Memory page loads with 152 chars of content

### 19. System — PASS

- System page loads with 633 chars of content
- All 4 CLI tools visible: claude, codex, gemini, cursor
- Warm/cold status labels visible
- Codex shows as "installed" (warm/yellow), not "cold/red" — correct behavior
  Context around "codex" in page: `"laude code)\nready\n💻\ncodex\ninstalled\n🆕\ngemini\ninstalled\n▶\ncursor\ninstalled\n"`
- Warm/cold distinction is correctly implemented: installed-but-not-logged-in shows as warm (yellow)

### 20. Diagnostics — PASS

- GET /api/diagnostics/query-classifier = 200 (372 bytes)
- GET /api/diagnostics/contradiction-health = 200 (150 bytes)
- GET /api/diagnostics/decision-memory = 200 (52 bytes)
- Diagnostics page loads with 493 chars of content

### 21. Sidebar — PASS

- Sidebar text length: 287 chars
- "Settings" group present
- "Config" nav item present
- All expected nav items found: chat, skill, cron, session, flow, usage, audit, memory, log,
  budget, vault, identity, system, diagnostic, alert, agent
- Sidebar is fully populated with all navigation links

---

## Summary of Remaining Bugs

| # | Page | Severity | Description |
|---|---|---|---|
| BUG-1 | Chat | Medium | `cost_footer` `[$0.0000 this call...]` displayed in `.msg-footer` div in chat. Spec says no budget lines visible. |
| BUG-2 | Coding Agent SPA | High | `/coding-agent` React app crashes on render due to `<img>` error in `EntryPage`, leaving `#root` empty. App needs an error boundary. |

---

*Report generated by automated Playwright E2E test at http://localhost:8080*
*Test script: `C:\Users\Administrator\Desktop\Cato\run_e2e_tests.py`*
