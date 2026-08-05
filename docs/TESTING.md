## Cato Testing & Manual Verification

This document describes high‑value regression checks for Cato, combining
existing automated tests with a small set of manual scenarios.

---

### 1. Python test suite

From the repo root:

```bash
pytest
```

This runs:

- Unit and integration tests under `cato/`.
- Orchestrator tests, watchdog tests, API tests.

All tests must pass (0 failures) before a change is considered shippable.

---

### 2. Desktop CLI pool / restart sanity check

Goal: ensure that the desktop **System** and **Auth & Keys** views correctly
reflect CLI backend status, and that Restart actually restarts the underlying
process.

Steps:

1. Start Cato daemon: `cato start`.
2. Open the desktop app and go to **System → CLI Process Pool**.
3. Click **Refresh** and confirm:
   - Claude shows `warm` if installed and logged in.
   - Other CLIs show `cold` or `unavailable` depending on install state.
4. In a separate terminal, kill the Claude CLI daemon process if running.
5. Back in the desktop app, click **Restart** for Claude in:
   - **System → CLI Process Pool**
   - or **Auth & Keys → Coding Agent Backends**
6. After a few seconds, press **Refresh** and confirm:
   - Claude returns to `warm` with a valid `--version` string.

---

### 3. Watchdog restart and reconnect

Goal: confirm `scripts/watchdog.py` and the scheduled task correctly restart
the daemon when it goes down, and that the desktop reconnects.

Steps:

1. Ensure the **Cato Watchdog** scheduled task is installed (see
   `scripts/install_watchdog.ps1`).
2. Start the daemon (`cato start`) and open the desktop app; verify it shows
   **Connected**.
3. In a terminal, kill the daemon process (e.g. `cato stop` or kill the PID).
4. Wait 30–60 seconds:
   - The watchdog should log a restart in `watchdog.log`.
   - The daemon should come back on port 8080.
5. Confirm:
   - `curl http://127.0.0.1:8080/health` returns status `ok`.
   - The desktop moves from “Connecting…” back to “Connected” without manual
     intervention.

---

### 4. Telegram UX and tool calls

Goal: ensure Telegram users only see natural‑language responses, not internal
tool call blocks or cost footers, and that long‑running tasks fail gracefully.

Steps:

1. Start the daemon and verify the Telegram adapter is running.
2. From Telegram, send a message that triggers tool usage (e.g. a coding task
   that runs `npm install` or `ls`).
3. Confirm in Telegram:
   - You only see the natural response text.
   - You **never** see `<minimax:tool_call>` blocks or `[$0.0000 this call…]`
     cost footers.
4. Trigger a task likely to run long or hang (e.g. instruct Cato to run a
   long shell command).
5. Confirm:
   - After ~3 minutes, Cato responds with a polite timeout message instead of
     hanging indefinitely.

---

### 5. Basic desktop chat / WebSocket health

Goal: verify that the desktop chat connects and streams messages via the
gateway WebSocket.

Steps:

1. Start the daemon (`cato start`).
2. Open the desktop app → **Chat**.
3. Confirm the header shows **Connected** and the input is enabled.
4. Send a short message.
5. Confirm:
   - Your message appears on the left as “You”.
   - Cato replies in the chat with a typing indicator while it is working.

---

### 5. Clean-machine install test (packaged desktop app)

Goal: verify the packaged desktop app (e.g. `cato-desktop.exe` plus bundled sidecar) runs on a machine that does not have the Cato repo or development environment.

Steps:

1. On a clean machine (or clean user profile / VM), copy only the built artifacts:
   - `desktop/src-tauri/target/release/cato-desktop.exe`
   - Any sidecar binaries or resources that Tauri bundles next to the exe (see `desktop/scripts/validate_frozen_bundle.py` and Tauri `externalBin` output).
2. Ensure no existing `%APPDATA%\cato` (or `~/.cato`) from a previous install, or use a fresh profile.
3. Run `cato-desktop.exe` (double-click or from a terminal). The app may start the bundled daemon sidecar.
4. Verify:
   - The desktop window opens.
   - After “Starting…” the UI shows **Connected** (or the daemon health is reported).
   - `curl http://127.0.0.1:8080/health` (or the port shown in the app) returns `{"status":"ok",...}`.
5. Optionally run `desktop/scripts/validate_frozen_bundle.py --skip-build` from a machine that has the repo to validate the same frozen bundle in isolation.

---

### 6. Sidecar stdout/stderr stress (no hang)

Goal: confirm the desktop wrapper drains the daemon’s stdout/stderr so a noisy daemon does not block the wrapper.

Steps:

1. Start the daemon with verbose logging (e.g. `log_level: DEBUG` in config or `CATO_LOG_LEVEL=DEBUG`).
2. Open the desktop app and use Chat or other features so the daemon produces log output.
3. Let it run for 1–2 minutes; the desktop should remain responsive and not hang. If the sidecar did not drain pipes, the wrapper could block on full pipes.

