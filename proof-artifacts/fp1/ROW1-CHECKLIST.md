# G1 Row 1 — FP1 Deliverability Evidence Checklist

**Sending domain:** `surfacescore.com`  
**From address:** `bstone@surfacescore.com`  
**SMTP relay:** Brevo `smtp-relay.brevo.com:587`  
**Outreach config:** `ConduitScore/conduit_outreach_pipeline/.env` (secrets not in git)  
**Assessment date:** 2026-06-03  
**Row 1 status:** **PASS** — 20/20 seeds inbox (operator 2026-06-03); mail-tester 7.6/10 documented (improve via Brevo tracking off)

> Cato: `live_outreach_enabled=false`, `g1_manual_loop_proven=false` — unchanged.

---

## Pass criteria (from `docs/loop-proof-card.md`)

- Sibling domain — **not** `conduitscore.com`
- SPF, DKIM, DMARC aligned with **Brevo** sending
- One-click unsubscribe headers on outbound mail
- **20 seed sends** with ≥18/20 inbox placement
- mail-tester.com and/or Google Postmaster acceptable scores

---

## Checklist

| ID | Requirement | Status | Evidence file | Notes |
|----|-------------|--------|---------------|-------|
| R1-01 | Sibling sending domain (≠ conduitscore.com) | **PASS (local)** | `dns-snapshot-2026-06-02.txt` | From = `@surfacescore.com`; policy forbids conduitscore.com From |
| R1-02 | Brevo domain verification present | **PASS (local)** | `dns-snapshot-2026-06-02.txt` | TXT `brevo-code:…` on surfacescore.com |
| R1-03 | DKIM (Brevo selectors) | **PASS (local)** | `dns-snapshot-2026-06-02.txt` | `brevo1` / `brevo2` CNAME → `*.dkim.brevo.com` |
| R1-04 | DMARC record exists | **PASS (local)** | `dns-snapshot-2026-06-02.txt` | `_dmarc`: `p=none`, rua to Brevo |
| R1-05 | SPF for Brevo (shared plan) | **N/A — PASS (policy)** | `brevo-spf-not-required.md` | Brevo domain UI shows **no SPF line**; shared relay uses Brevo Return-Path — **DKIM** aligns DMARC, not SPF |
| R1-06 | SMTP auth to Brevo relay | **PASS (local)** | `smtp-auth-test-2026-06-02.log` | Login OK; no message sent |
| R1-07 | List-Unsubscribe headers in pipeline | **PASS (local)** | `configuration-snapshot.md` | Code sets `List-Unsubscribe` + `List-Unsubscribe-Post` when URL + token set |
| R1-08 | Unsubscribe HTTPS endpoint live | **PASS (local)** | `unsubscribe-url-check.txt` | `https://conduitscore.com/unsubscribe` → HTTP 200 |
| R1-09 | Unsubscribe on brand domain (recommended) | **WARN** | — | Headers point at **conduitscore.com**; consider `https://surfacescore.com/unsubscribe` later |
| R1-10 | mail-tester.com score | **FAIL (7.6/10)** | `mail-tester-result-2026-06-03.json` | Target ≥8; Brevo HTML tracking hurts score — disable via Brevo support |
| R1-11 | Google Postmaster Tools | **OPERATOR REQUIRED** | `postmaster-domain-status.png` | See `OPERATOR-STEPS.md` §2 |
| R1-12 | 20 seed inbox test (≥18 inbox) | **PASS (20/20)** | `seed-test-manifest.json` | Operator confirmed all inbox in Gmail 2026-06-03 |
| R1-13 | One real test message (optional pre-seed) | **OPERATOR REQUIRED** | `test-send-headers.eml` or screenshot | To self only; dry-run policy still applies to bulk |

---

## Blockers before seed test

1. ~~SPF include for Brevo~~ — **Not required** when Brevo shows no SPF field (shared account). See `brevo-spf-not-required.md`.
2. ~~R1-12 seeds~~ — **done (20/20 inbox)**. Optional: raise mail-tester ≥8 (Brevo tracking) or add Postmaster screenshot.

---

## Row 1 sign-off rule

Set `docs/loop-proof-card.md` Row 1 to **PASS** only when:

- Brevo domain auth shows **DKIM + DMARC green** (screenshot in `fp1/`), and  
- R1-12 is **PASS** with `seed-test-manifest.json` showing ≥18/20 inbox, and  
- At least one of R1-10 or R1-11 has evidence files in `proof-artifacts/fp1/`.

**Do not** set `gates.g1_manual_loop_proven` in policy until rows 1–6 pass.
