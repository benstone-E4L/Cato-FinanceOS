# Cato Codebase Cross-Reference Audit
## Built in `cato/` vs. Integrated in Desktop App & Web UI

**Auditor:** Claude Opus 4.6 (Main Agent)
**Date:** 2026-03-09
**Scope:** Every file in `cato/` cross-referenced against desktop app (`desktop/src/`) and web UI (`cato/ui/dashboard.html`)

---

## CRITICAL BUGS (User-Reported Issues)

### Identity Page Save Failure
- [ ] **BUG: Identity page save returns "TypeError: Failed to fetch"** — IdentityView.tsx (line 71) sends `PUT /api/workspace/file` to `http://127.0.0.1:${httpPort}`. Server registers this route at server.py:1662. The endpoint exists and works for Skills. **Root cause**: The `workspace_put` handler (server.py:850-866) checks `if name not in _WORKSPACE_ALLOWED` — the allowed set is `{"SOUL.md", "IDENTITY.md", "USER.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md"}`. If the `_workspace_dir()` path doesn't exist or the daemon isn't running with the gateway properly initialized, the fetch itself will fail with a network error (not a 4xx). **Most likely**: The daemon is not running or there's a CORS pre-flight issue with PUT requests specifically. The CORS middleware handles OPTIONS (server.py:70) but PUT is not listed in `Access-Control-Allow-Methods` on line 75 — **YES IT IS** ("GET, POST, PATCH, DELETE, OPTIONS"). **PUT is MISSING from CORS Allow-Methods!** The CORS middleware at line 75 allows `GET, POST, PATCH, DELETE, OPTIONS` but **NOT PUT**. The browser blocks the PUT request at pre-flight. Skills use PATCH (line 1630), which is allowed. Identity uses PUT (line 1662), which is NOT in the CORS allow list.

### Chat Double Messages
- [ ] **BUG: Chat messages appear twice** — `useChatStream.ts` has two mechanisms that can add the same message: (1) The WS `onmessage` handler (line 123-152) adds assistant responses, AND (2) the `/api/chat/history` poller (line 82-107) polls every 5 seconds and also adds messages from the history. Both use `addMessages()` which deduplicates by `id`, BUT the WS response creates a NEW `crypto.randomUUID()` id (line 132), and the history endpoint returns a DIFFERENT id format (`{session_id}-{timestamp}-{index}` from gateway.py:221). So the same assistant response gets two different IDs and appears twice — once from WS, once from history poll.

### Chat Not Reaching Telegram
- [ ] **BUG: Desktop chat messages don't appear on Telegram** — When user sends via desktop chat, `useChatStream.ts:196-202` sends `{"type":"message", "text":..., "session_id":...}` over WS to port 8081. Gateway `_handle_ws_message` (gateway.py:401-409) ingests it with `channel="web"`. The response goes back via `gateway.send()` which broadcasts to WS clients only for `channel in ("web", "cron", "heartbeat")` (gateway.py:253). **Messages sent from web chat are web-channel only and are never forwarded to Telegram.** This is by design — web chat and Telegram are separate channels. To relay, a bridge adapter or explicit forwarding would be needed.

### No Working/Thinking Indicator
- [ ] **BUG: Send button doesn't show "working" state** — ChatView.tsx:151-156 always shows "Send" text. The `isStreaming` state from useChatStream is used to show typing dots (ChatView.tsx:125-134) but the send button itself never changes. Should change to "Working..." or disable with a spinner when `isStreaming` is true.

### System Page vs Auth Keys Inconsistency
- [ ] **BUG: CLI Process Pool and Auth Keys show different data** — SystemView's `CliPoolPanel` fetches `/api/cli/status` (server.py:374-403) which actually runs `shutil.which()` + `subprocess.run()` to detect installed CLIs. AuthKeysView has **HARDCODED** `CLI_BACKENDS` array (AuthKeysView.tsx:21-50) with static statuses: Codex="working", Cursor="working", Claude="working", Gemini="degraded". These are NOT live — they're just hardcoded strings from when the file was written. **Fix**: AuthKeysView should also fetch `/api/cli/status` for live status instead of hardcoding.

### No Restart Button for LLMs
- [ ] **BUG: No restart button for individual LLM backends** — Neither SystemView nor AuthKeysView has a button to restart individual CLI backends. SystemView has a "Restart Daemon" button (line 299) but no per-model restart. Need to add `/api/cli/{model}/restart` endpoint and UI buttons.

### Gemini Degraded
- [ ] **BUG: Gemini shows "degraded"** — AuthKeysView.tsx line 47 hardcodes `status: "degraded"` with note "Hangs in non-interactive mode on this machine". This matches MEMORY.md: "Gemini CLI hangs in non-interactive mode on this VPS". The `/api/cli/status` endpoint (server.py:394) runs `gemini --version` which may hang/timeout, returning `logged_in: false`. This is a real environment issue, not a code bug — but the hardcoded status in AuthKeysView masks whether it's actually fixed.

### Coding Agent Side Boxes
- [ ] **BUG: Boxes on side of coding agent chat** — CodingAgentView.tsx uses a three-panel layout with `sidebar-left` and `sidebar-right` (RightSidebar component, line 45-117). These sidebars show "Task" and "Results" panels. If the CSS isn't rendering correctly in the Tauri WebView, the borders/backgrounds of these sidebars appear as "boxes on the side". This may be a CSS issue in `desktop/src/styles/app.css`.

### Web UI Bot Name "AI" Instead of "Cato"
- [ ] **BUG: Web UI dashboard.html shows "AI" instead of "Cato"** — The dashboard.html is a monolithic HTML file. Need to search for hardcoded "AI" labels and replace with "Cato". Gateway's `build_system_prompt()` (gateway.py:54-79) correctly sets identity to "Cato" but the HTML UI may have hardcoded sender labels.

### Heartbeat Showing 45 Minutes Ago
- [ ] **BUG: Heartbeat shows stale (45 minutes)** — HeartbeatMonitor (heartbeat.py:79-169) only fires when there are agents with HEARTBEAT.md files in `~/.cato/agents/*/workspace/HEARTBEAT.md`. If no agent directories exist or no HEARTBEAT.md files exist, `_tick()` returns immediately and `_last_fire` stays empty. The gateway also has a `_run_heartbeat_poster` (gateway.py:187-188) that POSTs to `/api/heartbeat` every 30s. If this background task crashes or the gateway isn't fully started, heartbeat goes stale. **Fix**: Verify HEARTBEAT.md exists, ensure `_run_heartbeat_poster` is running.

### Duplicate Identity/Soul Files in Agents and Identity
- [ ] **BUG: SOUL.md, IDENTITY.md, AGENTS.md, USER.md appear in both Agents link and Identity link** — IdentityView.tsx shows `DEFAULT_FILES = ["SOUL.md", "IDENTITY.md", "USER.md", "AGENTS.md"]` (line 20). The sidebar has no separate "Agents" view that shows these same files — BUT the gateway WS handler has `workspace_files` (gateway.py:453-459) and `workspace_file_get` (gateway.py:461-465) which the old WS-based dashboard.html uses. The desktop app sidebar (Sidebar.tsx) does NOT have an "Agents" view — it may be in the web dashboard.html. **The duplication is between the web UI dashboard tabs and the desktop app IdentityView.**

---

## CATO/ MODULE INTEGRATION STATUS

### Fully Integrated (Backend + UI Endpoints + Frontend Views)

| Module | Backend | API Endpoint | Desktop View | Web UI |
|--------|---------|-------------|--------------|--------|
| `cato/gateway.py` | Gateway bus | WebSocket /ws | ChatView | dashboard.html |
| `cato/vault.py` | AES-256-GCM vault | /api/vault/* | AuthKeysView | dashboard.html |
| `cato/budget.py` | Spend caps | /api/budget/summary | BudgetView | dashboard.html |
| `cato/audit/` | Hash-chained log | /api/audit/* | AuditLogView | dashboard.html |
| `cato/core/schedule_manager.py` | Cron scheduler | /api/cron/* | CronView | dashboard.html |
| `cato/core/session_checkpoint.py` | Session state | /api/sessions/*/checkpoints | SessionsView | N/A |
| `cato/orchestrator/cli_invoker.py` | CLI fan-out | /ws/coding-agent/* | CodingAgentView | coding_agent.html |
| `cato/orchestrator/cli_process_pool.py` | Warm pool | /api/cli/status | SystemView | dashboard.html |
| `cato/orchestrator/metrics.py` | Token tracking | /api/usage/summary | UsageView | dashboard.html |
| `cato/orchestrator/clawflows.py` | Flow engine | /api/flows/* | FlowsView | N/A |
| `cato/heartbeat.py` | Health monitor | /api/heartbeat | DashboardView | dashboard.html |
| `cato/node.py` | Remote nodes | /api/nodes | NodesView | N/A |
| `cato/core/memory.py` | SQLite memory | /api/memory/* | MemoryView | dashboard.html |
| `cato/memory/contradiction_detector.py` | Contradiction check | /api/diagnostics/contradiction-health | DiagnosticsView | N/A |
| `cato/memory/decision_memory.py` | Decision tracking | /api/diagnostics/decision-memory | DiagnosticsView | N/A |
| `cato/monitoring/anomaly_detector.py` | Anomaly detection | /api/diagnostics/anomaly-domains | DiagnosticsView | N/A |
| `cato/orchestrator/skill_improvement_cycle.py` | Corrections | /api/diagnostics/skill-corrections | DiagnosticsView | N/A |
| `cato/orchestrator/query_classifier.py` | Tier routing | /api/diagnostics/query-classifier | DiagnosticsView | N/A |
| `cato/audit/action_guard.py` | Safety gate | /api/action-guard/status | SystemView | N/A |
| `cato/config.py` | YAML config | /api/config (GET/PATCH) | ConfigView | dashboard.html |
| `cato/replay.py` | Session replay | /api/sessions/*/replay | ReplayView | N/A |
| `cato/receipt.py` | Session receipt | /api/sessions/*/receipt | SessionsView | N/A |
| `cato/skills/` | SKILL.md files | /api/skills/* | SkillsView | dashboard.html |
| `cato/adapters/telegram.py` | Telegram bridge | /api/adapters | DashboardView | dashboard.html |

### Partially Integrated (Backend exists, limited/no UI)

- [ ] **`cato/adapters/whatsapp.py`** — Backend module exists but no WhatsApp adapter is active. Shows as "not_configured" in adapters list. No UI to configure or start it.
- [ ] **`cato/orchestrator/disagreement_surfacer.py`** — Multi-model Jaccard disagreement detection is implemented but has NO UI surface. Should be in DiagnosticsView.
- [ ] **`cato/orchestrator/epistemic_monitor.py`** — Premise extraction + gap detection is implemented but has NO UI surface. Should be in DiagnosticsView.
- [ ] **`cato/orchestrator/confidence_extractor.py`** — Used internally by coding agent but has no standalone UI panel.
- [ ] **`cato/orchestrator/early_terminator.py`** — Used internally by coding agent but has no UI visibility for when early termination occurs.
- [ ] **`cato/orchestrator/synthesis.py`** — Used internally by coding agent but no standalone synthesis history view.
- [ ] **`cato/core/context_builder.py`** — SlotBudget system has no UI visibility. Could show in DiagnosticsView.
- [ ] **`cato/core/context_gate.py`** — Context gating has no UI surface.
- [ ] **`cato/core/context_pool.py`** — Context pooling has no UI surface.
- [ ] **`cato/core/distiller.py`** — Distillation logic has no UI surface.
- [ ] **`cato/core/retrieval.py`** — HybridRetriever has no UI surface. Could show retrieval stats in DiagnosticsView.
- [ ] **`cato/personalization/habit_extractor.py`** — Habit extraction has no UI surface. Could show in DiagnosticsView or a new Personalization view.
- [ ] **`cato/context/volatility_map.py`** — URL volatility classification has no UI surface.
- [ ] **`cato/context/temporal_reconciler.py`** — Task reconciliation has no UI surface.
- [ ] **`cato/memory/outcome_observer.py`** — Outcome observation has no UI surface.
- [ ] **`cato/tools/browser.py`** — Browser tool exists but no UI to configure/monitor.
- [ ] **`cato/tools/conduit_bridge.py`** — Conduit bridge exists but no UI.
- [ ] **`cato/tools/conduit_crawl.py`** — Conduit crawler exists but no UI.
- [ ] **`cato/tools/conduit_monitor.py`** — Conduit monitor exists but no UI.
- [ ] **`cato/tools/conduit_proof.py`** — Conduit proof exists but no UI.
- [ ] **`cato/tools/file.py`** — File tool exists but no UI.
- [ ] **`cato/tools/github_tool.py`** — GitHub tool exists but no UI.
- [ ] **`cato/tools/python_executor.py`** — Python executor exists but no UI.
- [ ] **`cato/tools/shell.py`** — Shell tool exists but no UI.
- [ ] **`cato/tools/web_search.py`** — Web search tool exists but no UI to configure search backends.
- [ ] **`cato/tools/memory.py`** — Memory tool exists but no UI.
- [ ] **`cato/safety.py`** — Safety module exists but no UI visibility.
- [ ] **`cato/skill_validator.py`** — Skill validator exists but no UI visibility.
- [ ] **`cato/doctor.py`** — Doctor/diagnostics CLI command exists but not exposed in web UI.
- [ ] **`cato/migrate.py`** — Migration tool exists but no UI.
- [ ] **`cato/router.py`** — Model router exists but no UI to configure routing rules.
- [ ] **`cato/agent_loop.py`** — Core agent loop has no direct UI visibility (runs behind gateway).

### Not Integrated (Backend only, no API endpoint)

- [ ] **`cato/audit/ledger.py`** — LedgerMiddleware + verify_chain exists but audit endpoint only queries raw audit_log table, not ledger verification UI.
- [ ] **`cato/audit/reversibility_registry.py`** — Reversibility tagging exists but no UI to view/manage reversibility classifications.
- [ ] **`cato/auth/token_store.py`** — DelegationToken CRUD exists but no UI to create/manage delegation tokens.
- [ ] **`cato/auth/token_checker.py`** — Token authorization checker exists but no UI to view/manage authorized tokens.
- [ ] **`cato/commands/coding_agent_cmd.py`** — CLI command exists but not surfaced in web UI.
- [ ] **`cato/platform.py`** — Platform detection utility, no UI needed.
- [ ] **`cato/adapters/base.py`** — Base adapter class, no UI needed.

---

## UI-SPECIFIC ISSUES

### Desktop App (`desktop/src/`)

- [ ] **ChatView send button needs working state** — ChatView.tsx:151-156 send button always says "Send". Should show "Working..." when `isStreaming` is true.
- [ ] **AuthKeysView uses hardcoded CLI statuses** — Lines 21-50 hardcode status instead of fetching `/api/cli/status`.
- [ ] **AuthKeysView needs restart buttons** — No way to restart individual CLI backends from the UI.
- [ ] **SystemView needs restart buttons per model** — CliPoolPanel shows warm/cold status but no way to restart individual models.
- [ ] **CodingAgentView sidebar CSS** — Three-panel layout may have rendering issues in Tauri WebView2.
- [ ] **DashboardView heartbeat display** — Shows heartbeat status but relies on `/api/heartbeat` which may be stale.
- [ ] **No loading/error states for some views** — AlertsView, ReplayView may not handle API errors gracefully.

### Web UI (`cato/ui/dashboard.html`)

- [ ] **Bot name "AI"** — Need to verify and replace any hardcoded "AI" labels with "Cato" in dashboard.html.
- [ ] **Vault section shows wrong login status** — dashboard.html vault section may not correctly reflect live CLI status.
- [ ] **Dashboard.html is monolithic** — 1700+ line single HTML file is hard to maintain; no componentization.

### Cross-UI Issues

- [ ] **CORS middleware missing PUT** — server.py:75 `Access-Control-Allow-Methods` doesn't include PUT. This blocks IdentityView save which uses PUT.
- [ ] **Duplicate GET /api/config routes** — Both server.py (line 1652) and websocket_handler.py (line 586) register GET /api/config. The last one wins in aiohttp, which may cause unexpected behavior.
- [ ] **Duplicate PATCH /api/config routes** — Both server.py (line 1653) and websocket_handler.py (line 587) register PATCH /api/config. Same conflict issue.
- [ ] **Two WebSocket servers** — Gateway runs websockets on port 8081 (gateway.py:360), aiohttp runs /ws on port 8080 (server.py:114). Chat uses 8081 (correct), coding agent uses 8080 (correct). But this dual-WS architecture is confusing.
- [ ] **`_workspace_dir()` vs workspace files** — IdentityView reads from `_workspace_dir()` which is `~/.cato/default/workspace/`. Memory/config reads from `~/.cato/`. These are different locations for "identity" files.

---

## COMPETITOR FEATURE GAPS (OpenClaw Analysis)

Features that OpenClaw (214K+ stars) has that Cato currently lacks. Prioritized by competitive impact.

### HIGH Priority (Industry-Standard Features)

- [ ] **MCP Client Support** — OpenClaw implements the Model Context Protocol (MCP) as a first-class client, allowing any MCP-compatible tool server to plug in. Cato has custom tool registration (`register_all_tools` in `agent_loop.py`) but no MCP client. **Impact**: MCP is becoming the industry standard for tool integration. Without it, Cato can't use the growing ecosystem of MCP servers. **Implementation**: Add `cato/mcp/client.py` that connects to MCP servers, discovers tools, and registers them as native Cato tools.

- [ ] **Sub-Agent Spawning** — OpenClaw supports spawning child agents from a parent agent for complex task decomposition (`agent.spawn()` pattern). Cato's `agent_loop.py` runs a single loop per session with no ability to fork sub-agents. **Impact**: Critical for complex multi-step tasks where the agent needs to delegate sub-tasks. **Implementation**: Add `AgentLoop.spawn_child(task, tools_subset)` that creates a scoped child loop with its own context and budget, reporting back to parent.

- [ ] **Docker/Sandbox Isolation** — OpenClaw runs tool executions (code, shell, browser) in Docker containers for security isolation. Cato's `python_executor.py` uses `subprocess` with no container isolation, and `shell.py` executes directly on the host. **Impact**: Essential for production deployments where untrusted code execution is possible. **Implementation**: Add `cato/sandbox/docker_runner.py` that wraps tool execution in Docker containers with resource limits.

### MEDIUM Priority (Competitive Differentiators)

- [ ] **Additional Channel Adapters** — OpenClaw supports 20+ channels (Discord, Slack, WhatsApp, LINE, Messenger, Teams, email, SMS, etc.). Cato has only Telegram (working) and WhatsApp (stub). **Implementation**: Add `cato/adapters/discord.py`, `cato/adapters/slack.py`, `cato/adapters/email.py` at minimum. Use the existing `cato/adapters/base.py` abstract class.

- [ ] **Hooks/Lifecycle System** — OpenClaw has pre/post hooks for message processing, tool execution, and agent lifecycle events. Cato has `ActionGuard` for pre-execution checks but no general-purpose hook system. **Implementation**: Add `cato/hooks.py` with `register_hook(event, callback)` for events like `pre_message`, `post_message`, `pre_tool`, `post_tool`, `on_error`.

- [ ] **Plugin Architecture** — OpenClaw uses a formal plugin system where third-party packages can register tools, adapters, and middleware. Cato's tools are hardcoded in `register_all_tools()`. **Implementation**: Add `cato/plugins/` with entry-point based plugin discovery (`importlib.metadata.entry_points(group="cato.plugins")`).

- [ ] **Intelligent Heartbeat** — OpenClaw's heartbeat includes system metrics (CPU, memory, disk, active sessions, queue depth). Cato's heartbeat only checks if HEARTBEAT.md files exist. **Implementation**: Enhance `cato/heartbeat.py` to collect `psutil` metrics and include them in heartbeat payload.

- [ ] **CLI Expansion** — OpenClaw provides `claw doctor`, `claw config set`, `claw plugin install`, `claw adapter add` commands. Cato has `cato doctor` but lacks plugin/adapter management CLI commands. **Implementation**: Add Click subcommands in `cato/cli.py` for plugin and adapter management.

- [ ] **Config Hot Reload** — OpenClaw watches config files for changes and applies them without restart. Cato requires daemon restart to pick up config changes. **Implementation**: Add file watcher in `cato/config.py` using `watchdog` or polling to detect and apply config changes live.

- [ ] **Search Provider Fallback Chain** — OpenClaw chains multiple search providers (Tavily → SearXNG → DuckDuckGo → Brave). Cato's `web_search.py` has a single search implementation. **Implementation**: Add fallback chain logic to `cato/tools/web_search.py` with configurable provider priority.

- [ ] **Audio/Speech Support** — OpenClaw supports voice input/output via Whisper and TTS. Cato has no audio capabilities. **Implementation**: Add `cato/tools/audio.py` with Whisper transcription and TTS synthesis.

- [ ] **Multi-Channel Session Continuity** — OpenClaw allows a conversation started on Discord to continue on Telegram or web. Cato's channels are isolated — web chat and Telegram are separate sessions. **Implementation**: Add session linking in `cato/gateway.py` so a user can be identified across channels and continue conversations.

- [ ] **Security Audit CLI** — OpenClaw has `claw security audit` that scans for exposed secrets, weak permissions, and unsafe tool configs. Cato has `cato doctor` but no dedicated security scan. **Implementation**: Add `cato doctor --security` mode that checks vault integrity, file permissions, exposed ports, and config for secrets.

### LOW Priority (Nice-to-Have)

- [ ] **Skill Marketplace/Hub** — OpenClaw has ClawHub with 2857+ community skills. Cato has local SKILL.md files only. **Implementation**: Add `cato/skills/hub.py` with a registry API for discovering and installing community skills.

- [ ] **Visual Flow Builder** — OpenClaw has a drag-and-drop flow builder UI. Cato has `clawflows.py` but the FlowsView is text/form-based only. **Implementation**: Add a visual graph editor component to `desktop/src/views/FlowsView.tsx`.

- [ ] **Rate Limiting Middleware** — OpenClaw has built-in per-user and per-channel rate limiting. Cato has budget caps but no per-user rate limiting. **Implementation**: Add `cato/middleware/rate_limiter.py` with configurable limits per channel/user.

- [ ] **Conversation Branching** — OpenClaw supports branching conversations (fork a conversation to explore alternatives). Cato has linear session history only. **Implementation**: Add branch support to `cato/core/session_checkpoint.py`.

- [ ] **i18n/Localization** — OpenClaw supports 20+ languages for system prompts and UI. Cato is English-only. **Implementation**: Add `cato/i18n/` with locale files and message translation.

### Cato Competitive Advantages (Already Ahead of OpenClaw)

These are features Cato has that OpenClaw does NOT — preserve and promote these:

- **Multi-model orchestration** — CLI fan-out to Claude/Codex/Gemini/Cursor with confidence scoring and synthesis
- **Hash-chained audit trail** — SHA-256 linked audit log with field-level verification (OpenClaw has basic logging only)
- **Hard spending caps** — Per-session ($1) and monthly ($20) budget enforcement with real-time tracking
- **Knowledge graph memory** — SQLite-backed facts + knowledge graph nodes/edges (OpenClaw uses vector DB only)
- **Epistemic monitoring** — Premise extraction, gap detection, overconfidence profiling
- **Decision memory** — Track decisions, record outcomes, detect overconfidence patterns
- **Contradiction detection** — Jaccard-based fact contradiction detection and resolution
- **Habit extraction** — User behavior pattern recognition for personalization
- **AES-256-GCM vault** — Encrypted secret storage (OpenClaw stores keys in plaintext config)
- **Tiered context budget** — SlotBudget system with tier0/1/2/3 priority allocation
- **Official desktop app** — Tauri v2 native app (OpenClaw is web/CLI only)
- **Action guard** — 3-rule pre-execution safety gate with autonomy levels

---

## SUMMARY STATISTICS

| Category | Count |
|----------|-------|
| Python modules in `cato/` | 46 files |
| Fully integrated (backend + API + UI) | 24 modules |
| Partially integrated (backend exists, limited UI) | 28 modules |
| Not integrated (backend only) | 7 modules |
| Critical bugs (user-reported) | 10 issues |
| UI-specific issues | 12 issues |
| Cross-UI issues | 5 issues |
| Competitor feature gaps (HIGH) | 3 items |
| Competitor feature gaps (MEDIUM) | 11 items |
| Competitor feature gaps (LOW) | 5 items |
| **Total tasks** | **74 items** |
