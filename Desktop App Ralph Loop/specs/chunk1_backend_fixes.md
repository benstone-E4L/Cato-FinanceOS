# Spec: Chunk 1 — Critical Backend Bug Fixes

## Acceptance Criteria
1. CORS middleware allows PUT method (Identity save works)
2. `/api/config` does NOT return sensitive keys (tokens, passwords)
3. No duplicate route registrations between server.py and websocket_handler.py
4. CLI status endpoint separates `installed` from `logged_in` correctly
5. `/health` returns version from package, not hardcoded
6. `POST /api/cli/{name}/restart` endpoint exists and works

## Files to Modify
- `cato/ui/server.py` — CORS, config filtering, CLI status, health version, restart endpoint
- `cato/ui/websocket_handler.py` — Remove duplicate routes (if they exist)

## Test Scenarios
- PUT request through CORS succeeds
- GET /api/config response has no `token`, `password`, or `secret` values
- GET /health version matches pyproject.toml
- POST /api/cli/codex/restart returns success
- All existing 1285+ tests still pass
