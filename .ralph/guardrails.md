# RALPH LOOP GUARDRAILS
# Cato Integration Project

## HARD RULES
1. Tests MUST stay 100% passing after every iteration — check with: python -m pytest tests/ -x -q --tb=short
2. Never rename existing Python modules (breaks imports + tests)
3. Never modify existing working API routes — only ADD new ones
4. Never break existing desktop views — only ADD/MODIFY what's needed
5. Max 5 iterations per chunk before Hudson escalation
6. All file writes use dedicated Write/Edit tools — never bash echo/heredoc
7. All new TSX files follow React functional component pattern with named + default export
8. Never introduce hardcoded IP/port — use httpPort prop
9. All new server.py route handlers have try/except with logger.error + graceful fallback
10. Input validation on all new routes that take path params (regex allowlist on names)

## ITERATION PROTOCOL
- Each iteration: implement → run tests → check output → fix if needed
- If tests fail after 5 iterations: call Hudson agent, pass full error context
- Hudson fixes, returns control, continue to next chunk

## NAMING CONVENTIONS
- Views: PascalCase + "View" suffix (MemoryView, SystemView, etc.)
- Routes: lowercase hyphenated (/api/memory/stats, /api/cli/status)
- State variables: camelCase
- CSS classes: kebab-case matching existing patterns

## DO NOT TOUCH
- cato/orchestrator/clawflows.py (working, tests cover it)
- cato/audit/* (working, tested)
- cato/core/memory.py (working, tested)
- Any file in tests/ (unless adding new tests)
- pyproject.toml / Cargo.toml
- conftest.py
