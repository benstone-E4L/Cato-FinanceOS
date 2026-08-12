# Guardrails — Known Risks and Scope Exclusions

ralph: before taking any action, scan this file. If your action matches a SIGN, stop and report.

## Workstream Scope Boundary (read first, applies to every chunk)

This workspace covers ONLY the Cato repo (`C:\Users\Work\Desktop\vault\projects\My Github\Cato`),
Phases A, C, and D of the 2026-08-07 master architecture decision. Do NOT touch, scaffold into, or
write code/specs about `e4l-work-os`, `Genesis Agents`, the `E4L Coordination Ledger`, or
`FinanceOS` repos — separate agents are working those in parallel; any cross-scope edit risks a
collision with their work. If a task seems to require it, treat it as BLOCKED, not as an
invitation to reach into another repo.

## RESOLVED: Genesis dispatch safety — Cato's own registry is the canonical allowlist
Investigated directly (2026-08-08): `cato/tools/genesis.py` already implements independent,
fail-closed dispatch safety that supersedes the generic "21 of 57" concern for THIS repo. It
hardcodes its own `GENESIS_AGENTS` registry of exactly 20 slugs (all 20 verified to be real,
bundle-backed Genesis agents — none are bare unguarded personas), requires an explicit non-empty
`genesis_agent_allowlist` config entry before ANY dispatch (empty/missing = deny everything), and
carries a separate hardcoded `MONEY_DOMAIN_AGENTS` denylist (`genesis-finance`, `genesis-billing`,
`genesis-commerce`, `genesis-pricing`) that config can only add to, never remove from or override —
evaluated before the allowlist check, independent of it. Cato structurally cannot dispatch to any
of Genesis's 36 unguarded persona-only slugs; they aren't in its registry at all.
**Decision: `cato/tools/genesis.py::GENESIS_AGENTS` is now the one canonical, cross-repo-shared
allowlist definition for the whole estate** — `e4l-work-os`'s guardrails.md points here rather
than deriving a second, independently-maintained list from Genesis's persona catalogue. No chunk
in this workspace needs further action; this SIGN exists only to record why the earlier "open
item" language was removed and to prevent a future chunk from re-deriving a redundant list.
Minor sync note (P3, informational only — not a chunk): Cato's registry is missing 3 of Genesis's
24 real bundles (`genesis-domain`, `genesis-maintenance`, `genesis-onboarding` — all correctly
newly-reachable once Genesis's own `CHUNK_2_REGISTRY` lands); add them to `GENESIS_AGENTS` in a
future pass if Cato needs to call them. Missing entries only reduce capability, never create risk.

## RESOLVED: No WhatsApp — remove both implementations
Ben's decision (2026-08-08): Cato does not support WhatsApp at all. Both
`cato/adapters/whatsapp.py` (Twilio) and `cato/channels/whatsapp.py` (Meta Cloud API), and every
call site that registers/routes to either (expected in `cli.py`, `ui/server.py`,
`api/whatsapp_routes.py` — grep-confirm the full set before deleting, do not assume the audit's
citation list is exhaustive), are removed entirely by CHUNK_1_HYGIENE. This is a deletion, not a
consolidation — do not keep either implementation "just in case," and do not build a third,
unified WhatsApp path. If WhatsApp is ever wanted again, that's a new, explicitly-requested
feature, not a revival of either dead implementation.

## SIGN: FinanceOS is read-only from Cato, always
Per the master spec's non-negotiable boundaries: Cato may never hold Xero/Stripe/Gusto/Expensify
credentials, may never approve finance, and an assistant approval is never a financial approval.
Chunk 5 (Finance view) and Chunk 6 (Work Inbox) consume FinanceOS's `/api/v1/control-room` API
read-only. No chunk in this workspace may add a write path from Cato to FinanceOS, Xero, or any
finance system, under any circumstance.
Mitigation: any PR touching `financeos_client.py` or the Finance/Work-Inbox views must be
read-GET-only; reject any write/PATCH/POST call to a FinanceOS endpoint at review time.

## SIGN: No autonomous outbound sending, any channel, any tier
Standing order #1 (permanent until Ben explicitly revokes it): no system sends outbound
communication (email, Slack, WhatsApp, Telegram messages to third parties) autonomously. Drafts
only. This applies even though this workspace's chunks don't build new sending paths — if any
chunk's implementation of a draft/notification feature accidentally wires up a send call, that is
a guardrail violation, not a feature.
Mitigation: any new code path that could call `.send()` on any channel adapter must be reviewed
against this guardrail before it ships.

## SIGN: Cato's secrets are currently 100% plaintext (Phase A blocking risk)
Confirmed live on this host: `Cato\.env` holds live plaintext secrets, `vault.enc` was never
created, and the plaintext `CATO_VAULT_PASSWORD` itself is one of the exposed values (audit P0).
Chunk 2 must not be skipped or deferred for any reason — every chunk after it (3-6) assumes a
daemon running off `vault.enc`, not plaintext `.env`.
Mitigation: Chunk 2 is ordered immediately after Chunk 1 and blocks Chunks 3-6 explicitly in each
spec's Dependencies section.

## SIGN: Cato CI does not run on `main` (P1, until Chunk 1 fixes it)
`.github/workflows/ci.yml` is scoped to `e4l-runtime-hardening` only. Until Chunk 1 lands, any
merge to `main` ships with zero automated test signal. Chunk 1 fixes this first, before Chunks 2-6
generate real commits.

## SIGN: FinanceOS capability-token mint endpoint doesn't exist yet (O2O-FOS-1)
Per Cato's own `proof-artifacts/truth-audit-gate/VERDICT.md`, `financeos_client.py` is fail-closed
by design but the capability-token mint endpoint isn't live on FinanceOS's side yet. Chunk 5's
acceptance test is deliberately scoped to accept EITHER "FinanceOS reachable, real data renders"
OR "FinanceOS/mint endpoint not yet available, stale-marked state renders, no crash" as valid
proof — do not treat Chunk 5 as blocked by FinanceOS's own build timeline; do not fabricate a
mint-endpoint implementation on the FinanceOS side either (out of scope, different repo).

## SIGN: SwarmSync proof-rail is one controller, not a two-hop AuditProof→VerifyAPI chain
Not directly relevant to any of this workspace's 6 chunks (that integration lives in FinanceOS/
SwarmSync repos), but noted here in case a later chunk in this workstream is extended toward
proof-rail work: AuditProof and VerifyAPI are the same `VerifyApiController` branched by a
`task` field, not two services in sequence. Do not design against a two-hop assumption.

## Scope Exclusions — Do Not Build

- DO NOT BUILD: the standalone Vault Knowledge Assistant app (Next.js UI, own auth, own Azure App
  Service, own Postgres server) — out of scope entirely, not a Cato concern, superseded per the
  master spec's §20 DELETE list.
- DO NOT BUILD: any code that revives or re-imports `Genesis_meta_agent.py` after Chunk 1 deletes
  it (3,991 LOC, imports a nonexistent `infrastructure/` package, confirmed dead).
- DO NOT BUILD: the legacy 23-view web dashboard as a parallel surface to the new 9-item nav —
  absorbed views survive only inside the Settings/Diagnostics operator/debug tier (Chunk 6).
- DO NOT BUILD: autonomous outbound sending on any channel at any tier (standing order #1,
  permanent until Ben explicitly revokes it).
- DO NOT BUILD: a second finance surface, second task board, or second orchestrator inside Cato —
  Finance view (Chunk 5) is strictly read-only against FinanceOS's control-room API.
- DO NOT BUILD: cross-system correlated-card logic (Gmail+Slack+Monday+FinanceOS on one card) —
  that's Phase F's E4L Coordination Ledger work, a separate out-of-scope workstream. Chunk 6 only
  needs Work Inbox live with FinanceOS status cards.

## Standing Guardrails (always active)

- DO NOT add npm/pip/gem dependencies without updating AGENTS.md.
- DO NOT skip the validation gate (`ruff check cato/ && pytest`), even for trivial changes.
- DO NOT commit with --no-verify.
- DO NOT generate code for a future chunk's domain.
- DO NOT modify files outside the current task's scope.
- DO NOT hard-code secrets, API keys, or credentials — Chunk 2 onward, all secrets come from
  `vault.enc` via `vault_bootstrap.py`, never from a literal in source.
- DO NOT touch e4l-work-os, Genesis Agents, the Coordination Ledger, or FinanceOS repos.

## Accumulation Instructions

When ralph encounters a new failure pattern, append below:

### Learned: {SHORT_TITLE}
{what went wrong and how to avoid it}

### BLOCKED (CHUNK_1_HYGIENE): `mcp` is not a dead dependency — do not remove it
Investigated directly (2026-08-08): CHUNK_1_HYGIENE's spec asserts `mcp>=1.22.0` is unused and
should be deleted from `pyproject.toml`'s `dependencies`. That premise is false. `mcp` backs a
real, tested, config-gated feature — Cato's own remote MCP server (`cato/mcp/runtime.py`,
`create_mcp_server`/`CatoMCPRuntime`, wired from `cato/ui/server.py`'s `mcp_runtime_ctx` behind
`config.mcp_enabled` which defaults `False`). Evidence it's real, not dead code the audit missed:
- `cato/mcp/runtime.py` dynamically imports `mcp.server.fastmcp` via `importlib.import_module`
  (not a static `import mcp`, which is why the audit's grep likely missed it).
- `cato/ui/server.py`'s `start_mcp_runtime()` already explicitly catches `ModuleNotFoundError` for
  this exact import and logs a warning + disables the runtime — the code was written anticipating
  `mcp` might be absent, i.e. it is already designed as an optional feature, not a stray import.
- `tests/test_mcp_runtime.py` module-level `try/except` + `pytest.mark.skipif(not _MCP_AVAILABLE)`
  shows the same graceful-degradation pattern was deliberately built into the test suite too.
- `tests/test_gateway_mcp.py` and `tests/test_windows_mcp_client.py` are separate and do not
  require the `mcp` pip package at all (confirmed by import inspection).
Per this chunk's own spec ("Failure case" bullet): do not silently re-add it disguised, and do not
guess at a fix — block and report. The two candidate fixes both have tradeoffs beyond a "hygiene"
change's scope: (a) leave `mcp` as a hard dependency (status quo, contradicts the literal
acceptance criterion) or (b) move it to a new `[project.optional-dependencies]` extra (satisfies
the literal "removed from dependencies list" wording and is a safe, standard pattern given the
existing `ModuleNotFoundError` handling, but silently drops MCP-runtime test coverage from the
default `pip install -e ".[dev]"` CI install unless a maintainer also decides to add the new extra
to `dev` or to CI). That is a packaging/CI-coverage product decision, not a mechanical hygiene
fix — left to Ben rather than guessed. **`mcp` was NOT removed from `pyproject.toml` in this
iteration.** This is the one CHUNK_1_HYGIENE acceptance-criteria line item left undone; every
other line item was completed. Suggested next action: Ben picks (a) or (b) above (or a third
option — e.g. splitting `cato/mcp/` into a truly optional package) in a short follow-up task.

### Learned: guardrails.md's own "grep the citation list, don't assume it's exhaustive" instruction was correct
CHUNK_1_HYGIENE's WhatsApp-removal spec listed 3 files to grep
(`cato/cli.py`, `cato/ui/server.py`, `cato/api/whatsapp_routes.py`) as a starting point, explicitly
warning not to assume that list was exhaustive. A repo-wide case-insensitive grep for "whatsapp"
found live references in 11 more files the spec's citation list did not name: `cato/adapters/
__init__.py`, `cato/adapters/base.py` (comment only), `cato/agent_loop.py` (tool-description
string), `cato/api/integration_routes.py`, `cato/api/routes.py`, `cato/config.py`,
`cato/doctor.py`, `cato/gateway.py`, `cato/integrations/registry.py`, `cato/mcp/runtime.py`,
`cato/skills/daily_digest.md`, `cato/ui/dashboard.html`, `cato/ui/settings_panel.html`,
`cato/vault_bootstrap.py`, plus 4 test files (`tests/test_whatsapp.py`,
`tests/test_integrations.py`, `tests/test_port_fallback_integration.py`,
`tests/test_start_channel.py`). All were grepped and updated/removed in this pass. Confirms the
guardrail's instinct was right — future chunks should always grep-verify a spec's citation list
rather than trusting it as exhaustive.

### Learned (CHUNK_2_VAULT): GITHUB_FOXFIREPOETS_TOKEN / SWARMSYNC_VERIFYAPI_KEY are not in `OPERATOR_VAULT_KEYS`
`cato/vault_bootstrap.py`'s `OPERATOR_VAULT_KEYS` (the list `apply_vault_to_environ` uses at daemon
launch to copy vault-stored secrets back into `os.environ`) uses the names `GITHUB_TOKEN`/`GH_TOKEN`
and `SWARMSYNC_API_KEY`/`SWARM_SYNC_API_KEY` — not `GITHUB_FOXFIREPOETS_TOKEN` or
`SWARMSYNC_VERIFYAPI_KEY`, the names actually used in this repo's `.env`/AGENTS.md and now in
`vault.enc` (migrated under their real names via `migrate_env_to_vault(keys=(...))` directly,
since the CLI's `cato vault migrate-env` only offers the `OPERATOR_VAULT_KEYS` default set with no
`--keys` override). This does not break either consumer today: `cato/tools/swarmsync_proof.py`
calls `vault.get("SWARMSYNC_VERIFYAPI_KEY")` directly (bypasses environ, unaffected), and
`cato/tools/github_tool.py` looks for `GITHUB_TOKEN`/`GH_TOKEN` specifically (a separate,
pre-existing naming mismatch with `GITHUB_FOXFIREPOETS_TOKEN` that predates this chunk and was not
introduced by it). Flagging so a future chunk doesn't assume `OPERATOR_VAULT_KEYS` is a complete
name map — it isn't, for these two credentials. Not fixed here: CHUNK_2_VAULT's acceptance
criteria only required migrating the 9 named secrets into `vault.enc` and getting `.env` clean,
not reconciling every consumer's expected key name (that is a separate, pre-existing naming
mismatch, out of "surgical changes" scope for this chunk).

### Learned (CHUNK_2_VAULT): `router.py`'s `has_tools` log field is derived from task_type, not from `requires_tools`
`cato/router.py::_decision_log_base` sets `"has_tools": bool(decision.task_type is
TaskType.GENERAL_TOOL_USE)` — i.e. it infers "this call had tools available" from the task type
label rather than from `descriptor.requires_tools` (the actual deterministic signal). Before this
chunk's fix this was accidentally consistent (every call really was GENERAL_TOOL_USE), but now
that `agent_loop.py`'s `_classify_task_type` can return `DRAFT_CORRESPONDENCE` or
`DOCUMENT_CLASSIFICATION` for non-tool-using turns, `has_tools` in the routing log will always read
`False` for those turns regardless of whether tools were actually offered — it was already
decoupled from truth before this chunk for every non-agent_loop caller (gmail_adapter.py,
telegram.py), so this is not a regression this chunk introduces, just a pre-existing log-accuracy
gap made slightly more visible. Cosmetic (routing_log.sqlite3 diagnostic field only — does not
affect which tier/model gets selected), left unfixed here as out of this chunk's explicit scope;
flagging for whoever next touches `router.py`'s logging.

### Decision (CHUNK_3_VAULT_INDEX): vault-chunk metadata reuses existing kg_nodes columns, no DDL change
CHUNK_3's own spec text is internally in tension: the acceptance criteria require frontmatter
(`entity`/`type`/`status`/`updated`/`supersedes`) to be "stored as filterable metadata... not
discarded," while the Database Changes section says "no schema change... no new tables." `kg_nodes`
has only 5 columns (`type`, `label` UNIQUE, `embedding`, `source_session`, `created_at`) — none of
them a natural fit for 5+ arbitrary frontmatter fields. Resolution taken: zero DDL changes (no
`ALTER TABLE`, no new table) — instead: `label` = the canonical chunk ID (already UNIQUE, perfect
for idempotent upsert-by-ID); `type` = `f"vault:{frontmatter.type}"` (a namespace no existing
caller uses — `add_node`/`seed_nodes_from_facts`/`extract_and_add_nodes` only ever write
`"file"`/`"person"`/`"concept"` — so it cannot collide, and `type LIKE 'vault:%'` cleanly
distinguishes vault-chunk nodes from every other kg_nodes row); `source_session` (a free-text
provenance field with no other structural meaning for this new node class) repurposed to hold a
JSON blob of the full frontmatter + `content_sha256` + `vault_path`/`heading_slug`/`chunk_index`.
Filtering (e.g. excluding `status: superseded`) happens by parsing that JSON in Python after a
`type LIKE 'vault:%'` SQL fetch, not via a SQL `WHERE status = ...` — vault size (hundreds of
files, not web-scale) makes this an acceptable tradeoff. Chunk *content* itself reuses the
existing `chunks` table as-is (`content`, `embedding`, `source_file` = canonical ID) — no changes
there either. This is a judgment call under an internally-conflicting spec, made in the direction
of the literal "no schema change" text; flagging here per "surface conflicts" rather than silently
picking one reading. If a future chunk needs real SQL-level metadata filtering (e.g. at vault
scale), the honest fix is an actual `ALTER TABLE kg_nodes ADD COLUMN status TEXT` migration
(idiom already established in this file via `_apply_facts_migration`), not more JSON-in-TEXT.

### Decision (CHUNK_3_VAULT_INDEX): nested independent-repo directories are excluded from the ingest walk
`C:\Users\Work\Desktop\vault\projects\e4l-financeOS\repo\` (and any future `.git`-containing
subdirectory under `vault\projects\*\`) is skipped by `iter_vault_markdown_files` — any directory
containing its own `.git` folder is treated as a separate codebase's knowledge system, not vault
notes, per the vault's own `CLAUDE.md` ("It is not the FinanceOS codebase... its `CLAUDE.md` is
authoritative for anything about FinanceOS code"). Only markdown physically inside the vault's own
coordination layer (`knowledge/`, `memory/`, `decisions/`, `entities/`, `projects/*/`-that-are-not-
independent-repos, `sessions/`, `rules/`, `daily/`) gets ingested. Documented here since CHUNK_3's
spec text just says "walks the vault's markdown tree" without this carve-out — a literal
whole-tree walk would ingest an entire unrelated Node.js/TS codebase's docs as if they were E4L
knowledge notes, which is exactly the kind of silent scope creep the vault's own CLAUDE.md warns
against.

### Decision (CHUNK_4_ASK_E4L): contradiction detection is a model-judgment step, gated by a deterministic marker
"Do these two ACTIVE notes actually disagree on a fact?" cannot be answered by pure text-matching
— it is exactly the kind of judgment/synthesis CLAUDE.md rule 5 reserves for the model. Design:
deterministic code (`_find_contradiction_candidates`) pre-filters *candidate* pairs — both
`status: active`, different source files, same declared `entity` — and hands them to the model
with an explicit instruction to emit a structured `[CONTRADICTION: id_a | id_b]` marker only if it
finds a genuine conflict. The caller parses that marker mechanically rather than trusting the
model's own summary of whether it found a contradiction, so a model that silently glosses over a
real conflict still fails the explicit-marker check rather than getting the benefit of the doubt.
Everything else in the Retrieval Contract (refusal gate, citation formatting, superseded exclusion,
staleness flag) is fully deterministic and untested-by-LLM — see `tests/test_ask_e4l.py`, which
proves the refusal path never even invokes `llm_complete`.

### Learned (CHUNK_4_ASK_E4L): BM25 is degenerate over a single-document corpus — calibrate retrieval-threshold tests accordingly
`search_vault_chunks`'s hybrid score (`0.4*bm25 + 0.6*cosine`) can go negative for a genuinely
relevant chunk when the corpus has exactly one document — `rank_bm25`'s idf term degenerates at
n=N=1. Confirmed directly: the exact same query/chunk scored -0.14 with a 1-document corpus and
+0.91 with a 3-document corpus. Not a bug in this chunk's code (the same scoring formula already
existed in `MemorySystem.search()` before this chunk); real vaults always have many documents, so
this only bites tiny test fixtures. `tests/test_ask_e4l.py`'s fixtures each include 2 unrelated
"distractor" notes for this reason — a future chunk building more retrieval tests should do the
same rather than assume a single-document fixture will produce a realistic score.

### Learned (CHUNK_4_ASK_E4L): `passes_bar` is proportional (>=80%), not a literal ">= 8" count
The spec says "≥8/10 correct+cited" for the real 10-question set. `EvalReport.passes_bar` computes
`correct_count / total >= 0.8` rather than hardcoding `>= 8`, so it is meaningful against a smaller
question set in tests too — for the real `DEFAULT_EVAL_QUESTIONS` (exactly 10), this is
mathematically identical to "≥8/10."

### BLOCKED (CHUNK_5_FINANCE_VIEW / CHUNK_6_WORK_INBOX): the desktop UI was already redesigned by an independent, non-master-spec workstream — nav architecture conflict
Investigated directly (2026-08-08) before writing any Chunk 5/6 code. `desktop/src/components/
Sidebar.tsx` and `desktop/src/App.tsx` do NOT currently reflect "the current 23-view sidebar" that
both chunk specs' opening lines assume as their starting point. What's actually on disk:

- **Git history proves this predates this workstream, not concurrent with it.** `git log --oneline
  --graph` on `e4l-runtime-hardening` shows `0b7b99d` ("feat: harden and redesign FinanceOS Cato")
  through `50a4832` ("fix: declare raster validation build dependencies") as direct ancestors of
  this branch's HEAD, landing *before* `98322e1`/`11e5e44`/etc. and therefore before CHUNK_1_HYGIENE
  (`7d43093`). One of those commits (`32d75c8`) is titled "test: authenticate browser WebSocket
  harness" and matches `CodexWork8.5.md` (repo root, untracked) — a full transcript of a separate,
  user-directed Codex session that redesigned the sidebar, pushed to
  `https://github.com/benstone-E4L/Cato-FinanceOS` (a *different* remote than this repo's own
  `origin`), and ran its own `failure-mode-auditor` + `truth-before-launch` passes (documented
  16-then-22-item finding register, `test-outputs/financeos-cato/FAILURE_MODE_AUDIT.md` /
  `E2E_REPORT.md`) — independent, already-audited work, not a draft.
- **The resulting nav does not match the master spec's §10 table at all.** Current
  `Sidebar.tsx`'s `PRIMARY_NAV` is 5 items + Settings: `dashboard` ("Control room"), `chat` ("Ask
  Cato"), `inbox` ("Inbox"), `flows` ("Automations"), `audit` ("Activity"), `settings`. The master
  spec (`vault/decisions/2026-08-07-master-architecture-assistant-into-cato-genesis.md` §10, the
  same doc `README.ralph.md` cites as this workspace's source) requires exactly: **Work Inbox
  (default/home), Waiting/Follow-ups, Approvals, Calendar, Company Tasks, Finance, Ask E4L,
  Activity/Automations, Settings/Diagnostics.** These are materially different information
  architectures — different default landing view (`dashboard`, not `inbox`), no `Finance`/`Ask
  E4L`/`Waiting`/`Approvals`/`Calendar`/`Company Tasks` items, different absorption groupings.
  `App.tsx`'s `View` type still lists all 22 legacy views and `renderView()` still routes to every
  one of them — the underlying view files were never deleted, only *removed from sidebar nav* by
  the Codex session, which is a different action than CHUNK_6's "absorbed into Settings/Diagnostics
  operator/debug tier" requirement.
- **CHUNK_5's own literal endpoint requirement is not what's implemented.** The spec requires
  consuming `/api/v1/control-room` and `/api/v1/control-room/integrations-health` via
  `cato/integrations/financeos_client.py` "as-is or extended — not rewritten." What's live today
  (`DashboardView.tsx` + `cato/ui/server.py::_fetch_finance_os_health`/`finance_os_health`) instead
  calls a Cato-side proxy hitting FinanceOS's plain `/health` endpoint directly via `aiohttp`,
  bypassing `financeos_client.py` entirely (confirmed: zero references to `FinanceOSClient` in
  `cato/ui/server.py`). It surfaces a narrower field set (`db`, `module_layer_wired`, `queue_depth`,
  `production_write_enabled`, `version`) than the spec's "close status, exceptions/HOLDs,
  integration health, write-gate state" and has no capability-token/O2O-FOS-1 handling at all (not
  needed for a plain `/health` GET, but also not the contract CHUNK_5 asks for).
- **A second, separate, already-COMPLETE ralph workstream touched the same UI.** `Desktop App
  Ralph Loop/` (sibling directory in this same repo, `.ralph/state.md`: all 6 chunks COMPLETE,
  "1331 passed, 1 skipped, 0 failed") built "Critical Backend Bug Fixes," "Chat System Fixes,"
  "AuthKeys & System View," "Diagnostics Expansion," "Missing Module Integrations," "Advanced
  Features" — a different chunk set entirely, not obviously the source of the Sidebar.tsx redesign
  either (its own chunk names don't mention navigation restructuring), but confirms this repo has
  had at least two independent build processes touch `desktop/` outside this workstream's
  awareness.

**Why this blocks rather than just informs a judgment call:** CHUNK_6's job is to overwrite an
already-shipped, already-audited, already-pushed-to-a-different-GitHub-remote UI redesign with a
different information architecture. That is a product decision (which UX direction is canonical
going forward — the master spec's Work-Inbox-as-home 9-item nav, or the already-live
Control-Room-as-home 6-item nav) squarely in the territory the task's own hard rule 6 reserves for
Ben, not something to guess at even though it is mechanically buildable (the underlying 22 view
files still exist, so a literal rewrite of `Sidebar.tsx`/`App.tsx` to the master-spec's 9 items is
technically straightforward). Building CHUNK_6 as spec'd would silently discard/hide Ben's
already-approved Cato-FinanceOS redesign without his sign-off; refusing to build it would leave the
master architecture decision's §10 acceptance test permanently unmet. Neither is a call ralph
should make unilaterally. CHUNK_5 is included in the same block because CHUNK_6 explicitly
"Requires: CHUNK_4_ASK_E4L, CHUNK_5_FINANCE_VIEW" and a Finance view built against the literal
`/api/v1/control-room` contract would produce a *third* finance surface if the Codex-redesigned
`DashboardView.tsx` (which already shows finance signals under the other architecture) is also kept
— compounding the same undecided question rather than resolving it.

**What Ben needs to decide before either chunk can proceed:**
1. Is the master architecture decision's §10 nav (Work Inbox home, 9 items) still the target, or
   has the Cato-FinanceOS Codex redesign (Control Room home, 6 items) superseded it as the
   accepted design?
2. If the master-spec nav is still the target: should the Codex redesign's polish (E4Life brand
   styling, the `/api/finance-os/health` proxy pattern, the no-green-hues constraint, the WebSocket
   auth hardening from `32d75c8`) be preserved and re-skinned onto the 9-item structure, or is a
   clean rebuild acceptable?
3. Which GitHub remote is canonical for this branch going forward — this repo's own `origin`
   (`e4l-runtime-hardening`, where chunks 1-4 are committed) or `benstone-E4L/Cato-FinanceOS` (where
   the Codex session pushed)? They have diverged; nothing in this workstream should be pushed
   anywhere until this is resolved regardless (task's hard rule 2), but Chunk 5/6 code depends on
   knowing which UI state is the trunk.

### Note: this session found a commit/progress-log entry for its own CHUNK_4 work already present, mid-task, with no explicit `git commit` from this session
Mid-way through this session's own CHUNK_4_ASK_E4L work — after independently reading the same
interrupted uncommitted files, independently hitting the same real bug (chunks crossing the
retrieval-score threshold without actually grounding an answer, e.g. "what's my Gmail password"
retrieving a Gmail-OAuth-setup chunk, scored `confidently_wrong` even though the LLM honestly
declined in prose), and independently landing on the same fix (a second, model-emitted
`NO_GROUNDED_ANSWER` marker, deterministically parsed, same pattern as the contradiction marker) —
a `git status` check turned up a commit (`4308f45`) and matching `.ralph/progress.md`/`state.md`
entries already on disk, timestamped almost exactly when this session's own edits and live-eval
runs happened, and containing content (the same fix, the same file set, live-eval scores from what
appear from `.ralph/context-log.md`'s timestamps to be this session's own two eval runs) that this
session never explicitly ran `git add`/`git commit` to produce. Honest accounting, not a confident
causal story: it is NOT established whether this was (a) a genuinely separate concurrent agent
session operating on the identical working directory that independently converged on the same fix
and committed first, or (b) some auto-commit/auto-log mechanism in this harness acting on this
session's own file edits and command output without an explicit `git commit` invocation appearing
in this session's own tool-call history. This session verified the committed content is accurate
(re-ran the full CHUNK_4 test suite: 13/13 pass; re-ran `ruff check` on every touched file: same
deltas already recorded) and, given it matched this session's own independently-verified work
exactly, adopted `4308f45` as correct rather than attempting any reset/amend — but flags the
ambiguity itself as a real operational risk worth a human answer: if it is (a), two agent sessions
writing the same files in the same working tree is exactly the "two sessions committing against two
histories" failure mode this workspace's guardrails already warn about for repo *clones*, now
possible without even needing a second clone. Future sessions resuming this workspace should run a
fresh `git log`/`git status` immediately before AND after any batch of edits, not just at session
start, to catch this either way.

### Learned (CHUNK_4_ASK_E4L): `phoenix_eval.py`'s default log path collides with an unrelated, already-complete Ralph workstream's own `.ralph/` directory
`run_phoenix_eval`'s default `log_path` is `Path(".ralph") / "context-log.md"` — a path relative to
the process's cwd, not to this ralph workspace (`ralph/e4l-assistant-buildout-ralph/.ralph/`).
Running `cato memory ask-e4l-eval` from the Cato repo root (the natural place to run it) writes into
the *repo-root* `.ralph/` directory — which turns out to already exist, tracked in git since
`0b7b99d`, as the entirely separate "Desktop App Ralph Loop" workstream's own state directory
(`.ralph/state.md`/`progress.md`/`guardrails.md`/`implementation_plan.md`, all dated 2026-08-05, all
6 chunks already COMPLETE, unrelated to this workstream). `.ralph/context-log.md` is a new filename
so nothing there was overwritten, but it now sits inside a directory this workstream doesn't own,
intermingling two unrelated ralph runs' state. Not worth a destructive git op to relocate after the
fact (the commit is accurate and the file itself is harmless additive evidence), but any future
`cato memory ask-e4l-eval` invocation in this workspace should pass `--log-path` explicitly (e.g.
into this ralph workspace's own `.ralph/`) rather than rely on the cwd-relative default.

### Learned: baseline `ruff check cato/` and `pytest` are NOT clean on this branch, pre-dating this workstream
Captured 2026-08-08 before any CHUNK_1 edits, on `e4l-runtime-hardening`: `ruff check cato/` exits
1 with 907 pre-existing errors (mostly `UP045`/typing-modernization style, repo-wide, unrelated to
any of this workstream's 6 chunks). `pytest` baseline: 3 failed / 2899 passed / 5 skipped / 4
deselected — the 3 failures are all in `tests/pipeline/test_pipeline_components.py`
(`TestEnvironment::test_cursor_agent_installed`, `TestEnvironment::test_cursor_node_and_index_exist`,
`TestInvokeCursor::test_resolve_cursor_agent_returns_paths`), which require the external
`cursor-agent` CLI to be installed on the host — an environment dependency, not a code regression,
and unrelated to any of this workstream's chunks. AGENTS.md's validation gate
(`ruff check cato/ && pytest`) therefore does **not** exit 0 on a clean checkout of this branch
today, independent of anything CHUNK_1_HYGIENE does. Do not treat a failing full-gate run as proof
a later chunk broke something — diff against this baseline instead. Fixing the 907 ruff errors or
the Cursor-CLI environment gap is out of scope for every chunk in this workstream (none of the 6
chunk specs mention repo-wide lint modernization or Cursor CLI provisioning) and was not attempted
here, per "surgical changes" / "do not modify files outside the current task's scope."

### UNBLOCKED (CHUNK_5_FINANCE_VIEW / CHUNK_6_WORK_INBOX): Ben's direct decision, 2026-08-09
Per an explicit, direct dispatching-agent instruction (not an in-band message): Work Inbox stays
the master spec's Section-10 9-item home nav; the existing Codex 6-item Control-Room-home nav is
reorganized AROUND that target where sound, not treated as having superseded it. This does not
retract the investigation above - it was accurate and the product decision genuinely needed a
human call - it records that the call has now been made.

One sub-claim in the original BLOCKED finding was independently re-checked and found to be wrong
at the time it was written, not just resolved since: "these two GitHub remotes have diverged" is
false. `git remote -v` on this repo shows exactly one remote, `origin` ->
`https://github.com/benstone-E4L/Cato-FinanceOS.git`. The Codex session's `CodexWork8.5.md`
transcript does say it pushed to `benstone-E4L/Cato-FinanceOS` - that is this repo's own origin,
not a second remote. Flagging this as a real lesson: the original finding treated "this repo's own
origin" and "benstone-E4L/Cato-FinanceOS" as two different things without ever running `git remote
-v` to check - future sessions should verify a remote-identity claim directly before citing it as
evidence, the same discipline this guardrails file already demands for grep citation lists.

### Surfaced conflict (CHUNK_6_WORK_INBOX): dispatching instruction's stated acceptance bar vs. the chunk spec's own literal acceptance bar
The dispatching instruction that unblocked this chunk describes CHUNK_6's acceptance bar as the
master architecture's full Section-10 "Acceptance test (Phase F gate)" - a real cross-system item
rendering as ONE correlated card across Gmail/Slack/Monday/FinanceOS. That is NOT what
`specs/06_CHUNK_6_WORK_INBOX.md` itself says. The spec's own Summary is explicit: "This chunk's
acceptance bar is intentionally narrower than the full Section-10/Phase-F acceptance test: it only
needs Work Inbox live with FinanceOS status cards rendering (via Chunk 5's view) - NOT the
one-correlated-card cross-system correlation across Gmail/Slack/Monday/FinanceOS, which is Phase
F's job in a separate, out-of-scope workstream." This guardrails file's own "Scope Exclusions - Do
Not Build" section already says the same thing in its own words: "DO NOT BUILD: cross-system
correlated-card logic (Gmail+Slack+Monday+FinanceOS on one card) - that's Phase F's E4L
Coordination Ledger work, a separate out-of-scope workstream. Chunk 6 only needs Work Inbox live
with FinanceOS status cards." Per CLAUDE.md rule 7 ("surface conflicts... do not average them;
pick the newest/most-tested/local pattern, explain why, mark the other for cleanup"): this session
built to the chunk spec's own literal, already-reconciled acceptance criteria (narrower bar) rather
than the full Phase-F gate quoted in the dispatching instruction, because (a) the Coordination
Ledger and the Gmail/Slack/Monday correlation-key infrastructure the full gate requires do not
exist anywhere in this repo - building a "real cross-system correlated card" without them would
require either fabricating fake Gmail/Slack/Monday data (banned) or quietly building Phase F's
actual infrastructure inside a chunk explicitly scoped to exclude it, and (b) the spec file and
this guardrails file are both dated artifacts of the same 2026-08-07 planning pass that already
reconciled the master architecture doc against realistic per-chunk scope, which is more
load-bearing than a paraphrase in a later dispatching message. This is flagged prominently in the
final report rather than silently resolved - if Ben actually wants the full Phase F gate proven in
this same session, that is new scope (the Coordination Ledger) and should be chartered explicitly,
not inferred from a one-line acceptance-bar description.
