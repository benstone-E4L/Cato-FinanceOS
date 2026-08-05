# CATO — MANDATORY DEVELOPMENT RULES

## ⚠️ ROUTING — READ THIS FIRST, EVERY TIME

**Cato calls the Anthropic API DIRECTLY. SwarmSync is NOT in the model-execution path.**

> Superseded 2026-08-03 by explicit owner decision (task t10). The previous rule
> ("Cato routes ALL LLM calls through SwarmSync. Full stop.") is void.

* **Credential:** `ANTHROPIC_API_KEY` — in the root `.env` and in the vault. This is
  the only credential the model-execution path needs. Never read, print, or log its value.
* **Model selection is policy, not prompt.** `cato/model_policy.py` is the single
  source of truth. `route(TaskDescriptor) -> RoutingDecision` is the ONLY sanctioned
  selection path. It takes no model argument and honours no override.
* **A model-supplied argument can never change the model.** `model`, `use_model`,
  `tier`, `effort`, `max_tokens`, `escalation_level` etc. arriving in tool arguments
  are scrubbed by `strip_model_selection_args()`. Precedent: a model-supplied
  `_approval_granted` arg was a live privilege-escalation bypass in the approval gate.
  Do not repeat that shape.
* **Execution:** `cato/anthropic_client.py` (`AnthropicDirectClient`) implements the
  Anthropic retry contract; `ModelRouter.complete_message()` in `cato/router.py`
  wires policy → call → escalation → routing log.
* **Escalation is bounded** at `MAX_ESCALATIONS = 2` and is driven only by deterministic
  validators and `stop_reason` (`refusal`, `max_tokens`, `model_context_window_exceeded`).
  There is NO confidence signal in the API — never escalate on self-assessment.
* **Cost gate runs pre-dispatch.** Projected worst-case cost = input tokens × input rate
  + `max_tokens` × output rate. `effort`/`task_budget` are SOFT hints, not caps;
  `max_tokens` is the only hard ceiling. Exceeding the ceiling BLOCKS dispatch — it
  never downgrades the model to fit.
* **Model ids are pinned snapshots** (no `-latest` aliases): `claude-opus-5`,
  `claude-sonnet-5`, `claude-haiku-4-5`, `claude-fable-5`. `claude-opus-4-1-20250805`
  is RETIRED (2026-08-05) and must never be selected.
* **Haiku 4.5 is a different call shape**, not "the same call, cheaper": no
  `output_config.effort`, no adaptive thinking (uses `thinking:{type:"enabled",budget_tokens:N}`),
  no interleaved thinking between tool calls, 200k context / 64k output.
* **Sonnet 5 intro pricing ends 2026-08-31** ($2/$10 → $3/$15). The cost model carries
  this date as data — do not hardcode today's price.
* If Cato returns empty responses, check `ANTHROPIC_API_KEY` and the daemon log's
  `[model-route]` lines first.

**SwarmSync is retained ONLY outside the model path** and must not be reintroduced to it:
`cato/tools/genesis.py` (Genesis agent tool), `cato/integrations/registry.py`
(credential registry entry), and the site-services bridge
(`cato/tools/site_services_bridge.py`). `swarmsync_enabled` / `swarmsync_api_url`
remain in config for those consumers and are inert for model execution.

> **Removed 2026-08-03 (task t22): the arbitrage subsystem.** Cato no longer does
> arbitrage. `cato/core/arbitrage_pulse.py`, `cato/core/arbitrage_cycle.py`, the
> `unified_arbitrage` integration, the `/arbitrage` Telegram command, the
> `arbitrage.*` scheduler skills and their policy/token-map rows are all gone.
> Those skill names are now UNKNOWN and therefore refused at the highest tier —
> do not re-add a row for any of them. `cato/core/site_services_pulse.py` and the
> site-services "permit arbitrage" bridge are a DIFFERENT feature and remain.

\---

## AUDIT GATE: NOTHING GETS PUSHED TO GITHUB WITHOUT PASSING THIS PIPELINE

Every change — no matter how small — must pass through the audit pipeline before any `git push`:

```
CODE COMPLETE
     |
     v

\[1] /HKO-truth-audit — Verification \& Reality Check
     - Verify authentic and complete
     - Independently verify test results
     - Implement any additional fixes Kraken deems necessary
     
     |
     v
\[2] GIT PUSH — Only after both agents approve
```



## WHAT THIS APPLIES TO

* All Python source changes (`cato/`, `tests/`)
* All frontend changes (`desktop/src/`, `cato/ui/`)
* All configuration changes (`pyproject.toml`, `Cargo.toml`, etc.)
* All new files added to the repo
* ALL commits intended for the `main` branch

## PROJECT OVERVIEW

**Cato** — Privacy-focused AI agent daemon. Alternative to OpenClaw/ClawdBot/MoltBot.

* Package: `cato-daemon` v0.2.0, entry point `cato.cli:main`
* Python 3.11+, asyncio, aiohttp, websockets, patchright, tiktoken, sentence-transformers
* Tauri v2 desktop app (`desktop/`) — React 19 + TypeScript + Rust sidecar
* SQLite memory, YAML config, AES-256-GCM encrypted vault
* **Ports: HTTP 8080, WS 8081** (canonical defaults)
* Live install: `pip install -e .` at `C:\\Users\\Administrator\\Desktop\\Cato`

## DAEMON CONFIGURATION

* Config: `%APPDATA%\\cato\\config.yaml`
* Default model: `openai/gpt-4o-mini`
* **workspace\_dir**: defaults to `%APPDATA%\\cato\\workspace` on Windows, `\~/.cato/workspace` on macOS/Linux (critical for identity files)
* **ANTHROPIC\_API\_KEY** — required for all LLM calls (direct Anthropic API). If missing, Cato returns a user-visible error rather than silently failing. `swarmsync\_enabled` is inert for model execution (see ROUTING above).
* Vault: `%APPDATA%\\cato\\vault.enc` — stores `OPENROUTER\_API\_KEY`, `TELEGRAM\_BOT\_TOKEN`, `SWARMSYNC\_API\_KEY`
* Vault password: `CATO\_VAULT\_PASSWORD=mypassword123` (**example only — always choose a unique, strong password in real installs**)
* Run daemon: `CATO\_VAULT\_PASSWORD=<your-strong-password> python cato\_svc\_runner.py`
* Health check: `curl http://localhost:8080/health`

## TELEGRAM INTEGRATION (2026-03-09)

* **Status**: ENABLED and bidirectional
* **Bot token**: Stored in encrypted vault as `TELEGRAM\_BOT\_TOKEN` (NOT in config.yaml)
* config.yaml has `telegram\_bot\_token: ''` and `telegram\_enabled: 'true'`
* Messages flow: Telegram → TelegramAdapter → gateway.ingest() → WebSocket broadcast → desktop app
* Responses flow: Agent loop → gateway.send() → WebSocket (desktop) + Telegram adapter (phone)
* Desktop app: `useChatStream.ts` handles `type: "message"` for incoming Telegram user messages
* Gateway: Both `ingest()` and `send()` broadcast telegram/whatsapp channels to WebSocket clients

## KEY DIRECTORIES

```
cato/                  Python daemon source
  api/                 aiohttp web + WebSocket handlers
  orchestrator/        Multi-model CLI fan-out (Claude/Codex/Gemini/Cursor)
    cli\_invoker.py     Claude/Codex/Gemini/Cursor invocation with timeouts
    cli\_process\_pool.py Warm pool for Claude/Codex
  audit/               Hash-chained audit log (PACKAGE)
  auth/                Token store + checker
  core/                Memory, context, scheduling
    memory.py          MemorySystem
    context\_builder.py ContextBuilder (loads SOUL.md, IDENTITY.md, SKILL.md)
    schedule\_manager.py SchedulerDaemon
  ui/
    server.py          aiohttp server, workspace\_put/get endpoints, CORS middleware
    dashboard.html     Web UI (monolithic SPA, \~1700 lines)
  adapters/
    telegram.py        Telegram long-polling adapter
  cli.py               Main Click CLI
  agent\_loop.py        Core agent loop + tool registry (file, browser, shell, github, conduit, memory, graph, web\_search, python, clawflows)
  gateway.py           Message routing hub — WebSocket broadcast + adapter delivery + activity indicator
  vault.py             AES-256-GCM vault
  budget.py            Hard spend caps
desktop/               Tauri v2 desktop app
  src/                 React/TypeScript frontend
    hooks/
      useChatStream.ts WebSocket hook — handles web + Telegram messages, 5s history poll
    components/
      ActivityIndicator.tsx  Real-time busy/idle pill (polls /api/activity + WS events)
    views/
      ChatView.tsx     Main chat interface
      SettingsView.tsx Settings tabs (general/memory/channels/scheduling/workspace)
  src-tauri/           Rust sidecar
    target/release/    cato-desktop.exe (17MB release build)
tests/                 pytest test suite (1869+ tests)
```

## DESKTOP APP DETAILS

* Built: `desktop/src-tauri/target/release/cato-desktop.exe`
* Desktop shortcut: `C:\\Users\\Administrator\\Desktop\\Cato.lnk` → points to exe above
* Build script: `desktop/build\_release.ps1`
* Build env: MSVC 14.44.35207 + Windows SDK 10.0.26100.0
* **Heartbeat timeout**: 45s (server sends every 30s)
* **CORS**: `cors\_middleware` in `cato/ui/server.py` — whitelists `tauri://localhost`, `http://tauri.localhost`, `https://tauri.localhost`, `http://127.0.0.1`, `http://localhost`
* Coding agent WS is on port 8080 (aiohttp), NOT 8081 (gateway)
* Logo: `cato-logo.png` (transparent 1024×1024 PNG), 44×44px in sidebar
* **Activity Indicator**: green "Idle" / amber "Working… <task>" pill in Dashboard + Chat headers. Backend: `gateway.\_broadcast\_activity()` pushes WS events + `GET /api/activity` HTTP polling (token-exempt). Frontend: `ActivityIndicator.tsx` polls every 2s, listens for WS `type: "activity"` events.

## SKILLS SYSTEM

* Skills directory: `\~/.cato/skills/` (18+ skills: add-notion, coding-agent, daily-digest, etc.)
* System prompt injection: `agent\_loop.py` builds prompt with `skills\_dir` parameter
* Model selection for each call is made by `cato/model\_policy.py` before dispatch (see ROUTING above)
* Workspace files (`SOUL.md`, `IDENTITY.md`, `AGENTS.md`, `TOOLS.md`) loaded from `workspace\_dir`

## CODING AGENT STATUS

Fan-out to Claude/Codex/Gemini/Cursor in parallel (60s timeout each):

* **Claude**: cli\_process\_pool (warm) — nested execution, blocked in production
* **Codex**: cli\_process\_pool (warm) — works
* **Gemini**: Subprocess only — hangs on Windows (stdin pipe detection issue)
* **Cursor**: Subprocess only — most reliable on this system
* All timeouts return degraded response with confidence 0.5

## WINDOWS-SPECIFIC NOTES

* npm CLIs (codex, gemini) are .CMD files; resolved via `shutil.which()` + `\["cmd.exe", "/c", path]`
* ANTHROPIC\_API\_KEY loaded from `.env` (python-dotenv); OpenRouter env key in `.env` is STALE — use vault
* Cato is run as SEPARATE daemon — Claude CLI is NOT nested in production
* PowerShell required for build scripts; bash available via Git Bash

## TEST INFRASTRUCTURE

* pytest asyncio\_mode=auto, tests/ directory
* Coverage via pytest-cov; `norecursedirs` excludes `.claude`, `BRAINSTORM`, `venv`
* **1869 passed, 2 failed** as of 2026-05-22 (1 collection error in `tests/test\_conduit\_proof.py`; 4 skipped)

## AUDIT REPORT LOCATIONS

* Alex audit: `CATO\_ALEX\_AUDIT.md` (repo root)
* Kraken verdict: `CATO\_KRAKEN\_VERDICT.md` (repo root)
* Historical verdicts: `KRAKEN\_VERDICT\_\*.md`

