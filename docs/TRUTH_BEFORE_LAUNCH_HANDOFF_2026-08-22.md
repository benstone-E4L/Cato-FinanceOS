# TRUTH-BEFORE-LAUNCH HANDOFF PROMPT (Claude Code)

Copy this entire prompt into a fresh Claude Code session after pulling latest `feat/e4l-genesis-orchestration-wiring` from https://github.com/benstone-E4L/Cato-FinanceOS and Genesis-Agents main.

---

## Mission

Run `/truth-before-launch` on the **Cato + Genesis posting model build** (2026-08-22), fix **every** HIGH, MEDIUM, and LOW finding, then **restart Demo Xero account seeding** (opening balances, Gate A bill post via `genesis-e4l-ap`).

## Pin target (fill before audit)

- **Product:** Cato-FinanceOS + Genesis E4L accounting specialists
- **Live URLs:** Cato ACA health endpoint; Genesis `https://swarmsync-agents.onrender.com`; Demo Xero MCP on Azure
- **Branch/SHA:** `feat/e4l-genesis-orchestration-wiring` @ latest push
- **Demo entity:** Xero Demo Company US (`demo`)

## What was built (verify live)

1. `cato/xero_scope.py` + `cato/posting_policy.py` — scope map + remediation policy
2. Cato `genesis.execute()` injects `allowed_xero_operations`, `scope_map_version`, `execution_realm`
3. `cato genesis doctor` requires `scope_map_loaded: true`
4. Genesis `xero_scoped_invoke` tool — VerifyAPI gate, scope check, MCP bridge or dry_run
5. Updated `CROSS_AGENT_HANDOFF_CONTRACT.yaml` — receipt fields (`xero_resource_id`, proof IDs)
6. Ralph workspace: `ralph/cato-genesis-posting-model-ralph/`

## Truth-before-launch (all 8 specialists in order)

Run each; capture live evidence; no hedging language.

1. source-of-truth-audit — pin live Cato, Genesis, demo MCP URLs + SHAs
2. canonical-route-and-product-surface-audit — `/health`, `/agents`, Cato `genesis doctor`
3. auth-billing-entitlement-audit — gateway API key, allowlist fail-closed
4. integration-reality-audit — `xero_scoped_invoke` with real `XERO_MCP_BRIDGE_URL` + VerifyAPI
5. production-parity-gate — deployed SHA matches git HEAD
6. deploy-custody-and-github-reconciliation — no unpushed commits
7. claims-copy-and-demo-truth-audit — handoff contract matches runtime behavior
8. end-to-end-money-path-proof — N/A unless live payment path tested; document N/A with reason

**Overall GREEN only if all non-N/A rows have live evidence.**

## Fix pass (mandatory after audit)

For each YELLOW/RED row:
- Implement fix in correct repo (Cato vs Genesis vs demo MCP server)
- Re-run affected pytest
- Re-run **all 8** truth-before-launch specialists (partial re-audit forbidden)

## Demo Xero seeding restart (after GREEN or documented YELLOW with blockers listed)

Read first:
- `E4L-Project-Control-Plane/Xero DEMO COMPANY/PREFLIGHT_FINDINGS_2026-08-21_O2O.md`
- `E4L-Project-Control-Plane/CURRENT/` truth pack
- `docs/AMENDMENT_2026-08-22_POSTING_MODEL.md` in Cato repo

Sequence:
1. Confirm Xero API quota reset (was exhausted 2026-08-21)
2. **T8 opening balances** — split path (not single manual journal); target TB $1,229,250
3. **S11 / Gate A** — one bill via `genesis-e4l-ap` after InvoiceProof + VerifyAPI (dry_run OK if bridge unset; live post if bridge configured)
4. Read-back + delete malformed draft journal if still present
5. Archive stock tracking options (6 stock options)
6. Emit proof bundle under `proof-artifacts/` with executor=`genesis-e4l-ap`, proof IDs, read-back hashes

## Validation commands

```bash
cd Cato && python -m pytest tests/test_xero_scope_posting_model.py tests/test_accounting_router.py -q
cd "../Genesis Agents" && python -m pytest tests/test_xero_scope_posting_model.py -q
cd Cato && python -m cato genesis doctor
```

## Do not

- Post to live production orgs without explicit gate
- Let Cato execute routine AP bills (executor must be `genesis-e4l-ap`)
- Skip VerifyAPI before writes
- Declare demo complete without read-back evidence

---

**End prompt**
