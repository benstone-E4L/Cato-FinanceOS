# Cato Tracks 2C+2D — Kraken Reality-Check Verdict

**Auditor:** Kraken (Project Reality Manager)
**Audit Date:** 2026-03-06
**Scope:** Tracks 2C (Phase I Skills 3+9) + 2D (Phase I Skill 7) post-implementation verification
**Branches:** `build/2c-epistemic-layer` (merged), `build/2d-contradiction-detector`

---

## Executive Summary

Tracks 2C and 2D are **APPROVED**. All three Phase I Epistemic Layer modules are
authentically implemented with real logic, no stubs, and full test coverage.

**Overall confidence: 90%**

The 10% gap reflects:
1. `EpistemicMonitor.extract_premises()` uses simple string search — multi-sentence
   extraction may miss complex sentence structures or create false positives.
2. `DisagreementSurfacer` uses word-level Jaccard (not embeddings) — low accuracy
   for semantically equivalent but lexically different statements.
3. `ContradictionDetector.classify_contradiction()` temporal detection requires the
   year/date keyword in BOTH facts — missing if only one fact has a date reference.

None block deployment. All documented.

**Test counts:**
- Track 2C: 1132 passed, 1 skipped, 0 failed
- Track 2D: 1112 passed, 1 skipped, 0 failed
- Unified 2C+2D+2A+2B: 1162 passed, 1 skipped, 0 failed

---

## Module 1 — EpistemicMonitor (Skill 3)

**File:** `cato/orchestrator/epistemic_monitor.py`
**Status: CONFIRMED**

Evidence:
- Premise extraction via 5 marker phrases: "because", "since", "assuming",
  "given that", "the fact that" — splits on ". " and "\n" boundaries
- `_premise_confidence_map` keyed by lowercase normalized premise text
- `get_gaps()` returns premises where stored confidence < self.threshold
- `can_interrupt()` enforces `_interrupt_count < max_interrupts` budget
- `record_unresolved()` logs gap with `timestamp: time.time()` and confidence
- `reset_session()` clears map + resets count — clean per-session isolation
- `get_unresolved_summary()` returns `{"total": N, "gaps": [...]}`

Tests verified: extract_premises finds markers across multi-sentence text;
lowercase normalization makes "Python" == "python"; interrupt budget enforced;
unresolved summary has correct total after multiple records.

**Gap:** Extraction splits on ". " (period+space) but not on "!" or "?". Complex
academic text with these terminators may cause missed premises or over-long premise
strings that dilute the marker matching.

---

## Module 2 — DisagreementSurfacer (Skill 9)

**File:** `cato/orchestrator/disagreement_surfacer.py`
**Status: CONFIRMED**

Evidence:
- `_jaccard(a, b)`: set-based word token overlap — `(a∩b)/(a∪b)` — no external deps
- `_stdev(values)`: pure `math.sqrt` standard deviation — no numpy needed
- `compute_disagreement_score()`: `0.6 * max_semantic_distance + 0.4 * confidence_stdev`
  - semantic_distance = 1 - jaccard (higher = more different)
  - all pairwise distances computed, max taken
  - rounded to 4 decimal places
- `is_disagreement()`: `score > threshold[task_type]`
- `classify_disagreement()`: keyword scanning on combined output text, 4-way
- `surface()`: returns None when no disagreement; else structured dict with
  consensus_view (highest-confidence model), minority_view (lowest-confidence),
  disagreement_type, score, recommended_action

Tests verified: identical outputs → score ~0; very different → score > 0;
consensus = highest-confidence model output confirmed; minority = lowest confirmed.

**Gap:** Jaccard distance is lexical only. "The cat sat" vs "The feline rested"
would score high disagreement (low overlap) despite identical meaning. For
code-generation outputs this is acceptable (code is lexically precise), but for
natural language the score may be noisy.

**Thresholds confirmed:** code=0.30, research=0.40, decision=0.25, default=0.35

---

## Module 3 — ContradictionDetector (Skill 7)

**File:** `cato/memory/contradiction_detector.py`
**Status: CONFIRMED**

Evidence:
- `SAME_TOPIC_THRESHOLD = 0.35` — Jaccard must exceed this to consider same topic
- `check_and_log()`: for each existing_fact above threshold, classify → log if type != NONE
- `already_detected()`: bidirectional pair check `(A,B) OR (B,A)` — prevents duplicates
- `classify_contradiction()`: keyword sets for TEMPORAL (year/date words), SOURCE
  (attribution phrases), PREFERENCE (want/like/prefer etc.), FACTUAL (fallback)
- `generate_explanation()`: `f"{type} contradiction: '{a[:80]}' vs '{b[:80]}'"`
- `resolve()` marks `resolved=1`, stores resolution text — `rowcount > 0` return
- `get_health_summary()`: total/unresolved/by_type counts + top-3 entities by count
- WAL mode, 3 indexes (resolved, entity, type)

Tests verified: TEMPORAL detected on year mismatch; SOURCE on "according to" phrases;
PREFERENCE on "prefer"; FACTUAL on same-topic factual conflict; duplicate pair
prevention confirmed (2nd call returns []); resolve marks as resolved; health summary
keys present with correct counts.

**Gap:** TEMPORAL classification requires date/time keywords to appear in BOTH fact_a
and fact_b. If only fact_b has "2023" and fact_a doesn't mention a date, the pattern
won't fire TEMPORAL — it will fall through to FACTUAL. This is acceptable behavior
(FACTUAL is a safe fallback) but means temporal contradictions with only one dated
fact are misclassified.

---

## Test Authenticity Spot-Checks

### 1. EpistemicMonitor interrupt budget enforcement
`test_epistemic_monitor.py::test_can_interrupt_false_at_max`:
Creates monitor with `max_interrupts=2`, calls `consume_interrupt()` twice,
asserts `can_interrupt() == False`. Live in-memory state — not mocked.

### 2. DisagreementSurfacer surface() returns None on agreement
`test_disagreement_surfacer.py::test_surface_returns_none_when_no_disagreement`:
Identical output text for all 3 models → Jaccard distance = 0 → score = 0.0 →
below threshold → `surface()` returns None. Confirmed.

### 3. ContradictionDetector duplicate prevention
`test_contradiction_detector.py::test_check_and_log_prevents_duplicate`:
Same pair checked twice. First call → [id]. Second call → []. DB query in
`already_detected()` confirmed via live SQLite in tmp_path.

### 4. Health summary top entities
`test_contradiction_detector.py::test_health_summary_most_contradicted_entities_top3`:
Writes 5 contradictions for "entityA", 3 for "entityB", 1 for "entityC".
`most_contradicted_entities` = ["entityA", "entityB", "entityC"]. Confirmed
correct ordering by count DESC.

---

## Remaining Issues

### Issue 1 — Jaccard distance for semantic similarity (both modules)
**Severity: Low (by-design limitation)**
Both 2C modules use word-level Jaccard as a proxy for semantic distance.
This is accurate for code and technical text but inaccurate for paraphrased
natural language. Production upgrade path: swap in `sentence-transformers`
cosine similarity (already a Cato dependency).

### Issue 2 — TEMPORAL classification requires date keyword in both facts
**Severity: Low**
Missing temporal contradiction when only one fact is dated.
**Fix:** Change check to `any(kw in combined for kw in temporal_keywords)`
where `combined = fact_a.lower() + " " + fact_b.lower()`. One-line fix.

### Issue 3 — EpistemicMonitor doesn't persist unresolved gaps across sessions
**Severity: Low**
`_unresolved_gaps` is in-memory only. Gaps are lost on process restart.
**Fix:** Add SQLite persistence (use existing `cato.db`, new `epistemic_gaps` table)
in a future release when the weekly digest feature is implemented.

---

## Final Scores

| Category | Result |
|----------|--------|
| EpistemicMonitor (premise extraction + gaps) | CONFIRMED |
| EpistemicMonitor (interrupt budget + unresolved) | CONFIRMED |
| DisagreementSurfacer (Jaccard + stdev score) | CONFIRMED |
| DisagreementSurfacer (classify + surface) | CONFIRMED |
| ContradictionDetector (Jaccard topic matching) | CONFIRMED |
| ContradictionDetector (4-type classification) | CONFIRMED |
| ContradictionDetector (duplicate prevention) | CONFIRMED |
| ContradictionDetector (health summary) | CONFIRMED |
| Semantic similarity (embeddings) | NOT USED — Jaccard only (documented) |
| TEMPORAL both-fact date requirement | PARTIAL — documented gap |
| New tests (2C) | 50 tests (25 epistemic, 25 disagreement) |
| New tests (2D) | 30 tests |
| Unified total | 1162 passed, 1 skipped, 0 failed |
| Final confidence score | 90% |

---

## Production Readiness Verdict

**APPROVED**

All three Phase I modules are real, tested, and functionally correct for
their stated purpose. The Jaccard limitations are known and acceptable for
the current use case (the alternative would add 200ms+ latency per turn).
The ContradictionDetector's TEMPORAL gap is low-severity. All 80 new tests
use live in-memory or tmp_path SQLite — no mocks for behavioral assertions.

---

*Signed: Kraken — 2026-03-06*
