# Spec: Chunk 6 — Advanced Feature Integrations

## Acceptance Criteria
1. Heartbeat includes CPU/memory/disk metrics via psutil
2. Config changes detected and applied without restart
3. Hook system with register_hook() for lifecycle events
4. Plugin discovery via entry_points
5. Search provider fallback chain (Brave → DuckDuckGo → Tavily)

## Files to Modify/Create
- `cato/heartbeat.py` — Add psutil metrics
- `cato/config.py` — Add file watcher for hot reload
- `cato/hooks.py` — New: lifecycle hook system
- `cato/plugins/__init__.py` — New: plugin discovery
- `cato/tools/web_search.py` — Add fallback chain
- `cato/ui/server.py` — New endpoints for hooks, plugins
- `desktop/src/views/SystemView.tsx` — Hooks panel
- `desktop/src/views/DashboardView.tsx` — Enhanced heartbeat display

## Test Scenarios
- Heartbeat response includes cpu_percent, memory_percent, disk_percent
- Config file change triggers reload callback
- register_hook("pre_message", callback) works
- Plugin entry points discovered
- Search falls back when primary fails
- All tests pass, frontend builds
