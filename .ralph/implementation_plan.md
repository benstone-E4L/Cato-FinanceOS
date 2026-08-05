# CATO INTEGRATION IMPLEMENTATION PLAN
# Generated: 2026-03-08
# Owner: Ralph Wiggum Loop

## OBJECTIVE
Integrate all backend modules from cato/ into the Cato Desktop App and Web UI.
Fix broken save buttons. Add missing views for every exposed API route.
Max 5 iterations per chunk. Escalate to Hudson if chunk fails after 5 iterations.
Backend-architect handles migration/wiring after each chunk. Alex assembles. Kraken audits live.

---

## CHUNKS

### CHUNK 1 — Fix Broken Save Buttons (CRITICAL)
**Files:** SkillsView.tsx, IdentityView.tsx (investigate why save fails)
**Tasks:**
- [ ] Add Save button + save() fn to SkillsView.tsx (PATCH /api/skills/{name}/content)
- [ ] Add "saved" toast/banner to SkillsView.tsx
- [ ] Debug IdentityView.tsx save (button disabled when isDirty=false — investigate why)
- [ ] Verify workspace_put route in server.py returns correct JSON
- [ ] Test both saves end-to-end against live daemon
**Escalation:** Hudson if >5 iterations

### CHUNK 2 — Memory View
**Files:** NEW desktop/src/views/MemoryView.tsx, server.py (routes already exist)
**Tasks:**
- [ ] Create MemoryView.tsx with tabs: Facts | Chunks | Stats | Graph
- [ ] Facts tab: list stored facts, search, delete individual facts
- [ ] Stats tab: total facts, kg_nodes, kg_edges, embedding model, DB size
- [ ] Chunks tab: recent context chunks with token counts
- [ ] Wire /api/memory/files, /api/memory/content, /api/memory/stats
- [ ] Add "Memory" to Sidebar nav (Monitoring group)
- [ ] Update App.tsx with MemoryView import + case
**Escalation:** Hudson if >5 iterations

### CHUNK 3 — CLI Process Pool Monitor + Action Guard Dashboard
**Files:** NEW desktop/src/views/SystemView.tsx
**Tasks:**
- [ ] Create SystemView.tsx with two panels:
  - Panel A: CLI Process Pool (GET /api/cli/status) — warm/cold status, model PIDs
  - Panel B: Action Guard (GET /api/action-guard/status) — 3-rule gate status, autonomy level
  - Panel C: Daemon restart button (POST /api/daemon/restart)
- [ ] Add "System" to Sidebar nav (Settings group)
- [ ] Update App.tsx
**Escalation:** Hudson if >5 iterations

### CHUNK 4 — Replay Visualization
**Files:** NEW desktop/src/views/ReplayView.tsx, update SessionsView.tsx
**Tasks:**
- [ ] Create ReplayView.tsx — shows step-by-step replay with match/mismatch
- [ ] Add "Replay" button to SessionsView.tsx that triggers POST /api/sessions/{id}/replay
- [ ] Navigate to ReplayView with results after replay completes
- [ ] Show: total steps, matched %, mismatched list, timing per step
- [ ] Update App.tsx + Sidebar
**Escalation:** Hudson if >5 iterations

### CHUNK 5 — Skill Improvement + Diagnostics Panel
**Files:** server.py (new routes), NEW desktop/src/views/DiagnosticsView.tsx
**Tasks:**
- [ ] Add GET /api/diagnostics/query-classifier — expose QueryClassifier tier decisions
- [ ] Add GET /api/diagnostics/skill-corrections — list stored corrections
- [ ] Add GET /api/diagnostics/contradiction-health — ContradictionDetector health summary
- [ ] Add GET /api/diagnostics/decision-memory — DecisionMemory open decisions + overconfidence
- [ ] Add GET /api/diagnostics/anomaly-domains — AnomalyDetector domain summaries
- [ ] Create DiagnosticsView.tsx with tabs for each diagnostic
- [ ] Add "Diagnostics" to Sidebar nav (Monitoring group)
- [ ] Update App.tsx
**Escalation:** Hudson if >5 iterations

### CHUNK 6 — Adapter Status + Heartbeat View
**Files:** server.py (new routes), update DashboardView.tsx
**Tasks:**
- [ ] Add GET /api/adapters — list active adapters (Telegram, WhatsApp) and their status
- [ ] Add GET /api/heartbeat — last heartbeat timestamp + agent name + uptime
- [ ] Add adapter status pills to DashboardView.tsx
- [ ] Add heartbeat info to DashboardView.tsx
- [ ] Wire Telegram adapter status to ConfigView.tsx (already has Telegram section)
**Escalation:** Hudson if >5 iterations

### CHUNK 7 — Session Checkpoints + Receipts
**Files:** server.py (new routes), update SessionsView.tsx, AuditLogView.tsx
**Tasks:**
- [ ] Add GET /api/sessions/{id}/checkpoints — list checkpoints for session
- [ ] Add GET /api/sessions/{id}/checkpoints/{checkpoint_id} — get checkpoint summary
- [ ] Add GET /api/sessions/{id}/receipt — generate signed receipt (receipt.py)
- [ ] Add "Checkpoints" tab to SessionsView.tsx
- [ ] Add "Download Receipt" button to AuditLogView.tsx
- [ ] Update SessionsView.tsx to show checkpoint count per session
**Escalation:** Hudson if >5 iterations

### CHUNK 8 — Web UI (dashboard.html + coding_agent.html) Sync
**Files:** cato/ui/dashboard.html, cato/ui/coding_agent.html
**Tasks:**
- [ ] Audit dashboard.html for all nav items — add Memory, System, Diagnostics, Replay pages
- [ ] Add JS handlers for Memory page (facts table, stats, search)
- [ ] Add JS handlers for System page (CLI pool status, action guard, daemon restart)
- [ ] Add JS handlers for Diagnostics page
- [ ] Fix MODEL_ICONS in coding_agent.html (C/X/G/⊕) — keep as text abbreviations (these are intentional)
- [ ] Verify coding_agent.html has logo in header (currently favicon only)
**Escalation:** Hudson if >5 iterations

---

## INTEGRATION RULES

1. All new views follow existing patterns (fetch on mount, auto-refresh where needed)
2. All new API routes follow existing handler pattern in server.py
3. All new views exported as named + default export
4. All new routes registered in router section of server.py
5. Tests must stay 100% passing after every chunk
6. No hardcoded ports — use httpPort prop
7. Error states shown with existing .error-banner / .page-error classes
8. Loading states shown with .app-loading-spinner

---

## AGENT HANDOFF PROTOCOL

```
Ralph Loop → chunk complete
     ↓
backend-architect → migration/wiring verification
     ↓
Next chunk (Ralph Loop)
     ↓
[After all chunks]
     ↓
Alex → assemble + integration check
     ↓
Kraken → live audit + fix
     ↓
DONE
```
