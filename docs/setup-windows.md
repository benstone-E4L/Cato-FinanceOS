## Cato on Windows — Setup Guide

This guide covers running the Cato daemon and desktop UI on Windows.

---

### 1. Prerequisites

- **OS**: Windows 10/11.
- **Python**: 3.11+ with `pip` (e.g. from [python.org](https://www.python.org/downloads/)).
- **Node.js**: 20+ (for building the Tauri/React desktop).
- **Rust toolchain** (optional, only for building the Tauri desktop): install via [rustup](https://rustup.rs/) with the MSVC target.
- **Visual Studio Build Tools** (for Tauri): MSVC and Windows SDK.

---

### 2. Clone and install Cato

From the repo root (e.g. `C:\Users\...\Cato`):

```powershell
cd C:\Users\Administrator\Desktop\Cato
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -e .
```

This installs the `cato` CLI in your virtualenv.

---

### 3. Optional: Interactive CLI (PTY) support

The **Interactive CLIs** view in the desktop app (Claude / Codex / Gemini in a terminal) requires a PTY backend. On Windows, install the optional dependency:

```powershell
pip install -e ".[pty]"
```

This installs `pywinpty`. Without it, the Interactive CLIs view still loads, but **Start Session** will return a 503 with a message to install the PTY dependency.

On Linux/macOS, the same optional group installs `ptyprocess` instead:

```bash
pip install -e ".[pty]"
```

---

### 4. Initial configuration

Run the init wizard once:

```powershell
.\.venv\Scripts\Activate.ps1
cato init
```

This creates `%APPDATA%\cato\config.yaml` and the encrypted vault. Set secrets:

```powershell
cato vault set OPENROUTER_API_KEY
cato vault set TELEGRAM_BOT_TOKEN
```

---

### 5. Running the daemon

Start the daemon (with vault password if you set one):

```powershell
.\.venv\Scripts\Activate.ps1
$env:CATO_VAULT_PASSWORD = "your_password"
cato start
```

Or use the service runner script:

```powershell
$env:CATO_VAULT_PASSWORD = "your_password"
python cato_svc_runner.py
```

- HTTP and WebSocket (gateway) default to port 8080.
- Health check: `curl http://localhost:8080/health`

---

### 6. Optional: Tauri desktop build (Windows)

To build and run the desktop app:

```powershell
cd desktop
npm install
npm run tauri build
```

The executable is at `desktop\src-tauri\target\release\cato-desktop.exe`. You can create a shortcut to it.

To use **Interactive CLIs** in the desktop app: open the sidebar, choose **Interactive CLIs**, pick a tab (Claude / Codex / Gemini), click **Start Session**, and use the terminal. If the PTY backend is not installed, the view loads but Start Session returns 503 with instructions to run `pip install -e ".[pty]"`.
