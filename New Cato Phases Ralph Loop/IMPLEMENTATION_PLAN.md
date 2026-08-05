# Implementation Plan - Cato OpenClaw Integration (5 Chunks)

**Total Subtasks**: 28 across 6 chunk sequences
**Max Iterations Per Chunk**: 5
**Test Requirement**: 100% pytest passing
**Git Checkpoints**: One per successful chunk
**Escalation**: Hudson if chunk fails 5x

---

## Chunk 1: Workspace Template Files (6 subtasks)

**Objective**: Create foundational workspace memory templates (AGENTS.md, MEMORY.md, USER.md, HEARTBEAT.md, TOOLS.md) + Desktop UI initialization wizard

**Subtasks**:
1. Create `/templates` folder with 5 .md template files
2. Update ContextBuilder to load and inject workspace files
3. Add workspace file validation
4. Implement Desktop app wizard (React component)
5. Create workspace initialization endpoint
6. Add unit tests for workspace loading

**Files to Create/Modify**:
- ✨ `~/.cato/workspace/AGENTS.md` (template)
- ✨ `~/.cato/workspace/MEMORY.md` (template)
- ✨ `~/.cato/workspace/USER.md` (template)
- ✨ `~/.cato/workspace/HEARTBEAT.md` (template)
- ✨ `~/.cato/workspace/TOOLS.md` (template)
- 📝 `cato/core/context_builder.py` (load all templates)
- ✨ `desktop/src/components/WorkspaceWizard.tsx` (new)
- ✨ `cato/api/workspace_routes.py` (new)
- 📝 `tests/test_workspace_templates.py` (new)

**Success Criteria**:
- ✅ All 5 template files exist and are valid markdown
- ✅ ContextBuilder loads and injects templates without errors
- ✅ Token budget respected (all files combined < 2200 tokens)
- ✅ Desktop app wizard creates workspace files
- ✅ Web API endpoints return workspace file contents
- ✅ 100% pytest pass rate

**Expected Iteration Count**: 2-3 (straightforward file creation)

---

## Chunk 2: Daily Log Auto-Creation (5 subtasks)

**Objective**: Automatically create and manage YYYY-MM-DD.md daily logs, with previous day context injection

**Subtasks**:
1. Implement daily log generator function
2. Add daily log to ContextBuilder injection
3. Create log browser component (date picker)
4. Implement log archival (compress 30+ day old logs)
5. Add tests for log generation and archival

**Files to Create/Modify**:
- ✨ `cato/core/daily_log_manager.py` (new)
- 📝 `cato/core/context_builder.py` (inject daily log)
- ✨ `desktop/src/components/LogBrowser.tsx` (new)
- 📝 `cato/ui/dashboard.html` (add log date display)
- ✨ `cato/api/logs_routes.py` (new)
- 📝 `tests/test_daily_logs.py` (new)

**Success Criteria**:
- ✅ YYYY-MM-DD.md auto-created on first message of day
- ✅ Previous day log loaded and injected for context
- ✅ Log archival compresses logs 30+ days old
- ✅ Log browser UI functional with date selection
- ✅ No race conditions (concurrent message edge case handled)
- ✅ 100% pytest pass rate

**Expected Iteration Count**: 2-3 (moderate complexity, date handling)

---

## Chunk 3: Semantic Memory Search (5 subtasks)

**Objective**: Implement vector-based semantic search using sentence-transformers over MEMORY.md and logs

**Subtasks**:
1. Initialize sentence-transformers model on daemon startup
2. Implement vector search function (embed + search)
3. Add search result injection to ContextBuilder
4. Create memory search API endpoint
5. Add search UI to desktop + web, with tests

**Files to Create/Modify**:
- ✨ `cato/core/semantic_search.py` (new)
- 📝 `cato/core/context_builder.py` (inject search results)
- ✨ `cato/api/search_routes.py` (new)
- ✨ `desktop/src/components/MemorySearch.tsx` (new)
- 📝 `cato/ui/dashboard.html` (add search box)
- 📝 `tests/test_semantic_search.py` (new)

**Success Criteria**:
- ✅ Embeddings generated on startup (< 5 second delay)
- ✅ Search completes in < 500ms
- ✅ Top-3 results relevant to query
- ✅ Results injected without exceeding token budget
- ✅ Works on Windows (no Gemini CLI dependency)
- ✅ 100% pytest pass rate

**Expected Iteration Count**: 3-4 (model initialization, performance tuning)

---

## Chunk 4: WhatsApp Integration (5 subtasks)

**Objective**: Add WhatsApp as a channel alongside Telegram, with webhook + routing + tests

**Subtasks**:
1. Research WhatsApp Cloud API integration points
2. Implement WhatsApp webhook handler
3. Update gateway for WhatsApp routing
4. Add WhatsApp config to YAML with vault storage
5. Add comprehensive tests for messaging

**Files to Create/Modify**:
- ✨ `cato/api/whatsapp_handler.py` (new)
- 📝 `cato/gateway.py` (register WhatsApp channel)
- 📝 `cato/vault.py` (add WhatsApp credential storage)
- 📝 `config.yaml` (add whatsapp section)
- ✨ `tests/test_whatsapp_integration.py` (new)
- 📝 `cato/core/schedule_manager.py` (route WhatsApp messages)

**Success Criteria**:
- ✅ WhatsApp webhook receives messages
- ✅ Messages route to correct agent
- ✅ Session isolation per WhatsApp chat
- ✅ Credentials stored in vault (not plaintext)
- ✅ Message deduplication working
- ✅ 100% pytest pass rate

**Expected Iteration Count**: 3-4 (API integration, edge cases)

---

## Chunk 5: Settings UI - Desktop App (6 subtasks)

**Objective**: Create Settings panel in React for configuring memory, channels, scheduling, workspace

**Subtasks**:
1. Create SettingsView.tsx component
2. Build Memory Settings tab (edit SOUL.md, IDENTITY.md, USER.md)
3. Build Channels Settings tab (Telegram + WhatsApp config)
4. Build Scheduling Settings tab (heartbeat, archival, search thresholds)
5. Build Workspace Settings tab (initialize, upload, download)
6. Route Settings in App.tsx sidebar

**Files to Create/Modify**:
- ✨ `desktop/src/views/SettingsView.tsx` (new)
- ✨ `desktop/src/components/MemorySettingsTab.tsx` (new)
- ✨ `desktop/src/components/ChannelsSettingsTab.tsx` (new)
- ✨ `desktop/src/components/SchedulingSettingsTab.tsx` (new)
- ✨ `desktop/src/components/WorkspaceSettingsTab.tsx` (new)
- 📝 `desktop/src/App.tsx` (route to Settings)
- ✨ `desktop/src/hooks/useSettings.ts` (new - fetch/save settings)
- 📝 `cato/api/config_routes.py` (new - GET/POST config)

**Success Criteria**:
- ✅ SettingsView renders without console errors
- ✅ All form inputs have validation
- ✅ Settings persist to config.yaml via API
- ✅ Settings load on app restart
- ✅ Responsive on 360px+ screens
- ✅ No Tauri errors on window
- ✅ 100% pytest pass rate

**Expected Iteration Count**: 3-4 (form validation, state management)

---

## Chunk 5b: Settings UI - Web Dashboard (6 subtasks)

**Objective**: Create Settings panel in vanilla JavaScript for web UI

**Subtasks**:
1. Create Settings view in dashboard.html
2. Build Memory Settings panel (edit files)
3. Build Channels Settings panel (Telegram + WhatsApp)
4. Build Scheduling Settings panel
5. Build Workspace Settings panel
6. Wire up API calls to persist settings

**Files to Create/Modify**:
- 📝 `cato/ui/dashboard.html` (add Settings tab + panels)
- ✨ `cato/ui/js/settings-manager.js` (new - handle settings logic)
- 📝 `cato/api/config_routes.py` (GET/POST endpoints)

**Success Criteria**:
- ✅ Settings tab accessible from navigation
- ✅ All panels functional with validation
- ✅ Settings POST to `/api/config`
- ✅ Settings GET and load correctly
- ✅ Responsive on mobile/tablet/desktop
- ✅ No console errors
- ✅ 100% pytest pass rate

**Expected Iteration Count**: 2-3 (straightforward web form)

---

## Completion Workflow

### After Each Chunk:

1. **Test Phase**
   - Run: `pytest tests/ -v --tb=short`
   - MUST: 100% pass rate (no exceptions)
   - If fail: Debug and iterate (up to 5 times)

2. **Git Checkpoint**
   - Commit: `chunk: N - [feature description]`
   - Message: 1-2 sentences
   - Include subtask checklist status

3. **Migration Handoff**
   - Pass to Jason agent
   - Jason runs: migration to integrate chunk
   - Jason returns control

4. **Progress Update**
   - Update `.ralph/progress.md`
   - Increment chunk counter
   - Record iteration count

### After All Chunks:

1. **Alex Agent Audit**
   - Full code review
   - Run all tests (must be 100%)
   - Generate CATO_ALEX_AUDIT.md
   - Must be: APPROVED

2. **Kraken E2E Testing**
   - Run `/web-app-e2e-tester` on desktop app
   - Run `/web-app-e2e-tester` on web UI
   - Fix issues as found
   - Generate CATO_KRAKEN_VERDICT.md

3. **Final Push**
   - Git push to main
   - All features live

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Chunk fails 5x | Escalate to Hudson agent |
| Token budget exceeded | Compress workspace files, trim logs |
| Async race conditions | Test with concurrent messages |
| Windows path issues | Use Path.home(), test cross-platform |
| Desktop app crashes | Test Tauri sidecar messages |
| Web UI unresponsive | Test on 360px viewport |
| API endpoint breaks | Follow existing patterns, test routes |
| Vault encryption fails | Never log secrets, validate encryption |
| Git conflicts | Merge main before chunk 1, rebase if needed |

---

## Success Metrics

✅ **Execution**: 0 failed iterations (deterministically successful)
✅ **Testing**: 100% pytest pass rate (1346+ tests)
✅ **Quality**: Alex audit APPROVED
✅ **Functionality**: Kraken E2E test PASSED
✅ **Integration**: All 5 phases fully working
✅ **Performance**: Search <500ms, daily log creation instant
✅ **Security**: All secrets in vault, no plaintext credentials
