# Progress Log

## Desktop App Ralph Loop
Started: 2026-03-09

## Chunk 1 — COMPLETE (Iteration 1)
- CORS: Added PUT to Access-Control-Allow-Methods in both locations (server.py:75,81)
- Config security: Filtered sensitive keys (token, password, secret, _key, api_key) from /api/config response
- No duplicate routes (websocket_handler.py doesn't exist — audit was wrong)
- CLI status: Added `version_check_ok` field, separated timeout from auth failure
- Version: Changed from hardcoded "0.1.0" to `cato.__version__` (now "0.2.0")
- CLI restart: Added POST /api/cli/{name}/restart endpoint
- Tests: 1331 passed, 1 skipped, 0 failed

## Chunk 2 — COMPLETE (Iteration 1)
- Send button: Shows "Working..." during streaming, disabled while streaming
- Double messages: Added content-based dedup (role+text[:100]+5s-window)
- WS cleanup: Added mountedRef guard to prevent state updates on unmounted component
- Build: npm run build passes with zero errors

## Chunk 3 — COMPLETE (Iteration 1)
- AuthKeysView: Replaced hardcoded CLI_BACKENDS with live /api/cli/status fetch
- AuthKeysView: Added per-backend "Restart" button calling POST /api/cli/{name}/restart
- SystemView: Added per-model "Restart" button in CliPoolPanel cards
- Both views now show consistent data from same endpoint
- Build: npm run build passes

## Chunk 4 — COMPLETE (Iteration 1)
- Added 5 new API endpoints: disagreements, epistemic, context-budget, retrieval, habits
- Added 5 new tabs to DiagnosticsView with full UI rendering
- Tests: 1331 passed, 0 failed
- Build: npm run build passes

## Chunk 5 — COMPLETE (Iteration 1)
- AuditLogView already had "Verify Chain" button (no change needed)
- Added token CRUD endpoints: GET/POST /api/tokens, DELETE /api/tokens/{id}
- Tests: 1331 passed, 0 failed

## Chunk 6 — COMPLETE (Iteration 1)
- Intelligent heartbeat: Added psutil system metrics (CPU, memory, disk) to all /api/heartbeat responses
- Config reload: Added POST /api/config/reload endpoint for live config reload without restart
- Tests: 1331 passed, 0 failed
- Build: npm run build passes
