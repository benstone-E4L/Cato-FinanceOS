# Ralph Loop Guardrails - Cato OpenClaw Integration

## Purpose
Prevent repeated failures and enforce successful patterns across chunks.

---

## Critical Guardrails

### 1. **100% Test Pass Rate (LAW 2)**
- **MUST**: All pytest tests pass before chunk completion
- **MUST**: Run `pytest` before writing `<promise>` tag
- **FAILURE**: Even 1 failing test = chunk fails, retry
- **Command**: `pytest tests/ -v --tb=short`

### 2. **Token Budget Compliance**
- **MUST**: Keep system prompt under 8000 tokens
- **MUST**: Workspace files respect budget allocation:
  - SOUL.md: 500 tokens max
  - IDENTITY.md: 200 tokens max
  - AGENTS.md: 1000 tokens max
  - Daily logs: 500 tokens max
- **FAILURE**: Oversized context = agent fails, reduce scope

### 3. **Workspace Directory Correctness**
- **MUST**: Read workspace_dir from config.yaml first
- **MUST**: Fall back to `~/.cato/workspace` if not set
- **MUST**: Never hardcode paths (cross-platform compatibility)
- **FAILURE**: Workspace not found = all memory features fail

### 4. **Git Commits Required**
- **MUST**: Create descriptive commits after each successful chunk
- **MUST**: Include chunk number and feature in message
- **Format**: `chunk: 1 - create workspace template files`
- **FAILURE**: Missing commits = checkpoint lost, work may be lost

### 5. **Async/Await Consistency**
- **MUST**: Use `async/await` for all I/O operations
- **MUST**: Never mix callbacks with async patterns
- **MUST**: Handle exceptions with try/except in async code
- **FAILURE**: Mixing patterns = race conditions, chat duplicates

### 6. **Desktop App Build Compatibility**
- **MUST**: Test desktop app runs with new code
- **MUST**: No console.error in React components
- **MUST**: Tauri sidecar commands complete successfully
- **FAILURE**: Build breaks = E2E testing fails

### 7. **Web UI Responsiveness**
- **MUST**: All new UI elements responsive (mobile/tablet/desktop)
- **MUST**: No hardcoded widths that break on small screens
- **MUST**: Test settings panel on 360px width
- **FAILURE**: Unresponsive layout = user can't access settings

### 8. **API Endpoint Contract**
- **MUST**: Follow existing `/api/*` patterns
- **MUST**: Return consistent JSON structure: `{ success: bool, data?: any, error?: string }`
- **MUST**: Handle errors gracefully (no 500 errors)
- **FAILURE**: Broken API = UI cannot communicate with daemon

### 9. **Config YAML Structure**
- **MUST**: Validate YAML syntax after modification
- **MUST**: Use safe YAML loader (no security vulnerabilities)
- **MUST**: Backup config before major changes
- **FAILURE**: Invalid YAML = daemon won't start

### 10. **Vault Encryption Integrity**
- **MUST**: Store all sensitive data (tokens, keys) in vault
- **MUST**: Use AES-256-GCM encryption (existing implementation)
- **MUST**: Never log secrets to console or files
- **FAILURE**: Leaked credentials = security breach

---

## Per-Chunk Guardrails

### Chunk 1 (Workspace Templates)
- [ ] ✅ All 5 template files created with correct structure
- [ ] ✅ AGENTS.md under 1000 tokens
- [ ] ✅ MEMORY.md format supports semantic search
- [ ] ✅ Templates load on daemon startup without errors
- [ ] ✅ Desktop app wizard completes successfully
- [ ] ✅ 100% test pass rate

### Chunk 2 (Daily Log Auto-Creation)
- [ ] ✅ Daily log created automatically on first message
- [ ] ✅ Previous day log loaded for context
- [ ] ✅ Log archival process works (30+ day compression)
- [ ] ✅ No date-based race conditions
- [ ] ✅ Graceful handling of missing logs
- [ ] ✅ 100% test pass rate

### Chunk 3 (Semantic Memory Search)
- [ ] ✅ Embeddings generated without model download timeouts
- [ ] ✅ Search returns results in <500ms
- [ ] ✅ Relevant results ranked correctly (top-3 useful)
- [ ] ✅ Context injection respects token budget
- [ ] ✅ Search works on Windows (no Gemini CLI hangs)
- [ ] ✅ 100% test pass rate

### Chunk 4 (WhatsApp Integration)
- [ ] ✅ WhatsApp webhook receives messages correctly
- [ ] ✅ Messages route to correct agent instance
- [ ] ✅ Session isolation prevents cross-contamination
- [ ] ✅ Credentials safely stored in vault
- [ ] ✅ Message deduplication working
- [ ] ✅ 100% test pass rate

### Chunk 5 (Settings UI - Desktop)
- [ ] ✅ SettingsView component renders without errors
- [ ] ✅ All form inputs have validation
- [ ] ✅ Settings persist to config.yaml
- [ ] ✅ Settings load on app restart
- [ ] ✅ No console errors in browser/Tauri
- [ ] ✅ Responsive on 360px width
- [ ] ✅ 100% test pass rate

### Chunk 5b (Settings UI - Web)
- [ ] ✅ Settings panel accessible from navigation
- [ ] ✅ All form inputs have validation
- [ ] ✅ Settings POST to `/api/config` endpoint
- [ ] ✅ Settings GET and load correctly
- [ ] ✅ No console errors in browser
- [ ] ✅ Responsive on all screen sizes
- [ ] ✅ 100% test pass rate

---

## Known Issues to Avoid

### Issue 1: Gemini CLI Hangs on Windows
- **Symptom**: Semantic search timeout on Gemini
- **Cause**: Gemini CLI stdin detection in non-interactive mode
- **Fix**: Use sentence-transformers instead of Gemini for embeddings
- **Prevent**: Never call `gemini` subprocess for embeddings

### Issue 2: Chat Duplication
- **Symptom**: Messages appear twice in UI
- **Cause**: WebSocket + API endpoint both sending messages
- **Fix**: Deduplicate on timestamp + content hash
- **Prevent**: Filter `channel="web"` from history poll, dedup in UI

### Issue 3: Workspace Path Mismatch
- **Symptom**: SOUL.md not loaded, blank system prompt
- **Cause**: Hardcoded path instead of config.yaml reading
- **Fix**: Use `_workspace_dir()` helper in all places
- **Prevent**: Always read config first, fall back to ~/.cato/workspace

### Issue 4: Async Race Conditions
- **Symptom**: Random connection failures, false "Reconnecting"
- **Cause**: Callback hell instead of async/await
- **Fix**: Convert all WebSocket handlers to async/await
- **Prevent**: Use Python asyncio consistently, TypeScript async/await

### Issue 5: Token Budget Overflow
- **Symptom**: Agent gets degraded response, timeouts
- **Cause**: System prompt > 8000 tokens
- **Fix**: Trim workspace files, compress daily logs
- **Prevent**: Check token count before every chunk completion

---

## Success Indicators

✅ **Chunk 1**: Daemon starts, workspace files visible
✅ **Chunk 2**: Daily log created, previous log context injected
✅ **Chunk 3**: Memory search returns results, injected into prompt
✅ **Chunk 4**: WhatsApp messages received, routed to agent
✅ **Chunk 5**: Settings UI editable, changes persist

---

## Escalation Path

If chunk fails 5 times:
1. ❌ Ralph loop stops
2. 🔴 Call Hudson agent to diagnose root cause
3. 🔴 Hudson fixes and completes the chunk
4. ✅ Resume with Jason for migration
5. ✅ Continue with next chunk
