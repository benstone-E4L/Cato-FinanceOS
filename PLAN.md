# Cato Desktop App — Implementation Plan

## Approach: Tauri v2 + Vite/React frontend + Python sidecar

Wrap Cato's existing Python daemon and web UI into a native desktop app using Tauri v2. The Python daemon runs as a managed sidecar process, and the existing React components are extracted into a proper Vite build. Communication uses the existing WebSocket protocol — no backend changes needed.

---

## Phase 1: Project scaffolding

### 1.1 Create Tauri v2 + Vite + React project

- Create `desktop/` directory at repo root
- Initialize with `npm create tauri-app@latest` (React + TypeScript template)
- Directory structure:
  ```
  desktop/
  ├── src/              # React frontend (Vite)
  │   ├── App.tsx
  │   ├── main.tsx
  │   ├── components/   # Extracted from cato/ui/components/
  │   ├── hooks/        # Extracted from cato/ui/hooks/
  │   └── styles/       # Extracted from cato/ui/styles/
  ├── src-tauri/        # Rust backend (Tauri)
  │   ├── src/
  │   │   └── main.rs
  │   ├── Cargo.toml
  │   ├── tauri.conf.json
  │   └── icons/
  ├── package.json
  ├── tsconfig.json
  └── vite.config.ts
  ```

### 1.2 Configure Tauri

- `tauri.conf.json`: Set window title, default size (1200x800), min size (800x600)
- Enable features: `system-tray`, `global-shortcut`, `notification`, `shell` (for sidecar)
- Set app identifier: `ai.cato.desktop`

---

## Phase 2: Extract and adapt the React frontend

### 2.1 Extract components from inline HTML to proper modules

The existing components live as `.tsx` files in `cato/ui/components/` and `cato/ui/hooks/` but are inlined into `coding_agent.html` via Babel runtime transpilation. Extract them into the Vite project as proper ES module imports:

- `desktop/src/components/TalkPage.tsx` — conversation view
- `desktop/src/components/MessageBubble.tsx` — per-model message card
- `desktop/src/components/TaskInput.tsx` — input form
- `desktop/src/components/ConfidenceBadge.tsx` — confidence display
- `desktop/src/components/CodingAgentPage.tsx` — page root
- `desktop/src/hooks/useTalkPageStream.ts` — WebSocket + message handling
- `desktop/src/hooks/useLocalStorage.ts` — localStorage persistence
- `desktop/src/styles/talk-page.css` — shared styles

### 2.2 Adapt WebSocket connection

- Update `useTalkPageStream` to connect to `ws://127.0.0.1:{port}` where port comes from Tauri config or daemon discovery
- Add reconnection logic (the daemon may start after the window opens)
- Add connection state indicator in the UI header

### 2.3 Add chat view

The existing UI is focused on the "coding agent" multi-model comparison flow. Add a simpler **chat view** that maps to the gateway's general WebSocket protocol:

- Single-model chat interface (uses `default_model` from config)
- Message format: `{"type": "message", "text": "...", "session_id": "..."}`
- Response rendering with markdown support
- Session history sidebar

### 2.4 Add settings/onboarding view

- First-run wizard (mirrors `cato init`): vault password, budget caps, API keys
- Settings page: model selection, budget caps, channel toggles, Conduit on/off
- Invoke these via Tauri commands that shell out to `cato init` or directly modify `~/.cato/config.yaml`

---

## Phase 3: Python sidecar management

### 3.1 Bundle Python daemon

- Use PyInstaller to freeze `cato` into a single executable binary
- Configure as a Tauri sidecar in `tauri.conf.json`:
  ```json
  {
    "bundle": {
      "externalBin": ["binaries/cato"]
    }
  }
  ```
- Build scripts for each platform (macOS arm64/x64, Windows x64, Linux x64)

### 3.2 Lifecycle management in Rust

In `src-tauri/src/main.rs`:

- **On app launch**: Spawn `cato start --channel webchat` as a sidecar child process
- **Health polling**: Hit `GET /health` on `localhost:{webchat_port}` until the daemon is ready, then load the frontend
- **On app quit**: Send `cato stop` (graceful shutdown), wait up to 5s, then SIGKILL if needed
- **Crash recovery**: If the sidecar exits unexpectedly, show a "Daemon stopped — restart?" dialog

### 3.3 Vault unlock flow

- On startup, if vault exists but is locked, show a native password prompt
- Pass the password to the daemon via stdin or a temporary Unix socket (never CLI args — would be visible in `ps`)
- Clear the password from memory after unlock

---

## Phase 4: Native desktop features

### 4.1 System tray

- Tray icon with status indicator (green = running, yellow = busy, red = stopped)
- Tray menu:
  - "Open Cato" — focus/show window
  - "Budget: $X.XX / $20.00 remaining" — read-only status
  - "Start/Stop Daemon"
  - "Quit"
- Window close minimizes to tray (doesn't quit the app)

### 4.2 Global hotkey

- Register `Cmd+Shift+C` (macOS) / `Ctrl+Shift+C` (Windows/Linux) to toggle the chat window
- When invoked: if window hidden → show + focus + cursor in input; if visible → hide
- Make the hotkey configurable in settings

### 4.3 Notifications

- Use Tauri's notification API for:
  - Long-running task completion ("Your task finished — confidence: 92%")
  - Budget warnings ("80% of session budget used")
  - HIGH_STAKES action confirmation requests from Conduit
- Only fire when the window is not focused

### 4.4 Deep links (optional, stretch)

- Register `cato://` protocol handler
- Enable links like `cato://chat?text=summarize+this+page` from browser extensions

---

## Phase 5: Packaging and distribution

### 5.1 Build pipeline

- `desktop/scripts/build.sh`:
  1. `pyinstaller cato/cli.py --onefile --name cato` → produces frozen binary
  2. Copy binary to `desktop/src-tauri/binaries/cato-{target-triple}`
  3. `cd desktop && npm run tauri build` → produces installer

### 5.2 Platform-specific installers

- **macOS**: `.dmg` with drag-to-Applications (Tauri built-in)
- **Windows**: `.msi` installer (Tauri built-in via WiX)
- **Linux**: `.AppImage` + `.deb` (Tauri built-in)

### 5.3 Auto-updater

- Use Tauri's built-in updater plugin
- Check for updates on launch (configurable interval)
- Update both the Tauri shell and the Python sidecar binary

---

## File changes summary

| Action | Path | Description |
|--------|------|-------------|
| Create | `desktop/` | Tauri v2 + Vite + React project |
| Create | `desktop/src/components/*.tsx` | Extracted React components |
| Create | `desktop/src/hooks/*.ts` | Extracted React hooks |
| Create | `desktop/src/styles/` | Extracted CSS |
| Create | `desktop/src-tauri/src/main.rs` | Sidecar lifecycle, tray, hotkey |
| Create | `desktop/src-tauri/tauri.conf.json` | App config, sidecar, permissions |
| Create | `desktop/scripts/build.sh` | Build pipeline script |
| Create | `cato.spec` | PyInstaller spec for freezing daemon |
| No change | `cato/` | No backend changes needed |

---

## Implementation order

1. **Phase 1** — Scaffold the Tauri project, get a window showing "Hello World"
2. **Phase 3.2** — Get the sidecar launching `cato start` and confirm health check works
3. **Phase 2.1–2.2** — Extract React components, connect to live daemon WebSocket
4. **Phase 2.3** — Build the chat view
5. **Phase 4.1** — System tray
6. **Phase 4.2** — Global hotkey
7. **Phase 4.3** — Notifications
8. **Phase 2.4** — Settings/onboarding
9. **Phase 3.1** — PyInstaller bundling
10. **Phase 5** — Packaging and distribution

Phases 1–4 can be developed against a manually-started `cato start` daemon (no bundling needed during dev). Phase 5 is packaging only.
