# Desktop App Implementation Plan

## Chunk 1: Critical Backend Bug Fixes (MAX 5 ITERATIONS)

### Task 1.1: CORS PUT Method Fix

* **File**: `cato/ui/server.py` lines 75 and 81
* **Change**: Add `PUT` to `Access-Control-Allow-Methods` in both locations
* **Before**: `"GET, POST, PATCH, DELETE, OPTIONS"`
* **After**: `"GET, POST, PUT, PATCH, DELETE, OPTIONS"`
* **Test**: Existing tests must still pass

### Task 1.2: Config Endpoint Security

* **File**: `cato/ui/server.py` — `get\_config` handler
* **Change**: Filter sensitive keys (containing `token`, `password`, `secret`, `key` in lowercase) before returning config dict
* **Test**: Add test that sensitive keys are filtered from `/api/config` response

### Task 1.3: Duplicate Route Cleanup

* **Files**: `cato/ui/server.py`, `cato/ui/websocket\_handler.py`
* **Change**: Remove duplicate `GET /api/config` and `PATCH /api/config` routes from `websocket\_handler.py`
* **Test**: Verify only one handler serves each route

### Task 1.4: CLI Login Detection Fix

* **File**: `cato/ui/server.py` — `get\_cli\_status` handler (\~line 396)
* **Change**: Rename or clarify `logged\_in` field — version check success ≠ logged in. Add `version\_check\_ok` field separate from `logged\_in`. Set `logged\_in` to `null` (unknown) when we can't determine auth state.
* **Test**: Existing cli\_status tests must pass

### Task 1.5: Version from Package

* **File**: `cato/ui/server.py` — `health` handler
* **Change**: Import version from `cato.\_\_init\_\_` or read from `pyproject.toml` instead of hardcoding `0.1.0`
* **Test**: `/health` returns correct version

### Task 1.6: Per-CLI Restart Endpoint

* **File**: `cato/ui/server.py`
* **Change**: Add `POST /api/cli/{name}/restart` that calls `cli\_process\_pool.restart(name)` or equivalent
* **Test**: Add test for the new endpoint

**HARD STOP after Chunk 1**: Run full test suite. If >5 iterations needed, escalate to Hudson.

\---

## Chunk 2: Chat System Fixes (MAX 5 ITERATIONS)

### Task 2.1: Send Button Working State

* **File**: `desktop/src/views/ChatView.tsx` lines 151-156
* **Change**: `{isStreaming ? "Working..." : "Send"}` and `disabled={!input.trim() || connectionStatus !== "connected" || isStreaming}`
* **Test**: `npm run build` passes

### Task 2.2: Chat Double Message Dedup

* **File**: `desktop/src/hooks/useChatStream.ts`
* **Change**: Instead of only deduplicating by `id`, also deduplicate by content hash (text + approximate timestamp within 2s window). When WS receives a response, store the text content. When history poll returns entries, skip any that match text+timestamp within the dedup window.
* **Test**: `npm run build` passes

### Task 2.3: Chat WS Cleanup Guard

* **File**: `desktop/src/hooks/useChatStream.ts`
* **Change**: Add `mountedRef` to track component mount state. Check `mountedRef.current` before `setConnectionStatus`, `setIsStreaming`, `addMessages` calls in WS event handlers.
* **Test**: `npm run build` passes

**HARD STOP after Chunk 2**: `npm run build` must pass.

\---

## Chunk 3: AuthKeys \& System View Fixes (MAX 5 ITERATIONS)

### Task 3.1: AuthKeysView Live Status

* **File**: `desktop/src/views/AuthKeysView.tsx`
* **Change**: Remove hardcoded `CLI\_BACKENDS`. Add `useEffect` to fetch `/api/cli/status`. Map response to display cards with live `installed`/`logged\_in` status.
* **Test**: `npm run build` passes

### Task 3.2: AuthKeysView Restart Buttons

* **File**: `desktop/src/views/AuthKeysView.tsx`
* **Change**: Add "Restart" button per CLI backend that calls `POST /api/cli/{name}/restart`
* **Test**: `npm run build` passes

### Task 3.3: SystemView Restart Buttons

* **File**: `desktop/src/views/SystemView.tsx`
* **Change**: Add "Restart" button per model card in CliPoolPanel
* **Test**: `npm run build` passes

### Task 3.4: Verify Consistency

* **Verification**: Both SystemView and AuthKeysView show same data from same endpoint

**HARD STOP after Chunk 3**: Full validation.

\---

## Chunk 4: Diagnostics View Expansion (MAX 5 ITERATIONS)

### Task 4.1-4.5: Add 5 New Diagnostic Tabs

* **Backend**: Create 5 new API endpoints in `server.py`
* **Frontend**: Add 5 new tabs in `desktop/src/views/DiagnosticsView.tsx`
* Each tab: fetch endpoint, display data in table/card format
* **Test**: All tests pass, `npm run build` passes

**HARD STOP after Chunk 4**: Full validation.

\---

## Chunk 5: Missing Module Integrations (MAX 5 ITERATIONS)

### Tasks 5.1-5.5: WhatsApp UI, Ledger verification, Delegation tokens, Confidence display, Early termination indicator

* **Backend**: New endpoints where needed
* **Frontend**: New components/panels
* **Test**: All tests pass, `npm run build` passes

**HARD STOP after Chunk 5**: Full validation.

\---

## Chunk 6: Advanced Features (MAX 5 ITERATIONS)

### Tasks 6.1-6.5: Intelligent heartbeat, Config hot reload, Hooks system, Plugin architecture, Search fallback

* **Backend**: New modules and enhanced existing ones
* **Frontend**: New views and panels
* **Test**: All tests pass, `npm run build` passes

**HARD STOP after Chunk 6**: Full validation + Kraken E2E test.

\---

## Completed

(Tasks move here when done)

