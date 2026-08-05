# ConduitScore Revenue Loop + Cato Night-Shift Manager — Full Build Spec

**Document ID:** `CONDUITSCORE-NIGHT-SHIFT-001`  
**Created:** 2026-06-02  
**Status:** IN PROGRESS — Phase 0 complete; P2-CATO-001..010 implemented in repo (G1 still operator-only; no live sends)  
**Owner:** Operator (PhilPro / Benjamin)  
**Source decisions:** [WAR-ROOM-MASTER-DELIVERABLE.md](file:///C:/Users/Administrator/Desktop/Decision%20Oracle/Assets%20Marketing%20Output/WAR-ROOM-MASTER-DELIVERABLE.md)  
**Related audits:** Bughound investigation (2026-06-02), `INVENTORY-05-conduitscore.md` (war-room companion)

---

## Executive summary

**Goal:** Prove the ConduitScore **audit-as-cold-open → inbox → click → pay → fulfill** loop by hand, then wire Cato to orchestrate that **same** loop under spend caps, hash-chained audit logs, signed AP2 Genesis calls, and human approval gates—applying **full autonomy last**.

**Non-goals:**

- Do **not** run SwarmSync cross-platform arbitrage with real funds (NO-GO per war-room).
- Do **not** automate outreach at volume before FP1 (deliverability) and manual canary pass.
- Do **not** lead with IETF/protocol push before first-dollar proof.

**Success definition (90 days):**

| Milestone | KPI |
|-----------|-----|
| Loop proven manually | Loop Proof Card 100% green for canary (25 sends) |
| Cato supervised orchestration | 5/5 supervised runs match manual quality; no cap bypass; no silent sends |
| Night-shift manager (limited) | 30 days: scheduled runs, caps enforced, daily Telegram summary, no FP1 regression |

---

## Glossary

| Term | Meaning |
|------|---------|
| **FP1** | Flip-point: mail actually reaches inbox (sibling domain + SPF/DKIM/DMARC + seed test) |
| **Representation Fidelity** | AIVS-style MVP: what LLMs say about a site vs. real content (2–3 day build) |
| **Audit-as-cold-open** | Cold email where the message *is* a pre-run cryptographically signed per-prospect audit |
| **Loop Proof Card** | One-page pass/fail checklist for all 7 loop stages (Phase 0 artifact) |
| **Canary batch** | First 25 hand-approved sends to validated contacts |
| **Night-shift manager** | Cato running the proven loop unattended within caps + approvals |
| **Genesis fleet** | 24 SwarmSync-hosted agents invoked via `genesis` tool + signed AP2 envelopes |
| **Cold engines** | `conduit_outreach_pipeline/` and `reverse_funnel_outreach/` (outside Cato repo) |

---

## System architecture (failing path — full loop)

```
[Prospect list CSV/DB]
        │
        ▼
[Lead verify / enrich] ── skill: lead-sourcing-enrichment (manual or agent)
        │
        ▼
[Per-prospect audit] ── Conduit browser + Genesis analyst/content
        │                  (Representation Fidelity artifact)
        ▼
[Draft 5-touch sequence] ── cold engine OR Genesis email + halbert-copy-doctor
        │
        ▼
[Human approve send] ── Telegram / desktop (mandatory until Phase 3)
        │
        ▼
[Gmail / SMTP send] ── cold-outreach-deliverability infra (sibling domain)
        │
        ▼
[Track open/reply/click] ── spreadsheet or lightweight CRM
        │
        ▼
[ConduitScore landing + Stripe] ── stranger converts without operator
        │
        ▼
[Fulfill scan/report] ── ConduitScore SaaS + signed delivery
        │
        ▼
[Audit + spend log] ── Cato AuditLog + BudgetManager + (target) LedgerMiddleware
```

**Cato’s role in architecture:** Control plane between steps—not replacement for ConduitScore product or cold-engine repos until explicitly integrated.

---

## Phase gates (hard stops)

| Gate | Condition to proceed | Blocked if |
|------|----------------------|------------|
| **G0** | Loop Proof Card template approved | — |
| **G1** | Phase 1 complete (manual canary + first $) | FP1 red, zero replies, or no stranger payment |
| **G2** | `war-audit` / `truth-audit` GO on engines + funnel | NO-GO on cold engines |
| **G3** | Phase 2 complete (5 supervised Cato runs) | Cap bypass, silent send, or audit chain break |
| **G4** | Alex + Kraken APPROVED on Cato changes | Any failing test or rejected audit |
| **G5** | Phase 3 autonomy ramp | Complaint rate >0.1% or cap violation in week 1 |

---

# PHASE 0 — Definition & artifacts (no code)

## P0-001 — Create Loop Proof Card

**Owner:** Operator  
**Depends on:** None  
**Deliverable:** `docs/loop-proof-card.md` (or Desktop copy)

**Checklist fields (pass/fail each):**

1. **FP1 deliverability** — 20 seed emails; mail-tester / Google Postmaster green on **sibling domain** (never `conduitscore.com` as sending domain).
2. **Artifact contract** — Representation Fidelity output defined (format, URL/PDF, signature, credibility statement).
3. **Engine audit** — Both cold engines + funnel: GO from truth-audit/war-audit.
4. **Canary outreach** — 25 sends hand-approved; ≥1 reply OR ≥1 audit-view; complaint rate <0.1%.
5. **Stranger payment** — One Stripe conversion with operator out of loop; receipt timestamp recorded.
6. **Fulfillment** — Paid customer receives promised deliverable end-to-end.
7. **Unit economics** — Cost per canary send (LLM + Conduit + mail) documented vs. one conversion LTV.

**Verification:** Operator signs card with date; screenshot/links archived in `proof-artifacts/`.

---

## P0-002 — Document asset locations

**Owner:** Operator  
**Depends on:** None  
**Deliverable:** `docs/conduitscore-asset-map.md`

**Must list absolute paths for:**

- 303 validated + 573 harvested contact files  
- `conduit_outreach_pipeline/` root  
- `reverse_funnel_outreach/` root  
- ConduitScore repo + production URL + Stripe payment link(s)  
- Genesis agents source (`Github/Genesis-Agents/skill_bundles/`)  
- AIVS spec files used for Representation Fidelity  

**Verification:** Each path exists on disk or URL returns 200.

---

## P0-003 — Define kill switches & budgets (operator policy)

**Owner:** Operator  
**Depends on:** None  
**Deliverable:** `docs/night-shift-policy.yaml`

**Fields:**

```yaml
daily_llm_cap_usd: 3.00          # match config.yaml defaults unless changed
monthly_llm_cap_usd: 20.00
per_flow_cap_cents: 500          # example: $5 per clawflow run
max_sends_per_day: 10            # Phase 3 start; ramp documented
max_genesis_usd_per_day: 5.00
pause_on_complaint_rate_pct: 0.1
pause_on_bounce_rate_pct: 5.0
require_telegram_approval_for: [send_email, integration.action.smtp]
forbidden_until_g1: [autonomous_send, bulk_enqueue]
```

**Verification:** Policy reviewed; Telegram bot can receive approve/deny messages.

---

# PHASE 1 — Prove ConduitScore loop by hand (business proof)

> **No Cato unattended automation in Phase 1.** Skills and Genesis may assist; operator approves every send.

## P1-001 — Deliverability gate (FP1)

**Owner:** Operator + `cold-outreach-deliverability` skill  
**Depends on:** P0-003  
**Tasks:**

1. Register sibling sending domain (not primary brand domain).
2. Configure SPF, DKIM, DMARC (and one-click unsubscribe headers per skill).
3. Seed-send 20 messages to test inboxes.
4. Run mail-tester / Google Postmaster; archive results.

**Pass:** FP1 row green on Loop Proof Card.  
**Fail action:** Stop all outreach; fix DNS/reputation before P1-004.

---

## P1-002 — Representation Fidelity MVP + artifact contract

**Owner:** Genesis builder/qa + operator  
**Depends on:** P0-001  
**Estimate:** 2–3 days  
**Tasks:**

1. Define output schema: inputs (URL), outputs (fidelity score, LLM quotes vs. page truth, Ed25519 signature, verify URL).
2. Implement minimal generator (Conduit fetch + LLM comparison + sign via Conduit crypto layer).
3. Produce 3 sample artifacts for fake/test domains + 1 real prospect.
4. Add “what you receive” copy for email footer.

**Pass:** Artifact contract section on Loop Proof Card signed; samples in `proof-artifacts/fidelity/`.  
**Reference:** War-room § “AIVS Representation Fidelity (~2–3 day MVP)”.

---

## P1-003 — Truth audit cold engines + funnel

**Owner:** Operator invokes `war-audit` or `truth-audit`  
**Depends on:** P0-002  
**Tasks:**

1. Audit `conduit_outreach_pipeline/` (warmup, unsubscribe, send path, secrets).
2. Audit `reverse_funnel_outreach/`.
3. Audit ConduitScore live funnel: landing → Stripe → fulfillment.
4. File GO/NO-GO report per engine (separate verdicts).

**Pass:** G2 gate — both engines and funnel GO (or documented remediations complete + re-audit GO).  
**Fail action:** Do not proceed to bulk send; fix CRITICALs first.

---

## P1-004 — Pre-render 25 per-prospect audits

**Owner:** Genesis analyst/content + Conduit  
**Depends on:** P1-002, P0-002  
**Tasks:**

1. Select best 25 from 303 validated contacts (criteria documented).
2. For each: run Representation Fidelity pipeline; store artifact path/URL.
3. QA 3 random artifacts for accuracy and signature verify.

**Pass:** 25 artifacts indexed in `proof-artifacts/canary-25/manifest.json`.  
**KPI:** 25/25 generated; 3/3 verify pass.

---

## P1-005 — Hand-send canary 25

**Owner:** Operator (manual approve each)  
**Depends on:** P1-001, P1-003, P1-004  
**Tasks:**

1. Personalize email bodies with audit link/attachment per prospect.
2. Send via approved engine or Gmail with deliverability headers.
3. Log: sent_at, message_id, domain, template_variant in tracking sheet.
4. Monitor replies, complaints, bounces for 7 days.

**Pass:** Loop Proof Card canary row green (≥1 reply or audit-view; complaints <0.1%).  
**Fail action:** Pause scale; revise copy/artifact/FP1.

---

## P1-006 — Prove stranger Stripe conversion

**Owner:** Operator  
**Depends on:** P1-003 (funnel GO)  
**Tasks:**

1. Identify one live payable URL (landing + Stripe Checkout or Payment Link).
2. Run checkout as non-operator (incognito, different card/PayPal if needed).
3. Archive receipt, webhook/log proof, customer email.

**Pass:** Loop Proof Card payment row green.  
**Reference:** War-room validate-first #2.

---

## P1-007 — Fulfill one paid customer E2E

**Owner:** Operator + ConduitScore product  
**Depends on:** P1-006  
**Tasks:**

1. Deliver scan/report per tier purchased.
2. Confirm customer received access/email.
3. Document support thread if issues.

**Pass:** Fulfillment row green on Loop Proof Card.  
**Gate:** **G1** — Phase 1 complete.

---

## P1-008 — Unit economics snapshot

**Owner:** Operator  
**Depends on:** P1-005, P1-006  
**Tasks:**

1. Sum: domain cost, mail infra, LLM/Genesis cost for 25 audits + sends.
2. Record one conversion revenue (or $0 if none yet—document CAC anyway).
3. Decision: continue loop vs. revise offer.

**Deliverable:** `proof-artifacts/unit-economics-canary.md`

---

# PHASE 2 — Cato engineering (orchestration shell)

> Implement only after **G1**. All Python changes require Alex → Kraken → git push per `AGENTS.md`.

## P2-CATO-001 — Single cron dispatcher + start on daemon boot

**Priority:** CRITICAL (fixes C3, H3)  
**Files:** `cato/gateway.py`, `cato/cli.py`, `cato_svc_runner.py`, `cato/core/schedule_manager.py`  
**Problem:** Live daemon runs `CRONS.json` poller only; YAML `SchedulerDaemon` never starts; two systems confuse operators.

**Tasks:**

1. On `Gateway.start()`, also start `SchedulerDaemon` with a real `dispatch_fn`.
2. `dispatch_fn` routes to same path as manual ingest (agent loop or flow.run)—document behavior.
3. Deprecate or merge duplicate cron UX in CLI docs (one “schedules” story).
4. Add integration test: YAML schedule fires and executes skill.

**Acceptance:**

- Create `~/.cato/schedules/test-fire.yaml`; daemon fires within 2 min of cron.
- Audit log contains `cron_fire` + tool calls.

---

## P2-CATO-002 — Enforce `budget_cap` on Clawflows

**Priority:** CRITICAL (fixes C2)  
**Files:** `cato/orchestrator/clawflows.py`, `cato/budget.py`, `cato/agent_loop.py`  
**Problem:** `budget_cap` parsed in YAML but never enforced in `run_flow`.

**Tasks:**

1. Pass `BudgetManager` (or per-run sub-cap) into `FlowEngine.run_flow`.
2. Before each step: check remaining flow budget (cents); stop flow if exceeded.
3. Record flow spend in audit log with `flow_name` + `step_idx`.
4. Tests: `tests/test_clawflows.py` — flow stops when cap exceeded mid-run.

**Acceptance:**

- Flow with `budget_cap: 1` and expensive steps returns FAILED with `budget_exceeded`.
- No silent continuation past cap.

---

## P2-CATO-003 — Wire `budget_cap` on schedule + API cron run

**Priority:** CRITICAL (fixes C4)  
**Files:** `cato/core/schedule_manager.py`, `cato/ui/server.py`, `cato/cli.py`  
**Problem:** `run_cron_job_now` ignores budget; `schedule run` has no `dispatch_fn`.

**Tasks:**

1. Implement shared `async def dispatch_scheduled_skill(skill, args, session_id, budget_cap)` that enforces cap then runs agent/flow.
2. Fix `POST /api/cron/jobs/{name}/run` to use dispatch + `sched.args` + `budget_cap`.
3. Fix `cato schedule run` to use same dispatch (not no-op daemon).
4. Extend `CRONS.json` schema with optional `budget_cap` (default from policy).

**Acceptance:**

- Manual API run respects cap; audit shows cap value in inputs.

---

## P2-CATO-004 — Genesis calls deduct from BudgetManager

**Priority:** CRITICAL (fixes C6)  
**Files:** `cato/tools/genesis.py`, `cato/agent_loop.py`, `cato/budget.py`  
**Problem:** Genesis POST has no `check_and_deduct`; fleet can exceed daily cap.

**Tasks:**

1. Add per-agent estimated cost table (cents) from `GENESIS_AGENTS.price_usd` or config override.
2. Before POST: `await budget.check_and_deduct("genesis-{agent}", est_tokens_in, est_tokens_out)` or flat cents.
3. On HTTP failure after deduct: document refund policy (no double charge on retry).
4. Tests in `tests/test_genesis_tool.py`.

**Acceptance:**

- Genesis call when daily cap nearly full returns structured budget error JSON.
- Telegram `/budget` reflects Genesis spend.

---

## P2-CATO-005 — Wire LedgerMiddleware into AgentLoop tool path

**Priority:** HIGH (fixes C7)  
**Files:** `cato/agent_loop.py`, `cato/audit/ledger.py`  
**Problem:** Causal ledger tested but not used on live tool calls; only `AuditLog` writes.

**Tasks:**

1. Instantiate `LedgerMiddleware` alongside `AuditLog` when `audit_enabled`.
2. On each tool dispatch: append ledger record (tool_name, input/output hashes, confidence if available).
3. Expose `GET /api/audit/ledger/verify` (or CLI `cato audit verify-ledger`).
4. Do not duplicate storage unnecessarily—document relationship AuditLog vs Ledger.

**Acceptance:**

- `verify_chain()` passes after 10 tool calls in one session.
- Desktop or API can show last ledger tail.

---

## P2-CATO-006 — Revenue loop Clawflow template (reference)

**Priority:** HIGH (fixes C1)  
**Files:** `~/.cato/flows/conduitscore-revenue-loop.yaml` (shipped example in repo `examples/flows/`), `docs/flows/conduitscore-revenue-loop.md`  
**Depends on:** P2-CATO-002  

**Steps (documented YAML):**

```yaml
name: conduitscore-revenue-loop
trigger:
  type: manual
budget_cap: 500
steps:
  - skill: file.read
    args: { path: "{{prospect_manifest}}" }
  - skill: genesis
    args: { agent: genesis-analyst, task: representation_fidelity, params: { url: "{{url}}" } }
  - skill: genesis
    args: { agent: genesis-email, task: draft_outreach, params: { audit_url: "{{artifact_url}}" } }
  - skill: send_email
    args: { draft_only: true }
    on_error: stop
```

**Tasks:**

1. Add example flow in repo; document placeholders.
2. Map each step to P1 manual procedure (parity table in doc).
3. `dry_run: true` mode flag on flow (no send_email Send click).

**Acceptance:**

- `cato flow run conduitscore-revenue-loop` completes dry-run with audit entries for each step.

---

## P2-CATO-007 — Block budget bypass in unattended modes

**Priority:** HIGH (fixes H2)  
**Files:** `cato/agent_loop.py`, `cato/config.py`  
**Tasks:**

1. Add config `unattended_mode: false` (default).
2. When `unattended_mode: true`, ignore `_BUDGET_BYPASS_PHRASES` in user messages.
3. Log attempted bypass to audit as security event.

**Acceptance:**

- Test: unattended + “bypass budget” does not skip `check_and_deduct`.

---

## P2-CATO-008 — Telegram approval gate for outbound email

**Priority:** HIGH  
**Files:** `cato/adapters/telegram.py`, `cato/gateway.py`, `cato/tools/` (send path)  
**Depends on:** P0-003  
**Tasks:**

1. Before `send_email` Send: hold draft in session state; Telegram message with Approve/Reject inline buttons.
2. Timeout: reject after N hours; audit log `approval_denied` or `approval_granted`.
3. Integrate with `send_email.md` skill rules (always confirm).

**Acceptance:**

- Unapproved send never reaches Gmail Send click in supervised test.

---

## P2-CATO-009 — Bridge to cold outreach engines (integration spike)

**Priority:** HIGH (fixes C1, H1)  
**Files:** New `cato/tools/outreach_bridge.py` OR documented subprocess wrapper; config keys  
**Depends on:** P1-003 GO, P0-002 paths  
**Tasks:**

1. SPIKE: invoke outreach pipeline CLI with args `{contact_id, artifact_path, template}` from Cato tool.
2. Return stdout + path to send log; write audit entry.
3. If engines lack CLI: add thin `run_batch.py` in outreach repo (separate PR) — document dependency.
4. Do **not** replace `send_email.md` until engine bridge proven.

**Acceptance:**

- One contact sent via bridge with operator approve; audit + engine log match.

---

## P2-CATO-010 — Night-shift Telegram digest

**Priority:** MEDIUM  
**Files:** `cato/adapters/telegram.py`, `cato/gateway.py`  
**Tasks:**

1. Daily cron (CRONS or YAML): summarize spend (LLM/Genesis/Conduit), sends attempted, approvals pending, audit chain head hash.
2. Alert if cap >80% or complaint flag set in policy file.

**Acceptance:**

- Operator receives digest at scheduled time on test day.

---

## P2-CATO-011 — Desktop/UI: schedules + flow budget visibility

**Priority:** MEDIUM  
**Files:** `desktop/src/views/`, `cato/ui/server.py`  
**Tasks:**

1. Settings or System view: list YAML schedules, next fire, `budget_cap`.
2. Show flow run history from `flow_runs.db` with spend if tracked.
3. Cron “Run now” uses fixed API from P2-CATO-003.

**Acceptance:**

- UI shows cap and last run status without reading logs manually.

---

## P2-CATO-012 — Genesis allowlist for revenue loop agents only

**Priority:** MEDIUM  
**Files:** `%APPDATA%/cato/config.yaml`, docs  
**Tasks:**

1. Set `genesis_agent_allowlist` to revenue-loop agents only: `genesis-analyst`, `genesis-content`, `genesis-email`, `genesis-marketing` (adjust per P1 usage).
2. Document pending agents blocked until deployed.

**Acceptance:**

- Call to `genesis-legal` returns `pending_deployment` or `not_in_allowlist`.

---

# PHASE 2 — Supervised Cato proof (operator + system)

> Depends on **G1** and P2-CATO-001 through P2-CATO-008 minimum.

## P2-PROOF-001 — Dry-run 5 prospects

**Owner:** Operator  
**Depends on:** P2-CATO-006, P2-CATO-002  
**Tasks:**

1. Run `conduitscore-revenue-loop` with `dry_run: true` for 5 prospects.
2. Verify audit log: file.read → genesis ×2 → send_email draft only.
3. Confirm zero Gmail Send actions.

**Pass:** 5/5 dry-runs complete; audit chain verifies.

---

## P2-PROOF-002 — Supervised live 5 prospects

**Owner:** Operator  
**Depends on:** P2-PROOF-001, P2-CATO-008, P1-001  
**Tasks:**

1. Run flow live with Telegram approve per send.
2. Enforce daily LLM cap intentionally low ($1) once to confirm stop.
3. Compare outcomes to P1-005 manual sends (reply rate qualitative).

**Pass:** G3 gate — 5/5 match manual quality; no cap bypass; no silent sends.

---

## P2-PROOF-003 — Alex audit + full pytest

**Owner:** Alex agent  
**Depends on:** All P2-CATO tasks coded  
**Deliverable:** `CATO_ALEX_AUDIT.md` status APPROVED, 100% tests pass.

---

## P2-PROOF-004 — Kraken verification

**Owner:** Kraken agent  
**Depends on:** P2-PROOF-003  
**Deliverable:** `CATO_KRAKEN_VERDICT.md` status APPROVED.

---

# PHASE 3 — Limited autonomy (night-shift manager)

> Depends on **G3**, **G4**, and 7+ days stable supervised runs.

## P3-001 — Autonomous schedule with ramp policy

**Owner:** Operator  
**Depends on:** P2-PROOF-002, P0-003  
**Tasks:**

1. Enable `unattended_mode: true` only on dedicated agent profile `night-shift`.
2. YAML schedule: off-hours cron, `max_sends_per_day: 10` week 1.
3. Week 2: 25/day if metrics green; never exceed 303 without new FP1 check.

**Pass:** 7 days without cap violation or unapproved send.

---

## P3-002 — Complaint/bounce auto-pause

**Owner:** Engineering  
**Depends on:** P2-CATO-009 or tracking sheet webhook  
**Tasks:**

1. Feed bounce/complaint counts into Cato (file drop or API).
2. When policy threshold exceeded: disable schedule + Telegram alert.

**Pass:** Simulated bounce triggers pause in test.

---

## P3-003 — 30-day night-shift verification

**Owner:** Operator + Kraken  
**Tasks:**

1. Daily digests archived.
2. Weekly ledger verify + budget reconciliation.
3. Re-run truth-audit on composed system (Cato + engines + Stripe).

**Pass:** Phase 3 success KPI in Executive Summary.

---

# EXTERNAL / NON-CATO TASKS (track in same board)

| ID | Task | Owner | Phase |
|----|------|-------|-------|
| EXT-001 | Sibling domain + DNS | Operator | 1 |
| EXT-002 | Representation Fidelity MVP in ConduitScore/Conduit repo | Genesis | 1 |
| EXT-003 | war-audit cold engines | Operator | 1 |
| EXT-004 | Stripe stranger test | Operator | 1 |
| EXT-005 | Product Hunt / launch-builder | Operator | 2+ |
| EXT-006 | Badge + certificate viral build | Builder | 2+ |
| EXT-007 | Deploy 5 pending Genesis agents on SwarmSync | Ops | 2 |
| EXT-008 | `GATEWAY_API_KEY` + move off Render free tier | Ops | 2 |
| EXT-009 | Refill list via lead-sourcing-enrichment | Operator | 2+ |

---

# BUG REGISTER (from Bughound — link to fixes)

| ID | Severity | Summary | Fix task |
|----|----------|---------|----------|
| C1 | CRITICAL | No E2E revenue workflow in Cato | P2-CATO-006, P2-CATO-009 |
| C2 | CRITICAL | Clawflow `budget_cap` not enforced | P2-CATO-002 |
| C3 | CRITICAL | YAML SchedulerDaemon not on live daemon | P2-CATO-001 |
| C4 | CRITICAL | API/CLI cron ignore budget / no dispatch | P2-CATO-003 |
| C5 | CRITICAL | CRONS.json no per-job budget | P2-CATO-003 |
| C6 | CRITICAL | Genesis not budget-gated | P2-CATO-004 |
| C7 | HIGH | LedgerMiddleware not wired | P2-CATO-005 |
| H1 | HIGH | send_email ≠ cold engines | P2-CATO-009 |
| H2 | HIGH | Budget bypass phrases | P2-CATO-007 |
| H3 | HIGH | Two cron systems | P2-CATO-001 |
| H4 | HIGH | 5 Genesis agents pending | EXT-007 |
| H5 | HIGH | Render cold start | EXT-008 |
| M1 | MEDIUM | Cheerio-only product limits | EXT-002 |
| M2 | MEDIUM | Stale contact list | EXT-009 |
| M3 | MEDIUM | Integration approvals for Stripe | P1-003 audit |

---

# TEST PLAN (minimum)

| Area | Command / check |
|------|-----------------|
| Full suite | `pytest` — 100% pass before any push |
| Clawflows budget | `pytest tests/test_clawflows.py -k budget` |
| Cron scheduler | `pytest tests/test_cron_scheduler.py` |
| Genesis budget | `pytest tests/test_genesis_tool.py` |
| Ledger chain | `pytest tests/test_e2e_full_pipeline.py -k Ledger` |
| Manual E2E | P2-PROOF-001, P2-PROOF-002 scripts in `docs/manual-e2e-night-shift.md` (create during P2) |
| Audit gate | `CATO_ALEX_AUDIT.md` + `CATO_KRAKEN_VERDICT.md` APPROVED |

---

# DOCUMENTATION DELIVERABLES

| File | Phase | Owner |
|------|-------|-------|
| `docs/loop-proof-card.md` | 0 | Operator |
| `docs/conduitscore-asset-map.md` | 0 | Operator |
| `docs/night-shift-policy.yaml` | 0 | Operator |
| `docs/flows/conduitscore-revenue-loop.md` | 2 | Engineering |
| `docs/manual-e2e-night-shift.md` | 2 | Engineering |
| `examples/flows/conduitscore-revenue-loop.yaml` | 2 | Engineering |
| `proof-artifacts/**` | 1 | Operator |

---

# RISK PRE-MORTEM (monitor during build)

1. **Automating before FP1** → spam folder, domain burned. Mitigation: G1 hard stop.  
2. **Using arbitrage engine** → financial exposure. Mitigation: out of scope forever.  
3. **Silent sends** → brand/legal risk. Mitigation: P2-CATO-008 through Phase 3.  
4. **Cap theater** → caps logged but not enforced. Mitigation: P2-CATO-002/003/004 tests.  
5. **Wrong outreach path** → Gmail UI skill vs engine. Mitigation: P2-CATO-009.  
6. **Stale contacts** → bounces spike. Mitigation: re-verify before ramp (EXT-009).  
7. **Multi-root failure** → payment works, fulfillment broken. Mitigation: P1-007 separate gate.

---

# IMPLEMENTATION ORDER (recommended sprint sequence)

```
Sprint 0 (operator):  P0-001, P0-002, P0-003
Sprint 1 (business):    P1-001 → P1-003 → P1-002 → P1-004 → P1-005 → P1-006 → P1-007 → P1-008  [G1]
Sprint 2 (Cato core):   P2-CATO-001, P2-CATO-002, P2-CATO-003, P2-CATO-004  [parallel where possible]
Sprint 3 (Cato trust):  P2-CATO-005, P2-CATO-007, P2-CATO-008, P2-CATO-006
Sprint 4 (bridge+UI):   P2-CATO-009, P2-CATO-010, P2-CATO-011, P2-CATO-012
Sprint 5 (proof):       P2-PROOF-001 → P2-PROOF-004  [G3, G4]
Sprint 6 (autonomy):    P3-001 → P3-003  [only if G3/G4 green]
```

**Parallel track:** EXT-001 through EXT-004 during Sprint 1; EXT-007/008 during Sprint 3.

---

# TASK STATUS BOARD (update as you go)

Copy to project tracker or check boxes here:

### Phase 0
- [ ] P0-001 Loop Proof Card
- [ ] P0-002 Asset map
- [ ] P0-003 Night-shift policy YAML

### Phase 1 — Business proof
- [ ] P1-001 FP1 deliverability
- [ ] P1-002 Representation Fidelity MVP
- [ ] P1-003 Truth audit engines + funnel
- [ ] P1-004 25 audits rendered
- [ ] P1-005 Canary 25 sent
- [ ] P1-006 Stranger Stripe
- [ ] P1-007 Fulfillment E2E
- [ ] P1-008 Unit economics
- [ ] **G1 PASSED**

### Phase 2 — Cato build
- [x] P2-CATO-001 Unified cron + daemon start
- [x] P2-CATO-002 Clawflow budget enforce
- [x] P2-CATO-003 Schedule/API budget + dispatch
- [x] P2-CATO-004 Genesis budget
- [x] P2-CATO-005 Ledger middleware wire
- [x] P2-CATO-006 Revenue loop flow template
- [x] P2-CATO-007 Unattended bypass block
- [x] P2-CATO-008 Telegram approve send (pending queue + callbacks; live send still policy-gated)
- [x] P2-CATO-009 Outreach bridge spike (dry-run default; engine path from policy)
- [x] P2-CATO-010 Telegram digest (`/digest`, schedule `night-shift-digest`, API status)
- [x] P2-CATO-011 Desktop schedule UI (budget_cap column in CronView; flow cap in FlowsView)
- [x] P2-CATO-012 Genesis allowlist (policy YAML + genesis tool budget gate)
- [ ] P2-PROOF-001 Dry-run 5
- [ ] P2-PROOF-002 Supervised live 5
- [ ] P2-PROOF-003 Alex APPROVED
- [ ] P2-PROOF-004 Kraken APPROVED
- [ ] **G3 PASSED** · **G4 PASSED**

### Phase 3 — Night shift
- [ ] P3-001 Ramp schedule
- [ ] P3-002 Auto-pause on complaints
- [ ] P3-003 30-day verification

### External
- [ ] EXT-001 … EXT-009 (as needed)

---

# REFERENCES

- War room master: `C:\Users\Administrator\Desktop\Decision Oracle\Assets Marketing Output\WAR-ROOM-MASTER-DELIVERABLE.md`
- Cato dev rules: `AGENTS.md`, `CLAUDE.md`
- Bughound session: ConduitScore night-shift investigation (2026-06-02)
- Skills: `cold-outreach-deliverability`, `war-audit`, `truth-audit`, `lead-sourcing-enrichment`, `halbert-copy-doctor`, `autonomous-cro`

---

**End of build spec.** Start with **P0-001** (Loop Proof Card). Do not begin **P2-CATO-*** until **G1** is explicitly signed off on the Loop Proof Card.
