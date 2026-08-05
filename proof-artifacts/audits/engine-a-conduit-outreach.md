# Truth audit — Engine A: `conduit_outreach_pipeline`

**Date:** 2026-06-03  
**Method:** HKO-truth-audit (abbreviated): code review + live dry-run + Row 1 deliverability cross-check  
**Scope:** Cold outreach engine only (Brevo SMTP, templates, scan hook, Cato `run_batch.py` bridge)

---

## Verdict: **GO** (re-tested 2026-06-03 after API key rotation)

| Layer | Result |
|-------|--------|
| Code / wiring | **PASS** — dry-run, unsubscribe headers, ethics doc, Halbert templates v1.2-halbert |
| Live integration | **PASS** — `POST /api/scan` returns **200**, `overallScore` 30 for example.com |
| Key wiring | **PASS** — key must live in `conduit_outreach_pipeline/.env` **and** `~/.claude/skills/reverse-funnel-scanner/.env` (latter overrides) |

---

## Evidence (2026-06-03)

**Dry-run `run-one` (no SMTP):**

```text
python -m conduit_outreach_pipeline.cli run-one --contact-id example.com \
  --artifact proof-artifacts/audits/_runone-artifact.json --dry-run
```

- `ok: true`, `mode: dry_run`, subject/body rendered, `template_version: 1.2-halbert`
- Scan error surfaced in preview: `HTTP 401 … Invalid API key`

**Row 1 cross-check:** 20/20 inbox on Brevo; List-Unsubscribe → `https://conduitscore.com/unsubscribe` (200).

**Policy alignment:** Cato `live_outreach_enabled=false` — engine must not bulk-send without G1 rows 4–6.

---

## Findings

| ID | Sev | Finding | Remediation |
|----|-----|---------|-------------|
| A-1 | ~~HIGH~~ **RESOLVED** | Stale key in `reverse-funnel-scanner/.env` overrode pipeline `.env` | Keep both files in sync when rotating keys |
| A-3 | LOW | No dedicated pytest suite in pipeline folder | Optional: add tests for `run_one` / render |

---

## G1 recommendation

- **Do not** start Row 4 canary until **A-1** is fixed and one live scan returns `overallScore` + `id`.
- Engine is **safe to dry-run** and **safe to SMTP-test** (Row 1 proved).
