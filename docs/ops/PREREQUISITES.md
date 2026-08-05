# Prerequisites

Everything required to run or verify Cato + Genesis on this machine.

Verified 2026-08-03 against Cato commit `8731f21`.

**No credential value appears in this document, and none ever should. Variables
are documented by name and purpose only.**

---

## 1. Machine

| Item | Value | How verified |
|---|---|---|
| OS | Windows 11 Pro, 10.0.26200 | environment |
| Hostname / domain prefix | `ACEMAGIC-WINDOW` | `icacls` output |
| Shell | PowerShell 5.1 primary; Git Bash available | environment |

Two Windows profiles matter, and **they are separate profiles, not junctions**:

| Profile | Role |
|---|---|
| `C:\Users\benst` | Production Windows home. Holds the live `.cato` runtime tree. |
| `C:\Users\Work` | This development tree. Holds the repos. |

Read `RUNBOOK.md` §0 Fact 2 before running anything. There is no `CATO_HOME`
variable; the launching account decides which state tree is used.

---

## 2. Python

| Item | Path | Version |
|---|---|---|
| System Python | `C:\Users\benst\AppData\Local\Programs\Python\Python312\python.exe` | 3.12.10 |
| **Cato venv — the only interpreter for Cato work** | `C:\Users\Work\Desktop\GitHub\Cato\.venv\Scripts\python.exe` | 3.12.10 (verified: `--version`) |

`pyproject.toml` declares `requires-python = ">=3.11"`.

**Use the venv interpreter for every Cato command in these documents.** The
system Python does not have Cato's dependencies installed.

Genesis has **no `.venv`** (verified: absent from `Genesis Agents\`). Genesis'
containment tests run under Cato's venv — verified, 48 passed in 0.39s. See
`VERIFICATION.md` §5.

### Runtime dependencies (from `pyproject.toml`)

`cryptography>=42`, `argon2-cffi>=23`, `pyyaml>=6`, `click>=8.1`, `tiktoken>=0.7`,
`rank-bm25>=0.2.2`, `sentence-transformers>=3`, `aiohttp>=3.10`,
`websockets>=13`, `croniter>=2`, `python-telegram-bot>=21`, `mcp>=1.22`,
`patchright>=1.49`, `rich>=13`, `numpy>=1.26`, `python-dotenv>=1`,
`uvicorn>=0.38`, `google-api-python-client>=2.100`, `google-auth>=2.20`,
`google-auth-oauthlib>=1`.

### Optional dependency groups

| Extra | Contents | When you need it |
|---|---|---|
| `dev` | `pytest>=8`, `pytest-asyncio>=0.23`, `pytest-cov>=4` | **Required to run the test suite.** |
| `pty` | `pywinpty>=2` (win32), `ptyprocess>=0.7` (posix) | Terminal-attached tooling. |
| `conduit` | `patchright>=1.49` | Conduit browser engine. |

Console script: `cato = "cato.cli:main"`. These documents use
`python.exe -m cato ...` throughout, which works whether or not the script
shim is on `PATH`.

---

## 3. Node

| Item | Path | Version |
|---|---|---|
| Node | `C:\nvm4w\nodejs\node.exe` | v20.19.0 |
| npm | | 10.8.2 |

Not required for the Python daemon or the test suite. Required only for the
desktop app / web UI build under `desktop\`, which was **not built or verified**
for this documentation.

---

## 4. External CLIs

Two external CLIs are referenced by `tests/pipeline/test_pipeline_components.py`
and are **not installed**:

| CLI | Expected location per the test | Present? |
|---|---|---|
| `codex` | anywhere on `PATH` | No |
| `cursor-agent` | `%LOCALAPPDATA%\cursor-agent\versions\` | No |

Their absence is a known, attributed cause of part of the test baseline. See
`VERIFICATION.md` §4. **You do not need to install them.**

---

## 5. Network

| Endpoint | Purpose | Status 2026-08-03 |
|---|---|---|
| `https://swarmsync-agents.onrender.com` | Genesis agent gateway | LIVE — `GET /health` returns 200 in 0.36s |
| `https://api.anthropic.com` | Model calls (direct, not proxied) | not independently probed |

Genesis runs on Render free tier: 30s proxy timeout; warm latency up to ~15s on
`/marketplace/search` and `/.well-known/agents.json` (measured: `agents.json`
200 in 13.44s). **Cold start has never been measured.**

---

## 6. Credentials — `Cato\.env`

Path: `C:\Users\Work\Desktop\GitHub\Cato\.env`
Gitignored: yes (verified, `.gitignore:11`).
Loaded by: `cato start`, from the **current working directory**. Start the daemon
from the repo root or none of these are visible to it.

14 keys, verified present by name:

| Variable | Purpose | Required? |
|---|---|---|
| `CATO_VAULT_PASSWORD` | Unlocks `vault.enc`. **See `RUNBOOK.md` §8 CRITICAL-3 — the live value is published in two git-tracked files and no vault exists.** | Required once a vault exists |
| `ANTHROPIC_API_KEY` | Model calls. Cato routes direct to Anthropic. | **Required** — no model work without it |
| `SWARMSYNC_API_KEY` | SwarmSync platform API. Removed from the model path; still used for platform calls. | Optional |
| `GENESIS_AGENTS_SWARMSYNC_API_KEY` | Genesis-side SwarmSync key. | Optional |
| `GMAIL_ADDRESS` | Gmail adapter identity. | Optional — Gmail adapter only |
| `GMAIL_CLIENT_ID` | Gmail OAuth client. | Optional — Gmail adapter only |
| `GMAIL_CLIENT_SECRET` | Gmail OAuth client secret. | Optional — Gmail adapter only |
| `GMAIL_REDIRECT_URI` | Gmail OAuth redirect. | Optional — Gmail adapter only |
| `GMAIL_REFRESH_TOKEN` | Gmail OAuth refresh token. | Optional — Gmail adapter only |
| `CATODESKTOP_BOT_TOKEN` | Telegram bot token. | Optional — `--channel telegram` only |
| `CATODESKTOP_BOT_USERNAME` | Telegram bot username. | Optional — `--channel telegram` only |
| `TELEGRAM_CHAT_ID` | Telegram destination chat. | Optional — `--channel telegram` only |
| `GITHUB_FOXFIREPOETS_TOKEN` | GitHub API token for the `cato github` commands. | Optional |
| `conduit_enabled` | Enables the Conduit browser engine (per-action billing). Also settable per-run with `cato start --browser conduit`. | Optional |

Adapter registration is best-effort: `cato start` logs a warning and continues if
the Telegram or Gmail adapter fails to register. A missing optional credential
degrades a channel; it does not stop the daemon.

---

## 7. Credentials — `Genesis Agents\.env`

Path: `C:\Users\Work\Desktop\GitHub\Genesis Agents\.env`

23 keys, verified present by name:

### Gateway auth
| Variable | Purpose | Required? |
|---|---|---|
| `AGENT_GATEWAY_SECRET` | Shared secret for agent→gateway auth. | Required |
| `GATEWAY_API_KEY` | API key for gateway callers. | Required |
| `GENESIS_GATEWAY_PRIVKEY_B64` | Base64 gateway signing private key. | Required |
| `GENESIS_GATEWAY_PUBKEY_B64` | Base64 gateway signing public key. | Required |
| `GENESIS_SESSION_VAULT_KEY` | Encrypts session vault contents. | Required |

### Model
| Variable | Purpose | Required? |
|---|---|---|
| `LLM_API_KEY` | Model provider key. | Required |
| `LLM_API_URL` | Model provider endpoint. | Required |
| `GENESIS_LLM_MODEL` | Model identifier. | Required |
| `GENESIS_ALLOW_OPENROUTER_FALLBACK` | Permits fallback to OpenRouter. | Optional |

### Storage
| Variable | Purpose | Required? |
|---|---|---|
| `DATABASE_URL` | Postgres connection string. | Required |
| `AWS_ACCESS_KEY_ID` | S3/R2 access key. | Required for artifact storage |
| `AWS_SECRET_ACCESS_KEY` | S3/R2 secret. | Required for artifact storage |
| `AWS_REGION` | S3 region. | Required for artifact storage |
| `R2_API_TOKEN` | Cloudflare R2 token. | Optional |
| `GENESIS_S3_BUCKET` | Artifact bucket name. | Required for artifact storage |
| `GENESIS_S3_ENDPOINT` | S3-compatible endpoint. | Required for artifact storage |

### Worker
| Variable | Purpose | Required? |
|---|---|---|
| `GENESIS_WORKER_ENABLED` | Master switch for the background worker. | Optional |
| `WORKER_CONCURRENCY` | Parallel jobs per worker. | Optional |
| `WORKER_HEARTBEAT_INTERVAL_S` | Heartbeat period, seconds. | Optional |
| `WORKER_POLL_INTERVAL_S` | Queue poll period, seconds. | Optional |
| `WORKER_STALE_CHECK_INTERVAL_S` | Stale-job sweep period, seconds. | Optional |

### Marketplace
| Variable | Purpose | Required? |
|---|---|---|
| `SWARMSYNC_PLATFORM_FEE_PCT` | Platform fee percentage. | Optional |
| `SWARMSYNC_ADMIN_EMAILS` | Admin allowlist. | Optional |

---

## 8. Variables referenced in code but NOT in either `.env`

These are read by the code and are currently unset. Each one changes behaviour by
its absence — read the "if absent" column before assuming a default is harmless.

| Variable | Read at | Purpose | If absent |
|---|---|---|---|
| `CATO_HOME` | **nowhere** | — | **Does not exist.** There is no way to override the state root. The launching Windows account decides it. See `RUNBOOK.md` §0 Fact 2. |
| `CATO_APPROVAL_POLICY` | `cato/core/approval_policy.py:611` | Overrides the approval policy file path. | Falls back to `docs/approval-policy.yaml`, then to the built-in policy. A missing or unparseable policy never widens the gate. |
| `CATO_APPROVAL_SIGNING_KEY` | `cato/core/outbound_approval.py:143-147` | Hex HMAC key for approval tickets. | Each process derives its own key. **Set this in both processes if the daemon and the API run separately against one `cato.db`,** or tickets minted by one will not verify in the other. |
| `CATO_PROOF_ARTIFACTS_DIR` | `cato/canary25/paths.py:12` | Overrides the proof-artifact output directory. | Falls back to the night-shift policy `paths` entry, then a default. |
| `GENESIS_DEPLOYMENT_PROFILE` | `escrow_guard.py:47` | Must equal `swarmsync-marketplace` for escrow to be permitted. | **Unset blocks escrow.** `escrow_permitted()` returns `False`. This is the intended safe state. |
| `CONDUIT_INVOICE_SECRET` | `conduit_verifier.py:83` | HMAC secret for signing proof bundles. | **Proof bundles are currently unsigned** — `conduit_verifier.py:668-674` falls back to a plain SHA-256 content hash and logs a warning. A content hash proves integrity, not origin. |
| `APPDATA` | `cato/platform.py:51` | Windows roaming app data root. | Falls back to `Path.home()/AppData/Roaming`. Always set on Windows in practice. |

---

## 9. Directory state, verified 2026-08-03

```
C:\Users\benst\.cato\                     EXISTS  (last write 2026-06-14)
    cato.db, conduit_identity.key (32 bytes), session_count.txt
    sessions\ (EMPTY), workspace\, browser_profile\
    NO skills\ subdirectory
    NO vault.enc

C:\Users\benst\AppData\Roaming\cato\      DOES NOT EXIST
C:\Users\Work\.cato\                      DOES NOT EXIST

C:\Users\Work\AppData\Roaming\cato\       EXISTS  (created 2026-08-01)
    cato.db, flow_runs.db, routing_log.sqlite3, daemon.token
    workspace\, businesses\, flows\, logs\, memory\, uploads\, browser_profile\
    NO config.yaml
    NO vault.enc

%APPDATA%\cato\config.yaml                DOES NOT EXIST for either account
vault.enc                                 DOES NOT EXIST anywhere
```

`C:\Users\benst\AppData\Roaming\cato` not existing is informative:
`get_data_dir()` calls `mkdir(parents=True, exist_ok=True)` on every import, so
**this build of Cato has never been imported under the `benst` account.** The
`benst\.cato\` tree is legacy — written by an older build, or by `Path.home()`
call sites only. Its `cato.db` has no `ledger_records` table.

---

## 10. Filesystem permissions — currently wrong

Three critical items are **open**. They are documented in full, with the exact
verification commands and the exact remediation commands, in `RUNBOOK.md` §8.
Summary:

1. `ACEMAGIC-WINDOW\CodexSandboxUsers` has `(OI)(CI)(RX)` on `C:\Users\Work\Desktop`,
   inherited onto both `.env` files. Members: `CodexSandboxOffline`, `CodexSandboxOnline`.
2. `ACEMAGIC-WINDOW\Work` has `(OI)(CI)(F)` on the entire `C:\Users\benst` profile,
   reaching `conduit_identity.key` and `cato.db`.
3. `CATO_VAULT_PASSWORD`'s live value is present verbatim in two git-tracked files
   (`CLAUDE.md`, `PROJECT_BLACKBOX_AUDIT.md`), and no `vault.enc` exists — so every
   credential is plaintext in `.env`, protected only by (1) and (2).

**Close all three before starting the daemon with real credentials.**
