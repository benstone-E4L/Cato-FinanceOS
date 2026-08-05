## Cato on Linux — Setup Guide

This guide covers running the Cato daemon and desktop UI on a Linux machine.

---

### 1. Prerequisites

- **OS**: Recent Ubuntu/Debian, Fedora, Arch, or similar.
- **Python**: 3.11+ with `pip`.
- **Node.js**: 20+ (for building the Tauri/React desktop if you want it).
- **Rust toolchain** (optional, only for building the Tauri desktop):
  - `rustup`, latest stable toolchain.
  - `pkg-config` and native build deps for your distro (GTK/WebView2 equivalents).

Install base tools (Ubuntu/Debian example):

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip build-essential \
  curl git pkg-config libssl-dev

curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
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

This installs the `cato` CLI in your virtualenv.

---

### 3. Initial configuration

Run the init wizard once to set budget caps and create the vault:

```bash
source .venv/bin/activate
cato init
```

This will:

- Create `~/.cato/config.yaml` with your budget caps.
- Create an encrypted vault at `~/.cato/vault.enc`.
- Optionally enable Telegram/WhatsApp.

To update secrets later:

```bash
cato vault set OPENROUTER_API_KEY
cato vault set TELEGRAM_BOT_TOKEN
```

---

### 4. Running the daemon

Start the Cato daemon:

```bash
source .venv/bin/activate
cato start
```

- HTTP UI serves on `http://127.0.0.1:8080` by default.
- WebSocket runs on `ws://127.0.0.1:8081`.

Check health:

```bash
curl http://127.0.0.1:8080/health
```

Stop the daemon:

```bash
cato stop
```

---

### 5. Optional: Tauri desktop build (Linux)

If you want the full desktop app:

```bash
cd desktop
npm install
npm run tauri build
```

This produces a native desktop binary under `desktop/src-tauri/target/release/`.

---

### 6. Systemd service (example)

To run Cato as a background service, create a simple `systemd` unit:

```ini
[Unit]
Description=Cato AI Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/youruser/cato
ExecStart=/home/youruser/cato/.venv/bin/cato start
Restart=on-failure

[Install]
WantedBy=default.target
```

Save as `/etc/systemd/system/cato.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cato.service
```

