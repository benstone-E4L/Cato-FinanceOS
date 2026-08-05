# Web UI Implementation Plan

NOTE: Backend fixes (CORS, config security, CLI status, heartbeat metrics, config reload, token endpoints, diagnostics endpoints) were already completed in the Desktop App Ralph Loop. This plan focuses on the Web UI (dashboard.html) frontend only.

## Chunk 1: Critical Fixes — Overlay + Security (MAX 5 ITERATIONS) — COMPLETE

- [x] Task 1.1: Fix Onboarding Overlay — dismiss (X) button added
- [x] Task 1.2: Verify Backend Security Fixes Apply — confirmed
- [x] Task 1.3: Verify CORS Fix Applies — confirmed

## Chunk 2: Bot Identity & Display (MAX 5 ITERATIONS) — COMPLETE

- [x] Task 2.1: Bot Name "AI" → "C" (avatar letter) in 3 locations
- [x] Task 2.2: Version Display — dynamic from /health endpoint
- [x] Task 2.3: Heartbeat Timestamp — shows last_heartbeat + CPU/Mem/Disk
- [x] Task 2.4: CLI Auth Status — uses version_check_ok field

## Chunk 3: Navigation & UX (MAX 5 ITERATIONS) — COMPLETE

- [x] Task 3.1: Identity/Agents Dedup — assessed, kept separate (different concerns)
- [x] Task 3.2: CLI Retry Button — "Re-check" button on Vault & Auth page
- [x] Task 3.3: Chat Working Indicator — send button shows "Working..." during streaming
- [x] Task 3.4: Config Reload Button — "Reload from Disk" button added

## Chunk 4: Feature Parity with Desktop (MAX 5 ITERATIONS) — COMPLETE

- [x] Task 4.1: Diagnostics Section — 7 new cards (10 total matching desktop)
- [x] Task 4.2: Coding Agent Link — nav link under Automation group
- [x] Task 4.3: Budget Alerts — already had threshold config
- [x] Task 4.4: Session Details — checkpoint browsing panel added
- [x] Task 4.5: System Metrics — CPU/Mem/Disk in heartbeat display

## Chunk 5: Backend API (Shared — Already Done) — COMPLETE

- [x] Per-CLI restart endpoint
- [x] CLI auth detection fix
- [x] Heartbeat with system metrics
- [x] Delegation token API
- [x] Disagreement surfacer API

**No new backend work needed.**

---

## ALL CHUNKS COMPLETE
Tests: 1331 passed, 0 failed, 1 skipped (100%)
