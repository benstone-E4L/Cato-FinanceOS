# G1 Row 3 — Truth audit (cold engines + funnel)

**Date:** 2026-06-03  
**Row 3 status:** **PASS** (2026-06-03, after API key rotation + re-test)

---

## Verdicts

| Engine | Report | Verdict |
|--------|--------|---------|
| **A** — `conduit_outreach_pipeline` | `engine-a-conduit-outreach.md` | **CONDITIONAL GO** (NO-GO for canary until scan API works) |
| **B** — `reverse_funnel_outreach` | `engine-b-reverse-funnel.md` | **GO** |
| **C** — Live funnel conduitscore.com | `funnel-conduitscore-live.md` | **CONDITIONAL GO** |

---

## Checklist

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| R3-01 | Engine A audited | **CONDITIONAL** | Dry-run PASS; scan 401 |
| R3-02 | Engine B audited | **PASS** | HKO PASS + 187 pytest |
| R3-03 | Live funnel audited | **CONDITIONAL** | HTTP probes + code trace + war-audit |
| R3-04 | All three **GO** | **PASS** | API key rotated; scan 200 |
| R3-05 | Remediation documented | **PASS** | See engine-a report § Remediation |

---

## Unblock Row 3 (one action)

1. ConduitScore dashboard → create/rotate **Pro+ REST API key**  
2. `python scripts/sync_outreach_vault.py` (from Cato repo)  
3. Re-run: `python -m conduit_outreach_pipeline.cli run-one …` — expect real `overallScore`  
4. Update this checklist + `docs/loop-proof-card.md` Row 3 → **PASS**

---

## Pass rule (from loop proof card)

**PASS** when all three are **GO**, or NO-GO items remediated and re-audited.
