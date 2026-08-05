# Architecture Cartographer Report — Cato

**Audited:** 2026-06-13  
**Auditor:** architecture-cartographer skill  

---

## Executive Summary

Cato is a privacy-focused AI agent daemon with a Tauri v2 desktop app, Telegram/WhatsApp adapters, a multi-model orchestrator, and a conduit headless browser engine. The most important finding is **a bifurcated routing architecture with dual entry paths** (`router.py` for direct LLM calls vs. `swarmsync.py`/`agent_loop.py` for SwarmSync routing) that creates contradictory fallback behavior: when `SWARMSYNC_API_KEY` is absent the agent silently degrades rather than hard-failing, which undermines the stated guarantee that "Cato returns a user-visible error rather than silently failing." Additionally, the WhatsApp channel is a stub — messages are received but never reach the agent loop — and the `arbitrage_pulse.py` has a hardcoded absolute path to a separate repo on this specific machine. **Top recommendation:** harden the SwarmSync key-absence path to error loudly, complete or remove the WhatsApp stub, and fix the hardcoded path in `arbitrage_pulse.py`.

---

## Project Map

### Project Type
Python 3.11+ asyncio daemon (`cato-daemon` v0.2.0) + Tauri v2 desktop app (React 19 + TypeScript + Rust sidecar). Monorepo: Python package at root, Rust/TS desktop app at `desktop/`.

### Main Applications

| App/Service | Path | Framework | Runtime | Purpose |
|---|---|---|---|---|
| Cato Daemon | `cato/` | asyncio, aiohttp | Python 3.11+ | Core AI agent daemon — HTTP/WS server, agent loop, tool execution |
| Cato Desktop | `desktop/` | Tauri v2 + React 19 | Node (build) + Rust (sidecar) | Desktop UI — chat, settings, activity indicator, PTY terminal |
| `cato_svc_runner.py` | root | plain Python | Python 3.11 | Windows service launcher (for Task Scheduler / NSSM) |

### Main Packages (Python)

| Package | Path | Exported To |
|---|---|---|
| `cato.cli` | `cato/cli.py` | Entry point `cato` (pyproject.toml scripts) |
| `cato.gateway` | `cato/gateway.py` | Imported by `cato/ui/server.py` |
| `cato.agent_loop` | `cato/agent_loop.py` | Imported by `gateway.py`, `commands/coding_agent_cmd.py` |
| `cato.router` | `cato/router.py` | Imported by `agent_loop.py`, `core/compactor.py` |
| `cato.swarmsync` | `cato/swarmsync.py` | Imported by `agent_loop.py`, `doctor.py`, many |
| `cato.vault` | `cato/vault.py` | Imported by almost every module |
| `cato.ui.server` | `cato/ui/server.py` | Started by `cli.py` `_run_daemon()` |
| `cato.tools.*` | `cato/tools/` | Registered in `agent_loop.py` |
| `cato.orchestrator.*` | `cato/orchestrator/` | Imported by `agent_loop.py`, `gateway.py` |
| `cato.adapters.*` | `cato/adapters/` | Started by `cli.py`, wired through `gateway.py` |

### Runtime Targets

Node 20 (Vite build only) / Python 3.11+ (daemon) / Rust 1.71+ (Tauri sidecar) / Browser (Tauri WebView)

### Entry Points

| Entry | File Path | Notes |
|---|---|---|
| `cato` CLI | `cato/cli.py:main` | Click group, 20+ subcommands |
| Daemon start | `cato/cli.py:_run_daemon()` ~L502 | Starts aiohttp server + gateway |
| Windows service | `cato_svc_runner.py` | Calls `_run_daemon("claude", "all")` |
| Tauri sidecar | `desktop/src-tauri/src/main.rs` | Delegates to `app_lib::run()` |
| Desktop UI | `desktop/src/` | Vite build, served by Tauri WebView |

### Important Config Files

| File | Path | What It Controls |
|---|---|---|
| Config | `%APPDATA%/cato/config.yaml` | All daemon config (model, ports, safety mode, etc.) |
| `.env` | `<repo_root>/.env` | Vault password, SwarmSync keys, Gmail OAuth, Telegram, GitHub |
| `pyproject.toml` | root | Python build, deps, test config, scripts |
| `desktop/package.json` | `desktop/` | Desktop build, TS deps |
| `desktop/src-tauri/Cargo.toml` | `desktop/src-tauri/` | Rust sidecar deps |

### Deployment Surface

| Platform | Config File | Services Deployed | Notes |
|---|---|---|---|
| Windows local | `cato_svc_runner.py` | Daemon as Task Scheduler/NSSM service | Primary install |
| Desktop | `desktop/build_release.ps1` | `cato-desktop.exe` (17 MB) | Ships with daemon as sidecar |
| SwarmSync routing | `config.yaml:swarmsync_api_url` | `https://api.swarmsync.ai/v1/chat/completions` | External dependency |
| Genesis Agents | `config.yaml:genesis_endpoint` | `https://swarmsync-agents.onrender.com` | External dependency |
| Arbitrage Pulse | `cato/core/arbitrage_pulse.py:_DEFAULT_SERVICE_URL` | `https://swarmsync-arbitrage-production.up.railway.app` | External dependency |
| No CI/CD | — | — | No `.github/workflows/` found |

### Test Surface

| Type | Directory | File Count | Framework |
|---|---|---|---|
| Unit + integration | `tests/` | 96+ files | pytest, asyncio_mode=auto |
| Server lifecycle | `cato/ui/tests/` | 1 file | pytest |
| Orchestrator | `cato/orchestrator/tests/` | Several files | pytest |
| Status | — | 1869 passed, 2 failed (as of 2026-05-22) | — |

### Documentation Surface

| Doc | Path | Apparent Status |
|---|---|---|
| README | `README.md` | 460 lines, marketing + architecture |
| CLAUDE.md | `CLAUDE.md` | Developer rules, routing, audit gate |
| REALITY_CHECK_REPORT.md | root | 2026-03-05 NO-GO audit (Kraken) |
| WEEK1_MVP_STATUS.md | root | Sprint tracking doc (in progress) |
| CATO_ALEX_AUDIT.md | root | Prior audit |
| CATO_KRAKEN_VERDICT.md | root | Prior verdict |
| AUDIT_PIPELINE.md | root | Audit process doc |

---

## System Understanding

### Apparent Product Purpose

Cato is a privacy-focused, locally-run AI agent daemon that routes all LLM calls through SwarmSync (a model-routing proxy), exposes HTTP/WebSocket APIs consumed by a Tauri desktop app, and integrates Telegram messaging, Gmail, GitHub, and a headless browser (Conduit/Patchright). It is positioned as an alternative to OpenClaw/ClawdBot/MoltBot. — Evidence: `README.md L1–20`, `CLAUDE.md`, `cato/__init__.py`.

### Core User Flows

1. **Chat via Desktop**: User sends message in Tauri app → WebSocket to `gateway.py:ingest()` → `agent_loop.py` runs planning loop → LLM called via `router.py`/SwarmSync → tool calls dispatched → response streamed back via WS — Evidence: `desktop/src/hooks/useChatStream.ts`, `cato/gateway.py`, `cato/agent_loop.py`
2. **Chat via Telegram**: Telegram message → `TelegramAdapter.run()` → `gateway.ingest()` → same agent loop path → response sent back via `TelegramAdapter.send()` — Evidence: `cato/adapters/telegram.py`, `cato/gateway.py:send()`
3. **Coding Agent Fan-out**: User triggers coding task → `orchestrator/cli_invoker.py` fans out to Claude/Codex/Cursor in parallel (60s timeout each) → synthesis → result returned — Evidence: `cato/orchestrator/cli_invoker.py`, `cato/orchestrator/synthesis.py`
4. **Night-Shift / Outreach**: Cron scheduler fires → `HeartbeatMonitor` sends checklist → agent runs outreach pipeline via `canary25/` + `conduit_bridge.py` — Evidence: `cato/core/schedule_manager.py`, `cato/heartbeat.py`, `cato/canary25/`
5. **Vault Operations**: User stores/retrieves API keys via `cato vault set/get` → `vault.py` (AES-256-GCM, Argon2id KDF) — Evidence: `cato/vault.py`, `cato/cli.py:297`

### Core Backend Flows

1. **LLM Routing**: `agent_loop.py` → `router.py:ModelRouter.complete()` → if `swarmsync_enabled` and key present: POST to `swarmsync_api_url`; else: direct OpenRouter/Anthropic call — Evidence: `cato/router.py:247–310`, `cato/swarmsync.py`
2. **Tool Dispatch**: `agent_loop.py:_dispatch_with_progress()` → `_TOOL_REGISTRY[tool_name]()` → audit log write → optional approval gate — Evidence: `cato/agent_loop.py:_dispatch_with_progress`, `cato/audit/action_guard.py`
3. **Memory**: Each agent turn → BM25 + sentence-transformer retrieval → `MemorySystem.search()` → results injected into context via `ContextBuilder` — Evidence: `cato/core/memory.py`, `cato/core/context_builder.py`
4. **Audit Chain**: Every tool execution writes hash-chained entry to `audit_log` SQLite table (SHA-256 of `id:session:action:tool:cost:timestamp:prev_hash`) — Evidence: `cato/audit/audit_log.py:107–135`
5. **ClawFlows**: Persistent multi-step workflows stored in SQLite, executed by `FlowEngine` in `gateway.py:764` — Evidence: `cato/orchestrator/clawflows.py`, `cato/gateway.py:891`

### Critical Systems

| System | Why Critical | Evidence |
|---|---|---|
| `cato/gateway.py` | Message hub — all inbound/outbound flows pass through it | `gateway.py:Gateway.ingest()` |
| `cato/agent_loop.py` | Core reasoning loop — all LLM calls and tool executions | `agent_loop.py:AgentLoop.run()` |
| `cato/router.py` | LLM routing — if broken, all responses fail | `router.py:ModelRouter.complete()` |
| `cato/vault.py` | Credential store — if locked, all integrations fail | `vault.py:Vault.get()` |
| `cato/ui/server.py` | HTTP/WS server — desktop app cannot connect without it | `server.py:app` |
| SwarmSync (external) | Routes all LLM calls when `swarmsync_enabled: True` | `config.py:swarmsync_api_url` |

### Experimental / Demo / Stub Systems

| System | Evidence of Stub/Demo/Experimental Status | Risk |
|---|---|---|
| WhatsApp channel | `whatsapp_routes.py:128`: `# TODO: Integrate with agent_loop for message processing` — messages received but never routed | Messages silently dropped |
| `/config POST` endpoint | `server.py:8`: `POST /config → Save config (stub; gateway wires real handler)`; `server.py:1574`: `# TODO: wire to CatoConfig.save()` | Config saves fail silently |
| `cato/ui/server.py:/compact POST` | `server.py:887`: `return web.json_response({"status": "ok", "message": "Context compacted (stub)."})` when gateway offline | Compact appears to succeed when it hasn't |
| Arbitrage Pulse | `arbitrage_pulse.py:_PULSE_SCRIPT` hardcoded to `C:\Users\Administrator\Desktop\Github\SwarmSync-Arbitrage\scripts\cato-arbitrage-pulse.ps1` — only works on Ben's machine | Feature fails on any other machine |
| `pipeline/workers.py:72` | `source="mock"` in pipeline worker | Pipeline telemetry marked as mock |
| Genesis Agents (5 of 20) | `tools/genesis.py` defines 20 agents; 5 marked `status: "pending"` | Pending agents silently unavailable |
| BRAINSTORM/ + Cato-1A/1B/2A/ dirs | Prior version snapshots at repo root | Dead weight; confuses codebase structure |

### Production-Critical Assumptions

1. `SWARMSYNC_API_KEY` is always present — if absent, daemon logs a warning but continues with degraded fallback (`agent_loop.py:1631`)
2. SwarmSync service at `https://api.swarmsync.ai` is always reachable — no circuit breaker exists
3. Genesis endpoint at `https://swarmsync-agents.onrender.com` is always up — timeouts result in degraded agent with confidence 0.5
4. Vault password (`CATO_VAULT_PASSWORD`) is always in environment — if absent, vault is locked and all integrations fail
5. SQLite databases in `%APPDATA%/cato/` are never corrupted — no WAL mode, no backup strategy found

---

## Architecture Map

### Frontend Surface

| Area | File Path | Purpose | Status |
|---|---|---|---|
| Chat view | `desktop/src/views/ChatView.tsx` | Main user chat UI | Active |
| Settings view | `desktop/src/views/SettingsView.tsx` | Config tabs (general/memory/channels/scheduling/workspace) | Active |
| WebSocket hook | `desktop/src/hooks/useChatStream.ts` | Connects to WS 8080, handles messages + Telegram events, polls history | Active |
| Activity indicator | `desktop/src/components/ActivityIndicator.tsx` | Polls `/api/activity` every 2s, listens for WS `type: "activity"` | Active |
| PTY terminal | `desktop/src/` (xterm.js) | Interactive CLI sessions | Active |
| Dashboard HTML | `cato/ui/dashboard.html` | Web UI (~1700 lines, monolithic SPA) | Active (legacy web UI path) |
| Logo | `cato/ui/assets/logo_b64.py` | Base64 encoded PNG, 44×44 in sidebar | Active |

### API Surface

| Route / Handler | File Path | Method | Auth Required | Used By | Notes |
|---|---|---|---|---|---|
| `/health` | `server.py` | GET | No (exempt) | Desktop app, `cato doctor` | Returns daemon status + SwarmSync check |
| `/` | `server.py` | GET | No (exempt) | Browser/desktop | Dashboard HTML |
| `/chat` | `server.py` | POST | Yes | Desktop WS fallback | HTTP chat endpoint |
| `/ws` | `server.py` | WS | Yes | `useChatStream.ts` | Primary message channel |
| `/api/activity` | `server.py` | GET | No (exempt) | `ActivityIndicator.tsx` | Busy/idle status |
| `/api/memory/*` | `api/memory_routes.py` | GET/POST/DELETE | Yes | Settings view | Memory browser |
| `/api/workspace/*` | `api/workspace_routes.py` | GET/POST | Yes | Settings/chat | Identity files (SOUL.md etc.) |
| `/api/integrations/*` | `api/integration_routes.py` | GET/POST | Yes | Settings view | Integration status (read-only) |
| `/api/whatsapp/*` | `api/whatsapp_routes.py` | GET/POST | Yes | WhatsApp webhook | **STUB** — messages not routed |
| `/coding-agent` | `server.py` | WS | No (exempt) | Desktop PTY | Coding agent WebSocket |
| `/api/pty/*` | `api/pty_routes.py` | WS/GET/DELETE | Yes | Desktop terminal | PTY sessions |
| `/api/flows/*` | `server.py` | GET/POST/DELETE | Yes | Desktop | ClawFlow CRUD + run |
| `/api/nodes/*` | `server.py` | GET/POST | Yes | Desktop | Remote node management |
| `/config` | `server.py` | POST | Yes | Desktop Settings | **STUB** — `CatoConfig.save()` not wired |
| `/api/sessions/*` | `server.py` | GET | Yes | Desktop | Session history + replay |
| `/heartbeat` | `server.py` | GET/POST | Yes (GET exempt) | `HeartbeatMonitor` | HB-001 fix applied |
| `/api/delegation-tokens/*` | `server.py` | CRUD | Yes | Desktop | Token management |
| `/api/diagnostics/*` | `server.py` | GET | Yes | Desktop | Query classifier, anomaly, epistemic |
| `/restart` | `server.py` | POST | Yes | Desktop | SIGTERM after 1s |

### Database / Persistence

| Model / Table | Schema File | Used By | Risk |
|---|---|---|---|
| `audit_log` | `cato/audit/audit_log.py:22` | `agent_loop.py`, `server.py` | Active |
| `ledger` | `cato/audit/ledger.py:91` | `budget.py`, `server.py` | Active |
| `chunks`, `distilled_summaries`, `chunk_usage`, `facts`, `kg_nodes`, `kg_edges` | `cato/core/memory.py:274` | `agent_loop.py`, `server.py` | Active |
| `delegation_tokens` | `cato/auth/token_store.py:_SCHEMA` | `server.py`, `api/` | Active |
| `flows` | `cato/orchestrator/clawflows.py:115` | `gateway.py`, `server.py` | Active |
| `personal_inbox` | `cato/core/personal_store.py:52` | `site_services_bridge.py`, `server.py` | Active |
| `outbound_approvals` | `cato/core/outbound_approval.py:61` | `agent_loop.py`, `server.py` | Active |
| `routing_log` | `cato/routing_log.py:59` | `router.py` | Active |
| `session_checkpoints` | `cato/core/session_checkpoint.py:72` | `server.py` | Active |
| `pipeline_runs` | `cato/pipeline/store.py:56` | `workers.py`, `server.py` | Active (`source="mock"` at L72) |
| `contradiction_events` | `cato/memory/contradiction_detector.py:96` | `server.py` | Active |
| `decision_memory` | `cato/memory/decision_memory.py:68` | `server.py` | Active |
| `anomaly_events` | `cato/monitoring/anomaly_detector.py:96` | `server.py` | Active |
| `cato_habits` | `cato/personalization/habit_extractor.py:94` | `server.py` | Active |
| `context_pool` | `cato/core/context_pool.py:97` | `agent_loop.py` | Active |
| `epistemic_monitor` | `cato/orchestrator/epistemic_monitor.py:136` | `server.py` | Active |
| No backup/WAL config found | — | — | **Risk: SQLite corruption on crash** |

### External Integrations

| Integration | Package | Config / Env Var | Import Location | Risk / Concern |
|---|---|---|---|---|
| SwarmSync (LLM router) | None (HTTP) | `SWARMSYNC_API_KEY` (vault/.env) | `cato/swarmsync.py`, `cato/router.py` | Single external dependency for ALL LLM calls; no circuit breaker |
| OpenRouter (direct fallback) | None (HTTP) | `OPENROUTER_API_KEY` (vault) | `cato/router.py:631` | Used only when SwarmSync absent |
| Anthropic (direct fallback) | None (HTTP) | `ANTHROPIC_API_KEY` (vault) | `cato/router.py:968` | Used only when SwarmSync absent |
| Telegram | `python-telegram-bot>=21.0` | `TELEGRAM_BOT_TOKEN`/`CATODESKTOP_BOT_TOKEN` (vault/.env) | `cato/adapters/telegram.py:92–95` | Two key names for same thing (see Deadweight) |
| WhatsApp | None (aiohttp HTTP) | `WHATSAPP_PHONE_ID`, `WHATSAPP_TOKEN`, `WHATSAPP_WEBHOOK_VERIFY` | `cato/channels/whatsapp.py`, `cato/api/whatsapp_routes.py` | **STUB** — `TODO: Integrate with agent_loop` at `whatsapp_routes.py:128` |
| Gmail | `google-api-python-client>=2.100`, `google-auth*` | `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` (vault) | `cato/adapters/gmail_adapter.py:285–287` | Also `BEN_VOICE_PATH` env var (personal/hardcoded) |
| GitHub | `gh` CLI (subprocess) | `GITHUB_TOKEN`/`GH_TOKEN`/`GITHUB_FOXFIREPOETS_TOKEN` (vault/.env) | `cato/tools/github_tool.py:124–136` | Three key names for same credential |
| Patchright/Playwright | `patchright>=1.49.0` | `conduit_enabled: bool` in config | `cato/tools/browser.py`, `cato/tools/conduit_bridge.py` | Works on local Windows; would fail on any cloud host |
| MCP | `mcp>=1.22.0` | `mcp_enabled`, `mcp_host`, `mcp_port` in config | `cato/mcp/windows_client.py` | Windows MCP client only |
| Genesis Agents | None (HTTP) | `GENESIS_AGENTS_SWARMSYNC_API_KEY` (.env), `genesis_endpoint` | `cato/tools/genesis.py` | External endpoint on Render free tier; 5/20 agents pending |
| Arbitrage Pulse | subprocess (PS1) | `_DEFAULT_SERVICE_URL` hardcoded | `cato/core/arbitrage_pulse.py:_PULSE_SCRIPT` | **Hardcoded path** to `C:\Users\Administrator\Desktop\Github\...` |
| Conduit search engines | None (HTTP) | `BRAVE_API_KEY`, `EXA_API_KEY`, `TAVILY_API_KEY`, `PERPLEXITY_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY` | `cato/api/integration_routes.py:111–132` | Optional; none required |

### Internal Services

| Service | File Path | Purpose | Called By |
|---|---|---|---|
| Gateway | `cato/gateway.py` | Message routing hub, WS broadcast, cron | `server.py`, adapters |
| AgentLoop | `cato/agent_loop.py` | LLM planning + tool execution | `gateway.py:_build_agent_loop()` |
| ModelRouter | `cato/router.py` | LLM API routing (SwarmSync/OpenRouter/Anthropic) | `agent_loop.py` |
| MemorySystem | `cato/core/memory.py` | Hybrid BM25+embedding retrieval, SQLite | `agent_loop.py`, `server.py` |
| ContextBuilder | `cato/core/context_builder.py` | Builds 12K token context window from priority files | `agent_loop.py` |
| BudgetManager | `cato/budget.py` | Hard spend caps (daily/monthly), Conduit session | `agent_loop.py`, `gateway.py` |
| AuditLog | `cato/audit/audit_log.py` | Hash-chained action log (SQLite) | `agent_loop.py` |
| ActionGuard | `cato/audit/action_guard.py` | Pre-execution reversibility check | `agent_loop.py` |
| SafetyGuard | `cato/safety.py` | Risk tier enforcement, STOP file | `agent_loop.py` |
| SchedulerDaemon | `cato/core/schedule_manager.py` | YAML/JSON cron scheduler | `gateway.py` |
| HeartbeatMonitor | `cato/heartbeat.py` | HEARTBEAT.md checklist polling | `gateway.py` |
| NodeManager | `cato/node.py` | Remote node registration/invocation | `gateway.py`, `server.py` |
| ClawFlows/FlowEngine | `cato/orchestrator/clawflows.py` | Multi-step workflow engine (SQLite) | `gateway.py`, `server.py` |
| CliProcessPool | `cato/orchestrator/cli_process_pool.py` | Warm pool for Claude/Codex CLI | `server.py:_start_cli_pool()` |
| ConduitBridge | `cato/tools/conduit_bridge.py` | Headless browser wrapper | `agent_loop.py` |
| Canary25 | `cato/canary25/` | Cold-email outreach safety gate (25 contacts/batch) | `agent_loop.py` (night-shift) |

### Background Jobs / Scripts

| Script / Job / Cron | File Path | Trigger | Used in CI/CD? | Notes |
|---|---|---|---|---|
| HeartbeatMonitor | `cato/heartbeat.py` | 30s poll, reads `HEARTBEAT.md` | No CI | Sends checklist to agent loop |
| SchedulerDaemon (YAML) | `cato/core/schedule_manager.py` | YAML cron entries in config | No CI | croniter-based |
| Gateway cron (JSON) | `cato/gateway.py` | `cato_cron.json` in workspace | No CI | Secondary cron path |
| CLI pool warmup | `cato/ui/server.py:_start_cli_pool()` | 120s after server start | No CI | Warms Claude/Codex processes |
| MemoryUpkeepService | `cato/core/memory_upkeep.py` | Called from gateway | No CI | Distillation + pruning |
| ArbitragePulse | `cato/core/arbitrage_pulse.py` | Manual / night-shift | No CI | Hardcoded PS1 path |
| `sync_version.py` | `scripts/` | `npm run build` (pre-check) | No CI | Version sync between pyproject.toml + package.json |
| `verify_python_build.py` | `scripts/` | `hatch run verify` | No CI | Build verification |
| No CI/CD pipelines | `.github/workflows/` | None found | — | No automated test runs on push |

---

## Integration Forensics

| Integration | Installed? | Env Vars? | Imported? | Live Route Usage? | Verdict | Recommendation |
|---|:---:|:---:|:---:|:---:|---|---|
| SwarmSync (HTTP) | No pkg (HTTP) | Yes (vault + .env) | Yes (`swarmsync.py`) | Yes (all LLM calls) | **Keep** | Add circuit breaker + health fallback |
| OpenRouter (HTTP) | No pkg (HTTP) | Yes (vault) | Yes (`router.py`) | Partial (fallback only) | **Keep** | Document as explicit fallback |
| Anthropic (HTTP) | No pkg (HTTP) | Yes (vault) | Yes (`router.py`) | Partial (fallback only) | **Keep** | Document as explicit fallback |
| python-telegram-bot | Yes (pyproject.toml) | Yes (2 key names) | Yes (`adapters/telegram.py`) | Yes (bidirectional) | **Refactor** | Consolidate to single key name `TELEGRAM_BOT_TOKEN` |
| WhatsApp (aiohttp) | No pkg | Partial (vault keys) | Yes (`channels/whatsapp.py`) | No (`TODO` at L128) | **Replace** | Wire to `gateway.ingest()` or remove until complete |
| Gmail (`google-api-python-client`) | Yes (pyproject.toml) | Yes (vault) | Yes (`adapters/gmail_adapter.py`) | Yes (telegram night-shift) | **Keep** | Remove `BEN_VOICE_PATH` personal env ref |
| GitHub (`gh` CLI subprocess) | External CLI | Yes (3 key names) | Yes (`tools/github_tool.py`) | Yes (registered tool) | **Refactor** | Consolidate to single key name `GITHUB_TOKEN` |
| Patchright/Playwright | Yes (pyproject.toml) | Config flag | Yes (`tools/browser.py`) | Yes (conduit tools) | **Keep** | Document cloud-hosting incompatibility |
| MCP (`mcp>=1.22.0`) | Yes (pyproject.toml) | Config + ports | Yes (`mcp/windows_client.py`) | Partial (opt-in) | **Verify** | Confirm MCP server registration works end-to-end |
| Genesis Agents (HTTP) | No pkg (HTTP) | Yes (.env) | Yes (`tools/genesis.py`) | Yes (15/20 agents) | **Refactor** | Remove 5 pending agents from registry or mark clearly |
| ArbitragePulse (subprocess) | External PS1 | Config URL | Yes (`core/arbitrage_pulse.py`) | Partial | **Refactor** | Replace hardcoded absolute path with relative/config lookup |
| Conduit search engines | No pkg (HTTP) | Optional vault keys | Yes (`tools/conduit_bridge.py`) | Yes (when keys present) | **Keep** | All keys optional; correct pattern |
| uvicorn | Yes (pyproject.toml) | — | Not found in production path | No | **Remove** | `grep -rn "uvicorn" cato/` shows no import in production code; only aiohttp used |

---

### WhatsApp — Replace / Complete

**Evidence:**
- `cato/api/whatsapp_routes.py:128` — `# TODO: Integrate with agent_loop for message processing`
- `cato/channels/whatsapp.py:1` — `WHATSAPP_API_BASE = "https://graph.instagram.com/v18.0"` (implemented)
- `cato/api/whatsapp_routes.py:1–214` — routes exist: `GET/POST /api/whatsapp/webhook`, `POST /api/whatsapp/send`, `GET /api/whatsapp/config`
- `cato/api/integration_routes.py:67–84` — integration status endpoint references WhatsApp as a configured integration

**Why this verdict:**
WhatsApp webhook receives messages, parses them, but then does nothing with them — no call to `gateway.ingest()` or any agent path. The message is silently dropped. Meanwhile the integration status page shows WhatsApp as a "configured integration," which is misleading.

**Recommended action:**
1. mark as `whatsapp_enabled: False` in default config and remove from integration status until complete.

---

### Arbitrage Pulse — Refactor

**Evidence:**
- `cato/core/arbitrage_pulse.py` — `_PULSE_SCRIPT = Path("C:/Users/Administrator/Desktop/Github/SwarmSync-Arbitrage/scripts/cato-arbitrage-pulse.ps1")`
- `cato/core/arbitrage_pulse.py:58` — `env = os.environ.copy()`; script invoked as subprocess
- `_DEFAULT_SERVICE_URL = "https://swarmsync-arbitrage-production.up.railway.app"` — hardcoded

**Why this verdict:**
The PS1 script path is an absolute path to a specific location on one developer's machine. This feature is completely non-functional on any other machine. The service URL is also hardcoded rather than config-driven.

**Recommended action:**
1. Add `arbitrage_pulse_script: str = ""` to `CatoConfig` (or derive from workspace/repo root).
2. Replace the hardcoded `_PULSE_SCRIPT` with `Path(config.arbitrage_pulse_script)` — raise a clear error if unset.
3. Move `_DEFAULT_SERVICE_URL` to `config.yaml` field `arbitrage_pulse_url`.

---

### Telegram Dual Key Names — Refactor

**Evidence:**
- `cato/adapters/telegram.py:92–95` — tries `TELEGRAM_BOT_TOKEN` then `CATODESKTOP_BOT_TOKEN` (both vault and env)
- `cato/.env` — key is `CATODESKTOP_BOT_TOKEN` (not the canonical name)
- `cato/api/integration_routes.py:87–88` — vault_keys=`("TELEGRAM_BOT_TOKEN",)`, env_keys=`("TELEGRAM_BOT_TOKEN",)` — status check uses canonical name only

**Why this verdict:**
The integration status endpoint only checks `TELEGRAM_BOT_TOKEN` but the actual adapter also accepts `CATODESKTOP_BOT_TOKEN`. A user could have `CATODESKTOP_BOT_TOKEN` set (Telegram works), yet the status page reports Telegram as unconfigured.

**Recommended action:**
1. `cato init` should normalize to `TELEGRAM_BOT_TOKEN` in the vault.
2. Update `integration_routes.py:87` to include both names in `vault_keys` and `env_keys`.
3. Document the canonical key name in README.

---

### GitHub Triple Key Names — Refactor

**Evidence:**
- `cato/tools/github_tool.py:124–136` — checks `GITHUB_TOKEN`, `GH_TOKEN`, `github_token`, `GITHUB_FOXFIREPOETS_TOKEN` (4 names)
- `cato/integrations/registry.py:110` — `credential_groups=(("GITHUB_TOKEN", "GH_TOKEN", "github_token"),)`
- `cato/.env` — `GITHUB_FOXFIREPOETS_TOKEN` (account-specific legacy name)

**Why this verdict:**
Four different key names for the same credential. The account-specific name `GITHUB_FOXFIREPOETS_TOKEN` is a personal artifact that should not be in production lookup logic.

**Recommended action:**
1. Standardize on `GITHUB_TOKEN` as the canonical name.
2. Remove `GITHUB_FOXFIREPOETS_TOKEN` from `github_tool.py:127` and `vault.py:125`.
3. `cato init` migration step: if `GITHUB_FOXFIREPOETS_TOKEN` exists in vault, copy to `GITHUB_TOKEN` and delete old key.

---

### uvicorn — Remove

**Evidence:**
- `pyproject.toml:dependencies` — `"uvicorn>=0.38.0"` listed as a production dependency
- No import of `uvicorn` found in any `.py` file under `cato/`
- Server is `aiohttp` throughout: `cato/ui/server.py`, `cato/api/routes.py`

**Why this verdict:**
`uvicorn` is an ASGI server (for Starlette/FastAPI), not used by aiohttp. It adds ~5 MB and an unnecessary ASGI dependency to every install.

**Recommended action:**
Remove `"uvicorn>=0.38.0"` from `pyproject.toml:dependencies`. Move to `[project.optional-dependencies]` only if any future ASGI endpoint is planned.

---

## Deadweight / Stale System Findings

| Finding | File Path(s) | Evidence | Why It Matters | Recommendation | Priority |
|---|---|---|---|---|---|
| WhatsApp stub — messages silently dropped | `cato/api/whatsapp_routes.py:128` | `# TODO: Integrate with agent_loop` — no `gateway.ingest()` call | Users expect bidirectional WA; they get webhook registered, no replies | Wire to gateway or disable channel | P1 |
| `/config POST` stub | `cato/ui/server.py:8,1574` | `stub; gateway wires real handler`; `# TODO: wire to CatoConfig.save()` | Settings saves appear to succeed but do not persist | Wire `CatoConfig.save()` or return 501 | P1 |
| `compact` endpoint stub (offline path) | `cato/ui/server.py:887` | Returns `{"status": "ok", "message": "Context compacted (stub)."}` when gateway is None | User gets false success confirmation | Return 503 when gateway unavailable | P2 |
| `uvicorn` unused dependency | `pyproject.toml` | No import found in `cato/` | Extra install weight, version conflicts possible | Remove from dependencies | P2 |
| Hardcoded `BEN_VOICE_PATH` in gmail_adapter | `cato/adapters/gmail_adapter.py:147` | `os.environ.get("BEN_VOICE_PATH", "")` — personal env var | Feature silently absent on all other machines | Add to vault/config or remove | P2 |
| `GITHUB_FOXFIREPOETS_TOKEN` legacy key | `cato/tools/github_tool.py:127`, `cato/vault.py:125` | Account-specific personal key name in production lookup | Confuses key management; should not be in source | Remove; migrate vault entry to `GITHUB_TOKEN` | P2 |
| Arbitrage Pulse hardcoded PS1 path | `cato/core/arbitrage_pulse.py:_PULSE_SCRIPT` | Absolute path `C:\Users\Administrator\Desktop\Github\...` | Feature broken on every machine except Ben's | Move to config field | P1 |
| Dual Telegram key names (status vs. adapter mismatch) | `integration_routes.py:87`, `adapters/telegram.py:92–95` | Status checks `TELEGRAM_BOT_TOKEN`; adapter also accepts `CATODESKTOP_BOT_TOKEN` | False "not configured" status when `CATODESKTOP_BOT_TOKEN` is set | Unify key lookup | P2 |
| `pipeline/workers.py:72` `source="mock"` | `cato/pipeline/workers.py:72` | `source="mock"` in live pipeline telemetry | Pipeline runs logged as mock data | Change to real source string | P2 |
| 5 pending Genesis agents in registry | `cato/tools/genesis.py` | `status: "pending"` on 5 of 20 registered agents | Routing to pending agents silently fails | Remove or clearly gate pending agents | P3 |
| Old project snapshots at repo root | `Cato-1A/`, `Cato-1B/`, `Cato-2A/` | Directories found at root level from prior versions | Pollutes codebase; adds confusion | Delete or move to `archive/` | P3 |
| BRAINSTORM/ directory at repo root | `BRAINSTORM/` | Non-source artifact directory | Bloats repo; not gitignored | Add to `.gitignore` or move to `docs/` | P3 |
| `google-auth-oauthlib` in deps | `pyproject.toml` | Listed as dep; `gmail_adapter.py` uses offline token only (refresh flow) | OAuth flow installed but unused in production path | Verify if `InstalledAppFlow` is called anywhere; if not, remove | P3 |
| `croniter` and `schedule_manager.py` vs `gateway.py` cron | Both `cato/core/schedule_manager.py` and `cato/gateway.py` | Two separate cron systems (YAML file + JSON file) | Dual scheduler creates confusion; which one wins? | Document canonical scheduler or consolidate | P2 |
| No CI/CD | `.github/workflows/` absent | No workflow files found | Tests never auto-run on push/PR | Add GitHub Actions workflow | P2 |
| `session_cap` deprecated but still in config | `cato/config.py:96–99` | Comment: `DEPRECATED — retained for backward compatibility but no longer enforced` | Misleads operators who set it | Mark as hidden in `cato status`; plan removal | P3 |

---

## Misfit Architecture Findings

| Area | File Path(s) | Current Implementation | Why It Is Misfit | Better Pattern | Priority |
|---|---|---|---|---|---|
| SwarmSync degraded fallback (silent) | `cato/agent_loop.py:1631` | When `SWARMSYNC_API_KEY` absent, logs warning and continues with `openai/gpt-4o-mini` directly | CLAUDE.md says "Cato returns a user-visible error rather than silently failing" — code violates this guarantee | Hard error on startup when `swarmsync_enabled: True` and key absent; expose error in `/health` | P0 |
| Dual cron schedulers | `cato/core/schedule_manager.py`, `cato/gateway.py:cron_*.json` | Two separate cron systems running in same process | Tasks scheduled in one system are invisible to the other; overlap/conflict possible | Single scheduler with a unified config source | P2 |
| Patchright on Windows-only daemon | `cato/tools/browser.py`, `pyproject.toml` | Patchright required as a hard dependency (not optional) | Forces Chromium download on every install even when `conduit_enabled: False` | Move to `optional-dependencies` group `conduit`; guard import with `try/except ImportError` | P2 |
| Multiple SQLite DBs with no WAL/backup | All `*.py` with `aiosqlite.connect()` | Each subsystem opens its own SQLite file with default journal mode | Single machine crash risks silent corruption of audit log, memory, ledger, and flow state simultaneously | Enable WAL mode on each DB open; implement daily backup via `cato backup` command | P1 |
| `context_gate.py` (temporal reconciler) vs `context_builder.py` | `cato/context/temporal_reconciler.py`, `cato/core/context_builder.py` | Two separate context management paths — `context/` and `core/` — with unclear separation | Developers cannot easily determine which context path is authoritative | Consolidate under `cato/core/`; deprecate `cato/context/` | P3 |
| `GENESIS_AGENTS_SWARMSYNC_API_KEY` vs `SWARMSYNC_API_KEY` | `cato/.env`, `cato/tools/genesis.py` | Separate key for Genesis routing vs. main SwarmSync routing | Dual key management for same routing infrastructure; can diverge | Consolidate to single `SWARMSYNC_API_KEY`; use for both paths | P2 |
| AgentLoop created fresh per conversation | `cato/gateway.py:_ensure_agent_loop()` | New `AgentLoop` instance per lane/session | Memory is loaded fresh each time (via `MemorySystem`); warm state not preserved across restarts | Persist `AgentLoop` across conversations per agent_id; share MemorySystem singleton | P2 |

---

### SwarmSync Silent Degradation — P0

**Evidence:**
- `cato/agent_loop.py:1631` — `logger.warning("SWARMSYNC_API_KEY not found in vault — SwarmSync routing disabled, using degraded fallback model")`
- `cato/agent_loop.py:1637–1643` — Falls through to direct `openai/gpt-4o-mini` call with no error returned to user
- `CLAUDE.md:swarmsync_enabled: true` — "if the key is missing, Cato returns a user-visible error rather than silently failing"
- `cato/ui/server.py:/health` — does check SwarmSync but returns `{"status": "ok"}` body even when routing degraded

**Why this verdict:**
The project's own CLAUDE.md explicitly states that a missing key must produce a user-visible error. The code instead logs a warning and silently falls back. A user running in this state would receive responses from `gpt-4o-mini` directly (billing them on OpenRouter) while believing SwarmSync is routing — a silent billing/routing contract violation.

**Recommended action:**
1. In `cato/agent_loop.py:~1628`, change the key-absence path to raise a user-visible error message returned as a chat response: `"SwarmSync key not configured. Run: cato vault set SWARMSYNC_API_KEY <key>"`
2. Update `cato/ui/server.py:/health` to return `{"status": "degraded", "reason": "SWARMSYNC_API_KEY missing"}` when key absent.
3. Update `cato doctor` check at `cato/doctor.py:352` to FAIL loudly (exit code 1) when key absent and `swarmsync_enabled: True`.

---

## Risk Register

| Risk | Category | Evidence (file:line) | Impact | Recommended Fix | Priority |
|---|---|---|---|---|---|
| SwarmSync silent fallback violates stated contract | Production Risk | `agent_loop.py:1631`, `CLAUDE.md` | User billed on OpenRouter unknowingly; no routing guarantee | Hard error when key absent + `swarmsync_enabled: True` | P0 |
| No SQLite WAL mode / no backup | Data Risk | All `aiosqlite.connect()` calls | Silent DB corruption on daemon crash (power loss, OOM) wipes audit log, memory, ledger | Enable WAL mode; add `cato backup` command | P1 |
| WhatsApp messages silently dropped | Production Risk | `whatsapp_routes.py:128` | Messages from WA users disappear with no error | Wire to `gateway.ingest()` or disable | P1 |
| `/config POST` stub returns 200 | Production Risk | `server.py:8,1574` | Config changes appear saved but are not; user data loss | Wire `CatoConfig.save()` or return 501 | P1 |
| Arbitrage Pulse broken off Ben's machine | Deployment Risk | `arbitrage_pulse.py:_PULSE_SCRIPT` | Feature 100% broken on any other machine | Config-driven path | P1 |
| No CI/CD — tests never auto-run | Maintainability Risk | `.github/workflows/` absent | Regressions merge silently; 1869-test suite goes unrun on push | Add GitHub Actions | P2 |
| Dual cron systems could fire same task twice | Production Risk | `schedule_manager.py` + `gateway.py` cron | Duplicate outreach emails or agent actions | Consolidate to single scheduler | P2 |
| `uvicorn` in production deps (unused) | Deployment Risk | `pyproject.toml` | Version conflict with aiohttp on some Python versions | Remove from deps | P2 |
| `BEN_VOICE_PATH` personal env var in production | User Trust Risk | `gmail_adapter.py:147` | Feature silently absent on all other installs | Config field or remove | P2 |
| `GITHUB_FOXFIREPOETS_TOKEN` in source | Security Risk | `github_tool.py:127`, `vault.py:125` | Personal account key name leaked in source; suggests personal vault contents in shared code | Remove; migrate to `GITHUB_TOKEN` | P2 |
| Patchright as hard dependency | Deployment Risk | `pyproject.toml` | Forces Chromium install (~300 MB) even when conduit disabled | Move to optional deps | P2 |
| Context budget 12K tokens — no dynamic adjustment | Production Risk | `context_builder.py:MAX_CONTEXT_TOKENS=12000` | Models with larger context windows underused; models with smaller windows overflow | Make token budget model-aware via router | P3 |
| Genesis endpoint on Render free tier | Integration Risk | `config.py:genesis_endpoint` | Render free tier sleeps after 15 min inactivity; first genesis call fails with cold start delay | Add retry + warm-up ping | P3 |
| `session_cap` deprecated but in config | Compliance Risk | `config.py:96–99` | Operators believe session cap is enforced; it is not | Remove field or re-enforce | P3 |
| No rate limiting on WebSocket `/ws` | Security Risk | `server.py` | Authenticated WS has no message rate limit; resource exhaustion possible | Add per-connection message rate limit | P3 |
| Audit log hash chain not verified on read | Compliance Risk | `audit/audit_log.py` | Hash chain is written but `verify-ledger` CLI command must be run manually; no runtime integrity check | Add startup integrity check for last N rows | P3 |

---

## Recommended Target Architecture

### Keep

- **SwarmSync routing** (`cato/swarmsync.py`, `cato/router.py`) — correct architecture; just harden the key-absence path — Evidence: `router.py:247–310`
- **AES-256-GCM vault** (`cato/vault.py`) — excellent security design with Argon2id KDF — Evidence: `vault.py:1–354`
- **Hash-chained audit log** (`cato/audit/audit_log.py`) — correct audit pattern — Evidence: `audit_log.py:_row_hash()`
- **ContextBuilder priority stack** (`cato/core/context_builder.py`) — clean 12K token budget with HOT/COLD delimiter — Evidence: `context_builder.py:SlotBudget`
- **SafetyGuard risk tiers** (`cato/safety.py`) — correct read/write/irreversible/high-stakes classification — Evidence: `safety.py:RiskTier`
- **Telegram adapter** (`cato/adapters/telegram.py`) — bidirectional, well-structured — just normalize key names
- **ClawFlows engine** (`cato/orchestrator/clawflows.py`) — correct multi-step workflow pattern — Evidence: `clawflows.py:FlowEngine`
- **Canary25 safety gates** (`cato/canary25/safety.py`) — correct operator-loop gate for outreach — Evidence: `canary25/safety.py:assert_canary_operator_safe()`

### Remove

- `uvicorn>=0.38.0` from `pyproject.toml:dependencies` — zero imports found in `cato/`
- `GITHUB_FOXFIREPOETS_TOKEN` from `github_tool.py:127` and `vault.py:125` — personal artifact
- `BEN_VOICE_PATH` env var from `gmail_adapter.py:147` — personal artifact
- `session_cap` field from `CatoConfig` — explicitly marked deprecated, never enforced
- `Cato-1A/`, `Cato-1B/`, `Cato-2A/` snapshot dirs at repo root — confirmed stale
- `BRAINSTORM/` from repo (add to `.gitignore`)

### Replace

- WhatsApp stub (`whatsapp_routes.py` with no agent wiring) → Full `WhatsAppAdapter` mirroring `TelegramAdapter` pattern, or remove until built

### Consolidate

- `TELEGRAM_BOT_TOKEN` + `CATODESKTOP_BOT_TOKEN` → single `TELEGRAM_BOT_TOKEN` everywhere
- `GITHUB_TOKEN` + `GH_TOKEN` + `github_token` + `GITHUB_FOXFIREPOETS_TOKEN` → single `GITHUB_TOKEN`
- `SWARMSYNC_API_KEY` + `GENESIS_AGENTS_SWARMSYNC_API_KEY` → single `SWARMSYNC_API_KEY` (unless genesis routing is deliberately isolated)
- `cato/core/schedule_manager.py` + `cato/gateway.py` JSON cron → single `SchedulerDaemon` reading one config source
- `cato/context/` + `cato/core/context_builder.py` → consolidate under `cato/core/`

### Refactor

- **SwarmSync key-absence path** (`agent_loop.py:1628–1643`) — hard error instead of silent fallback
- **Arbitrage Pulse** (`core/arbitrage_pulse.py`) — replace hardcoded absolute path with `config.arbitrage_pulse_script` field
- **Patchright** (`pyproject.toml`) — move from `dependencies` to `[optional-dependencies]` group `conduit`; guard import with `try/except ImportError`
- **SQLite WAL mode** — add `PRAGMA journal_mode=WAL` on every `aiosqlite.connect()` open (all affected files in `cato/core/`, `cato/audit/`, `cato/memory/`, `cato/monitoring/`, `cato/orchestrator/`)
- **Genesis pending agents** — guard 5 pending agent lookups with explicit `status != "pending"` filter in `tools/genesis.py`

### Add Tests For

1. **SwarmSync key-absence → hard error path** (`agent_loop.py:1628`): no test verifies the error message is surfaced to the user
2. **WhatsApp webhook → agent loop integration**: zero integration tests for WA path
3. **`/config POST` persistence**: no test verifies config actually saves to disk
4. **Audit log hash chain integrity on read**: `verify-ledger` is a CLI command; no automated integrity test on startup
5. **Dual cron deduplication**: no test verifying same task doesn't fire twice from both schedulers

### Source-of-Truth Decisions Needed

- **WhatsApp**: Build `WhatsAppAdapter` or defer? Decision gating: does the product commitment include bidirectional WA?
- **Dual SwarmSync keys** (`SWARMSYNC_API_KEY` vs. `GENESIS_AGENTS_SWARMSYNC_API_KEY`): intentional isolation (separate billing) or consolidation target?
- **Dual cron**: Which scheduler is canonical? YAML (`schedule_manager.py`) or JSON (`gateway.py`)?
- **`google-auth-oauthlib`**: Is the OAuth setup flow (`InstalledAppFlow`) ever called in production, or is the refresh-token-only path the only supported path?

---

## Coder Task Plan

### P0 Tasks

#### Task 1: Harden SwarmSync key-absence into a user-visible error

**Goal:**
When `swarmsync_enabled: True` and `SWARMSYNC_API_KEY` is absent, return a user-visible error in chat and mark `/health` as degraded — never silently fall back.

**Files involved:**
- `cato/agent_loop.py:~1628–1643` — replace warning + silent fallback with error message returned to user
- `cato/ui/server.py:/health handler` — return `{"status": "degraded", "reason": "SWARMSYNC_API_KEY missing"}` when key absent
- `cato/doctor.py:~352` — change `_fail()` call to exit code 1 when key absent + swarmsync enabled

**Work:**
1. In `agent_loop.py:~1631`, change the `logger.warning(...)` block to construct and return an assistant message: `"⚠️ SwarmSync is enabled but SWARMSYNC_API_KEY is not configured. Run: cato vault set SWARMSYNC_API_KEY <your-key>"` and break the planning loop.
2. In `server.py:/health`, add a check: if `swarmsync_enabled` and key absent, set `"status": "degraded"` in the response body (HTTP 200 still acceptable, but body must indicate degraded).
3. In `doctor.py:352`, ensure `self._fail(...)` is called (not just logged) — confirm it sets the exit code.

**Validation:**
```bash
# Start daemon without SWARMSYNC_API_KEY in vault
# Send a chat message
# Expected: user sees error message, not a gpt-4o-mini response
curl http://localhost:8080/health | python -m json.tool
# Expected: "status": "degraded" or "swarmsync_ok": false
```

**Acceptance criteria:**
- [ ] Chat response when key absent is an error message, not an LLM response
- [ ] `/health` returns `"swarmsync_ok": false` when key absent and `swarmsync_enabled: True`
- [ ] `cato doctor` exits with code 1 when key absent and swarmsync enabled

**Risk if skipped:**
Users silently billed on OpenRouter fallback while believing SwarmSync is routing; contract violation with stated behavior in CLAUDE.md.

---


#### Task 2: Fix `/config POST` stub — wire CatoConfig.save()

**Goal:**
POSTing to `/config` actually persists the config to `%APPDATA%/cato/config.yaml`.

**Files involved:**
- `cato/ui/server.py:POST /config handler (~L1574)` — replace stub with `config.save()`
- `cato/config.py:save()` — verify method is fully implemented

**Work:**
1. Read `cato/config.py:save()` to confirm implementation.
2. In `server.py:POST /config`, after parsing the request body, call `config.save()` and return `{"status": "ok"}`.
3. Add test: POST config change → restart daemon → verify change persisted.

**Validation:**
```bash
curl -X POST http://localhost:8080/config \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"log_level": "DEBUG"}'
# Then check %APPDATA%\cato\config.yaml for log_level: DEBUG
```

**Acceptance criteria:**
- [ ] Config change survives daemon restart
- [ ] Response is not `stub` message

**Risk if skipped:**
All settings UI changes are silently lost on restart.

---

#### Task 3: Fix Arbitrage Pulse hardcoded path

**Goal:**
`arbitrage_pulse.py` resolves the PS1 script path from config, not a hardcoded absolute path.

**Files involved:**
- `cato/core/arbitrage_pulse.py:_PULSE_SCRIPT` — replace with config lookup
- `cato/config.py` — add `arbitrage_pulse_script: str = ""` field

**Work:**
1. Add `arbitrage_pulse_script: str = ""` to `CatoConfig` dataclass.
2. In `arbitrage_pulse.py`, replace `_PULSE_SCRIPT = Path("C:/Users/...")` with `Path(config.arbitrage_pulse_script)`.
3. Add a guard: if path is empty or doesn't exist, raise `RuntimeError("arbitrage_pulse_script not configured in config.yaml")`.
4. Document in README how to configure the field.

**Validation:**
```bash
# Set arbitrage_pulse_script in config.yaml to valid path
# Call arbitrage pulse function
# Verify it runs without hardcoded path error
```

**Acceptance criteria:**
- [ ] No hardcoded absolute path in source
- [ ] Clear error when `arbitrage_pulse_script` unset
- [ ] Works on a machine where path differs from Ben's

**Risk if skipped:**
Feature permanently broken on every machine except the original developer's.

---

#### Task 4: Enable SQLite WAL mode on all DB opens

**Goal:**
All SQLite databases use WAL journal mode to prevent corruption on crash.

**Files involved:**
- `cato/core/memory.py` — add WAL pragma after open
- `cato/audit/audit_log.py` — add WAL pragma after open
- `cato/audit/ledger.py` — add WAL pragma after open
- `cato/orchestrator/clawflows.py` — add WAL pragma after open
- `cato/auth/token_store.py` — add WAL pragma after open
- `cato/memory/contradiction_detector.py`, `decision_memory.py` — add WAL pragma
- `cato/monitoring/anomaly_detector.py`, `cato/personalization/habit_extractor.py` — add WAL pragma
- `cato/routing_log.py`, `cato/context/temporal_reconciler.py` — add WAL pragma
- `cato/pipeline/store.py`, `cato/core/outbound_approval.py`, `cato/core/personal_store.py` — add WAL pragma
- `cato/core/session_checkpoint.py`, `cato/core/context_pool.py` — add WAL pragma

**Work:**
1. Create helper in `cato/platform.py`: `async def open_db(path) -> aiosqlite.Connection` that opens and immediately executes `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`.
2. Replace all direct `aiosqlite.connect(path)` calls with `platform.open_db(path)` across all affected files.
3. Run the full test suite to confirm no regressions.

**Validation:**
```bash
cd C:\Users\Administrator\Desktop\Cato
python -m pytest tests/ -x -q
# All 1869 tests must pass
```

**Acceptance criteria:**
- [ ] Every SQLite file has WAL mode after open (verify with `PRAGMA journal_mode;`)
- [ ] Test suite passes

**Risk if skipped:**
Daemon crash (power loss, OOM, Windows kill) can corrupt audit log, memory, or flow state with no recovery path.

---

### P2 Tasks

#### Task 5: Remove uvicorn from production dependencies

**Goal:**
`uvicorn` is removed from `pyproject.toml:dependencies`.

**Files involved:**
- `pyproject.toml:dependencies` — remove `"uvicorn>=0.38.0"`

**Work:**
1. Search entire `cato/` for `import uvicorn` — confirm zero results.
2. Remove from `pyproject.toml`.
3. Run `pip install -e .` and verify install succeeds.
4. Run test suite.

**Validation:**
```bash
grep -rn "uvicorn" cato/
# Expected: zero results in .py files
pip install -e . && python -m pytest tests/ -q --tb=short
```

**Acceptance criteria:**
- [ ] `uvicorn` removed from `dependencies`
- [ ] Tests pass
- [ ] Install succeeds

**Risk if skipped:**
Unnecessary dependency; potential ASGI/WSGI version conflict.

---

#### Task 6: Fix compact endpoint stub

**Goal:**
`POST /compact` returns 503 (not 200) when gateway is unavailable.

**Files involved:**
- `cato/ui/server.py:~887`

**Work:**
1. Find the offline stub at `server.py:~887`.
2. Replace `web.json_response({"status": "ok", "message": "Context compacted (stub)."})` with `web.json_response({"status": "error", "message": "Gateway unavailable — cannot compact."}, status=503)`.

**Validation:**
```bash
# Stop the gateway but keep server running (if possible)
curl -X POST http://localhost:8080/compact \
  -H "Authorization: Bearer <token>"
# Expected: 503 response
```

**Acceptance criteria:**
- [ ] No false 200 returned when gateway unavailable
- [ ] Client shows error state

---

#### Task 8: Normalize Telegram + GitHub key names

**Goal:**
Single canonical key name for each integration; legacy names accepted on read but deprecated on write.

**Files involved:**
- `cato/adapters/telegram.py:92–95` — normalize to `TELEGRAM_BOT_TOKEN`
- `cato/api/integration_routes.py:87–88` — add `CATODESKTOP_BOT_TOKEN` to vault_keys
- `cato/tools/github_tool.py:124–127` — remove `GITHUB_FOXFIREPOETS_TOKEN`
- `cato/vault.py:125` — remove `GITHUB_FOXFIREPOETS_TOKEN` reference
- `cato/cli.py:init` — add migration step for legacy key names

**Work:**
1. In `cli.py:init`, after vault setup: if `CATODESKTOP_BOT_TOKEN` exists in vault but `TELEGRAM_BOT_TOKEN` does not, copy and delete.
2. In `github_tool.py:127`, remove `GITHUB_FOXFIREPOETS_TOKEN` from the lookup chain.
3. Update `integration_routes.py:87` to list both names in `env_keys` for status check accuracy.
4. Update README key name documentation.

**Acceptance criteria:**
- [ ] `cato integration status` shows Telegram configured when only `CATODESKTOP_BOT_TOKEN` set
- [ ] No personal key name in source code

---

#### Task 9: Consolidate dual cron schedulers

**Goal:**
One canonical scheduler reads one config source; duplicate firing is impossible.

**Files involved:**
- `cato/gateway.py:~cron section` — determine which JSON cron path to keep or remove
- `cato/core/schedule_manager.py` — make this the single source of truth
- `cato/config.py` — ensure `SchedulerDaemon` reads from a single config field

**Work:**
1. Audit `gateway.py` to find where `cato_cron.json` is read and what it controls vs. YAML scheduler.
2. Decide canonical format (YAML per CLAUDE.md references).
3. Migrate any JSON cron tasks to YAML format.
4. Remove JSON cron reader from `gateway.py`.

**Acceptance criteria:**
- [ ] Only one scheduler instance runs per daemon
- [ ] All cron tasks visible in `cato cron list`

---

#### Task 10: Add GitHub Actions CI

**Goal:**
Tests run automatically on every push and PR to `main`.

**Files involved:**
- `.github/workflows/ci.yml` — create

**Work:**
1. Create `.github/workflows/ci.yml` with: Python 3.11 setup, `pip install -e ".[dev]"`, `pytest tests/ -q --tb=short`.
2. Add badge to README.
3. Ensure `asyncio_mode=auto` and `norecursedirs` from `pyproject.toml` are respected.

**Validation:**
```bash
# Push a commit and verify GitHub Actions triggers
# All 1869 tests must pass in CI
```

**Acceptance criteria:**
- [ ] CI runs on push
- [ ] Tests pass in CI environment (Linux runner)

---

### P3 Tasks

#### Task 11: Move Patchright to optional dependency

**Goal:**
`pip install cato-daemon` does not pull in Patchright/Chromium unless explicitly requested.

**Files involved:**
- `pyproject.toml` — move `"patchright>=1.49.0"` to `[optional-dependencies]` group `conduit`
- `cato/tools/browser.py` — wrap `from patchright...` in `try/except ImportError`
- `cato/tools/conduit_bridge.py` — same guard

**Work:**
1. Move `"patchright>=1.49.0"` to `[project.optional-dependencies] conduit = [...]`.
2. Add `try/except ImportError` around patchright imports in `browser.py` and `conduit_bridge.py`.
3. If import fails, raise a helpful `RuntimeError("conduit requires patchright: pip install cato-daemon[conduit]")` when any conduit tool is invoked.

**Acceptance criteria:**
- [ ] `pip install cato-daemon` succeeds without Patchright
- [ ] `pip install cato-daemon[conduit]` installs Patchright
- [ ] Clear error when conduit tool invoked without optional dep

---

#### Task 12: Remove personal artifacts from source

**Goal:**
No personal/machine-specific artifacts in source code.

**Files involved:**
- `cato/adapters/gmail_adapter.py:147` — remove `BEN_VOICE_PATH` env var reference
- Add `Cato-1A/`, `Cato-1B/`, `Cato-2A/`, `BRAINSTORM/` to `.gitignore`

**Work:**
1. In `gmail_adapter.py:147`, determine what `BEN_VOICE_PATH` does — if it's a voice TTS path, move to a config field `voice_output_path: str = ""`.
2. Add a `.gitignore` entry for snapshot dirs and BRAINSTORM.

**Acceptance criteria:**
- [ ] No `BEN_` prefixed env var in source
- [ ] Snapshot dirs not tracked by git

---

## Validation Checklist

- [x] Project structure mapped from actual file tree (not assumed)
- [x] Entry points identified with file paths (`cato/cli.py:main`, `cato_svc_runner.py`, `desktop/src-tauri/src/main.rs`)
- [x] API routes/controllers mapped with file paths (`cato/ui/server.py`, `cato/api/`)
- [x] UI routes/pages mapped with file paths (`desktop/src/views/`)
- [x] Database models mapped with schema file citations (`cato/core/memory.py`, `cato/audit/audit_log.py`, etc.)
- [x] Env vars traced to actual usage (grep run — 60+ references found)
- [x] Installed dependencies checked against import usage (uvicorn: zero imports found)
- [x] External integrations checked (installed / imported / live-wired)
- [x] Scripts and jobs reviewed for active maintenance
- [x] Deployment configs reviewed (no CI/CD found)
- [x] Tests reviewed and compared to current product surface (1869 passing, no WA/WhatsApp tests)
- [x] Docs claims compared against actual code (CLAUDE.md silent-failure claim violated by `agent_loop.py:1631`)
- [x] Dead / stale systems identified with evidence (WhatsApp stub, `/config` stub, arbitrage path, uvicorn)
- [x] Misfit integrations identified with specific pattern named (SwarmSync silent degradation, dual cron, hardcoded path)
- [x] Risk register created with evidence citations
- [x] Coder-ready task plan created with file paths

---

## Open Questions / Decisions Needed

1. **WhatsApp deployment timeline**: Is bidirectional WhatsApp a committed feature for the next release? If not, the stub should return 501 at the route level to stop silent message dropping. *Resolve by: product decision.*

2. **`GENESIS_AGENTS_SWARMSYNC_API_KEY` isolation intent**: Is this key intentionally separate from `SWARMSYNC_API_KEY` for billing isolation, or should it consolidate? *Resolve by: checking SwarmSync billing model — are Genesis calls billed to a different account?*

3. **Canonical cron format**: YAML (`schedule_manager.py`) vs. JSON (`gateway.py:cata_cron.json`)? *Resolve by: searching all user-facing docs and the Tauri settings UI for which format users configure.*

4. **`google-auth-oauthlib` usage**: Is `InstalledAppFlow` ever invoked in a user-facing path, or is the refresh-token-only path the only supported flow? *Resolve by: `grep -rn "InstalledAppFlow\|installed_user_flow\|oauth_flow" cato/`.*

5. **Desktop sidecar startup**: How does `cato-desktop.exe` start the Python daemon? Does the Rust sidecar spawn `python cato_svc_runner.py` or connect to a running daemon? This determines whether the daemon lifecycle is managed by Tauri or independently. *Resolve by: reading `desktop/src-tauri/src/lib.rs` fully.*

6. **Context budget for large-context models**: When SwarmSync routes to a 128K-context model, should `MAX_CONTEXT_TOKENS=12000` in `context_builder.py` be raised? *Resolve by: checking if `ModelRouter` exposes a context window size that `ContextBuilder` can consume.*
