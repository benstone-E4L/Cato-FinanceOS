# IMPLEMENTATION_PLAN — Cato/Genesis posting model (2026-08-22)

## High priority

- [x] Copy XERO_SCOPE_TO_AGENT_MAP.yaml to Cato + Genesis accounting/
- [x] cato/xero_scope.py + cato/posting_policy.py
- [x] Genesis accounting/xero_scope.py + tools/xero_scoped_tool.py
- [x] Inject scope params in Cato genesis.execute()
- [x] Doctor report includes scope_map_loaded
- [x] Update CROSS_AGENT_HANDOFF_CONTRACT.yaml (receipt fields)
- [x] tool_policy: RISK_NETWORK + xero_scoped_invoke for e4l specialists
- [x] agent_runtime augment tools_advertised
- [x] Unit tests Cato + Genesis

## Medium priority

- [ ] Wire XERO_MCP_BRIDGE_URL to demo MCP HTTP bridge (deploy config)
- [ ] Bundle system_prompt batch update (remove WRITE: denied) — runtime scope supersedes

## Completed

- [x] Ralph workspace scaffold
- [x] Amendment doc in docs/

## Discovered Issues

- Genesis on Render needs XERO_MCP_BRIDGE_URL env for live posts (dry_run until set)
