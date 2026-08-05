## Cato on macOS — Setup Guide

This guide covers running the Cato daemon and using it from macOS.

---

### 1. Prerequisites

- **macOS**: 13+ recommended.
- **Homebrew** (recommended).
- **Python**: 3.11+.
- **Node.js**: 20+ (for building the Tauri/React desktop if desired).
- **Rust**: for Tauri desktop builds.

Install the basics with Homebrew:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.11 node rust
```

---

### 2. Clone and install Cato

```bash
git clone https://github.com/your-org/cato.git
cd cato

python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

---

### 3. Initial configuration

Run the interactive setup once:

```bash
source .venv/bin/activate
cato init
```

You’ll be prompted for:

- Monthly and per‑session budget caps.
- Vault master password (encrypts API keys in `~/Library/Application Support/cato/vault.enc`).
- Optional Telegram/WhatsApp channel enablement.

To configure OpenRouter and other keys later:

```bash
cato vault set OPENROUTER_API_KEY
cato vault set TELEGRAM_BOT_TOKEN
```

---

### 4. Run the daemon

From the repo root:

```bash
source .venv/bin/activate
cato start
```

- HTTP UI: `http://127.0.0.1:8080`
- WebSocket: `ws://127.0.0.1:8081`

Health check:

```bash
curl http://127.0.0.1:8080/health
```

Stop:

```bash
cato stop
```

---

### 5. Optional: macOS desktop app (Tauri)

To build the desktop:

```bash
cd desktop
npm install
npm run tauri build
```

The resulting `.app` bundle will be under `desktop/src-tauri/target/release/`.

Grant any required permissions (screen recording, microphone, etc.) the first time you run it.

---

### 6. Launch at login (daemon)

The simplest option is a LaunchAgent:

Create `~/Library/LaunchAgents/com.cato.daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.cato.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/youruser/cato/.venv/bin/cato</string>
    <string>start</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/youruser/cato</string>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

Then:

```bash
launchctl load ~/Library/LaunchAgents/com.cato.daemon.plist
```

