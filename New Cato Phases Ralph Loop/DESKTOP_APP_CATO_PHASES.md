# Cato Desktop App: OpenClaw Feature Integration (Phases 1-5)

## Overview

Integration of OpenClaw memory, scheduling, and channel management features into Cato Desktop App (Tauri v2 React/TypeScript).

\---

## Phase 1: Workspace Memory Templates

### Objective

Create template workspace files (.md) to establish OpenClaw-style bootstrap memory system.

* \[ ] **1.1** Create `AGENTS.md` template (operating manual, \~100 lines max)

  * Agent thinking patterns
  * Tool usage guidelines
  * Safety rules and constraints
  * Decision-making framework
  * Example: "Always verify before executing destructive commands"
* \[ ] **1.2** Create `MEMORY.md` template (long-term semantic memory)

  * Long-term facts and decisions
  * Technical configuration notes
  * Project decisions made together
  * Example: "Primary API endpoint: api.example.com"
* \[ ] **1.3** Create `USER.md` template (user profile)

  * How to address the user
  * User preferences and habits
  * Communication style
  * Example: "User prefers brief, technical responses"
* \[ ] **1.4** Create `HEARTBEAT.md` template (periodic checklist)

  * Regular monitoring tasks
  * Health checks to perform
  * Example: "Check daemon process running", "Verify API connectivity"
* \[ ] **1.5** Create `TOOLS.md` template (local tool hints)

  * Available scripts and tools
  * Command shortcuts
  * Example: "run\_tests.sh → pytest tests/"
* \[ ] **1.6** Add workspace initialization UI in Desktop App

  * React component to create template files
  * Guided setup wizard
  * Verify file creation
  * Sync templates to daemon config path

### Acceptance Criteria

* ✅ All 5 template files created in `\~/.cato/workspace/`
* ✅ Desktop app can create and edit workspace files
* ✅ Templates load correctly on daemon startup
* ✅ System prompt includes workspace memory content

\---

## Phase 2: Daily Log Auto-Creation (YYYY-MM-DD.md)

### Objective

Automatically create and manage daily log files for session tracking.

* \[ ] **2.1** Implement daily log file generator

  * Check if `YYYY-MM-DD.md` exists for current date
  * Auto-create on first chat message of the day
  * Load previous day's log for context
  * Template: "# Daily Log - 2026-03-09"
* \[ ] **2.2** Add daily log UI to Desktop ChatView

  * Display current log date
  * Show "New day" indicator
  * Button to view previous logs
  * Show relevant yesterday's tasks
* \[ ] **2.3** Integrate daily log into system prompt

  * ContextBuilder loads today's log
  * Inject into bootstrap memory (before SOUL.md)
  * Respect token budget
  * Handle missing files gracefully
* \[ ] **2.4** Implement log rotation and archival

  * Compress logs older than 30 days
  * Archive to `.cato/logs/archive/`
  * Keep recent 7 days uncompressed
  * Cleanup script runs on daemon startup

### Acceptance Criteria

* ✅ Daily log auto-created on first message
* ✅ Previous log content available via UI
* ✅ Logs persist across sessions
* ✅ Archival process works correctly
* ✅ System prompt includes current log

\---

## Phase 3: Semantic Memory Search

### Objective

Implement vector-based semantic search over MEMORY.md and historical logs.

* \[ ] **3.1** Add sentence-transformers embedding to daemon

  * Already installed: `sentence-transformers` in requirements
  * Initialize model on daemon startup
  * Build index from MEMORY.md and logs
* \[ ] **3.2** Implement vector search function

  * `search\_memory(query: str, top\_k=5) -> list\[str]`
  * Search across MEMORY.md, daily logs, skills SKILL.md
  * Return relevant chunks with scores
  * Cache embeddings for performance
* \[ ] **3.3** Integrate semantic search into ContextBuilder

  * On each message, search for relevant facts
  * Inject top-3 results before LLM
  * Format: "# Relevant Memory\\n- fact1\\n- fact2..."
  * Respect token budget (max 1000 tokens)
* \[ ] **3.4** Add memory search UI to Desktop App

  * Search box in ChatView header
  * Display search results with scores
  * One-click context injection
  * Show which file each result came from

### Acceptance Criteria

* ✅ Embeddings generated and cached
* ✅ Semantic search returns relevant results
* ✅ Search results injected into context
* ✅ Desktop app shows search functionality
* ✅ Performance: search completes <500ms

\---

## Phase 4: WhatsApp Channel Integration

### Objective

Add WhatsApp as a channel option alongside existing Telegram.

* \[ ] **4.1** Research WhatsApp Cloud API integration

  * WhatsApp Business Platform
  * Webhook configuration
  * Message format compatibility
  * Identify required credentials
* \[ ] **4.2** Implement WhatsApp gateway in daemon

  * New file: `cato/api/whatsapp\_handler.py`
  * Webhook endpoint: `/api/webhooks/whatsapp`
  * Message receive/send handlers
  * Status callbacks (delivered, read, failed)
* \[ ] **4.3** Update config.yaml for WhatsApp

  * Add `channels.whatsapp` section
  * Vault storage for credentials
  * Phone number mapping
  * Session persistence
* \[ ] **4.4** Add WhatsApp to gateway routing

  * Register WhatsApp in `gateway.py`
  * Channel → Agent bindings
  * Message deduplication
  * Session isolation per chat
* \[ ] **4.5** Add WhatsApp tests

  * Unit tests for message handlers
  * Mock webhook calls
  * Test message routing
  * Ensure 100% pass rate

### Acceptance Criteria

* ✅ WhatsApp webhook receives and sends messages
* ✅ Messages route correctly to agent
* ✅ Session isolation working
* ✅ All tests passing (100%)
* ✅ Credentials safely stored in vault

\---

## Phase 5: Settings UI for Integrations (Desktop App)

### Objective

Build desktop app UI for configuring channels, memory, and scheduling.

* \[ ] **5.1** Create SettingsView component

  * New React component in `desktop/src/views/SettingsView.tsx`
  * Tab-based navigation
  * Save/Cancel actions
  * Icon and styling consistent with app
* \[ ] **5.2** Build Memory Settings tab

  * Edit SOUL.md, IDENTITY.md, USER.md
  * Preview token usage
  * Validate markdown syntax
  * Auto-save with version history
* \[ ] **5.3** Build Channels Settings tab

  * Telegram: Bot token, Phone number inputs
  * WhatsApp: Business account, Phone inputs
  * Toggle channels on/off
  * Test connection buttons
* \[ ] **5.4** Build Scheduling Settings tab

  * Heartbeat frequency selector
  * Daily log settings
  * Memory archival policy
  * Semantic search threshold slider
* \[ ] **5.5** Build Workspace Settings tab

  * Initialize workspace from template
  * Upload workspace files
  * Download workspace backup
  * Reset to defaults button
* \[ ] **5.6** Route settings in App.tsx

  * Add Settings link to sidebar
  * Navigation logic
  * Close on save
  * Show success toast

### Acceptance Criteria

* ✅ SettingsView component created
* ✅ All tabs functional with validation
* ✅ Changes persist to daemon config
* ✅ Settings accessible from sidebar
* ✅ UI responsive and styled consistently
* ✅ All form validations working

\---

## Integration Summary

|Phase|Component|Status|Owner|
|-|-|-|-|
|1|Workspace Templates|☐ Pending|TBD|
|2|Daily Log Auto-Create|☐ Pending|TBD|
|3|Semantic Memory Search|☐ Pending|TBD|
|4|WhatsApp Integration|☐ Pending|TBD|
|5|Settings UI|☐ Pending|TBD|

\---

## Validation Gates

✅ Phase 1 complete → Phase 2 can start
✅ Phase 2 complete → Phase 3 can start
✅ Phase 3 complete → Phase 4 can start
✅ Phase 4 complete → Phase 5 can start
✅ Phase 5 complete → Full E2E testing via Kraken

\---

## Post-Completion

After all phases complete:

1. ✅ Alex agent runs full audit + 100% test pass
2. ✅ Kraken agent runs `/web-app-e2e-tester` on desktop app
3. ✅ Kraken fixes any issues found
4. ✅ Final git push to main

