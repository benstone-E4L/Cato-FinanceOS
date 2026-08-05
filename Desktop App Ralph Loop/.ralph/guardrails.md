# Guardrails - Lessons Learned

### Sign: Always run tests before declaring done
- **Trigger**: Completing any code change
- **Instruction**: Run `pytest tests/ -x --tb=short` AND `cd desktop && npm run build` before marking a chunk complete
- **Source**: Project CLAUDE.md Law 1 — 100% test pass rate, no exceptions

### Sign: CORS middleware has TWO locations
- **Trigger**: Editing CORS headers in server.py
- **Instruction**: The CORS `Access-Control-Allow-Methods` header is set in TWO places: the OPTIONS handler (line 75) AND the response middleware (line 81). Update BOTH.
- **Source**: Desktop App Audit — Identity save failure

### Sign: Don't break existing tests
- **Trigger**: Modifying any Python module in `cato/`
- **Instruction**: Read existing tests first. Many tests mock specific function signatures. Changing signatures breaks tests.
- **Source**: Project has 1285+ tests that must stay 100% passing

### Sign: Desktop app uses HTTP port, not WS port for API calls
- **Trigger**: Adding new API endpoints
- **Instruction**: Desktop app uses `http://127.0.0.1:${httpPort}` (port 8080) for REST API calls. WebSocket chat uses port 8081. Coding agent WS uses port 8080.
- **Source**: Memory file — App.tsx passes httpPort for wsBase

### Sign: Check for sensitive data in API responses
- **Trigger**: Creating or modifying API endpoints that return config/settings
- **Instruction**: Filter out sensitive keys (tokens, passwords, secrets) before returning config data
- **Source**: Web UI audit — /api/config leaks telegram_bot_token

### Sign: Use PATCH not PUT for workspace files to avoid CORS issues
- **Trigger**: Creating file save endpoints
- **Instruction**: Until CORS is fixed, prefer PATCH method. After fix, PUT will work too.
- **Source**: Identity save failure root cause
