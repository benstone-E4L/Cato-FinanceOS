# Cato UI — Comprehensive Bug Report

**Generated**: 2026-03-08 14:45:00
**Target**: http://localhost:8080 (Cato aiohttp daemon web UI)
**Test tool**: Playwright (Python) + direct API probes
**Test script**: `C:\Users\Administrator\Desktop\Cato\cato_playwright_full_test.py`

---

## Summary

| Metric | Value |
|--------|-------|
| Tests run | 96 |
| Tests passed | 81 |
| Tests failed | 15 |
| Total bugs found | 19 |
| Critical | 0 |
| High | 10 |
| Medium | 6 |
| Low | 3 |

---

## Bug Inventory

### High Severity

---

#### [HB-001] Heartbeat API returns status='unknown' with null last_heartbeat and null agent_name

- **Page**: Dashboard / Heartbeat API
- **Severity**: High
- **API Endpoint**: `/api/heartbeat`
- **Expected**: Heartbeat status should be 'alive' with a valid last_heartbeat timestamp when daemon is running
- **Actual**: `{"status": "unknown", "last_heartbeat": null, "agent_name": null, "uptime_seconds": null}`
- **Details**: Dashboard will display 'unknown' heartbeat status pill, misleading users into thinking the agent is not running. The `/api/heartbeat` endpoint exists to receive pings FROM the agent loop, but the agent loop never calls it. Fix: add a periodic heartbeat POST from `agent_loop.py` to `http://localhost:8080/api/heartbeat` every 30 seconds.

---

#### [CFG-001] GET /api/config returns empty object {}

- **Page**: Config page
- **Severity**: High
- **API Endpoint**: `GET /api/config`
- **Expected**: Should return current config values (agent_name, default_model, log_level, etc.) read from `%APPDATA%\cato\config.yaml`
- **Actual**: Returns `{}`
- **Details**: The Config page form shows all fields blank. The YAML config at `%APPDATA%\cato\config.yaml` is not being read by the API handler. Any user-visible config (default_model: `openrouter/minimax/minimax-m2.5`, agent_name, etc.) will not appear in the Config page.

---

#### [CFG-004] PATCH /api/config does not persist changes

- **Page**: Config page
- **Severity**: High
- **API Endpoint**: `PATCH /api/config`
- **Expected**: After PATCH, a subsequent GET /api/config should return the updated values
- **Actual**: After PATCH with `{"agent_name": "cato-playwright-test"}`, GET /api/config still returns `{}`
- **Details**: Config edits appear saved in the UI (PATCH returns `{status: ok}`) but are not written to disk. On next load or page refresh, all changes are lost. The PATCH handler does not persist to `%APPDATA%\cato\config.yaml`.

---

#### [CHAT-001] Chat response contains raw XML tool call markup

- **Page**: Chat page
- **Severity**: High
- **API Endpoint**: `GET /api/chat/history`
- **Expected**: Tool call XML should be stripped before storing/displaying chat responses
- **Actual**: Message text visible to user: `I'm Claude Code! Let me confirm this by checking with the Anthropic API.\n<minimax:tool_call>\n<invoke name="anthropic-sdk">...`
- **Details**: The MiniMax m2.5 model via OpenRouter outputs tool invocations as `<minimax:tool_call>` XML blocks. The gateway/agent loop must strip these before returning text to the WebSocket client and before storing in chat history. Currently the raw XML is both stored and displayed.

---

#### [CHAT-003] Chat assistant identifies itself as 'Claude Code' instead of 'Cato'

- **Page**: Chat page
- **Severity**: High
- **API Endpoint**: `GET /api/chat/history`
- **Expected**: Assistant should identify as 'Cato' per SOUL.md/IDENTITY.md workspace files
- **Actual**: Response: `"I'm Claude Code! Let me confirm this by checking with the Anthropic API."`
- **Details**: SOUL.md and IDENTITY.md workspace files define Cato's identity. These must be injected into the system prompt on every request. Either the system prompt is not being loaded, or the MiniMax model is ignoring it. The model appears to default to Claude Code behavior, which is its training identity, not the Cato persona.

---

#### [CHAT-004] Chat assistant attempts to call Anthropic API to verify its identity

- **Page**: Chat page
- **Severity**: High
- **API Endpoint**: `GET /api/chat/history`
- **Expected**: Cato should know its own identity from SOUL.md/IDENTITY.md without any external API calls
- **Actual**: The assistant attempts to invoke `anthropic-sdk` tool to ask "What model are you?" — visible as a raw tool call block in the response
- **Details**: This is both an identity confusion bug (CHAT-003) and a prompt injection / model confusion issue. Cato is running MiniMax m2.5 via OpenRouter, not Claude Code. The system prompt persona must be strengthened. The `anthropic-sdk` tool invocation is also a security/privacy concern — the model is trying to make external API calls to Anthropic.

---

#### [DASH-001] Dashboard heartbeat section displays 'unknown' status

- **Page**: Dashboard
- **Severity**: High
- **API Endpoint**: `/api/heartbeat`
- **Expected**: Should show 'alive' with last heartbeat time when daemon is running
- **Actual**: Dashboard shows heartbeat pill with 'unknown' status (grey) despite daemon being fully operational
- **Details**: Directly caused by HB-001. The DashboardView polls `/api/heartbeat` and renders the `status` field as a colored pill. With `status='unknown'` and null timestamps, no useful information is shown. Users cannot tell if the agent loop is running.

---

#### [IDENT-004] No dedicated Identity/workspace-files page in web UI dashboard

- **Page**: Identity page (web UI)
- **Severity**: High
- **API Endpoint**: `/api/workspace/files`, `/api/workspace/file`
- **Expected**: Web UI should have an Identity page for editing SOUL.md, IDENTITY.md, USER.md, AGENTS.md (these files govern Cato's persona)
- **Actual**: No `#identity-page` div exists in `dashboard.html`. The API endpoints `/api/workspace/files` and `PUT /api/workspace/file` are functional but unreachable from the web UI.
- **Details**: `IdentityView.tsx` exists in the Tauri desktop app (`.tsx` component) but has not been ported to the web dashboard. Given that CHAT-003 shows the identity files are critical to proper persona, users who only use the web UI have no way to edit them.

---

#### [ALERTS-001] Alerts nav item has no corresponding page div — clicking it shows nothing

- **Page**: Alerts (web UI)
- **Severity**: High
- **API Endpoint**: N/A (UI-only bug)
- **Expected**: Clicking "Alerts" in the sidebar should navigate to an alerts management page
- **Actual**: `navigate('alerts')` is called but there is no `id="alerts-page"` div in `dashboard.html`. The `navigate()` function does `document.getElementById('alerts-page')` which returns null, so no page is shown. The content area goes blank.
- **Details**: The alerts UI elements (`#alerts-count`, `#alerts-list`, filter buttons) exist in the HTML but are embedded inside the diagnostics section without a wrapper `#alerts-page` div. The nav item exists with `data-page="alerts"` and `onclick="navigate('alerts')"`. This is a broken navigation destination.

---

#### [DIAG-001] /api/diagnostics/contradiction-health returns SQLite thread safety error

- **Page**: Diagnostics page
- **Severity**: High
- **API Endpoint**: `GET /api/diagnostics/contradiction-health`
- **Expected**: Should return clean contradiction health data without error field
- **Actual**: Response includes: `{"error": "SQLite objects created in a thread can only be used in that same thread. The object was created in thread id 116148 and this is thread id..."}`
- **Details**: `ContradictionDetector` creates a SQLite connection in one thread and then the aiohttp request handler (running in a different thread/event loop) tries to use it. Fix: use `check_same_thread=False` on the SQLite connection, or create a fresh connection per request.

---

### Medium Severity

---

#### [CFG-002] PATCH /api/config returns {status: ok} instead of the updated config object

- **Page**: Config page
- **Severity**: Medium
- **API Endpoint**: `PATCH /api/config`
- **Expected**: Should return the updated config object so the UI can update its form state
- **Actual**: Returns `{"status": "ok"}`
- **Details**: `ConfigView.tsx` (Tauri) does `setConfig(data)` on the PATCH response. When the response is `{status:'ok'}` the form state is set to that object instead of the full config. The web UI's `saveConfig()` JS function similarly expects the updated config back. Combined with CFG-001/CFG-004, the config flow is fully broken.

---

#### [CRON-001] POST /api/cron/jobs/{name}/toggle returns 500 for nonexistent job

- **Page**: Cron Jobs page
- **Severity**: Medium
- **API Endpoint**: `POST /api/cron/jobs/{name}/toggle`
- **Expected**: Should return 404 Not Found with a message like `{"error": "job not found"}`
- **Actual**: HTTP 500, body: `{"status": "error", "message": "Expecting value: line 1 column 1 (char 0)"}`
- **Details**: The error message indicates a JSON parsing error — the handler attempts to parse an empty or missing config file for the named job. The 500 status means the Cron Jobs UI would show a generic error instead of a helpful "job not found" message.

---

#### [SYS-001] Codex, Gemini, and Cursor show as 'cold' in System page despite being installed

- **Page**: System page
- **Severity**: Medium
- **API Endpoint**: `GET /api/cli/status`
- **Expected**: Installed tools that the coding agent uses successfully should show as 'warm' (green badge)
- **Actual**: `{"codex": {"installed": true, "logged_in": false}, "gemini": {"installed": true, "logged_in": false}, "cursor": {"installed": true, "logged_in": false}}`
- **Details**: System page shows these as 'cold' (red badge). Project memory says Codex works in the coding agent. The `logged_in` check may not correctly detect auth state for these CLI tools. For Codex, the auth check may be looking for a config file in a different location. This creates a misleading red status for tools that are actually functional.

---

#### [CHAT-002] Chat responses show internal budget/cost lines to users

- **Page**: Chat page
- **Severity**: Medium
- **API Endpoint**: `GET /api/chat/history`
- **Expected**: Budget/cost information should only appear in the Budget page, not embedded in chat message text
- **Actual**: Chat response text ends with: `[$0.0000 this call | Month: $0.00/$20.00 | 100% remaining]`
- **Details**: The agent loop or gateway appends a spend summary line to every response text before storing it. This is implementation detail noise that pollutes chat history and confuses users. Strip this line in the gateway before sending to the WebSocket client and before persisting to chat history.

---

#### [FLOW-003] No dedicated Flows page in web UI dashboard

- **Page**: Flows page (web UI)
- **Severity**: Medium
- **API Endpoint**: `/api/flows`
- **Expected**: Web UI should have a Flows page for viewing and running declarative workflows
- **Actual**: No `#flows-page` div in `dashboard.html`. The `/api/flows` endpoints are functional (GET returns list, POST creates flows).
- **Details**: `FlowsView.tsx` exists in Tauri but not ported to the web dashboard. API is ready but there is no UI to use it.

---

#### [MEM-001] GET /api/memory/content returns 400 Bad Request

- **Page**: Memory page
- **Severity**: Medium
- **API Endpoint**: `GET /api/memory/content`
- **Expected**: HTTP 200 with memory content (facts, KG nodes/edges)
- **Actual**: HTTP 400
- **Details**: The Memory page's content tab calls `/api/memory/content`. Without required query parameters (agent_id, type, etc.) it returns 400. The web UI may be calling it without required params, or the endpoint needs to accept parameterless requests with reasonable defaults.

---

### Low Severity

---

#### [IDENT-002] POST /api/workspace/file returns 405 — only PUT is supported

- **Page**: Identity page / API
- **Severity**: Low
- **API Endpoint**: `POST /api/workspace/file`
- **Expected**: Either POST should work (with same behavior as PUT), or API should document that only PUT is accepted
- **Actual**: POST returns 405 Method Not Allowed; PUT returns 200
- **Details**: No user-facing impact since the Tauri frontend correctly uses PUT. However the API is inconsistent and should be documented or both methods supported.

---

#### [NAV-003] Sidebar has no 'Settings' group label

- **Page**: All pages / Sidebar
- **Severity**: Low
- **Expected**: Sidebar should have a labeled group "Settings" containing Config, Budget, Alerts, Auth, Identity items (as in the Tauri Sidebar.tsx)
- **Actual**: Web UI sidebar lists all nav items without group dividers or the "Settings" group label
- **Details**: The Tauri `Sidebar.tsx` has four labeled nav groups: Workspace, Automation, Monitoring, Settings. The web `dashboard.html` sidebar uses collapsible groups (Workspace, Automation, Monitoring, Settings) — but these may not be visually distinct enough. Minor UX issue.

---

#### [NODE-001] No dedicated Remote Nodes page in web UI dashboard

- **Page**: Nodes page (web UI)
- **Severity**: Low
- **API Endpoint**: `/api/nodes`
- **Expected**: Web UI should have a Nodes page for monitoring remote Cato instances
- **Actual**: No `#nodes-page` div in `dashboard.html`
- **Details**: `NodesView.tsx` exists in Tauri but not ported. The API `/api/nodes` works and returns `[]`. Low priority as nodes feature appears to be future/experimental.

---

## All Test Results

| # | Test | Result | Detail |
|---|------|--------|--------|
| 1 | API GET /health | PASS | status=200 |
| 2 | API GET /api/heartbeat | PASS | status=200 |
| 3 | API GET /api/adapters | PASS | status=200 |
| 4 | API GET /api/budget/summary | PASS | status=200 |
| 5 | API GET /api/sessions | PASS | status=200 |
| 6 | API GET /api/usage/summary | PASS | status=200 |
| 7 | API GET /api/config | PASS | status=200 |
| 8 | API GET /api/skills | PASS | status=200 |
| 9 | API GET /api/cron/jobs | PASS | status=200 |
| 10 | API GET /api/audit/entries | PASS | status=200 |
| 11 | API GET /api/logs | PASS | status=200 |
| 12 | API GET /api/flows | PASS | status=200 |
| 13 | API GET /api/nodes | PASS | status=200 |
| 14 | API GET /api/memory/stats | PASS | status=200 |
| 15 | API GET /api/cli/status | PASS | status=200 |
| 16 | API GET /api/action-guard/status | PASS | status=200 |
| 17 | API GET /api/vault/keys | PASS | status=200 |
| 18 | API GET /api/workspace/files | PASS | status=200 |
| 19 | API GET /api/diagnostics/query-classifier | PASS | status=200 |
| 20 | API GET /api/diagnostics/contradiction-health | PASS | status=200 |
| 21 | API GET /api/diagnostics/decision-memory | PASS | status=200 |
| 22 | API GET /api/diagnostics/anomaly-domains | PASS | status=200 |
| 23 | API GET /api/diagnostics/skill-corrections | PASS | status=200 |
| 24 | API GET /api/chat/history | PASS | status=200 |
| 25 | Heartbeat status is alive | FAIL | got status=unknown |
| 26 | Config returns non-empty data | FAIL | got {} |
| 27 | PATCH /api/config returns updated config | FAIL | got {'status': 'ok'} |
| 28 | PUT /api/workspace/file saves file | PASS | |
| 29 | Identity file endpoint method check | PASS | POST=405, PUT=200 |
| 30 | Cron toggle non-existent job returns 404 | FAIL | got 500 |
| 31 | Diagnostics contradiction-health no SQLite error | FAIL | error field in response |
| 32 | All installed CLI tools show warm | FAIL | cold: ['codex', 'gemini', 'cursor'] |
| 33 | Chat responses free of raw tool call XML | FAIL | <minimax:tool_call> in history |
| 34 | Chat responses free of cost lines | FAIL | cost line in message text |
| 35 | Chat assistant identifies as Cato | FAIL | says "I'm Claude Code" |
| 36 | Chat does not call Anthropic API for identity | FAIL | anthropic-sdk tool call visible |
| 37 | Page title set | PASS | title='Cato Dashboard' |
| 38 | Sidebar visible | PASS | |
| 39 | Navigation items present | PASS | found 17 items |
| 40 | All expected nav pages present | PASS | 17 pages |
| 41 | Dashboard: Gateway status visible | PASS | |
| 42 | Dashboard: Heartbeat section present | PASS | |
| 43 | Dashboard: Budget data visible | PASS | |
| 44 | Chat: Input field present | PASS | |
| 45 | Chat: Send button present | PASS | |
| 46 | Chat: WS/health status visible | PASS | health='Online' |
| 47 | Chat: Telegram integration visible | PASS | |
| 48 | Coding Agent: Page loaded | PASS | |
| 49 | Skills: Skills list renders | PASS | checking 5 skills, visible=True |
| 50 | Cron: Page loaded | PASS | |
| 51 | Cron: Create/Add job button present | PASS | |
| 52 | Sessions: Page loaded | PASS | |
| 53 | Sessions: Active sessions displayed | PASS | |
| 54 | Usage: Page loaded | PASS | |
| 55 | Logs: Page loaded | PASS | |
| 56 | Logs: Log entries rendered | PASS | |
| 57 | Audit: Page loaded | PASS | |
| 58 | Audit: Verify chain button present | PASS | |
| 59 | Audit: Verify chain button clickable | PASS | |
| 60 | Config: Page loaded | PASS | |
| 61 | Config: Form inputs present | PASS | found 42 inputs |
| 62 | Config: Save function invoked | PASS | result=called |
| 63 | Budget: Page loaded | PASS | |
| 64 | Budget: Spend data rendered | PASS | |
| 65 | Alerts: Nav item present in web UI | PASS | (but page div missing — see ALERTS-001) |
| 66 | Auth Keys: Page loaded | PASS | |
| 67 | Auth Keys: Vault keys rendered in list | PASS | |
| 68 | Identity: Dedicated page in web UI | FAIL | Not present — only in Tauri app |
| 69 | Flows: Dedicated page in web UI | FAIL | Not present |
| 70 | Nodes: Dedicated page in web UI | FAIL | Not present |
| 71 | Memory: Page loaded | PASS | |
| 72 | Memory: Stats rendered | PASS | |
| 73 | System: Page loaded | PASS | |
| 74 | System: CLI pool panel visible | PASS | |
| 75 | System: Cold CLI tools shown | PASS | 4 cold occurrences |
| 76 | System: Action Guard panel visible | PASS | |
| 77 | System: Restart Daemon button present | PASS | |
| 78 | Diagnostics: Page loaded | PASS | |
| 79 | Diagnostics: Tab buttons present | PASS | found 2 tabs |
| 80 | Diagnostics: Tab 'Git URL' clickable | PASS | |
| 81 | Diagnostics: Tab 'Upload SKILL.md' clickable | PASS | |
| 82 | Diagnostics: No raw SQLite error in UI | PASS | |
| 83 | Cron: Create job via UI | PASS | saveCron() called |
| 84 | Auth Keys: Add vault key via UI | PASS | |
| 85 | No significant console errors | PASS | |
| 86 | No failed network requests | PASS | |
| 87 | POST /api/flows create | PASS | status=200 |
| 88 | GET /api/flows returns list | PASS | count=1 |
| 89 | GET /api/memory/content | FAIL | status=400 |
| 90 | GET /api/memory/files | PASS | status=200 |
| 91 | DELETE /api/sessions/{id} nonexistent | PASS | status=404 |
| 92 | GET /api/audit/entries?session_id=... | PASS | status=200 |
| 93 | GET /api/sessions/{id}/receipt | PASS | status=200 |
| 94 | Session receipt has required fields | PASS | |
| 95 | WebSocket port 8081 is open | PASS | needed for chat |
| 96 | Config PATCH persists value | FAIL | after PATCH: {} |

---

## Screenshots

All screenshots saved to: `C:\Users\Administrator\Desktop\Cato\test_screenshots\`

| File | Description |
|------|-------------|
| T01_initial_load.png | First page load (onboarding dismissed) |
| T02_dashboard.png | Dashboard view |
| T03_chat.png | Chat view |
| T04_coding_agent.png | Coding Agent (Agents) view |
| T05_skills.png | Skills view |
| T06_cron_jobs.png | Cron Jobs view |
| T07_sessions.png | Sessions view |
| T08_usage.png | Usage view |
| T09_logs.png | Logs view |
| T10_audit_log.png | Audit Log view |
| T10b_audit_verify.png | After clicking Verify Chain |
| T11_config.png | Config view |
| T11b_config_save.png | After saveConfig() call |
| T12_budget.png | Budget view |
| T13_alerts.png | Alerts nav item click (page goes blank) |
| T14_auth_keys.png | Vault & Auth view |
| T15_identity_check.png | Confirming no identity page in web UI |
| T18_memory.png | Memory view |
| T19_system.png | System view (CLI pool, Action Guard) |
| T20_diagnostics.png | Diagnostics view |
| T20_diag_tab_0_Git URL.png | Diagnostics Git URL tab |
| T20_diag_tab_1_Upload SKI.png | Diagnostics Upload SKILL.md tab |
| T21_cron_created.png | After creating cron job via UI |
| T22_vault_key_added.png | After adding vault key via modal |
| T99_final_dashboard.png | Final state |

---

## Root Cause Analysis

### 1. Heartbeat 'unknown' (HB-001, DASH-001)

The `/api/heartbeat` endpoint exists to receive periodic pings from the running agent loop, but the agent loop never calls it. Root cause: no heartbeat POST is wired into `agent_loop.py` or `gateway.py`. Fix: add a background asyncio task that POSTs to `/api/heartbeat` every 30 seconds with `{"agent_name": "Cato", "uptime_seconds": ...}`.

### 2. Chat Raw XML Tool Calls (CHAT-001)

The MiniMax m2.5 model via OpenRouter outputs tool invocations as `<minimax:tool_call>` XML blocks. Root cause: the agent loop passes the raw LLM response text directly to the WebSocket client and to chat history without stripping tool call blocks. Fix: apply a regex or XML parser to remove `<minimax:tool_call>...</minimax:tool_call>` blocks from the response text before delivery.

### 3. Chat Cost Line in Messages (CHAT-002)

The agent loop appends `[$X.XXXX this call | Month: $X.XX/$20.00 | X% remaining]` to every response. Root cause: the budget summary is concatenated to the reply text in `gateway.py` or `agent_loop.py`. Fix: track budget internally and strip the bracket-enclosed cost line before sending to the WebSocket client.

### 4. Wrong Identity — 'I am Claude Code' (CHAT-003, CHAT-004)

The assistant responds as 'Claude Code' and attempts to call the Anthropic API to verify its identity. Root cause: SOUL.md and IDENTITY.md are not being injected into the system prompt, or the MiniMax model ignores the persona. Fix: (a) confirm workspace files are loaded and prepended to the system prompt on every request; (b) strengthen the system prompt with explicit first-person identity statements; (c) remove or gate the `anthropic-sdk` tool from the available toolset.

### 5. Config Not Persisting (CFG-001, CFG-002, CFG-004)

GET returns `{}`, PATCH returns `{status: ok}` but does not persist. Root cause: the config API handler does not read from or write to `%APPDATA%\cato\config.yaml`. Fix: wire the API to read/write the YAML config file using the same path resolution as `cato/vault.py` and the daemon startup code.

### 6. Alerts Page Broken Navigation (ALERTS-001)

`navigate('alerts')` is called but no `id="alerts-page"` div exists. The alerts HTML is embedded inside the diagnostics section. Fix: wrap the alerts HTML elements in a `<div id="alerts-page" class="page">` wrapper.

### 7. System Page Shows Tools as Cold (SYS-001)

Codex, Gemini, and Cursor show `logged_in: false`. Root cause: the `logged_in` probe in the CLI status checker may look for a specific auth file or config entry that is not present in the expected location. Fix: audit the logged_in detection logic in the CLI status handler for each tool — for Codex, check `~/.codex/` or similar; for Gemini, check `~/.gemini/`.

### 8. SQLite Thread Safety (DIAG-001)

`ContradictionDetector` creates a SQLite connection in the main thread but the aiohttp request handler runs in a different thread. Fix: open the connection with `check_same_thread=False`, or open a new connection per request in the diagnostics handler.

### 9. Memory Content 400 (MEM-001)

`GET /api/memory/content` returns 400. Root cause: likely requires query parameters (agent_id, type) that the Memory page JS does not supply. Fix: make query params optional with defaults, or update the client JS to include required params.

### 10. Missing Onboarding Dismissal in Tests

The web UI shows an onboarding wizard overlay (z-index 200) on first visit that intercepts all clicks. The overlay is controlled by `localStorage.getItem('cato_onboarded')`. This caused the initial test run to fail on all navigation. Fixed in the test script by injecting `localStorage.setItem('cato_onboarded', '1')` before testing.

---

## Verified Known Issues (from task brief)

| Known Issue | Status | Finding |
|-------------|--------|---------|
| Dashboard shows "heartbeat unknown" | CONFIRMED | Bug HB-001 + DASH-001 — agent loop never POSTs to /api/heartbeat |
| System page shows Codex/Gemini/Cursor as "cold" but coding agent says they work | CONFIRMED | Bug SYS-001 — logged_in check fails even though tools are installed and usable |
| Identity page save gives "failed to fetch" | PARTIALLY CONFIRMED | API PUT /api/workspace/file works correctly (returns 200). No dedicated Identity page in web UI (IDENT-004). In Tauri app, save uses PUT which works — "failed to fetch" may only occur when Tauri can't reach the daemon |
| Chat shows raw XML tool calls | CONFIRMED | Bug CHAT-001 — `<minimax:tool_call>` blocks visible in chat history and UI |
| Chat shows cost line | CONFIRMED | Bug CHAT-002 — `[$0.0000 this call \| Month: ...]` appended to every response |
| Chat says "I'm Claude Code" | CONFIRMED | Bug CHAT-003 — identity files not injected into system prompt |
| Missing Settings link in sidebar | PARTIALLY CONFIRMED | Bug NAV-003 — web UI sidebar has Settings items but no labeled 'Settings' group header |
