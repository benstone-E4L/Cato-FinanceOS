# AGENTS.md — cato-genesis-posting-model-ralph

## Build & Run

- Cato repo root: `C:\Users\Work\Desktop\vault\projects\My Github\Cato`
- Genesis repo: `C:\Users\Work\Desktop\vault\projects\My Github\Genesis Agents`

## Validation Commands

```bash
cd "C:/Users/Work/Desktop/vault/projects/My Github/Cato" && python -m pytest tests/test_xero_scope_posting_model.py tests/test_accounting_router.py -q && cd "../Genesis Agents" && python -m pytest tests/test_xero_scope_posting_model.py -q
```

## Codebase Patterns

- Scope map: `cato/accounting/XERO_SCOPE_TO_AGENT_MAP.yaml`
- Amendment: `docs/AMENDMENT_2026-08-22_POSTING_MODEL.md`

## Gotchas

- xero_scoped_invoke dry_runs without XERO_MCP_BRIDGE_URL
- fs-integrity cannot write bills per scope map
