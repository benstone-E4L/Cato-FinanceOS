# AMENDMENT 2026-08-22 — Posting model (supersedes 2026-08-21 interpretation)

**Status:** Authoritative for all Ralph workspaces in this pack and downstream (`financeos-xero-write-rail`, `swarmsync-proof-controls`, `accounts-payable-pilot`).

**Supersedes** conflicting language dated ≤2026-08-21 where it implies:
- Genesis "posts" only as a metaphor (proposal → intent) with **no Xero HTTP client**
- Cato is the default executor for routine domain work (demo or prod)
- FinanceOS Worker is the **only** production write path
- Success = `write_attempted: false` without executor/ realm qualifier
- "Second Xero client inside Genesis" is unconditionally forbidden

**Ben 2026-08-21:** "Cato delegates and Genesis agents post."  
**Ben 2026-08-22 clarification:** Genesis agents **literally post** their domain transactions to Xero. Cato is the **Controller** — routes work, reconciles, holds **full books access**, and posts **only for remediation** (override, correction, close adjustment, specialist failure). FinanceOS Worker remains for **production belt** jobs (queued intents, batch, non-Genesis paths) — **not** a substitute for AP/AR/cash specialists.

---

## Authoritative four-role model

| Role | Component | Responsibility | Xero access |
|---|---|---|---|
| **Orchestrate** | Cato | Intake from sources (Stripe, Shopify, Gmail, portal…), routing matrix, policy, reconciliation, escalation to controller specialist, **remediation posts** | **All OAuth scopes** on the app; runtime policy restricts routine writes to specialists |
| **Operate (domain)** | Genesis specialists (14) | Judgment + **domain posts** (AP bills, AR invoices, bank lines, journals, etc.) | **Scoped** tools per `XERO_SCOPE_TO_AGENT_MAP.yaml` |
| **Prove** | SwarmSync proof stack | InvoiceProof → VerifyAPI → AuditProof; mandatory fail-closed gates | None (verification only) |
| **Belt (production)** | FinanceOS Worker | `intent.execute` for approved intents from UI, Composio, batch replay, scheduled jobs — **after** proof chain | Production MCP with `XERO_PRODUCTION_WRITE_ENABLED` + entity allowlist |

```text
Source event
  → Cato (route + policy + evidence injection)
  → Genesis specialist (domain post) ──┐
  → VerifyAPI PASS + approval        │
  → Xero write + read-back           │  OR Cato remediation post (controller)
  → AuditProof (producer ≠ verifier) │  OR Worker execute (production belt)
  → FinanceOS receipt + proof bundle ┘
```

---

## Executor selection (canonical)

| Situation | Executor | `execution_realm` |
|---|---|---|
| Routine AP bill from Gmail pilot | `genesis-e4l-ap` | `genesis_specialist` |
| Routine AR invoice / revenue doc | `genesis-e4l-ar` / `genesis-e4l-revenue` | `genesis_specialist` |
| Stripe/Shopify rail clearing | `genesis-e4l-stripe` / `genesis-e4l-shopify` | `genesis_specialist` |
| Period-end / IC / adjusting entries | `genesis-e4l-journals` / `genesis-e4l-intercompany` / `genesis-e4l-close` | `genesis_specialist` |
| Controller override / fix / reclass | Cato | `cato_remediation` |
| Approved intent from Control Room / API (no live specialist session) | FinanceOS Worker | `production_worker` |
| Demo Company sandbox (same rules, demo MCP host) | Domain specialist **or** Cato remediation | `demo_mcp` (realm tag; executor still recorded) |

**Obsolete:** "Genesis never holds Xero HTTP client" — replaced by **scoped Genesis MCP client** per agent map, with constitution tests for scope violations (not blanket deny).

---

## Proof chain (unchanged requirement — all executors)

Every material write MUST traverse (where applicable):

1. **InvoiceProof** — source evidence (AP/receipt paths)
2. Genesis analysis + handoff JSON with proposed payload
3. **VerifyAPI** — boundary check (agent scope, entity binding, capability token)
4. FinanceOS policy + human approval when required
5. **Execute** — Genesis specialist | Cato remediation | Worker
6. **Read-back** — independent fetch; mismatch → FAILED, not CONFIRMED
7. **AuditProof** — producer session ≠ verifier session

Skipping any mandatory step → HOLD. Demo sandbox uses same proof IDs; `execution_realm` distinguishes environment.

---

## Success metrics (revised)

### L1–L7 / S1–S9 (accounting Q&A + read-heavy)
- Specialists may return `write_attempted: false` when question is analytical only.
- Live reads: no unscoped write.

### S10 / E2E posting scenarios (new baseline)
- Specialist proposes **and** executes domain post after VerifyAPI PASS → read-back matches → AuditProof emitted → Cato reconciles receipt into FinanceOS.
- Cato remediation path: only when routing policy marks `executor: cato_remediation` (conflict, override, specialist failure).
- Worker path: intent queued without active specialist session → Worker executes → same read-back + AuditProof.

### Gate A (40-bill AP pilot)
- **Primary executor:** `genesis-e4l-ap` (not Cato, not Worker unless belt path explicitly tested as alternate).
- Each bill row records: `executor`, `execution_realm`, proof IDs, Xero bill ID, read-back hash.

---

## Files to read with this amendment

| File | Purpose |
|---|---|
| `XERO_SCOPE_TO_AGENT_MAP.yaml` | OAuth scope → specialist primary/read/Cato remediation |
| `financeos-xero-write-rail/` | Intent model, Worker belt, read-back, demo bridge |
| `swarmsync-proof-controls/` | InvoiceProof, AuditProof, VerifyAPI, proof chain |
| `accounts-payable-pilot/` | Gate A harness — AP specialist as executor |
| `HANDOFF-CATO-GENESIS-XERO-DEMO-2026-08-21.md` (PCP) | Live demo build facts (COA, MCP v7, quota) |

---

## Obsolete phrases (do not use in new work)

- "Genesis posts = proposal becomes intent" **without** specialist HTTP execute step
- "Cato only agent that may call Xero" **without** specialist scoped writes
- "Success = write_attempted false" **without** analytical vs operational qualifier
- "Never post" for specialists on domain work
- Constitution test: "Genesis repo has zero Xero accounting write imports" — replace with **scoped-write allowlist** tests per agent
- Implying FinanceOS Worker is cancelled (it is not)
