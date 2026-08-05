# Spec: Chunk 4 — Diagnostics View Expansion

## Acceptance Criteria
1. Five new tabs in DiagnosticsView: Disagreements, Epistemic, Context Budget, Retrieval, Habits
2. Five new API endpoints serve real data from existing backend modules
3. Each tab displays data in a readable format (tables/cards)

## Files to Modify
- `cato/ui/server.py` — 5 new API endpoints
- `desktop/src/views/DiagnosticsView.tsx` — 5 new tabs

## API Endpoints
- GET /api/diagnostics/disagreements → disagreement_surfacer.get_recent_disagreements()
- GET /api/diagnostics/epistemic → epistemic_monitor.get_gaps()
- GET /api/diagnostics/context-budget → context_builder slot allocation
- GET /api/diagnostics/retrieval → retrieval stats
- GET /api/diagnostics/habits → habit_extractor.get_soft_constraints()

## Test Scenarios
- All endpoints return 200 with JSON
- Frontend builds without errors
- All existing tests pass
