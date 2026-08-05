# OpenClaw Feature Audit — Exhaustive Inventory

**Date:** 2026-03-07
**Purpose:** Competitive intelligence for Cato development
**Confidence:** 90% — based on official docs, GitHub README, community sources

---

## Table of Contents

1. [Background & Naming History](#1-background--naming-history)
2. [Architecture Overview](#2-architecture-overview)
3. [Web Control UI (Browser Dashboard)](#3-web-control-ui-browser-dashboard)
4. [WebChat (Native Chat Interface)](#4-webchat-native-chat-interface)
5. [Canvas / A2UI (Agent-Driven Visual Workspace)](#5-canvas--a2ui-agent-driven-visual-workspace)
6. [Messaging Channels (24 Total)](#6-messaging-channels-24-total)
7. [Model Providers & Routing](#7-model-providers--routing)
8. [Memory System](#8-memory-system)
9. [Skills / Plugin System (ClawHub)](#9-skills--plugin-system-clawhub)
10. [Session Management](#10-session-management)
11. [Cron Jobs & Scheduling](#11-cron-jobs--scheduling)
12. [Browser Automation](#12-browser-automation)
13. [Exec Approvals & Permissions](#13-exec-approvals--permissions)
14. [Nodes (Companion Devices)](#14-nodes-companion-devices)
15. [Voice & Audio](#15-voice--audio)
16. [Cost / Budget Tracking](#16-cost--budget-tracking)
17. [Security & Secrets Management](#17-security--secrets-management)
18. [MCP (Model Context Protocol) Integration](#18-mcp-model-context-protocol-integration)
19. [Desktop Apps](#19-desktop-apps)
20. [Agent-to-Agent Communication](#20-agent-to-agent-communication)
21. [Chat Commands](#21-chat-commands)
22. [Deployment & Installation](#22-deployment--installation)
23. [Localization](#23-localization)
24. [Known Weaknesses & Community Complaints](#24-known-weaknesses--community-complaints)
25. [Cato vs OpenClaw Gap Analysis](#25-cato-vs-openclaw-gap-analysis)

---

## 1. Background & Naming History

| Name | Period | Notes |
|------|--------|-------|
| ClawdBot | Original | Anthropic raised trademark concerns |
| MoltBot | Interim | Temporary rebrand |
| OpenClaw | Current (2025+) | Final name, open-source |

- **Tagline:** "Your own personal AI assistant. Any OS. Any Platform."
- **License:** Open-source (GitHub: openclaw/openclaw)
- **Written in:** TypeScript/Node.js (gateway), Swift (macOS/iOS), Kotlin (Android)
- **Package manager:** npm (`openclaw` package)
- **Stars/Community:** 13,729+ skills on ClawHub, very active GitHub Discussions

**Status:** CONFIRMED

---

## 2. Architecture Overview

### Core Components

| Component | Description |
|-----------|-------------|
| **Gateway** | Always-on WebSocket control plane at `ws://127.0.0.1:18789` |
| **Agent Runtime** | Assembles context, invokes LLM, executes tools, persists state |
| **Nodes** | Companion devices (macOS/iOS/Android/headless) connecting via WebSocket |
| **Skills** | Modular tool bundles (SKILL.md + supporting files) |
| **Canvas** | Agent-driven visual workspace (separate process, port 18793) |
| **Control UI** | Browser dashboard served by Gateway at port 18789 |
| **WebChat** | Native chat interface via Gateway WebSocket |

### Data Flow

```
User Message (any channel)
  --> Gateway (routing, auth, session lookup)
    --> Agent Runtime (context assembly, LLM call, tool dispatch)
      --> Response back through originating channel
```

### Storage Model

- **Config:** `~/.openclaw/openclaw.json` (YAML/JSON)
- **Memory:** Plain Markdown files on local filesystem
- **Sessions:** JSONL transcripts at `~/.openclaw/agents/<agentId>/sessions/<SessionId>.jsonl`
- **Search Index:** Per-agent SQLite at `~/.openclaw/memory/<agentId>.sqlite`
- **Exec Approvals:** `~/.openclaw/exec-approvals.json`

**Status:** CONFIRMED

---

## 3. Web Control UI (Browser Dashboard)

The Control UI is a browser-based admin surface served at `http://127.0.0.1:18789/` by the Gateway.

### 3.1 Chat Panel

| Feature | Description | Status |
|---------|-------------|--------|
| Chat with agent | Full chat via Gateway WebSocket | CONFIRMED |
| Streaming responses | Real-time token streaming | CONFIRMED |
| Tool call cards | Live tool output displayed as cards during agent events | CONFIRMED |
| Chat history | `chat.history` retrieval (truncates heavy metadata) | CONFIRMED |
| Chat send | `chat.send` with idempotent messaging | CONFIRMED |
| Chat inject | Append assistant notes to transcript without agent run | CONFIRMED |
| Chat abort | Stop active runs (`/stop`, abort phrases) with partial text retention | CONFIRMED |
| Abort metadata | Transcript marks partial completions | CONFIRMED |

### 3.2 Sessions Panel

| Feature | Description | Status |
|---------|-------------|--------|
| Sessions list | View all active sessions | CONFIRMED |
| Per-session overrides | Thinking/verbose toggles per session | CONFIRMED |
| Presence list | Show active connections (instances) | CONFIRMED |
| Session refresh | Refresh session state | CONFIRMED |

### 3.3 Channel Management

| Feature | Description | Status |
|---------|-------------|--------|
| Channel status | Monitor WhatsApp, Telegram, Discord, Slack, etc. | CONFIRMED |
| Plugin channels | Mattermost and custom integrations | CONFIRMED |
| QR login | QR code capability for channel connections | CONFIRMED |
| Per-channel config | Individual channel configuration | CONFIRMED |
| Delivery modes | Announce summary, none, or webhook | CONFIRMED |

### 3.4 Cron Jobs Panel

| Feature | Description | Status |
|---------|-------------|--------|
| Job list | View all scheduled jobs | CONFIRMED |
| Add/edit/delete jobs | Full CRUD for cron jobs | CONFIRMED |
| Run manually | Trigger job on-demand | CONFIRMED |
| Enable/disable toggles | Per-job activation | CONFIRMED |
| Run history | View past execution results | CONFIRMED |
| Delivery modes | Announce (default), none, webhook | CONFIRMED |
| Webhook config | Bearer token support (`cron.webhookToken`) | CONFIRMED |
| Delete-after-run | One-shot job support | CONFIRMED |
| Agent model overrides | Per-job model selection | CONFIRMED |
| Cron stagger | Prevent simultaneous execution | CONFIRMED |
| Form validation | Field-level error messaging | CONFIRMED |

### 3.5 Skills Panel

| Feature | Description | Status |
|---------|-------------|--------|
| Skills list | View all installed skills | CONFIRMED |
| Status display | Show enabled/disabled state | CONFIRMED |
| Enable/disable toggle | Per-skill activation | CONFIRMED |
| Install new skills | Add skills from ClawHub or workspace | CONFIRMED |
| API key management | Per-skill API key updates | CONFIRMED |

### 3.6 Nodes Panel

| Feature | Description | Status |
|---------|-------------|--------|
| Node listing | View connected companion devices | CONFIRMED |
| Capabilities display | Show what each node can do | CONFIRMED |
| Exec approvals card | Edit allowlists per node | CONFIRMED |

### 3.7 Configuration Panel

| Feature | Description | Status |
|---------|-------------|--------|
| View/edit config | `~/.openclaw/openclaw.json` via `config.get`/`config.set` | CONFIRMED |
| Apply and restart | Config validation + gateway restart | CONFIRMED |
| Base-hash guard | Prevents concurrent edit conflicts | CONFIRMED |
| Schema-driven forms | Dynamic form rendering for plugins/channels | CONFIRMED |
| Raw JSON editor | Fallback for advanced editing | CONFIRMED |

### 3.8 Diagnostics & Monitoring

| Feature | Description | Status |
|---------|-------------|--------|
| Status/health snapshots | System health overview | CONFIRMED |
| Models listing | Current model state | CONFIRMED |
| Event log | Gateway event display | CONFIRMED |
| Live log tail | Gateway log with filtering and export | CONFIRMED |
| Debug panel | Development diagnostics | CONFIRMED |
| Manual RPC calls | Test individual RPC endpoints | CONFIRMED |
| Update management | Package/git updates with restart reporting | CONFIRMED |

### 3.9 Dashboard Metrics

| Metric | Description | Status |
|--------|-------------|--------|
| Gateway status | Online/offline indicator | CONFIRMED |
| Uptime | Time since last restart | CONFIRMED |
| Memory usage | RAM consumption | CONFIRMED |
| CPU usage | Processor load | CONFIRMED |
| Connected channels | Count of active channels | CONFIRMED |
| Message counts | Total messages processed | CONFIRMED |
| Error rates | Failure frequency | CONFIRMED |
| Last activity | Timestamp of most recent event | CONFIRMED |
| Messages per day | Daily throughput chart | CONFIRMED |
| Response times | Latency metrics | CONFIRMED |
| Token usage | Input/output token counts | CONFIRMED |
| Model distribution | Which models are used and how often | CONFIRMED |
| Active sessions | Current session count | CONFIRMED |
| Session duration | Average/per-session timing | CONFIRMED |
| User activity | Per-user engagement metrics | CONFIRMED |

### 3.10 Authentication & Access

| Feature | Description | Status |
|---------|-------------|--------|
| Token auth | `connect.params.auth.token` at WebSocket handshake | CONFIRMED |
| Password auth | In-memory only, not persisted | CONFIRMED |
| Device pairing | First-time browser connection workflow | CONFIRMED |
| Device approval/revocation | Via CLI | CONFIRMED |
| Tailscale integration | Auto-approval for local, identity header verification | CONFIRMED |
| Loopback auto-approval | `127.0.0.1` connections auto-approved | CONFIRMED |
| Device ID generation | Per-browser profile | CONFIRMED |
| URL token stripping | Tokens removed from URL after load | CONFIRMED |
| Emergency bypass | `dangerouslyDisableDeviceAuth` flag | CONFIRMED |
| Allowed origins | CORS configuration for remote deployments | CONFIRMED |

**Status:** ALL CONFIRMED from official documentation

---

## 4. WebChat (Native Chat Interface)

| Feature | Description | Status |
|---------|-------------|--------|
| Native WS connection | Direct Gateway WebSocket (no embedded browser) | CONFIRMED |
| Deterministic routing | Replies always go back to WebChat | CONFIRMED |
| Same session/routing as channels | Unified session model | CONFIRMED |
| chat.history | Bounded conversation retrieval with truncation | CONFIRMED |
| chat.send | Send user messages | CONFIRMED |
| chat.inject | Append notes without triggering agent run | CONFIRMED |
| Abort handling | Partial output visible, abort metadata markers | CONFIRMED |
| Read-only fallback | When Gateway unreachable, history display only | CONFIRMED |
| Tools panel | Runtime tool catalog display in `/agents` section | CONFIRMED |
| Static fallback tool list | If dynamic catalog unavailable | CONFIRMED |

**Status:** CONFIRMED

---

## 5. Canvas / A2UI (Agent-Driven Visual Workspace)

| Feature | Description | Status |
|---------|-------------|--------|
| Separate server process | Port 18793, isolated from Gateway | CONFIRMED |
| Real-time HTML rendering | Agent pushes HTML over WebSocket | CONFIRMED |
| A2UI attributes | Agent-driven UI attributes embedded in HTML | CONFIRMED |
| Charts and dashboards | Agent-generated data visualizations | CONFIRMED |
| Interactive interfaces | User can interact with rendered content | CONFIRMED |
| Live updates | Content updates in real-time during agent runs | CONFIRMED |
| Canvas push/reset | Agent controls content lifecycle | CONFIRMED |
| Canvas eval | Execute JavaScript in canvas context | CONFIRMED |
| Canvas snapshot | Capture current canvas state | CONFIRMED |
| Multi-platform rendering | macOS (WebKit), iOS (SwiftUI), Android (WebView), Browser | CONFIRMED |
| Crash isolation | Canvas crash does not affect Gateway | CONFIRMED |

**Status:** CONFIRMED

---

## 6. Messaging Channels (24 Total)

| Channel | Library/Protocol | Status |
|---------|-----------------|--------|
| WhatsApp | Baileys | CONFIRMED |
| Telegram | grammY | CONFIRMED |
| Slack | Bolt | CONFIRMED |
| Discord | discord.js | CONFIRMED |
| Google Chat | API | CONFIRMED |
| Signal | signal-cli | CONFIRMED |
| iMessage | BlueBubbles (recommended) | CONFIRMED |
| iMessage Legacy | Direct | CONFIRMED |
| IRC | - | CONFIRMED |
| Microsoft Teams | - | CONFIRMED |
| Matrix | - | CONFIRMED |
| Feishu | - | CONFIRMED |
| LINE | - | CONFIRMED |
| Mattermost | Plugin | CONFIRMED |
| Nextcloud Talk | - | CONFIRMED |
| Nostr | - | CONFIRMED |
| Synology Chat | - | CONFIRMED |
| Tlon | - | CONFIRMED |
| Twitch | - | CONFIRMED |
| Zalo | - | CONFIRMED |
| Zalo Personal | - | CONFIRMED |
| WebChat | Built-in | CONFIRMED |
| macOS App | Native | CONFIRMED |
| iOS/Android | Native | CONFIRMED |

**Key channel features:**
- DM policies: pairing mode (default) or open mode
- Channel allowlisting: per-channel `allowFrom` configuration
- Group rules: mention gating, reply tags, per-channel chunking
- Media pipeline: image, audio, video handling with transcription hooks and size caps
- Typing indicators: presence and input signaling
- Streaming/chunking: response fragmentation and reassembly

**Status:** CONFIRMED

---

## 7. Model Providers & Routing

### 7.1 Provider Support

| Provider | Integration | Status |
|----------|-------------|--------|
| Anthropic (Claude) | Native | CONFIRMED |
| OpenAI (GPT) | Native | CONFIRMED |
| Google (Gemini) | Native + OAuth | CONFIRMED |
| OpenRouter | Built-in (no config needed) | CONFIRMED |
| Ollama | Auto-detected at localhost:11434 | CONFIRMED |
| AWS Bedrock | Supported | CONFIRMED |
| Azure OpenAI | Supported | CONFIRMED |
| Mistral | Supported | CONFIRMED |
| Voyage | Supported (embeddings) | CONFIRMED |
| Custom OpenAI-compatible | Configurable base URL | CONFIRMED |

### 7.2 Model Routing Features

| Feature | Description | Status |
|---------|-------------|--------|
| Failover chains | Ordered fallback list across providers | CONFIRMED |
| Auth profile rotation | Multiple credentials per provider | CONFIRMED |
| Exponential backoff | When provider goes down | CONFIRMED |
| Per-session model override | Change model mid-session | CONFIRMED |
| Per-cron model override | Different model for scheduled tasks | CONFIRMED |
| Model catalog | Built-in list of supported models | CONFIRMED |
| Custom model registration | Add models via config | CONFIRMED |
| Thinking/reasoning toggles | Enable/disable extended thinking per model | CONFIRMED |

**Status:** CONFIRMED

---

## 8. Memory System

### 8.1 Core Storage

| Feature | Description | Status |
|---------|-------------|--------|
| File-based memory | Plain Markdown files as source of truth | CONFIRMED |
| Daily logs | `memory/YYYY-MM-DD.md` (append-only, auto-loaded) | CONFIRMED |
| Long-term memory | `MEMORY.md` (curated, private sessions only) | CONFIRMED |
| Git-friendly | Back up with Git, grep through, edit in any editor | CONFIRMED |
| Workspace configurable | Via `agents.defaults.workspace` | CONFIRMED |

### 8.2 Search & Retrieval

| Feature | Description | Status |
|---------|-------------|--------|
| `memory_search` | Semantic recall over indexed snippets | CONFIRMED |
| `memory_get` | Targeted file/line-range reading | CONFIRMED |
| Hybrid search | Vector similarity + BM25 keyword matching | CONFIRMED |
| Score merging | `finalScore = vectorWeight * vectorScore + textWeight * textScore` | CONFIRMED |
| MMR re-ranking | Diversity mode to reduce redundant snippets | CONFIRMED |
| Temporal decay | Exponential recency boost (configurable half-life, default 30 days) | CONFIRMED |
| Evergreen files | `MEMORY.md` exempt from temporal decay | CONFIRMED |
| Extra paths | Index additional directories via `memorySearch.extraPaths` | CONFIRMED |

### 8.3 Embedding Providers (auto-selected in order)

1. Local GGUF models via node-llama-cpp
2. OpenAI API
3. Gemini embeddings
4. Voyage embeddings
5. Mistral embeddings
6. Ollama (requires explicit config)

### 8.4 Advanced Memory Backends

| Backend | Description | Status |
|---------|-------------|--------|
| Cognee | Knowledge graph from conversational data, GRAPH_COMPLETION search | CONFIRMED |
| Mem0 | Auto-extracts structured facts, vector DB storage, deduplication | CONFIRMED |
| Graphiti | Temporal knowledge graph (Episodes, Entities, Communities, 4 timestamps) | CONFIRMED |
| QMD | Experimental sidecar combining BM25 + vectors + reranking | CONFIRMED |

### 8.5 Session Memory (Experimental)

| Feature | Description | Status |
|---------|-------------|--------|
| Transcript indexing | Opt-in via `sessionMemory: true` | CONFIRMED |
| Delta-based triggers | Async indexing with configurable thresholds | CONFIRMED |
| Isolated per agent | Never blocks memory_search calls | CONFIRMED |
| QMD session export | Sanitized session transcripts indexed for recall | CONFIRMED |

### 8.6 Memory Management

| Feature | Description | Status |
|---------|-------------|--------|
| Pre-compaction flush | Silent agentic turn before token limit | CONFIRMED |
| Soft threshold | Configurable `softThresholdTokens` (default 4000) | CONFIRMED |
| File watcher | Auto-reindex on file changes (debounce 1.5s) | CONFIRMED |
| Embedding cache | SQLite-backed to avoid re-embedding | CONFIRMED |
| sqlite-vec acceleration | Optional vector virtual table for fast queries | CONFIRMED |
| Batch indexing | Async bulk embedding with configurable concurrency | CONFIRMED |

**Status:** CONFIRMED

---

## 9. Skills / Plugin System (ClawHub)

### 9.1 Skill Structure

| Feature | Description | Status |
|---------|-------------|--------|
| SKILL.md file | Main skill definition in Markdown | CONFIRMED |
| Supporting files | Additional text/config files in folder | CONFIRMED |
| Versioning | Semver, changelogs, tags | CONFIRMED |
| HOT/COLD split | HOT section for quick reference, COLD for full docs | CONFIRMED |

### 9.2 ClawHub Registry

| Feature | Description | Status |
|---------|-------------|--------|
| Public browsing | Browse skills and SKILL.md content | CONFIRMED |
| Vector search | Embedding-powered search (not just keywords) | CONFIRMED |
| Versioning | Semver with changelog history | CONFIRMED |
| Downloads | Zip per version | CONFIRMED |
| Stars and comments | Community feedback | CONFIRMED |
| Moderation hooks | Approval and audit workflows | CONFIRMED |
| CLI-friendly API | Automation and scripting support | CONFIRMED |
| 13,729+ skills | As of Feb 28, 2026 | CONFIRMED |
| GitHub account gating | Account must be 1+ week old to publish | CONFIRMED |

### 9.3 Skill Management in UI

| Feature | Description | Status |
|---------|-------------|--------|
| Auto-discovery | Agent can search ClawHub and install skills automatically | CONFIRMED |
| Enable/disable per skill | Toggle in Control UI | CONFIRMED |
| API key per skill | Manage credentials per skill | CONFIRMED |
| Install gating | Controlled skill installation | CONFIRMED |
| Three levels | Bundled, managed, workspace-level | CONFIRMED |

**Status:** CONFIRMED

---

## 10. Session Management

| Feature | Description | Status |
|---------|-------------|--------|
| Session store | Map of `sessionKey -> { sessionId, updatedAt, ... }` | CONFIRMED |
| JSONL transcripts | Per-session at `~/.openclaw/agents/<agentId>/sessions/` | CONFIRMED |
| `/status` command | Model, tokens, thinking/verbose state, credential freshness | CONFIRMED |
| `/compact` command | Summarize older context, persistent compaction | CONFIRMED |
| `/new` command | Start new session | CONFIRMED |
| `/reset` command | Reset session state | CONFIRMED |
| Token tracking | `inputTokens`, `outputTokens`, `totalTokens`, `contextTokens` | CONFIRMED |
| Context pruning | Automatic context management at limits | CONFIRMED |
| Per-session thinking override | Enable/disable reasoning per session | CONFIRMED |
| Per-session verbose override | Debug output toggle per session | CONFIRMED |
| Agent bindings | Route channels/users to specific agents | CONFIRMED |
| Main/group isolation | Separate DM and group session handling | CONFIRMED |
| Activation modes | Configurable trigger conditions | CONFIRMED |
| Queue modes | Message queuing behavior | CONFIRMED |

**Status:** CONFIRMED

---

## 11. Cron Jobs & Scheduling

| Feature | Description | Status |
|---------|-------------|--------|
| Cron syntax | Standard cron expressions | CONFIRMED |
| Delay/one-shot | "Poke agent in 20 minutes" type jobs | CONFIRMED |
| Persistent jobs | Survive gateway restarts | CONFIRMED |
| Delivery to chat | Optionally post results to a session | CONFIRMED |
| Announce summary | Default delivery mode | CONFIRMED |
| Webhook delivery | HTTP callback with optional bearer token | CONFIRMED |
| Silent execution | `delivery: none` for internal-only runs | CONFIRMED |
| Delete-after-run | One-shot execution | CONFIRMED |
| Model overrides | Per-job model selection | CONFIRMED |
| Stagger option | Prevent simultaneous execution | CONFIRMED |
| Run history | Track past executions | CONFIRMED |
| Gmail Pub/Sub | Integration for email-triggered jobs | CONFIRMED |

**Status:** CONFIRMED

---

## 12. Browser Automation

| Feature | Description | Status |
|---------|-------------|--------|
| Dedicated Chrome/Chromium | Separate browser instance | CONFIRMED |
| CDP control | Chrome DevTools Protocol integration | CONFIRMED |
| Page snapshots | Capture page state | CONFIRMED |
| Actions | Click, type, navigate, etc. | CONFIRMED |
| File uploads | Upload files to web pages | CONFIRMED |
| Browser profiles | Multiple profile support | CONFIRMED |
| Accessibility tree | Agent understands pages via a11y tree | CONFIRMED |
| OAuth flows | Automated authentication | CONFIRMED |
| Web scraping | Content extraction | CONFIRMED |

**Status:** CONFIRMED

---

## 13. Exec Approvals & Permissions

| Feature | Description | Status |
|---------|-------------|--------|
| Exec tool | Run shell commands on gateway or node host | CONFIRMED |
| Allowlist mode | Only pre-approved commands execute | CONFIRMED |
| Per-agent allowlists | Prevent cross-agent permission leakage | CONFIRMED |
| Policy + allowlist + approval | Three-layer permission check | CONFIRMED |
| Shell chaining rules | `&&`, `||`, `;` allowed when all segments pass | CONFIRMED |
| Redirect restrictions | Unsupported in allowlist mode | CONFIRMED |
| Elevated toggle | `/elevated on|off` for bash access | CONFIRMED |
| Tool policy | Allow/deny rules per agent and provider/channel | CONFIRMED |
| Control UI management | Edit defaults, per-agent overrides, allowlists | CONFIRMED |
| JSON config file | `~/.openclaw/exec-approvals.json` | CONFIRMED |

**Status:** CONFIRMED

---

## 14. Nodes (Companion Devices)

### 14.1 Node Architecture

| Feature | Description | Status |
|---------|-------------|--------|
| WebSocket connection | `role: "node"` to Gateway | CONFIRMED |
| Device pairing | Identity presentation + pairing request | CONFIRMED |
| Bonjour discovery | iOS device pairing | CONFIRMED |
| Command surface | `canvas.*`, `camera.*`, `device.*`, `notifications.*`, `system.*` | CONFIRMED |
| `node.invoke` | Gateway dispatches commands to nodes | CONFIRMED |

### 14.2 Node Capabilities

| Capability | Description | Status |
|------------|-------------|--------|
| Camera snap | Take photos | CONFIRMED |
| Camera clip | Record video clips | CONFIRMED |
| Screen record | MP4 recording (max 60s) | CONFIRMED |
| Location retrieval | GPS coordinates | CONFIRMED |
| Notifications | Push notifications | CONFIRMED |
| SMS access | Read/send messages (Android) | CONFIRMED |
| Photos access | Photo library (Android) | CONFIRMED |
| Contacts access | Contact list (Android) | CONFIRMED |
| Calendar access | Calendar events (Android) | CONFIRMED |
| Motion data | Accelerometer/gyroscope (Android) | CONFIRMED |
| App updates | Application management (Android) | CONFIRMED |
| System run | Execute commands with `--cwd`, `--env`, `--command-timeout` | CONFIRMED |

### 14.3 Platform-Specific Nodes

| Platform | Features | Status |
|----------|----------|--------|
| macOS | Menu bar app, Voice Wake, push-to-talk, WebChat, debug tools, SSH control | CONFIRMED |
| iOS | Canvas surface, Voice Wake, Talk Mode, camera, screen recording, Bonjour | CONFIRMED |
| Android | Connect/Chat/Voice tabs, Canvas, camera, screen capture, all device families | CONFIRMED |

**Status:** CONFIRMED

---

## 15. Voice & Audio

| Feature | Description | Status |
|---------|-------------|--------|
| Talk Mode | Continuous listen-think-speak loop | CONFIRMED |
| Voice Wake | macOS/iOS wake word detection | CONFIRMED |
| Push-to-talk | macOS manual voice activation | CONFIRMED |
| Voice Activity Detection (VAD) | Auto-detect speech start/end | CONFIRMED |
| Interrupt-on-speech | Stop playback when user speaks | CONFIRMED |
| TTS providers | ElevenLabs, Google Cloud TTS, Azure Speech, Coqui, system fallback | CONFIRMED |
| STT providers | Whisper API (OpenAI), Deepgram, Local Whisper (offline) | CONFIRMED |
| Node mic loop | Node handles microphone, Gateway handles model calls | CONFIRMED |
| Audio transcription hooks | Automatic voice-to-text on incoming audio | CONFIRMED |

**Status:** CONFIRMED

---

## 16. Cost / Budget Tracking

| Feature | Description | Status |
|---------|-------------|--------|
| `session_status` tool | Returns tokens in/out per run, model used | CONFIRMED |
| Token counting | Input/output/total/context tokens tracked | CONFIRMED |
| Cost estimation | Per-response cost when model provides data | CONFIRMED |
| `/usage` command | View token and cost data | CONFIRMED |
| Model distribution tracking | Which models are used how often | CONFIRMED |
| **NO native hard spend cap** | No built-in budget limit that cuts API calls | CONFIRMED |
| Proxy workaround | LiteLLM virtual keys with budget limits | CONFIRMED (community) |
| Cron-based budget alert | Custom skill to aggregate and alert | CONFIRMED (community) |
| Dashboard cost cards | Today's cost, all-time, projected monthly (community dashboards) | CONFIRMED (community) |

**NOTABLE GAP:** OpenClaw has NO built-in hard budget cap. This is a known pain point.

**Status:** CONFIRMED

---

## 17. Security & Secrets Management

### 17.1 Authentication

| Feature | Description | Status |
|---------|-------------|--------|
| Gateway token auth | WebSocket handshake authentication | CONFIRMED |
| Password auth | In-memory only | CONFIRMED |
| Device pairing | Browser device approval workflow | CONFIRMED |
| Tailscale integration | Tailnet-only HTTPS, identity verification | CONFIRMED |
| OAuth flows | Per-provider authentication | CONFIRMED |
| SecretRef | Managed token support | CONFIRMED |

### 17.2 Secrets Management

| Feature | Description | Status |
|---------|-------------|--------|
| `openclaw secrets` CLI | External secrets management tool | CONFIRMED |
| HashiCorp Vault | Integration via exec provider | CONFIRMED |
| AWS Secrets Manager | Integration via exec provider | CONFIRMED |
| Runtime injection | `${VAR}` references resolved at startup | CONFIRMED |
| No filesystem touch | Secrets never written to disk | CONFIRMED |
| Atomic reload | Secrets refreshed on Gateway restart | CONFIRMED |
| Exec provider bridge | Generic adapter to any external secret manager CLI | CONFIRMED |

### 17.3 Security Hardening

| Feature | Description | Status |
|---------|-------------|--------|
| `openclaw security audit` | Built-in security audit command | CONFIRMED |
| `openclaw doctor` | Misconfiguration detection and remediation | CONFIRMED |
| Allowlist mode | Command execution restrictions | CONFIRMED |
| Per-agent isolation | Agent permissions don't leak to others | CONFIRMED |
| TCC permission tracking | macOS permission awareness | CONFIRMED |
| Composio integration | Managed auth, least-privilege, audit logs, kill switch | CONFIRMED |

**Status:** CONFIRMED

---

## 18. MCP (Model Context Protocol) Integration

| Feature | Description | Status |
|---------|-------------|--------|
| Native MCP server support | `@modelcontextprotocol/sdk@1.25.3` | CONFIRMED |
| Config-based server registration | Specify in `openclaw.json` | CONFIRMED |
| Tool exposure | MCP server tools available to all agents | CONFIRMED |
| 1,000+ MCP servers | Community-built servers available | CONFIRMED |
| McPorter | Discovery/install/management tool for MCP servers | CONFIRMED |
| Bridge to Claude | MCP server connecting OpenClaw to Claude.ai with OAuth2 | CONFIRMED |

**Status:** CONFIRMED

---

## 19. Desktop Apps

### 19.1 Official/Native Apps

| Platform | Features | Status |
|----------|----------|--------|
| macOS | Menu bar app, TCC prompts, Voice Wake, push-to-talk, WebChat, debug tools, remote SSH | CONFIRMED |
| iOS | Canvas, Voice Wake, Talk Mode, camera, screen recording, Bonjour pairing | CONFIRMED |
| Android | Connect/Chat/Voice tabs, Canvas, camera, screen capture, device command families | CONFIRMED |

### 19.2 Community Desktop Apps

| App | Tech Stack | Features | Status |
|-----|-----------|----------|--------|
| OpenClaw Desktop | Tauri + SvelteKit + Ollama | Chat, documents, games, NPC mode, multi-gateway | CONFIRMED |
| OpenClaw-Windows | - | WSL/Native/Remote/WebSocket gateway connections | CONFIRMED |
| EasyClaw | Native Mac/Windows | Simplified OpenClaw interface | CONFIRMED |
| Claw Desktop | Native | Sessions, action approval, artifact review, proof export | CONFIRMED |
| OpenClaw-Windows-Hub | - | System tray, shared library, node, PowerToys integration | CONFIRMED |

**Status:** CONFIRMED

---

## 20. Agent-to-Agent Communication

| Feature | Description | Status |
|---------|-------------|--------|
| `sessions_list` | Discover active agents and metadata | CONFIRMED |
| `sessions_history` | Fetch other agent transcripts | CONFIRMED |
| `sessions_send` | Message other sessions with reply-back and announce toggles | CONFIRMED |
| Agent bindings | Route channels/users to specific agents | CONFIRMED |
| Thread-bound agents | First-class runtime feature (2026.2.26+) | CONFIRMED |

**Status:** CONFIRMED

---

## 21. Chat Commands

| Command | Function | Status |
|---------|----------|--------|
| `/status` | Model + tokens + toggles + credential status | CONFIRMED |
| `/new` | Start new session | CONFIRMED |
| `/reset` | Reset session | CONFIRMED |
| `/compact` | Summarize older context, free window space | CONFIRMED |
| `/think` | Toggle reasoning levels | CONFIRMED |
| `/verbose` | Toggle verbose output | CONFIRMED |
| `/usage` | Token and cost info | CONFIRMED |
| `/restart` | Restart gateway | CONFIRMED |
| `/activation` | Change activation mode | CONFIRMED |
| `/elevated on\|off` | Toggle elevated bash access | CONFIRMED |
| `/stop` | Abort current run | CONFIRMED |

**Status:** CONFIRMED

---

## 22. Deployment & Installation

| Method | Description | Status |
|--------|-------------|--------|
| `openclaw onboard` | Interactive wizard (gateway, workspace, channels, skills) | CONFIRMED |
| `--install-daemon` | Install as launchd (macOS) / systemd (Linux) user service | CONFIRMED |
| npm install | `npm install -g openclaw` | CONFIRMED |
| Docker | Container-based deployment | CONFIRMED |
| Nix | Declarative configuration | CONFIRMED |
| Stable/Beta/Dev channels | npm dist-tags | CONFIRMED |
| Tailscale Serve | Tailnet-only HTTPS | CONFIRMED |
| Tailscale Funnel | Public HTTPS (password required) | CONFIRMED |
| SSH tunnels | Remote access with token/password | CONFIRMED |

**Status:** CONFIRMED

---

## 23. Localization

| Feature | Description | Status |
|---------|-------------|--------|
| 6 languages | English, Simplified Chinese, Traditional Chinese, Portuguese (BR), German, Spanish | CONFIRMED |
| Auto-detection | Based on browser locale | CONFIRMED |
| Language picker | In Access card | CONFIRMED |
| Lazy-loaded translations | Non-English loaded on demand | CONFIRMED |
| Fallback to English | For missing translation keys | CONFIRMED |
| Persistent locale | Stored in browser storage | CONFIRMED |

**Status:** CONFIRMED

---

## 24. Known Weaknesses & Community Complaints

### Critical Pain Points

| Issue | Severity | Source |
|-------|----------|--------|
| **No hard budget cap** | HIGH | Community consensus |
| **Runaway API costs** | HIGH | Reddit horror stories ($300-$750/mo) |
| **Complex setup** | MEDIUM | Server config, API management, troubleshooting |
| **Security if misconfigured** | HIGH | Shell access = potential backdoor |
| **Name changes (3x)** | MEDIUM | Documentation chaos with each rebrand |
| **contextTokens reporting bug** | MEDIUM | Shows model max instead of actual usage |
| **Memory system "broken"** | MEDIUM | Blog post: defaults not optimal for most users |

### Architecture Limitations

| Limitation | Impact |
|------------|--------|
| Node.js/TypeScript only | No Python-native option |
| Gateway must stay running 24/7 | Resource consumption |
| No built-in encryption at rest | Files are plain Markdown |
| Memory relies on LLM quality | Bad writes pollute memory |
| No native audit trail | Relies on community tools for hash-chained audit |
| No built-in code execution sandbox | Security concern for exec tool |

**Status:** CONFIRMED from multiple community sources

---

## 25. Cato vs OpenClaw Gap Analysis

### Features Cato ALREADY HAS that match/exceed OpenClaw

| Feature | Cato | OpenClaw |
|---------|------|----------|
| Hard budget cap | YES ($1 session / $20 monthly) | NO (major Cato advantage) |
| Hash-chained audit log | YES (SHA-256, tamper-proof) | NO (community only) |
| AES-256-GCM vault | YES (encrypted secrets) | Partial (external vault integration) |
| Action guard (pre-execution gate) | YES (3-rule system) | Partial (exec approvals) |
| Reversibility registry | YES (track reversible actions) | NO |
| Delegation tokens | YES (scoped, time-limited) | NO |
| Knowledge graph memory | YES (kg_nodes, kg_edges) | Via plugins only (Cognee/Graphiti) |
| Multi-model orchestrator | YES (Claude/Codex/Gemini/Cursor fan-out) | YES (failover chains) |
| Query classification | YES (TIER_A/B/C routing) | NO (manual model selection) |
| Epistemic monitoring | YES (premise extraction, gap detection) | NO |
| Disagreement detection | YES (multi-model Jaccard) | NO |
| Decision memory | YES (write_decision, record_outcome) | NO |
| Contradiction detection | YES (Jaccard 0.35 threshold) | NO |
| Habit extraction | YES (behavioral patterns) | NO |
| Anomaly detection | YES (domain monitoring) | NO |
| Desktop app | YES (Tauri v2 + React) | Community only |
| Python-native | YES | NO (TypeScript only) |

### Features OpenClaw HAS that Cato LACKS

| Feature | Priority to Add | Difficulty |
|---------|----------------|------------|
| 24 messaging channels | LOW (Cato is daemon-first) | HIGH |
| Canvas / A2UI visual workspace | MEDIUM | MEDIUM |
| ClawHub skill marketplace (13K+ skills) | LOW (Cato uses SKILL.md) | HIGH |
| Voice / Talk Mode | MEDIUM | MEDIUM |
| Node system (companion devices) | LOW | HIGH |
| Cron scheduling | MEDIUM (Cato has schedule_manager) | LOW |
| Browser automation (CDP) | MEDIUM (Cato uses patchright) | LOW |
| MCP server integration | HIGH | MEDIUM |
| Localization (6 languages) | LOW | LOW |
| Config wizard (onboarding) | MEDIUM | LOW |
| File watcher for memory reindex | LOW | LOW |
| MMR re-ranking for search | MEDIUM | MEDIUM |
| Temporal decay for memory search | MEDIUM | MEDIUM |
| Session compaction (`/compact`) | MEDIUM | MEDIUM |
| Pre-compaction memory flush | MEDIUM | LOW |
| QMD experimental backend | LOW | HIGH |

### Cato's UNIQUE Advantages (OpenClaw Cannot Match)

1. **Hard budget enforcement** — OpenClaw has zero native spend caps; Cato has $1/$20 hard limits
2. **Tamper-proof audit chain** — SHA-256 hash-chained, field-level re-hash verification
3. **Action guard with 3-rule gate** — Pre-execution safety checks before any tool runs
4. **Reversibility tracking** — Know which actions can be undone
5. **Delegation tokens** — Scoped, time-limited, spending-capped authorization
6. **Epistemic monitoring** — Detect when the AI doesn't know enough to answer well
7. **Multi-model disagreement surfacing** — Catch when different models disagree
8. **Decision memory with outcome tracking** — Record decisions, track if they were correct
9. **Contradiction detection** — Automatically find conflicting information in memory
10. **Python-native** — Simpler deployment for Python shops, no Node.js dependency

---

## Sources

- [OpenClaw GitHub Repository](https://github.com/openclaw/openclaw)
- [OpenClaw Official Docs — Control UI](https://docs.openclaw.ai/web/control-ui)
- [OpenClaw Official Docs — Dashboard](https://docs.openclaw.ai/web/dashboard)
- [OpenClaw Official Docs — WebChat](https://docs.openclaw.ai/web/webchat)
- [OpenClaw Official Docs — Memory](https://docs.openclaw.ai/concepts/memory)
- [OpenClaw Official Docs — Model Providers](https://docs.openclaw.ai/concepts/model-providers)
- [OpenClaw Official Docs — Exec Approvals](https://docs.openclaw.ai/tools/exec-approvals)
- [OpenClaw Official Docs — ClawHub](https://docs.openclaw.ai/tools/clawhub)
- [OpenClaw Official Docs — Canvas](https://docs.openclaw.ai/platforms/mac/canvas)
- [OpenClaw Official Docs — Cron Jobs](https://docs.openclaw.ai/automation/cron-jobs)
- [OpenClaw Official Docs — Nodes](https://docs.openclaw.ai/nodes)
- [OpenClaw Official Docs — TTS](https://docs.openclaw.ai/tts)
- [OpenClaw Official Docs — Session Management](https://docs.openclaw.ai/concepts/session)
- [OpenClaw Official Docs — Secrets](https://docs.openclaw.ai/gateway/secrets)
- [ClawHub Skill Registry](https://github.com/openclaw/clawhub)
- [OpenClaw vs Claude Code — DataCamp](https://www.datacamp.com/blog/openclaw-vs-claude-code)
- [OpenClaw Architecture — Substack](https://ppaolo.substack.com/p/openclaw-system-architecture-overview)
- [OpenClaw Cost Optimization — LumaDock](https://lumadock.com/tutorials/openclaw-cost-optimization-budgeting)
- [OpenClaw Advanced Memory — LumaDock](https://lumadock.com/tutorials/openclaw-advanced-memory-management)
- [OpenClaw Security — Composio](https://composio.dev/blog/secure-openclaw-moltbot-clawdbot-setup)
- [OpenClaw MCP Integration — SafeClaw](https://safeclaw.io/blog/openclaw-mcp)
- [OpenClaw 20 Biggest Problems — GitHub Discussion](https://github.com/openclaw/openclaw/discussions/26472)
- [VoltAgent Awesome OpenClaw Skills](https://github.com/VoltAgent/awesome-openclaw-skills)
- [OpenClaw Community Dashboard](https://github.com/tugcantopaloglu/openclaw-dashboard)
- [Milvus — What Is OpenClaw](https://milvus.io/blog/openclaw-formerly-clawdbot-moltbot-explained-a-complete-guide-to-the-autonomous-ai-agent.md)
