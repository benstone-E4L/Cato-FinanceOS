# Cato Web UI — Consolidated Task List

**Source**: WEB_UI_AUDIT_TASKS.md + CODEBASE_CROSS_REFERENCE_TASKS.md
**Date**: 2026-03-09
**Target**: `cato/ui/dashboard.html` (monolithic SPA) + `cato/ui/server.py` (Python backend)

---

## CHUNK 1: Critical Fixes (Blocking Navigation + Security)

- [ ] **Onboarding overlay blocks ALL navigation**: The `<div id="onboarding-overlay">` intercepts pointer events on every nav item click. ALL 17 navigation bugs in the audit are this single root cause. Fix: Either remove the overlay after onboarding completes, add `pointer-events: none` when not active, or add a dismiss/close mechanism.
- [ ] **Config endpoint leaks secrets**: `/api/config` returns `telegram_bot_token` in plaintext. Filter sensitive keys (tokens, passwords, secrets) before returning. (Same fix as desktop — shared backend.)
- [ ] **CORS PUT Method**: Add `PUT` to CORS allowed methods. (Same fix as desktop — shared backend.)

**Verification**: Load `http://127.0.0.1:8080/` in browser. Click every nav item — all should work.

---

## CHUNK 2: Bot Identity & Display Fixes

- [ ] **Bot name "AI" → "Cato"**: Replace hardcoded "AI" in bot avatar elements at lines 1432 (renderMessages), 1439 (typing-indicator), 1549 (startStreaming) in `dashboard.html`. Should be "Cato" or configurable from identity.
- [ ] **Version hardcoded v0.1.0**: Dashboard shows v0.1.0. Should read version from `/health` endpoint (after backend fix to return correct version).
- [ ] **Heartbeat timestamp display**: Dashboard shows heartbeat status badge but not the `last_heartbeat` timestamp from the API. Add timestamp display so users can see WHEN the last heartbeat was.
- [ ] **CLI auth status confusion**: Vault & Auth section shows "not logged in" for CLIs where `--version` timed out. Align with backend fix to separate `installed` from `logged_in`.

**Verification**: Load dashboard, verify "Cato" appears instead of "AI", version shows 0.2.0.

---

## CHUNK 3: Navigation & UX Improvements

- [ ] **Identity/Agents overlap**: Identity page and Agents page show overlapping files (SOUL.md, IDENTITY.md, USER.md, AGENTS.md). Deduplicate: Identity page should be the canonical editor, Agents page should focus on agent-specific files (TOOLS.md, HEARTBEAT.md, MEMORY.md) or be merged.
- [ ] **No retry/reconnect button**: Vault & Auth page has no button to re-check CLI status. Add a "Re-check" button.
- [ ] **No working/thinking indicator**: Chat send button shows no loading state. Add spinner or "Working..." text during message processing.
- [ ] **Dashboard monolithic file**: `dashboard.html` is 1700+ lines. Consider splitting into sections with `<template>` tags or converting key sections to reusable functions for maintainability.

**Verification**: All navigation works. Retry buttons functional. Chat shows working state.

---

## CHUNK 4: Missing Feature Parity with Desktop

- [ ] **Diagnostics view**: Desktop has 5 diagnostic tabs (Query Tiers, Contradictions, Decisions, Anomalies, Corrections). Web UI has none. Add diagnostics section.
- [ ] **Coding agent view**: Desktop has full CodingAgentView with task creation. Web UI has separate `coding_agent.html` — ensure it's properly linked from dashboard nav.
- [ ] **Alerts/Budget threshold view**: Desktop has AlertsView with budget threshold controls. Web UI budget section may lack threshold configuration.
- [ ] **Sessions detail view**: Desktop has SessionsView with checkpoint browsing. Web UI sessions section may be basic.
- [ ] **Replay view**: Desktop has ReplayView for session replay. Web UI has no equivalent.

**Verification**: All views accessible and functional in web UI.

---

## CHUNK 5: Backend API Improvements (Shared)

- [ ] **Per-CLI restart endpoint**: `POST /api/cli/{name}/restart` — same endpoint used by desktop.
- [ ] **Proper CLI auth detection**: Separate `installed` check (shutil.which) from `logged_in` check (actual auth state, not version command).
- [ ] **Heartbeat with system metrics**: Include CPU/memory/disk in heartbeat response via `psutil`.
- [ ] **Delegation token API**: `GET /api/tokens`, `POST /api/tokens`, `DELETE /api/tokens/{id}`.
- [ ] **Disagreement surfacer API**: `GET /api/diagnostics/disagreements`.

**Verification**: `pytest tests/ -x --tb=short` — 100% pass rate.

---

## SUMMARY

| Chunk | Tasks | Focus |
|-------|-------|-------|
| 1 | 3 | Critical blockers (overlay, security, CORS) |
| 2 | 4 | Bot identity & display |
| 3 | 4 | Navigation & UX |
| 4 | 5 | Feature parity with desktop |
| 5 | 5 | Backend API improvements |
| **Total** | **21** | |
