# Cato Desktop App — Consolidated Task List

**Source**: DESKTOP_APP_AUDIT_TASKS.md + CODEBASE_CROSS_REFERENCE_TASKS.md
**Date**: 2026-03-09
**Target**: `desktop/src/` (React/TypeScript) + `cato/ui/server.py` (Python backend)

---

## CHUNK 1: Critical Bug Fixes (Backend + CORS)

- [ ] **CORS PUT Method**: Add `PUT` to `Access-Control-Allow-Methods` in `cato/ui/server.py` lines 75 and 81. Change `"GET, POST, PATCH, DELETE, OPTIONS"` to `"GET, POST, PUT, PATCH, DELETE, OPTIONS"`. This fixes Identity page save failure.
- [ ] **Config endpoint leaks secrets**: `/api/config` in `cato/ui/server.py` returns full config dict including `telegram_bot_token` in plaintext. Filter sensitive keys before returning.
- [ ] **Duplicate route registration**: Both `server.py` and `websocket_handler.py` register `GET /api/config` and `PATCH /api/config`. Remove duplicates from `websocket_handler.py`.
- [ ] **CLI login detection wrong**: `server.py` line 396 equates `--version` command success with `logged_in=True`. This is incorrect — version check timeout != not authenticated. Fix to separate `installed` from `logged_in` properly.
- [ ] **Version hardcoded as v0.1.0**: `/health` endpoint returns hardcoded `version=0.1.0`. Should read from `cato/__init__.py` or `pyproject.toml` (actual version is 0.2.0).
- [ ] **Add per-CLI restart endpoint**: Create `POST /api/cli/{name}/restart` endpoint that restarts a specific CLI backend process in the warm pool.

**Verification**: `pytest tests/ -x --tb=short` — 100% pass rate required.

---

## CHUNK 2: Chat System Fixes

- [ ] **Send button working state**: In `ChatView.tsx` line 151-156, change `Send` to `{isStreaming ? "Working..." : "Send"}`. Also disable the button while streaming.
- [ ] **Chat double messages**: In `useChatStream.ts`, WS creates `crypto.randomUUID()` IDs (line 132), history poll returns `{session_id}-{timestamp}-{index}` IDs. Same message gets two different IDs = appears twice. Fix: Use a content+timestamp hash for dedup instead of relying solely on ID matching, OR have the WS response include the server-assigned ID.
- [ ] **Chat WS race condition**: `[useChatStream] WebSocket error` logged during view mount/unmount. Add cleanup guard: check if component is still mounted before setting state after WS events.

**Verification**: Build `npm run build` in `desktop/` — no TypeScript errors.

---

## CHUNK 3: AuthKeys & System View Fixes

- [ ] **AuthKeysView live status**: Replace hardcoded `CLI_BACKENDS` const (lines 21-50) with live data fetched from `/api/cli/status`. Derive Working/Degraded badges from `installed` and `logged_in` fields.
- [ ] **AuthKeysView restart buttons**: Add per-backend restart/reconnect button that calls `POST /api/cli/{name}/restart`.
- [ ] **SystemView restart buttons**: Add per-model restart button in CliPoolPanel cards that calls `POST /api/cli/{name}/restart`.
- [ ] **SystemView + AuthKeysView consistency**: Both views should show identical data from the same `/api/cli/status` endpoint.

**Verification**: `npm run build` in `desktop/` — no errors. Manual visual check.

---

## CHUNK 4: Diagnostics View Expansion

- [ ] **Disagreement Surfacer tab**: Add tab in DiagnosticsView for `cato/orchestrator/disagreement_surfacer.py`. Create API endpoint `GET /api/diagnostics/disagreements` that returns multi-model disagreement data.
- [ ] **Epistemic Monitor tab**: Add tab in DiagnosticsView for `cato/orchestrator/epistemic_monitor.py`. Create API endpoint `GET /api/diagnostics/epistemic` that returns premise gaps.
- [ ] **Context Budget tab**: Add tab in DiagnosticsView for `cato/core/context_builder.py` SlotBudget. Create API endpoint `GET /api/diagnostics/context-budget` that returns tier0/1/2/3 allocation.
- [ ] **Retrieval Stats tab**: Add tab in DiagnosticsView for `cato/core/retrieval.py` HybridRetriever. Create API endpoint `GET /api/diagnostics/retrieval` that returns retrieval metrics.
- [ ] **Habit Extractor tab**: Add tab in DiagnosticsView for `cato/personalization/habit_extractor.py`. Create API endpoint `GET /api/diagnostics/habits` that returns extracted patterns.

**Verification**: `pytest tests/ -x --tb=short` — 100% pass. `npm run build` — no errors.

---

## CHUNK 5: Missing Module Integrations

- [ ] **WhatsApp adapter config UI**: Add WhatsApp configuration panel in AuthKeysView or a new AdaptersView. Wire to existing `cato/adapters/whatsapp.py`.
- [ ] **Ledger verification UI**: Add a "Verify Ledger" button in AuditLogView that calls the existing `verify_chain` from `cato/audit/ledger.py`.
- [ ] **Delegation token management**: Add UI for `cato/auth/token_store.py` — list, create, revoke delegation tokens. Create API endpoints: `GET /api/tokens`, `POST /api/tokens`, `DELETE /api/tokens/{id}`.
- [ ] **Confidence extractor display**: Show confidence scores in CodingAgentView sidebar from `cato/orchestrator/confidence_extractor.py`.
- [ ] **Early termination indicator**: Show when early termination occurs in CodingAgentView from `cato/orchestrator/early_terminator.py`.

**Verification**: `pytest tests/ -x --tb=short` — 100% pass. `npm run build` — no errors.

---

## CHUNK 6: Advanced Feature Integrations

- [ ] **Intelligent heartbeat**: Enhance `cato/heartbeat.py` to collect system metrics (CPU, memory, disk via `psutil`). Update `/api/heartbeat` response. Show metrics in DashboardView.
- [ ] **Config hot reload**: Add file watcher in `cato/config.py` to detect config changes and apply without daemon restart. Add "Config changed" notification in ConfigView.
- [ ] **Hooks/Lifecycle system**: Create `cato/hooks.py` with `register_hook(event, callback)` for `pre_message`, `post_message`, `pre_tool`, `post_tool`, `on_error`. Add UI panel in SystemView.
- [ ] **Plugin architecture**: Create `cato/plugins/` with entry-point based plugin discovery. Add "Plugins" view in desktop app sidebar.
- [ ] **Search provider fallback chain**: Add fallback chain (Brave → DuckDuckGo → Tavily) to `cato/tools/web_search.py`. Add config UI for search provider priority.

**Verification**: `pytest tests/ -x --tb=short` — 100% pass. `npm run build` — no errors.

---

## SUMMARY

| Chunk | Tasks | Focus |
|-------|-------|-------|
| 1 | 6 | Critical backend bug fixes |
| 2 | 3 | Chat system fixes |
| 3 | 4 | AuthKeys + System consistency |
| 4 | 5 | Diagnostics expansion |
| 5 | 5 | Missing module integrations |
| 6 | 5 | Advanced features |
| **Total** | **28** | |
