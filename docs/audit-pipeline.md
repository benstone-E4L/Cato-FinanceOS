## Cato Audit Pipeline — Alex & Kraken

Every change to Cato must pass through the Alex (audit) and Kraken (verification) agents
before being pushed to `main`. This document explains how to run that pipeline locally.

---

### 1. When to run the pipeline

Run the full Alex → Kraken sequence whenever:

- You’re preparing a PR that touches:
  - Python code under `cato/` or `tests/`.
  - Desktop frontend code under `desktop/src/` or `cato/ui/`.
  - Configuration files (`pyproject.toml`, Tauri config, etc.).
- You are about to push to `main`.

---

### 2. Alex — Audit & Test Agent

Alex is responsible for:

- Reviewing all changed files.
- Running the complete `pytest` suite.
- Ensuring 100% tests passing.
- Producing `CATO_ALEX_AUDIT.md` with APPROVED/REJECTED status.

Typical invocation (from repo root):

```bash
pytest
# Review changes, then run Alex via your preferred agent tooling.
```

Check that:

- `pytest` exits with status 0.
- `CATO_ALEX_AUDIT.md` is updated and clearly marked `Status: APPROVED`.

---

### 3. Kraken — Verification & Reality Check

Kraken verifies Alex’s work:

- Reruns tests independently.
- Confirms Alex’s audit is authentic and complete.
- Applies any additional fixes it deems necessary.
- Writes `CATO_KRAKEN_VERDICT.md` with a final GO/NO‑GO verdict.

Before pushing:

1. Ensure `CATO_ALEX_AUDIT.md` exists and is APPROVED.
2. Run Kraken via your agent tooling.
3. Confirm `CATO_KRAKEN_VERDICT.md` exists and the verdict is **GO**.

---

### 4. Push gate

Only push to `main` when:

- All tests are green.
- `CATO_ALEX_AUDIT.md` is APPROVED.
- `CATO_KRAKEN_VERDICT.md` is GO.

If either report is missing or not approved:

- Fix the issues called out in the reports.
- Re‑run Alex, then Kraken.

---

### 5. Troubleshooting

- **Tests fail under Kraken but pass locally**:
  - Ensure both runs are using the same virtualenv and dependencies.
  - Check for non‑hermetic tests (reliance on local paths, network, etc.).
- **Audit files not updated**:
  - Confirm your agent tooling has write access to the repo.
  - Check for permission issues or conflicting editor sessions.

