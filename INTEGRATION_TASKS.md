# CATO INTEGRATION TASKS
# Complete list of missing integrations between cato/ backend and desktop/web UI
# Generated: 2026-03-08 via full codebase audit

---

## BUGS TO FIX (Existing Views)

### BUG-1: SkillsView.tsx — No Save Button
- **File:** `desktop/src/views/SkillsView.tsx`
- **Problem:** Textarea has `onChange` handler updating `content` state, but there is NO save button and NO save function. Edits are lost on navigation.
- **Fix:** Add `save()` fn calling `PATCH /api/skills/{name}/content`, add Save button + toast
- **Route exists:** YES — `PATCH /api/skills/{name}/content` in server.py
- **Priority:** CRITICAL

### BUG-2: IdentityView.tsx — Save Button Disabled
- **File:** `desktop/src/views/IdentityView.tsx`
- **Problem:** Save button is disabled when `content === originalContent` (isDirty=false). The save() function itself is correct. The issue is the `btn-primary` class may have styling that hides the disabled state, or the file fetch isn't populating `originalContent` correctly on first load.
- **Fix:** Investigate CSS for btn-primary:disabled, verify originalContent is set on fetch, add visual dirty indicator
- **Route exists:** YES — `PUT /api/workspace/file` in server.py
- **Priority:** CRITICAL

---

## MISSING VIEWS (New Views Required)

### VIEW-1: MemoryView.tsx
- **Purpose:** Browse and manage Cato's hybrid memory (facts, knowledge graph, chunks)
- **Backend routes available:**
  - `GET /api/memory/files` — list memory docs
  - `GET /api/memory/content` — read memory chunk/fact content
  - `PATCH /api/memory/content` — edit memory facts
  - `GET /api/memory/stats` — facts count, kg_nodes, kg_edges counts
- **UI tabs:** Facts | Graph | Stats
- **Sidebar:** Monitoring group → "Memory" (🧠)
- **Priority:** HIGH

### VIEW-2: SystemView.tsx
- **Purpose:** System diagnostics — CLI process pool status, action guard, daemon controls
- **Backend routes available:**
  - `GET /api/cli/status` — warm/cold status per model (claude/codex/gemini/cursor)
  - `GET /api/action-guard/status` — 3-rule safety gate status, autonomy level
  - `POST /api/daemon/restart` — restart daemon
- **UI panels:** Process Pool | Safety Gate | Daemon Controls
- **Sidebar:** Settings group → "System" (⚙️)
- **Priority:** HIGH

### VIEW-3: DiagnosticsView.tsx
- **Purpose:** Internal AI diagnostics — query classification, decision memory, contradiction health
- **Backend routes needed (NEW):**
  - `GET /api/diagnostics/query-classifier` — recent tier decisions (A/B/C)
  - `GET /api/diagnostics/skill-corrections` — correction store entries
  - `GET /api/diagnostics/contradiction-health` — Jaccard health summary
  - `GET /api/diagnostics/decision-memory` — open decisions + overconfidence profile
  - `GET /api/diagnostics/anomaly-domains` — domain anomaly summaries
- **UI tabs:** Query Tiers | Corrections | Contradictions | Decisions | Anomalies
- **Sidebar:** Monitoring group → "Diagnostics" (🔬)
- **Priority:** MEDIUM

### VIEW-4: ReplayView.tsx
- **Purpose:** Visualize session replay results (dry-run audit validation)
- **Backend routes available:**
  - `POST /api/sessions/{session_id}/replay` — trigger dry-run replay
- **UI:** Step list with match/mismatch badges, timing, summary stats
- **Integration:** Add "Replay" button to SessionsView.tsx that navigates to ReplayView
- **Sidebar:** NOT a standalone nav item — launched from SessionsView
- **Priority:** MEDIUM

---

## MISSING API ROUTES (New Routes Required)

### ROUTE-1: Adapter Status
- **Route:** `GET /api/adapters`
- **Handler:** List active adapters (Telegram, WhatsApp) and connection status
- **Source:** `cato/adapters/telegram.py`, `cato/adapters/whatsapp.py`
- **UI:** DashboardView.tsx adapter pills + ConfigView.tsx
- **Priority:** MEDIUM

### ROUTE-2: Heartbeat Status
- **Route:** `GET /api/heartbeat`
- **Handler:** Last heartbeat timestamp, agent name, uptime
- **Source:** `cato/heartbeat.py` — `HeartbeatMonitor`
- **UI:** DashboardView.tsx heartbeat section
- **Priority:** MEDIUM

### ROUTE-3: Session Checkpoints
- **Routes:**
  - `GET /api/sessions/{id}/checkpoints` — list checkpoints
  - `GET /api/sessions/{id}/checkpoints/{cid}` — get checkpoint summary
- **Source:** `cato/core/session_checkpoint.py` — `SessionCheckpoint`
- **UI:** SessionsView.tsx — new "Checkpoints" tab
- **Priority:** MEDIUM

### ROUTE-4: Session Receipt
- **Route:** `GET /api/sessions/{id}/receipt`
- **Handler:** Generate signed receipt (cost, actions, hash chain)
- **Source:** `cato/receipt.py` — `ReceiptWriter`
- **UI:** AuditLogView.tsx — "Download Receipt" button
- **Priority:** LOW

### ROUTE-5: Query Classifier Diagnostics
- **Route:** `GET /api/diagnostics/query-classifier`
- **Handler:** Return recent query tier decisions with reasoning
- **Source:** `cato/orchestrator/query_classifier.py`
- **UI:** DiagnosticsView.tsx
- **Priority:** MEDIUM

### ROUTE-6: Contradiction Health
- **Route:** `GET /api/diagnostics/contradiction-health`
- **Handler:** ContradictionDetector health summary (resolved/unresolved counts)
- **Source:** `cato/memory/contradiction_detector.py`
- **UI:** DiagnosticsView.tsx
- **Priority:** MEDIUM

### ROUTE-7: Decision Memory
- **Route:** `GET /api/diagnostics/decision-memory`
- **Handler:** Open decisions + overconfidence profile
- **Source:** `cato/memory/decision_memory.py`
- **UI:** DiagnosticsView.tsx
- **Priority:** MEDIUM

### ROUTE-8: Anomaly Detector Domains
- **Route:** `GET /api/diagnostics/anomaly-domains`
- **Handler:** Domain anomaly detection summaries
- **Source:** `cato/monitoring/anomaly_detector.py`
- **UI:** DiagnosticsView.tsx
- **Priority:** LOW

---

## WEB UI SYNC (dashboard.html / coding_agent.html)

### WEB-1: dashboard.html — Add Missing Pages
- Memory page (facts browser, stats)
- System page (CLI pool status, action guard)
- Diagnostics page (contradiction health, decision memory)
- Adapters status section on Dashboard page

### WEB-2: dashboard.html — Save Buttons
- Skills page in web UI: verify save button works
- Identity page in web UI: verify save button works

### WEB-3: coding_agent.html — Header
- Verify logo appears in header (favicon-only currently)

---

## SUMMARY TABLE

| Item | Type | Priority | Chunk | Status |
|------|------|----------|-------|--------|
| SkillsView save button | BUG FIX | CRITICAL | 1 | PENDING |
| IdentityView save debugging | BUG FIX | CRITICAL | 1 | PENDING |
| MemoryView.tsx | NEW VIEW | HIGH | 2 | PENDING |
| SystemView.tsx | NEW VIEW | HIGH | 3 | PENDING |
| ReplayView.tsx + SessionsView btn | NEW VIEW | MEDIUM | 4 | PENDING |
| DiagnosticsView.tsx | NEW VIEW | MEDIUM | 5 | PENDING |
| GET /api/adapters | NEW ROUTE | MEDIUM | 6 | PENDING |
| GET /api/heartbeat | NEW ROUTE | MEDIUM | 6 | PENDING |
| GET /api/sessions/{id}/checkpoints | NEW ROUTE | MEDIUM | 7 | PENDING |
| GET /api/sessions/{id}/receipt | NEW ROUTE | LOW | 7 | PENDING |
| GET /api/diagnostics/* (5 routes) | NEW ROUTES | MEDIUM | 5 | PENDING |
| dashboard.html memory/system pages | WEB UI | MEDIUM | 8 | PENDING |
| dashboard.html identity/skill save verify | WEB UI | HIGH | 8 | PENDING |

**Total: 2 bugs, 4 new views, 8 new routes, 1 web UI sync**
