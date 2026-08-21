> **HISTORICAL / SUPERSEDED — NOT CURRENT OPERATING TRUTH.** This report preserves a 2026-08-01 point-in-time audit. Use `AGENTS.md`, `docs/ops/LIMITATIONS.md`, and `docs/ops/VERIFICATION.md` for current launch guidance.

# Architecture Cartographer Report — Cato + Genesis Agents

**Audited:** 2026-08-01 · **Mode:** FULL AUDIT, focus area = *fitness as the runtime for the E4L Finance OS*
**Repos:** `C:\Users\Work\Desktop\GitHub\Cato` · `C:\Users\Work\Desktop\GitHub\Genesis Agents`
**Governing rule:** nothing below is claimed working. Every finding cites a file path. Nothing was executed — this is a read-only pass. The Cato daemon was **not running** during the audit (`http://localhost:8080/health` timed out).

---

## Executive Summary

Cato is a privacy-focused Python AI agent daemon with an unusually strong control skeleton for financial work: a hash-chained Ed25519-signed action ledger, a reversibility registry, a budget cap manager, a cron scheduler, an outbound-approval store, and session replay. Genesis Agents is a separate FastAPI gateway of 24 persona agents that Cato calls over signed HTTP.

**The single most important finding: every Genesis money-domain tool is a stub that returns `{"ok": true, "stub": true}` without touching any real system** (`tools/finance_tool.py:17-27`, plus `billing_tool.py`, `commerce_tool.py`, `pricing_tool.py` — zero HTTP imports between them). A Genesis agent asked to "process a vendor invoice" reports success and does nothing.

**Top recommendation:** make Cato the enforcement runtime and `ap-hub` the only write rail. Genesis stays on the read/analysis side, permanently blocked from the ledger path.

---

## Project Map  *(Phase 1)*

### Project Type
Two separate deployables, coupled by one signed HTTP tool call.

| App/Service | Path | Framework | Runtime | Purpose |
|---|---|---|---|---|
| Cato daemon | `Cato/cato/` | asyncio + aiohttp | Python ≥3.11, local Windows | Agent loop, tools, memory, audit, scheduling |
| Cato web UI | `Cato/cato/ui/server.py`, `dashboard.html` | aiohttp + monolithic SPA (~1700 ln) | HTTP 8080 | Dashboard, workspace endpoints |
| Cato desktop | `Cato/desktop/` | Tauri v2 + React 19 + TS | Rust sidecar | Chat/Settings shell |
| Cato MCP server | `Cato/cato/mcp/runtime.py` | uvicorn + MCP | remote | Exposes `cato_chat`, `cato_status`, `cato_list_sessions`, `cato_get_history` |
| Genesis gateway | `Genesis Agents/main.py` (143 KB) | FastAPI | `https://swarmsync-agents.onrender.com` | `POST /agents/{slug}/run` for 24 agents |
| Genesis worker | `Genesis Agents/worker.py` | async job runner | same host | Durable jobs for browser-heavy agents |

### Entry Points

| Entry | File Path | Notes |
|---|---|---|
| `cato` CLI | `Cato/cato/cli.py` (`cato.cli:main`, `pyproject.toml:[project.scripts]`) | Primary operator surface |
| Daemon runner | `Cato/cato_svc_runner.py`, `cato_service.py` | Long-running service |
| Agent loop | `Cato/cato/agent_loop.py` (~2000 ln) | Tool registry + dispatch |
| Gateway | `Cato/cato/gateway.py` | Message routing, skill install |
| Genesis API | `Genesis Agents/main.py` | FastAPI app |

### Important Config

| File | Path | What It Controls |
|---|---|---|
| Config dataclass | `Cato/cato/config.py` | `genesis_enabled:90`, `genesis_endpoint:91`, `genesis_agent_allowlist:92`, `safety_mode:170` |
| Runtime config | `%APPDATA%\cato\config.yaml` (per `Cato/CLAUDE.md:58`) | Live daemon settings |
| Vault | `%APPDATA%\cato\vault.enc` | AES-256-GCM secrets |
| Repo `.env` | `Cato/.env` | 13 keys — see Deadweight |
| Genesis policy | `Genesis Agents/runtime/tool_policy.py` | Per-slug risk allow-lists |
| Genesis bundles | `Genesis Agents/skill_bundles/*.json` (24 files) | Persona, tools, token budget per agent |

### Test Surface

| Type | Directory | Count | Framework |
|---|---|---|---|
| Cato unit/integration | `Cato/tests/` | 1869 passing / 2 failing as of 2026-05-22 (`Cato/CLAUDE.md:155`) — **NOT RE-RUN in this audit** | pytest, `asyncio_mode=auto` |
| Cato orchestrator | `Cato/cato/orchestrator/tests/` | 7 files | pytest |
| Genesis | `Genesis Agents/test_*.py` | 21 files | pytest |

---

## System Understanding  *(Phase 2)*

**Apparent product purpose.** Cato is a self-hosted, auditable AI agent daemon — "the AI agent daemon you can audit in a coffee break" (`pyproject.toml:description`). It runs a tool-using agent loop locally, keeps memory in SQLite, encrypts secrets in a vault, and records every action in a tamper-evident ledger (`cato/audit/ledger.py:75`).

**Core backend flow (verified by reading `agent_loop.py:1883-1953`):**

```
LLM emits tool_calls
  → _resolve_tool_name()                    :1885
  → SafetyGuard.check_and_confirm()         :1889   ← risk gate
  → TokenChecker.check_authorization()      :1903   ← delegation token
  → _maybe_gate_outbound_tool()             :1914   ← human approval
  → _dispatch_with_progress()               :1920   ← actual execution
  → audit_log.log()                         :1930
  → LedgerMiddleware.append()               :1940   ← hash-chained + signed
```

That is a genuinely well-shaped write path. Three of its four gates have defects — see Risk Register.

**External service dependencies:** SwarmSync LLM router (`cato/router.py`), Genesis gateway (`cato/tools/genesis.py:289`), Telegram (`cato/adapters/telegram.py`), Gmail (`cato/adapters/gmail_adapter.py`), GitHub (`cato/tools/github_tool.py`), Conduit/Patchright browser (`cato/tools/conduit_bridge.py`).

**Production-critical systems:** `agent_loop.py`, `router.py` (all LLM traffic), `vault.py` + `vault_crypto.py` (secrets and the Ed25519 identity that signs Genesis envelopes), `budget.py`.

**Stubbed / demo-only systems:** see Misfit Architecture — this is where the E4L answer lives.

---

## Architecture Map  *(Phase 3)*

### Tool Registry (Cato) — the surface an accounting workload would use

| Tool group | File Path | Registered at | Status |
|---|---|---|---|
| file | `cato/tools/file.py` | `agent_loop.py:750` | Active |
| browser / conduit | `cato/tools/browser.py`, `conduit_bridge.py`, `conduit_crawl.py`, `conduit_monitor.py`, `conduit_proof.py` | `:769`, `:1016` | Active |
| shell | `cato/tools/shell.py` | `:619` | Active, opt-in gated |
| python | `cato/tools/python_executor.py` | `:634` | Active |
| github | `cato/tools/github_tool.py` | `:843` | Active |
| memory / graph | `cato/tools/memory.py` | `:661`, `:709` | Active |
| web_search | `cato/tools/web_search.py` | `:578` | Active |
| integration | `cato/tools/integration_tool.py`, `cato/integrations/registry.py` | `:954` | Active |
| clawflows | `cato/orchestrator/clawflows.py` | `:690` | Active |
| **genesis** | `cato/tools/genesis.py` | schema at `:419` | Active — calls remote gateway |
| **(none)** | — | — | **No accounting/ledger tool exists.** |

### Control & Audit Subsystem

| Service | File Path | Purpose | Called By |
|---|---|---|---|
| `SafetyGuard` | `cato/safety.py:88` | 4-tier risk gate, STOP-file kill switch | `agent_loop.py:1889` ✅ |
| `LedgerMiddleware` | `cato/audit/ledger.py:75` | Hash-chained Ed25519-signed record | `agent_loop.py:1940` ✅ |
| `LedgerQuery` / `verify_chain` | `cato/audit/ledger.py` | Replay + tamper verification | `cli.py` |
| `OutboundApprovalStore` | `cato/core/outbound_approval.py` | Human-in-the-loop, persisted in `cato.db` | `agent_loop.py:2143` ✅ |
| `TokenChecker` | `cato/auth/token_checker.py` | Delegation-token authorization | `agent_loop.py:1903` ✅ |
| `BudgetManager` | `cato/budget.py` | Per-call / daily / monthly caps | agent loop + `genesis.py:276` ✅ |
| `ReceiptWriter` | `cato/receipt.py` | Signed per-session billing transcript | `cli.py` |
| `ReplayEngine` | `cato/replay.py` | Dry-run session replay from audit log | `cli.py` |
| **`ActionGuard`** | `cato/audit/action_guard.py:26` | Reversibility × autonomy pre-action check | **`cato/ui/server.py:1919` only — NOT on the tool path** ❌ |
| **`ReversibilityRegistry`** | `cato/audit/reversibility_registry.py:44` | Tool → reversibility score 0.0–1.0 | Only via `ActionGuard` + `cli.py:2910` (list command) ❌ |

### Scheduling

| Component | File Path | Trigger | Notes |
|---|---|---|---|
| `SchedulerDaemon` | `cato/core/schedule_manager.py` | cron per YAML file in `~/.cato/schedules/` | Fields: `name, cron, skill, args, budget_cap, enabled` |
| `dispatch_scheduled_skill` | `cato/core/scheduled_dispatch.py` | called by scheduler | Enforces per-run `budget_cap` (cents) before dispatch |

### Skills

| Mechanism | File Path | Behaviour |
|---|---|---|
| Skill directories scanned | `agent_loop.py:1587-1593` | `~/.cato/skills/` **and** `~/.claude/skills/` (fix BH-004) |
| Activation matching | `cato/core/context_builder.py:105-160` (`resolve_active_skills`) | Requires a `## Trigger Phrases` heading; matches comma-separated phrases as case-insensitive substrings of the user message |
| Skill install | `cato/gateway.py:1140-1154` | Clones a repo or writes a raw `SKILL.md` into `~/.cato/skills/` |

### Genesis Agents

| Component | File Path | Notes |
|---|---|---|
| Registry (20 slugs) | `Cato/cato/tools/genesis.py:41-62` | 15 `deployed`, 5 `pending` |
| Bundles on disk (24) | `Genesis Agents/skill_bundles/*.json` | 4 more than Cato's registry knows about |
| Wire protocol | `genesis.py:76-121` | AP2 v1 envelope: canonical JSON + nonce + RFC3339 ts, Ed25519-signed from the Cato vault |
| Auth | `genesis.py:329-341` | `X-AP2-Pubkey` + optional `X-Agent-Api-Key` from vault key `GATEWAY_API_KEY` |
| Tool policy | `Genesis Agents/runtime/tool_policy.py` | Fail-closed: unknown tool → `RISK_ADMIN`; unknown slug → `read_only` only |
| Hosting | `Genesis Agents/CLAUDE.md:5,22-25` | Render free tier, 30 s proxy timeout; browser agents use `job_mode: "async"` |

---

## Integration Forensics  *(Phase 4)*

| Integration | Installed? | Env Vars? | Imported? | Live Usage? | Verdict | Recommendation |
|---|---|---|---|---|---|---|
| SwarmSync LLM router | n/a (HTTP) | `SWARMSYNC_API_KEY` in `.env` + vault | `cato/router.py` | Yes — all LLM traffic | **Keep** | Sole LLM path; do not add a second router |
| Genesis gateway | n/a (HTTP) | `GENESIS_AGENTS_SWARMSYNC_API_KEY`, vault `GATEWAY_API_KEY` | `cato/tools/genesis.py` | Yes — registered tool | **Isolate** | Read/analysis only; block all money slugs for E4L |
| Telegram | `python-telegram-bot>=21.0` | `CATODESKTOP_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `cato/adapters/telegram.py` | Yes | **Keep** | Becomes the approval channel |
| Gmail / Google | `google-api-python-client`, `google-auth*` | 5 `GMAIL_*` keys in `.env` | `cato/adapters/gmail_adapter.py` | Yes | **Keep** | AP document ingestion |
| GitHub | n/a (HTTP) | `GITHUB_FOXFIREPOETS_TOKEN` | `cato/tools/github_tool.py` | Yes | **Keep** | Build tracking only |
| Conduit / Patchright | `patchright>=1.49.0` | `conduit_enabled` in `.env` | `cato/tools/conduit_bridge.py` | Yes | **Keep** | Portals with no API (Tapfiliate, bank portals) — never the posting path |
| MCP | `mcp>=1.22.0` | `MCP_*` (see `cato/mcp/runtime.py`) | `cato/mcp/runtime.py` | Yes | **Keep** | How Claude Code reaches Cato |
| **Xero / any ledger** | **No** | **No** | **No** | **No** | **Add** | The gap this project exists to fill |
| `sentence-transformers` + `numpy` | `pyproject.toml` | — | `cato/core/semantic_search.py` | Verify | **Verify** | Heavy dep (~2 GB with torch) on a controller laptop; confirm it is required |

### Genesis gateway — **Isolate**

**Evidence:**
- `Genesis Agents/tools/finance_tool.py:1-6` — *"Phase 3 scaffolds… Real provider integration (payroll, AR/AP, bank feeds, AP2/x402) lands in Phase 9."*
- `finance_tool.py:17-27` — `_scaffold()` returns `{"ok": True, "stub": True, "action": …, "note": "Phase 3 scaffold"}`.
- Stub-marker / HTTP-import scan across `Genesis Agents/tools/`: `finance_tool.py` 23 stub markers / **0** HTTP imports · `commerce_tool.py` 24 / 0 · `pricing_tool.py` 24 / 0 · `billing_tool.py` 21 / 0 · `domain_tool.py` 16 / 1 · `hr_tool.py` 12 / 0. Compare the genuinely wired tools: `web_tool.py` 0 / 1, `github_tool.py` 0 / 1, `vision_tool.py` 0 / 1, `deploy_tool.py` 0 / 1.
- `Genesis Agents/skill_bundles/genesis-finance.json` — advertises `finance_process_vendor_invoice`, `finance_run_finance_close`, `finance_run_payroll_batch` with `"tools_verified": true`.
- `Genesis Agents/runtime/tool_policy.py` — `genesis-finance` is the one slug granted `RISK_PAYMENT`.
- `Cato/cato/tools/genesis.py:47` — `genesis-finance` status `deployed`, price `$400`.

**Why this verdict:** the bundle advertises a monthly close and vendor-invoice processing; the implementation returns success without doing anything. `"tools_verified": true` in the bundle refers to dispatchability, not to any real posting. An orchestrator that reads `{"ok": true}` will record a close as completed. For a general SaaS demo that is a harmless scaffold; for a ledger it manufactures false completion evidence. The `RISK_PAYMENT` grant makes it worse — the one agent with payment privilege is the one whose payment tools are hollow.

**Recommended action:** set `genesis_agent_allowlist` in `%APPDATA%\cato\config.yaml` (`cato/config.py:92`) to read/analysis slugs only — `genesis-research`, `genesis-analyst`, `genesis-content`, `genesis-qa`, `genesis-security`. Explicitly exclude `genesis-finance`, `genesis-billing`, `genesis-commerce`, `genesis-pricing`. The allow-list is only enforced when non-empty (`genesis.py:247-253`), so leaving it empty today means **all 15 deployed agents are callable**.

---

## Deadweight Findings  *(Phase 5)*

| Finding | File Path(s) | Evidence | Why It Matters | Recommendation | Priority |
|---|---|---|---|---|---|
| `ActionGuard` + `ReversibilityRegistry` are unreachable from the tool path | `cato/audit/action_guard.py`, `reversibility_registry.py` | Grep for `check_before_execute` across `cato/` returns only the definition; `cato/ui/server.py:1919-1926` constructs a guard then returns a **hardcoded** checks list and `"autonomy_level": 0.5` | The dashboard shows a safety control that does not run. Worst kind of dead code: it reads as reassurance | **Refactor** — call it in `agent_loop.py` before dispatch, or delete the dashboard panel | **P1** |
| Duplicate audit module | `cato/audit.py` **and** `cato/audit/` package | Both exist at the same import path root | Ambiguous imports; `cato/audit.py` may be shadowed by the package | **Verify** which one Python resolves, then delete the loser | P2 |
| 206 of 216 `~/.claude/skills` are invisible to Cato | `cato/core/context_builder.py:141` | Scan of `C:\Users\benst\.claude\skills`: 216 dirs with `SKILL.md`, **10** contain a `## Trigger Phrases` heading | The BH-004 fix (`agent_loop.py:1588-1593`) added the directory but not the format bridge. All four `e4l-*` skills and `xero-accounting` are in the invisible 206 | **Refactor** — parse YAML frontmatter `description:` as a trigger source, or append `## Trigger Phrases` per skill | **P1** |
| `~/.cato/skills/` does not exist | `C:\Users\benst\.cato\` | Directory listing shows `browser_profile`, `sessions`, `workspace`, `cato.db`, `conduit_identity.key`, `session_count.txt` — no `skills/` | The primary skills dir is absent; `CLAUDE.md:129` claims "18+ skills" installed there | **Document** the real state; create the dir during E4L install | P2 |
| Genesis registry drift | `Cato/cato/tools/genesis.py:41-62` vs `Genesis Agents/skill_bundles/` | Cato knows 20 slugs; 24 bundles on disk (`genesis-domain`, `genesis-maintenance`, `genesis-onboarding`, `genesis-seo` variance) | Callers cannot reach 4 agents; registry comment at `:38-40` says to keep them aligned | **Refactor** — generate the registry from bundles, or fetch it from the gateway | P2 |
| `.env` key naming mismatch | `Cato/.env` | Has `CATODESKTOP_BOT_TOKEN`; `CLAUDE.md:70` says the vault key is `TELEGRAM_BOT_TOKEN` | Confusion about which is authoritative — repeats the `SLACK_API_TOKEN` ambiguity already flagged in the E4L spec §I | **Document** | P2 |
| ~50 audit/positioning markdown files at repo root | `Cato/*.md` (BRUTAL_TRUTH, KRAKEN_VERDICT_*, REMIXFORGE_*, DARKMIRROR_*, POSITIONING_*, OPENCLAW_*) | Root listing | Signal-to-noise: a new operator cannot find the current truth | **Consolidate** into `docs/` with an index; dated verdicts to `docs/history/` | P3 |

---

## Misfit Architecture  *(Phase 6)*

| Area | File Path(s) | Current Implementation | Why Misfit | Better Pattern | Priority |
|---|---|---|---|---|---|
| **Genesis money agents** | `Genesis Agents/tools/{finance,billing,commerce,pricing}_tool.py` | `_scaffold()` returns `{"ok": true, "stub": true}` | **Mock data in production path** — success responses with no side effect, reachable through a live registered Cato tool | Real connector, or refuse the call. A stub must return `ok: false, error: "not_implemented"` | **P0 for E4L** |
| **SafetyGuard fails open for unknown tools** | `cato/safety.py:42-55`, `:130`, `:171` | `_TOOL_TIER` covers only 12 browser/file/memory tools. Everything else → `RiskTier.REVERSIBLE_WRITE` (1), which is **below** the strict threshold `IRREVERSIBLE` (2) → auto-allowed | A new `xero.post_bill` tool would post **with no gate at all**. The `shell` keyword escalation is the only dynamic rule | Fail-closed default, as Genesis already does (`runtime/tool_policy.py`: unknown → `RISK_ADMIN`) | **P0 for E4L** |
| **Approval routing is a hardcoded 3-name list** | `cato/core/outbound_approval.py:169-179` | `requires_approval()` returns True only for `send_email`, `outreach.run`, `outreach_bridge`, plus a `genesis-email` keyword heuristic | Not policy-driven. Any ledger tool defaults to no approval. Also: `args.get("dry_run")` short-circuits the gate, and that arg is **model-controlled** | Table-driven policy loaded from YAML (the `xero-accounting` skill already ships `permission-matrix.yaml` + `approval-policy.yaml` in this exact shape) | **P0 for E4L** |
| **Audit write is fail-open** | `cato/agent_loop.py:1938-1947` | `self._ledger.append(...)` wrapped in `try/except` that logs at `logger.debug` | If the tamper-evident ledger fails, the action still proceeds and the failure is invisible at default log level. For accounting, no-audit must mean no-action | Fail-closed: ledger failure aborts the tool call | **P0 for E4L** |
| **Denied actions are not ledgered** | `cato/agent_loop.py:1889-1897` vs `:1938` | Safety-denied calls write to `_audit_log` but the `_ledger.append` call sits inside the `else` branch | The hash-chained record has no evidence of refusals. `approval-policy.yaml` requires *"denied_tickets_logged_with_equal_fidelity_to_approved_ones"* | Move ledger append outside the branch | **P1** |
| **Dashboard safety panel is decorative** | `cato/ui/server.py:1919-1929` | Returns a static list of check descriptions and `autonomy_level: 0.5` | **Docs advertising unimplemented features**, in UI form | Render real `ReversibilityRegistry` entries and the live autonomy setting | P1 |
| **Browser automation on free-tier hosting** | `Genesis Agents/CLAUDE.md:22-25`, `conduit/` submodule | Patchright browser agents on Render free tier with a 30 s proxy timeout, worked around via `job_mode: "async"` | Known-incompatible hosting pattern; cold starts already force a 60 s warm-up in `Cato/cato/tools/genesis.py:308-311` | Run browser work locally in Cato's own Conduit, not remotely | P2 (P0 if ever on the posting path) |
| **Confidence is not persisted with proposals** | `cato/audit/ledger.py:126`, `orchestrator/confidence_extractor.py` | `confidence_score` exists as a ledger column; `LedgerRecord` carries it | Nothing computes a per-proposal confidence for a *coding* decision, which E4L spec §E3 band 2 requires | Compute at proposal time; store with the evidence that produced it | P1 |

---

## Risk Register  *(Phase 7)*

| Risk | Category | Evidence | Impact | Recommended Fix | Priority |
|---|---|---|---|---|---|
| A ledger-write tool added today would execute ungated | Security / Billing | `cato/safety.py:130` default `REVERSIBLE_WRITE`; `:171` `tier < threshold → return True` | An LLM could post to Xero with no risk gate, no approval, no confirmation | Fail-closed classification + policy table before any accounting tool is registered | **P0** |
| Audit-chain failure does not stop the action | Compliance | `agent_loop.py:1946-1947` `except … logger.debug` | Actions with no tamper-evident record; audit trail silently incomplete | Raise on ledger failure for tools tagged `financial` | **P0** |
| Genesis stubs return success | Data / User Trust | `Genesis Agents/tools/finance_tool.py:17-27` | Fabricated completion evidence inside a financial workflow | Empty `genesis_agent_allowlist` → set explicitly; make stubs return `ok:false` | **P0** |
| `genesis_agent_allowlist` defaults to empty = all agents allowed | Security | `cato/config.py:92`; `cato/tools/genesis.py:247` `if allowlist and …` | Fail-open allow-list | Ship a non-empty default; treat empty as deny-all | **P0** |
| Daemon has no TTY, so `SafetyGuard` denies rather than escalates | Production | `cato/safety.py:190-194` | Genuinely risky actions are silently dropped instead of queued for a human — work stalls with no visible reason | Route TTY-less confirmations into `OutboundApprovalStore` + Telegram | **P1** |
| Approval bypass via model-controlled `dry_run` | Auth | `cato/core/outbound_approval.py:170` | The model can set the flag that skips the gate | Derive `dry_run` from server-side mode, never from tool args | **P1** |
| Vault Ed25519 key signs all Genesis envelopes | Security | `cato/tools/genesis.py:112` `get_or_create_keypair` | Single key = single revocation blast radius across every agent | Per-purpose subkeys; rotate before production | P1 |
| Ledger DB and approvals share `cato.db` in the user profile | Data | `cato/core/outbound_approval.py`, `C:\Users\benst\.cato\cato.db` | No documented backup for the audit chain | Scheduled backup + `verify_chain` in the daily job | **P1** |
| No accounting connector exists in Cato | Production | Tool registry review (`agent_loop.py:578-1016`) | Cato cannot read or write a ledger today | Use `ap-hub` as the write rail; Cato calls it, does not reimplement | P1 |
| Test suite state is 71 days stale | Maintainability | `Cato/CLAUDE.md:155` (2026-05-22), plus 1 collection error | "1869 passing" is not current evidence | Re-run `hatch run test` before any E4L work is trusted | **P1** |
| `pyproject.toml` pins no upper bounds and pulls `sentence-transformers` | Deployment | `pyproject.toml:dependencies` | Large, drifting install on a controller machine | Pin, and confirm semantic search is required | P2 |

---

## Target Architecture  *(Phase 8)*

Minimum-viable cleaner state. One operator, one machine, bounded sessions.

**Keep** — the agent loop and its four-gate dispatch (`agent_loop.py:1883-1953`); the hash-chained ledger (`cato/audit/ledger.py`); `BudgetManager`; `SchedulerDaemon`; `OutboundApprovalStore`; `ReplayEngine`; `ReceiptWriter`; Conduit for API-less portals; the MCP server as the Claude Code entry point.

**Remove** — nothing yet. No item in this report has passed a zero-usage search; every candidate is `Refactor` or `Verify`.

**Replace** — `cato/safety.py`'s static `_TOOL_TIER` with a fail-closed, policy-file-driven classifier. The replacement already exists in two places to copy from: `Genesis Agents/runtime/tool_policy.py` (fail-closed shape) and `~/.claude/skills/xero-accounting/{risk-policy,permission-matrix,approval-policy}.yaml` (the R0–R5 × mode grid).

**Consolidate** — `cato/audit.py` + `cato/audit/` into the package. The Genesis registry into a single generated source. Root markdown into `docs/`.

**Refactor** — wire `ActionGuard` into `agent_loop.py`; make the ledger append fail-closed and branch-independent; make `requires_approval` table-driven; bridge YAML-frontmatter skills into `resolve_active_skills`.

**Add tests for** — the four dispatch gates (currently each has a unit test at most, none has a test proving a *financial* tool is blocked); ledger fail-closed behaviour; allow-list deny-by-default.

**Source-of-truth decisions needed** — (1) which of `cato/audit.py` / `cato/audit/` wins; (2) `TELEGRAM_BOT_TOKEN` vs `CATODESKTOP_BOT_TOKEN`; (3) whether the Genesis slug registry is owned by Cato or by the gateway.

---

## Coder Task Plan  *(Phase 9)*

#### Task 1: Fail-closed tool risk classification  (P0)
**Goal:** an unregistered tool name is treated as maximum risk, not minimum.
**Files:** `cato/safety.py` — replace `_TOOL_TIER.get(tool_name, RiskTier.REVERSIBLE_WRITE)` at `:130`; add a YAML policy loader.
**Work:** 1. Load tool→tier from a config file. 2. Unknown tool → `HIGH_STAKES`. 3. Keep the shell keyword escalation. 4. Add a `financial` tag that always requires approval.
**Validation:** `hatch run pytest tests/ -k safety -v`
**Acceptance:** - [ ] `classify_action("xero.post_bill", {})` returns `HIGH_STAKES` - [ ] existing browser/file tiers unchanged
**Risk if skipped:** any accounting tool posts with no gate.

#### Task 2: Fail-closed audit ledger  (P0)
**Goal:** no ledger record ⇒ no action, for tools tagged financial.
**Files:** `cato/agent_loop.py:1938-1947`.
**Work:** 1. Move `_ledger.append` outside the `else` so denials are recorded. 2. Append **before** dispatch as INTENT and after as CONFIRMED. 3. On append failure for a financial tool, abort and return an error result.
**Validation:** `hatch run pytest tests/ -k ledger -v`
**Acceptance:** - [ ] a forced ledger exception blocks a financial tool call - [ ] a safety-denied call appears in `LedgerQuery.last_n(1)`
**Risk if skipped:** unrecorded financial actions; audit trail is not evidence.

#### Task 3: Policy-driven approval routing  (P0)
**Goal:** approval requirement comes from a table, not three hardcoded names.
**Files:** `cato/core/outbound_approval.py:169-179`.
**Work:** 1. Load a tool→risk-tier→mode matrix from YAML. 2. Remove the `dry_run` short-circuit from model-supplied args. 3. Add ticket TTL and expiry per `approval-policy.yaml`.
**Validation:** `hatch run pytest tests/ -k approval -v`
**Acceptance:** - [ ] `requires_approval("xero.post_bill", {})` is True - [ ] `{"dry_run": true}` no longer bypasses - [ ] an expired ticket rejects
**Risk if skipped:** ledger writes execute with no human decision recorded.

#### Task 4: Deny-by-default Genesis allow-list  (P0)
**Goal:** an empty allow-list blocks every agent instead of allowing all 15.
**Files:** `cato/tools/genesis.py:247-253`; `cato/config.py:92`.
**Work:** 1. Invert to deny-on-empty. 2. Ship an explicit E4L default of read/analysis slugs. 3. Hard-deny `genesis-finance`, `genesis-billing`, `genesis-commerce`, `genesis-pricing` for finance sessions.
**Validation:** `hatch run pytest tests/ -k genesis -v`
**Acceptance:** - [ ] empty list → `not_in_allowlist` for every slug - [ ] `genesis-finance` denied under the E4L profile
**Risk if skipped:** stub agents reachable from a finance workflow.

#### Task 5: Genesis stubs stop reporting success  (P0)
**Goal:** an unimplemented operation returns an error, not `ok: true`.
**Files:** `Genesis Agents/tools/finance_tool.py:17-27` (and `billing`, `commerce`, `pricing`).
**Work:** change `_scaffold` to return `{"ok": false, "error": "not_implemented", "phase": 3}`.
**Validation:** `pytest test_bundle_tool_registry.py -v`
**Acceptance:** - [ ] no tool in those four files returns `ok: true` while stubbed
**Risk if skipped:** fabricated completion evidence inside financial workflows.

#### Task 6: Bridge YAML-frontmatter skills into Cato activation  (P1)
**Goal:** Claude-format skills (`description:` with `TRIGGER on:`) activate in Cato.
**Files:** `cato/core/context_builder.py:105-160`.
**Work:** 1. If no `## Trigger Phrases` heading, parse YAML frontmatter `description`. 2. Extract phrases after `TRIGGER`. 3. Keep existing behaviour when the heading exists.
**Validation:** `hatch run pytest tests/ -k context_builder -v`
**Acceptance:** - [ ] `resolve_active_skills("close the month for XPO", [~/.claude/skills])` returns `e4l-controller` - [ ] the 10 heading-format skills still match
**Risk if skipped:** 206 of 216 skills, including all E4L ones, never load.

#### Task 7: Wire ActionGuard onto the dispatch path  (P1)
**Goal:** the reversibility × autonomy check actually runs.
**Files:** `cato/agent_loop.py` (after `:1889`); `cato/ui/server.py:1919-1929`.
**Work:** 1. Instantiate `ActionGuard` in `__init__`. 2. Call `check_before_execute` before dispatch. 3. Make the dashboard render real registry entries.
**Validation:** `hatch run pytest tests/ -k action_guard -v`
**Acceptance:** - [ ] a tool with reversibility > 0.9 requires confirmation at any autonomy level
**Risk if skipped:** an advertised safety control that does not run.

#### Task 8: Re-establish the test baseline  (P1)
**Goal:** a current, pasted test result.
**Files:** none — execution only.
**Work:** `hatch run test`; fix the `tests/test_conduit_proof.py` collection error.
**Validation:** `hatch run pytest tests/ -q`
**Acceptance:** - [ ] exit code and pass/fail counts pasted into this file, dated
**Risk if skipped:** every downstream claim rests on a 71-day-old number.

#### Task 9: Resolve the duplicate audit module  (P2)
**Goal:** one `cato.audit`.
**Files:** `cato/audit.py`, `cato/audit/__init__.py`.
**Work:** determine which Python resolves; migrate references; delete the other.
**Validation:** `python -c "import cato.audit, inspect; print(inspect.getfile(cato.audit))"`
**Acceptance:** - [ ] one file remains, all imports pass

#### Task 10: Consolidate root documentation  (P3)
**Files:** `Cato/*.md` → `Cato/docs/` + `docs/history/`, with `docs/INDEX.md`.

---

## Validation Checklist

- [x] Structure mapped from actual file tree (PowerShell recursive listings, Glob)
- [x] Entry points and tool registry mapped with file paths
- [ ] DB models mapped — **[BLOCKED: no ORM/schema files; SQLite DDL is inline in `cato/audit/ledger.py:36` and `cato/core/outbound_approval.py`. Not separately enumerated.]**
- [x] Env vars listed from `Cato/.env` (keys only, values redacted at the shell)
- [ ] Every dependency checked against imports — **[PARTIAL: seed list + finance-relevant deps checked. `rank-bm25`, `croniter`, `rich`, `tiktoken` not individually traced.]**
- [x] Integrations checked installed / imported / live-wired
- [x] Scheduler, skills, deploy surface reviewed
- [x] Docs claims compared to code (`CLAUDE.md` skills count, test count, Administrator install path — all three do not match disk)
- [x] Dead/stale + misfit findings have evidence + a named Phase 6 pattern
- [x] Risk register cites file:line
- [x] Task plan has file paths; every P0/P1 has a validation command
- [ ] **NOT RUN: the test suite, the daemon, any Genesis call, any live HTTP.** Every claim here is code-reading.

---

## Open Questions / Decisions Needed

1. **Which machine and which user account runs the E4L Cato daemon?** `Cato/CLAUDE.md:54` says `C:\Users\Administrator\Desktop\Cato` — that path **does not exist**. The live runtime home is `C:\Users\benst\.cato\`; the repo is under `C:\Users\Work\`. *Resolve by:* running `cato status` on the intended machine and recording the paths it prints.
2. **Is `cato/audit.py` or `cato/audit/` authoritative?** *Resolve by:* the import command in Task 9.
3. **Does `sentence-transformers` semantic search earn its install cost on a controller laptop?** *Resolve by:* grep usage in `cato/core/semantic_search.py` callers and measure install size.
4. **Who owns the Genesis slug registry — Cato or the gateway?** *Resolve by:* deciding whether `GET /agents` exists on the gateway; if it does, generate the registry from it.
5. **Current test state.** *Resolve by:* Task 8.
