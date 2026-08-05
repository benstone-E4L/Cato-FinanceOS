# Changelog

All notable changes to `cato-daemon` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.2.0] — 2026-03-06

### Summary
Major feature release. Adds 20+ new subsystems across 6 phases of the
Cato roadmap (Phases A, B, H, I, J, and gap fixes). All 1271 tests pass.
Four independent Kraken audits: 94%, 91%, 90%, 98% confidence — all APPROVED.

### Added

#### Phase A — Token Reduction Infrastructure
- **HOT/COLD skill file split**: `<!-- COLD -->` delimiter in all skill `.md`
  files; context builder only loads HOT section (≤300 tokens) by default
- **Query tier classifier** (`cato/orchestrator/query_classifier.py`):
  routes queries to TIER_A (cheapest), TIER_B (mid), or TIER_C (fan-out all)
  based on keywords, token count, code blocks, file paths, and confidence
- **Memory distiller** (`cato/core/distiller.py`): compresses conversation
  history every 20 turns into 400-token SQLite chunks with semantic embeddings
- **SlotBudget** (`cato/core/context_builder.py`): explicit token allocation
  across 4 tiers (identity 2000, memory 4000, workspace 4000, overflow 2000)
- **HybridRetriever** (`cato/core/retrieval.py`): BM25 + cosine similarity
  hybrid search over MemorySystem chunks (0.4 BM25 + 0.6 semantic)
- **ContextGate** (`cato/core/context_gate.py`): admission control that
  enforces slot budgets before context is assembled

#### Phase B — Top 10 Skills
- **SchedulerDaemon** (`cato/core/schedule_manager.py`): YAML-based cron
  scheduler with per-schedule asyncio tasks, overlap prevention, hot-reload
- **SessionCheckpoint** (`cato/core/session_checkpoint.py`): token-aware
  context anchoring — checkpoints session state when usage > 80% of limit
- **MemorySystem** (`cato/core/memory.py`): hybrid BM25 + sentence-transformer
  long-term memory with ANN index (hnswlib) opt-in at 5000+ chunks
- **Mem0 Fact Store**: `store_fact`/`load_top_facts`/`apply_decay` on
  MemorySystem — persistent fact store with confidence decay
- **Knowledge Graph** (`cato/core/memory.py`): `kg_nodes`/`kg_edges` SQLite
  tables, entity extraction (files, @mentions, CamelCase, ALLCAPS), multi-hop
  traversal via recursive CTE
- **WebSearchTool** (`cato/tools/web_search.py`): query classifier (code /
  academic / news / general), multi-engine routing, result deduplication
- **GitHubTool** (`cato/tools/github_tool.py`): REST API wrapper for issues,
  PRs, file content, repo search — all read-only, no auth required for public
- **PythonExecutor** (`cato/tools/python_executor.py`): sandboxed subprocess
  execution with dangerous-pattern blocking, timeout, matplotlib capture
- **SkillImprovementCycle** (`cato/orchestrator/skill_improvement_cycle.py`):
  correction detection, structured ledger, versioned skill backups with SHA-256
- **ClawFlows** (`cato/orchestrator/clawflows.py`): declarative multi-step
  workflow engine with step chaining, variable substitution, retry logic
- **ContextPool** (`cato/core/context_pool.py`): pre-warmed context assembly
  for low-latency skill invocations

#### Phase H — Safety Foundation
- **ReversibilityRegistry** (`cato/audit/reversibility_registry.py`): singleton
  registry of tool reversibility scores (0.0 reversible → 1.0 irreversible),
  blast radius classification, custom tool registration
- **ActionGuard** (`cato/audit/action_guard.py`): pre-action gate that enforces
  confirmation rules based on reversibility × autonomy level thresholds
- **LedgerMiddleware** (`cato/audit/ledger.py`): hash-chained, Ed25519-signed
  tamper-evident record of every agent action; `verify_chain()` detects both
  `prev_hash` linkage breaks and field-level mutations (re-hash verification)
- **DelegationToken / TokenStore** (`cato/auth/token_store.py`): SQLite-backed
  scoped delegation tokens with spending ceilings, expiry, revocation
- **TokenChecker** (`cato/auth/token_checker.py`): pre-action scope check
  against active delegation tokens with wildcard category matching
- **AuditLog** (`cato/audit/audit_log.py`): SHA-256 hash-chained append-only
  audit log (migrated from `cato/audit.py` to `cato/audit/` package)

#### Phase I — Epistemic Layer
- **EpistemicMonitor** (`cato/orchestrator/epistemic_monitor.py`): premise
  extraction from agent reasoning, confidence tracking, gap detection,
  interrupt budget enforcement, unresolved gap persistence
- **DisagreementSurfacer** (`cato/orchestrator/disagreement_surfacer.py`):
  multi-model output comparison via Jaccard distance + confidence stdev,
  4-way disagreement classification, consensus/minority view identification
- **ContradictionDetector** (`cato/memory/contradiction_detector.py`):
  Jaccard-gated fact contradiction detection (TEMPORAL / SOURCE / PREFERENCE /
  FACTUAL), duplicate pair prevention, resolution tracking, health summary

#### Phase J — Memory & Temporal
- **DecisionMemory** (`cato/memory/decision_memory.py`): structured decision
  record with premises, confidence, ledger linkage, outcome quality scoring,
  overconfidence profile, reliable pattern extraction
- **OutcomeObserver** (`cato/memory/outcome_observer.py`): background asyncio
  task that polls open decisions and applies timeout outcomes; configurable
  per-action-type observation windows
- **HabitExtractor** (`cato/personalization/habit_extractor.py`): passive
  interaction observer that infers soft constraints from rejection/acceptance
  patterns; `get_soft_constraints()` for skill prompt injection
- **VolatilityMap** (`cato/context/volatility_map.py`): URL/resource type
  to volatility score mapping; domain override support
- **TemporalReconciler** (`cato/context/temporal_reconciler.py`): wake-up
  protocol that identifies stale dependencies and generates a structured
  `WakeupBriefing` on daemon restart
- **AnomalyDetector** (`cato/monitoring/anomaly_detector.py`): multi-domain
  weak-signal monitor with baseline tracking, cross-source anomaly detection,
  self-calibrating false-positive suppression, prediction record keeping

### Fixed
- **`verify_chain()` field re-hash** (Kraken 2A Issue 1): `verify_chain()` now
  re-computes each row's hash from all fields and compares against stored
  `record_hash`, detecting any field-level mutation (not just `prev_hash` breaks)
- **`OutcomeObserver` configurable windows** (Kraken 2B Issue 1): constructor
  now accepts optional `observation_windows: dict[str, float]` parameter;
  backward-compatible (defaults to module-level `_OBSERVATION_WINDOWS`)

### Tests
- Total: **1271 passed, 1 skipped, 0 failed**
- New test files: 30 (covering all new subsystems)
- New E2E smoke test: `tests/test_e2e_full_pipeline.py` (108 tests covering
  all Phase A–J integrations end-to-end with `tmp_path` isolation)

---

## [0.1.0] — 2026-02-15

### Added
- Initial release
- Core agent loop with asyncio WebSocket streaming
- Encrypted vault (AES-256-GCM) with `cato vault set/get`
- Hard spend caps ($1 session / $20 monthly)
- Telegram and WhatsApp adapters
- Patchright browser automation (Conduit)
- Multi-model coding agent (Claude + Codex + Gemini fan-out)
- Talk Page UI (`cato/ui/coding_agent.html`)
- Basic audit logging
- CLI process pool for warm model invocations
- 445 tests passing
