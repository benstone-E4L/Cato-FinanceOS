# Loop Proof Card — ConduitScore Revenue Loop

**Build spec:** `CONDUITSCORE-NIGHT-SHIFT-001`  
**Operator:** ________________________________  
**Started:** ____________  
**G1 signed off (Phase 1 complete):** ☐ Yes — date ____________  

> Rule: Do **not** enable Cato unattended outreach (Phase 3) or treat the loop as “proven” until every row you intend to rely on is **PASS** with evidence linked below.

---

## How to use this card

1. Fill in **Evidence link / path** for each row when you complete it.
2. Mark **Status:** `PASS` | `FAIL` | `PENDING` | `N/A`
3. If **FAIL**, write one line in **Blocker** and stop downstream rows until fixed.
4. **G1** requires rows 1–6 green (row 7 recommended but not required for G1).

---

## Row 1 — FP1 deliverability

| Field | Value |
|-------|--------|
| **Status** | PASS |
| **Requirement** | Sibling sending domain (not `conduitscore.com`); SPF, DKIM, DMARC; one-click unsubscribe headers; 20 seed sends; mail-tester / Google Postmaster acceptable |
| **Sending domain used** | `surfacescore.com` (From: `bstone@surfacescore.com`, Brevo SMTP) |
| **Evidence link / path** | `proof-artifacts/fp1/` — `ROW1-CHECKLIST.md`, `seed-test-manifest.json` (20/20 inbox), `mail-tester-result-2026-06-03.json` |
| **Blocker** | — (optional: mail-tester ≥8 after Brevo disables tracking; Postmaster screenshot) |

**Pass when:** Seeds land in inbox (not spam) on ≥18/20 test inboxes per your deliverability skill criteria.

**Proof (2026-06-03):** Operator confirmed **20/20 inbox** on Gmail (`bullrushinvestments+fp1s01..20`). mail-tester **7.6/10** on file — improve later via Brevo support. Cato live outreach still **off** until rows 2–6 pass.

---

## Row 2 — Representation Fidelity artifact contract

| Field | Value |
|-------|--------|
| **Status** | PASS |
| **Requirement** | Written contract: inputs (URL), outputs (score, LLM vs page diff, signature, verify URL), format (PDF/HTML/JSON), credibility copy for email |
| **Artifact schema version** | `conduitscore.report_card.v1` + AIVS-Micro |
| **Sample artifact paths** | 1) `fidelity/samples/sample-01-example.json` 2) `sample-02-linear.json` 3) `sample-03-conduitscore.json` |
| **Evidence link / path** | `proof-artifacts/fidelity/contract.md`, `what-you-receive.md`, `ROW2-CHECKLIST.md`, `verification-log.json` |
| **Blocker** | — (optional: export fresh live `/api/scan` JSON into `fidelity/samples/`) |

**Pass when:** 3 samples verify (signature checks) and a non-technical reader understands “what they get.”

**Proof (2026-06-03):** Contract + email copy on file. Three reference artifacts with **valid** Ed25519 verification (local, same production code path). Live scan verified after key rotation (see Row 3 / `api-key-rotation-2026-06-03.txt`).

---

## Row 3 — Truth audit: cold engines + funnel

| Field | Value |
|-------|--------|
| **Status** | PASS |
| **Requirement** | `war-audit` or `truth-audit` GO on: (a) conduit outreach engine, (b) reverse funnel engine, (c) live funnel landing → Stripe → fulfillment |
| **Engine A verdict** | **GO** — report: `proof-artifacts/audits/engine-a-conduit-outreach.md` |
| **Engine B verdict** | **GO** — report: `proof-artifacts/audits/engine-b-reverse-funnel.md` |
| **Funnel verdict** | **GO** — report: `proof-artifacts/audits/funnel-conduitscore-live.md` |
| **Evidence link / path** | `proof-artifacts/audits/ROW3-CHECKLIST.md`, `verification-log-row3.json` |
| **Blocker** | — |

**Pass when:** All three GO, or NO-GO items remediated and re-audited to GO.

**Proof (2026-06-03):** All three **GO** after API key rotation. Live scan `example.com` → score 30; outreach dry-run shows 30/100. Keep API key synced in pipeline `.env`, reverse-funnel-scanner `.env`, and Cato vault.

---

## Row 4 — Canary outreach (25 sends)

| Field | Value |
|-------|--------|
| **Status** | PENDING |
| **Requirement** | 25 hand-approved sends to validated contacts; personalized audit hook; track 7 days |
| **Contacts source file** | e.g. ConduitScore `outreach_valid_303.csv` or Clay export |
| **Manifest** | `proof-artifacts/canary-25/manifest.json` (via `cato canary select`) |
| **Selection criteria** | `proof-artifacts/canary-25/selection-criteria.md` |
| **Sent count** | ____ / 25 |
| **Replies or audit views** | ____ (need ≥1) |
| **Complaint rate** | ____% (need &lt;0.1%) |
| **Bounce rate** | ____% |
| **Evidence link / path** | e.g. `proof-artifacts/canary-25/tracking-sheet.csv` |
| **Blocker** | |

**Pass when:** ≥1 reply OR ≥1 confirmed audit view; complaints &lt;0.1%.

---

## Row 5 — Stranger Stripe conversion

| Field | Value |
|-------|--------|
| **Status** | PENDING |
| **Requirement** | One payment completed by non-operator (incognito / different payer); no manual checkout assist |
| **Payable URL tested** | ________________________________ |
| **Stripe receipt / session ID** | ________________________________ |
| **Date/time (UTC)** | ________________________________ |
| **Evidence link / path** | e.g. `proof-artifacts/stripe/receipt-redacted.pdf` |
| **Blocker** | |

**Pass when:** Receipt matches live product tier and timestamp is documented.

---

## Row 6 — Fulfillment E2E

| Field | Value |
|-------|--------|
| **Status** | PENDING |
| **Requirement** | Paid customer receives promised deliverable (scan/report/fidelity package per tier) |
| **Customer identifier** | (internal ID only, no PII in shared copies) __________ |
| **Deliverable delivered** | ☐ Yes |
| **Evidence link / path** | e.g. screenshot of delivered report + support thread summary |
| **Blocker** | |

**Pass when:** Customer confirms receipt OR system logs show successful delivery.

---

## Row 7 — Unit economics (canary)

| Field | Value |
|-------|--------|
| **Status** | PENDING |
| **Requirement** | Document cost of 25 audits + 25 sends vs. revenue from row 5 (or $0 with explicit CAC note) |
| **Total canary cost (USD)** | $________ |
| **Revenue from canary conversion (USD)** | $________ |
| **Decision** | Continue / Revise offer / Pause |
| **Evidence link / path** | `proof-artifacts/unit-economics-canary.md` |
| **Blocker** | |

---

## Gate summary

| Gate | Condition | Status |
|------|-----------|--------|
| **G1** | Rows 1–6 PASS | PENDING |
| **G2** | Row 3 all GO | PENDING |
| **G3** | Cato supervised 5/5 (Phase 2) | PENDING |
| **G4** | Alex + Kraken APPROVED | PENDING |
| **G5** | 30-day night-shift (Phase 3) | PENDING |

---

## Operator sign-off

```
I confirm the above PASS rows are backed by real evidence (not assumed).

Signature / name: _________________________   Date: ____________
```
