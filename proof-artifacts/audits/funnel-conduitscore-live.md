# Truth audit — Live funnel: conduitscore.com → Stripe → fulfillment

**Date:** 2026-06-03  
**Method:** Live HTTP probes + code trace + prior war-audit (2026-05-30)  
**Scope:** Revenue loop only — landing, scan, paywall, webhook, report delivery (not ghost-audit marketing stats)

---

## Verdict: **CONDITIONAL GO**

Core **paid loop wiring is real**. Marketing-page false stats (ghost-audit) are **out of scope** for this row but noted below.

---

## Live probes (2026-06-03)

| Endpoint | HTTP | Note |
|----------|------|------|
| `https://conduitscore.com/` | 200 | Landing loads |
| `https://conduitscore.com/pricing` | 200 | Pricing loads |
| `https://conduitscore.com/unsubscribe` | 200 | Outreach unsubscribe (Row 1) |
| `POST /api/scan` (no key) | 402 | API **live** — free-tier quota message (not 5xx) |
| `/.well-known/aivs-public-key` | 200 | Ed25519 public key JSON |
| `/health` | 404 | No health route (non-blocking) |

---

## Code trace — chain of custody

| Step | Implementation | Status |
|------|----------------|--------|
| 1. Prospect scans URL | `src/app/api/scan/route.ts` → `runScan()` | **Wired** |
| 2. Signed proof | `signProof` in scan orchestrator; `GET /api/verify/[scanId]` | **Wired** |
| 3. Report page | `/reports/[scanId]` + `GET /api/scans/[id]/report` | **Wired** |
| 4. Upgrade | `/pricing` → `POST /api/stripe/checkout` (auth required) | **Wired** |
| 5. Payment | Stripe Checkout `mode: subscription` | **Wired** |
| 6. Webhook | `api/stripe/webhook` — signature verify + idempotency + tier upsert | **Wired** |
| 7. Post-pay | `success_url` → `/dashboard?session_id=…` | **Wired** |
| 8. Fix order / SwarmSync | `api/swarmsync/create-fix-order` | **Wired** (parallel monetization) |

---

## War-audit cross-reference (2026-05-30)

**Overall:** CONDITIONAL GO (no CRITICAL).

**In revenue-loop path:** No CRITICAL blockers on scan → report → Stripe webhook.

**Outside loop (document, do not block G1 on):**

- HIGH: Ghost-audit hardcoded stats (“847 sites”, etc.)  
- HIGH: Leaderboard → compare `urlA` pre-fill broken  
- MEDIUM: Compare endpoint quota bypass; seeded leaderboard unlabeled  

---

## Blockers for full GO

| ID | Issue | Blocks |
|----|-------|--------|
| F-1 | Invalid API key for **automated** outreach scans (401) | Engine A + personalized hooks at scale |
| F-2 | No end-to-end **stranger payment** proof in `proof-artifacts/stripe/` yet | G1 Row 5 (not Row 3) |

---

## G1 recommendation

Row 3 **funnel** can be **CONDITIONAL GO** now. Upgrade to **GO** after stranger Stripe test (Row 5) or explicit CEO sign-off that marketing-page HIGHs are accepted debt.
