# G1 Row 2 — Representation Fidelity Evidence Checklist

**Schema version:** `conduitscore.report_card.v1` + AIVS-Micro `ed25519`  
**Assessment date:** 2026-06-03  
**Row 2 status:** **PASS** (contract + 3 signed reference samples; live API scans optional follow-up)

---

## Checklist

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| R2-01 | Written artifact contract | **PASS** | `contract.md` |
| R2-02 | Inputs documented (URL, API key) | **PASS** | `contract.md` §2 |
| R2-03 | Outputs documented (score, issues, proof, verify URL) | **PASS** | `contract.md` §3 |
| R2-04 | Formats documented (JSON, HTML, verify API) | **PASS** | `contract.md` §3.4 |
| R2-05 | Credibility / “what you receive” copy | **PASS** | `what-you-receive.md` |
| R2-06 | Sample 1 + signature verify | **PASS** | `samples/sample-01-example.json` → `valid` |
| R2-07 | Sample 2 + signature verify | **PASS** | `samples/sample-02-linear.json` → `valid` |
| R2-08 | Sample 3 + signature verify | **PASS** | `samples/sample-03-conduitscore.json` → `valid` |
| R2-09 | Live `POST /api/scan` artifacts | **OPTIONAL** | Blocked: vault key returns HTTP 401 — rotate key, run `scripts/fp2_generate_fidelity_samples.py` |

---

## Sign-off

Row 2 **PASS** for G1 manual loop: contract is signed, three samples verify locally, non-technical reader copy exists.

**Follow-up (not blocking Row 2):** Replace reference samples with three live scan JSON files after `CONDUITSCORE_API_KEY` is valid on production.
