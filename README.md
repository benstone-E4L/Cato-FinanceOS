# Cato — The AI agent daemon you can audit in a coffee break

> **Migrating from OpenClaw, ClawdBot, or MoltBot?** → [Jump to migration guide](#migrate-from-openclaw-clawdbot-or-moltbot)

**A local-first Python agent daemon with explicit budget controls and inspectable source.**

> **Verification status:** exact-HEAD operator-workstation acceptance has proven
> the packaged desktop and adjacent daemon, Work Inbox, encrypted credential
> custody, safe FinanceOS fallback, and a live direct Anthropic round trip. No
> public deployment, signed release publication, or live FinanceOS write is
> claimed. Read
> [Known Limitations](docs/ops/LIMITATIONS.md) and
> [Verification](docs/ops/VERIFICATION.md) before relying on it for financial or
> security-sensitive work.

- **Web UI always on when daemon runs** — `cato start` binds HTTP and WebSocket on `webchat_port` (default 8080); Telegram and WhatsApp use outbound polling only
- **Budget controls** — configured caps are checked in the model and browser paths covered by tests; see the known limitations for paths not runtime-proven
- **Inspectable implementation** — source and tests are included; auditability still depends on reviewing the exact build and its dependencies
- **Migration command** — `cato migrate --from-openclaw` supports the documented workspace formats; dry-run first and verify the result
- **Conduit browser tooling** — includes Ed25519 identity and SHA-256 hash-chain mechanisms; unsigned proof bundles remain possible when the signing secret is absent

---

## Why Not OpenClaw, ClawdBot, or MoltBot?

This project offers a local-first design for operators evaluating alternatives to
OpenClaw-family agents. The comparison below describes design goals and must be
verified against the exact upstream versions you evaluate.

This repository does not audit or certify competing projects. Compare credential
storage, network behavior, dependency provenance, budget controls, and runtime
requirements against the exact upstream release and its primary documentation.

Cato includes an AES-256-GCM vault implementation and does not include a dedicated
telemetry client. A vault is not created automatically in every existing setup,
credentials may remain in environment files until migrated, and enabled model,
search, browser, marketplace, and messaging integrations can make outbound calls.

---

## Quick Start

### Install

```bash
git clone https://github.com/benstone-E4L/Cato-FinanceOS
cd Cato
pip install -e .
patchright install chromium   # one-time browser download (~130 MB)
```

### First run (~60 seconds)

```bash
cato init
```

The wizard asks for:
- Monthly and session budget caps (defaults: $20 / $1)
- A vault master password (used to encrypt all API keys with AES-256-GCM)
- Whether to enable Telegram, WhatsApp, or optional non-model integrations

### Start the daemon

```bash
cato start                        # Web UI on localhost:8080 + all enabled channels
cato start --channel webchat      # Web UI only (default)
cato start --channel telegram     # Web UI + Telegram adapter
cato start --channel all          # Web UI + Telegram + WhatsApp (if enabled in config)
```

That's it. No Docker. No PostgreSQL. No Redis. SQLite for memory, a single YAML for config, one encrypted file for secrets.

---

## Migrate from OpenClaw, ClawdBot, or MoltBot

Coming from **OpenClaw**, **ClawdBot**, or **MoltBot**? One command brings everything over:

```bash
# Preview what would be migrated (safe, no files written)
cato migrate --from-openclaw --dry-run

# Apply the migration
cato migrate --from-openclaw
```

This command:
1. Scans `~/.openclaw/agents/` for all agent workspaces (works for OpenClaw, ClawdBot, and MoltBot — all used the same directory structure)
2. Copies workspace files: `SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md`, `MEMORY.md`, `TOOLS.md`, `HEARTBEAT.md`, `CRONS.json`
3. Validates each `SKILL.md` — must have a `# Title` and `## Instructions` section
4. Validates each session `.jsonl` — every line must be valid JSON
5. Copies `sessions/*.jsonl` and `skills/*.md` per agent
6. Prints a summary: agents migrated, skills migrated, sessions migrated, files skipped

What is NOT copied from OpenClaw / ClawdBot / MoltBot:
- `config.json` — Cato uses YAML; re-run `cato init` to configure
- `node_modules/`, Node binaries — not applicable to Cato
- `.env` files — migrate API keys with the explicit `cato vault migrate-env` command and verify the vault. Cato will report the source file; only the owner may decide whether to retain, encrypt, move, or delete it. Automation must not alter it without explicit authorization.

After migration, run `cato doctor` to audit token budgets and `cato init` to configure API keys.

### Design comparison checklist

| Issue | OpenClaw / ClawdBot / MoltBot | Cato |
|-------|-------------------------------|------|
| API key storage | Verify selected release | AES-256-GCM vault available; migration must be verified |
| Telemetry | Verify against the selected upstream release | No dedicated telemetry client found; enabled integrations make outbound calls |
| Budget enforcement | Verify selected release | Configured caps in tested execution paths |
| Infrastructure | Verify selected release | Local SQLite/Python runtime for core Cato |
| Dependency provenance | Verify selected release | Review the lockfile and exact packaged build |
| Migration path | Verify selected release | `cato migrate --from-openclaw` with dry-run |

---

## Direct Anthropic Model Routing

Cato calls the Anthropic API directly. `cato/model_policy.py` is the single
source of truth for model selection; prompts and tool arguments cannot override
it. SwarmSync is not in the model-execution path.

### Optional SwarmSync integrations

```yaml
# config.yaml (Windows: %APPDATA%\cato; macOS/Linux: ~/.cato)
swarmsync_enabled: true
swarmsync_api_url: https://api.swarmsync.ai/v1/chat/completions
```

These settings are retained only for Genesis, the integration registry, and the
site-services bridge. Enabling them does not send Cato chat messages through
SwarmSync and does not change model selection.

---

## Conduit — Local Browser Automation

Conduit is Cato's built-in headless browser engine. Its behavior depends on local
configuration and installed browser dependencies; the repository has not yet
proven the full feature set in a published production artifact.

```yaml
# Already enabled by default in your config
conduit_enabled: true
```

### Implemented Conduit capabilities

#### 1. Cryptographic Agent Identity (Ed25519)
The implementation can generate an **Ed25519 keypair**, stored at
`{data_dir}/conduit_identity.key`, and associate browser records with that
identity. Attribution requires protected key custody and signed proof
configuration; an unsigned SHA-256 digest proves integrity, not origin.

#### 2. SHA-256 Hash-Chained Audit Log
Supported browser actions can be written to a **SHA-256 hash-chained audit log**
in SQLite. `cato audit --verify` checks chain continuity for the records it can
read; coverage and trusted-anchor custody must be verified for the active build.

```bash
cato audit --session <id>      # full action-by-action replay
cato audit --verify            # tamper detection across all sessions
cato receipt --session <id>    # signed fare receipt with line-item log
```

This makes changes detectable when the chain and its trusted anchor are both
preserved; it is not, by itself, an independent audit or non-repudiation proof.

#### 3. VOIX Protocol Support
Conduit includes normalization for **VOIX `<tool>` and `<context>` tags** in
extracted content. Treat this as a parser feature, not a security boundary.

#### 4. Budget-Enforced Browser Actions
Covered browser-action paths check the session budget before execution and raise
`BudgetExceededError` when the configured cap would be exceeded. See the test
and runtime limitations before treating that as universal coverage.

```json
{"error": "Conduit budget 100¢ would be exceeded", "budget_exceeded": true}
```

#### 5. Sensitive Input Redaction
The audit path redacts values whose keys match known sensitive patterns
(`api_key`, `token`, `password`, `secret`, `authorization`, `bearer`,
`credential`, etc.). Pattern matching is not proof that arbitrary secret values
cannot enter logs.

#### 6. Safety Gate Integration
Conduit includes a **reversibility safety gate** for the classified actions below:

| Action | Risk Tier | Requires Confirmation |
|--------|-----------|----------------------|
| `navigate`, `extract`, `screenshot` | READ | Never |
| `click`, `type` | REVERSIBLE_WRITE | Never |
| Form submissions that send data externally | HIGH_STAKES | Yes (strict mode) |

In daemon mode (no TTY), HIGH_STAKES actions fail safe — denied by default, logged with reason.

#### 7. Local Execution
Conduit browser actions run in the local Cato process. External websites and any configured integrations can still receive requests, and normal network/provider costs may apply outside Cato.

#### 8. Local Browser Runtime
Conduit uses **Patchright** and a locally installed Chromium runtime. It does not require a Selenium server, WebDriver binary, Docker browser container, or remote browser API. Cato model execution separately requires the Anthropic API.

### Using Conduit

Conduit exposes the same `browser` tool interface as before — nothing changes in how you write skills or prompts:

```markdown
# In any skill or agent prompt:
Use browser.navigate to go to https://example.com
Use browser.extract to get the page content
Use browser.click on the "Submit" button
Use browser.screenshot to capture the result
```

For supported paths, `cato receipt --session <id>` renders the records captured
for that session. Verify signing configuration before calling a receipt signed.

---

## Model Support

The Cato model-execution path uses pinned Anthropic model snapshots selected by
`cato/model_policy.py`. The policy owns model choice, bounded escalation, call
shape, and cost ceilings. `ANTHROPIC_API_KEY` is the only credential required by
this path and belongs in the encrypted vault.

---

## Built-in Skills

Cato ships with 6 ready-to-use skills in `cato/skills/`. They are loaded automatically by the agent loop and are fully compatible with OpenClaw / ClawdBot / MoltBot skill files (same SKILL.md format).

| Skill file | Capabilities | What it does |
|------------|-------------|--------------|
| `web_search.md` | browser.search, browser.navigate | DuckDuckGo search with source citations |
| `summarize_url.md` | browser.navigate, browser.snapshot | Fetch any URL and return a 3-5 sentence summary |
| `send_email.md` | browser.navigate, browser.click, browser.type | Draft and send email via Gmail web UI (confirms before sending) |
| `add_notion.md` | shell | Add pages to a Notion database via the REST API |
| `daily_digest.md` | browser.search, memory.search, file.read | Personalized news digest from tracked topics + open tasks |
| `coding_agent.md` | shell | Delegate tasks to Claude Code, Codex, or Gemini CLIs installed locally |

### Writing your own skill

A SKILL.md file requires exactly two structural elements (same format as OpenClaw / ClawdBot / MoltBot skills — they migrate directly):

```markdown
# My Skill Name
**Version:** 1.0.0
**Capabilities:** shell, browser.navigate

## Instructions
Tell the agent exactly what to do step by step.
Use numbered lists for sequential actions.
Reference tools by their canonical names: `shell`, `browser`, `file`, `memory`.
```

Drop the file into `~/.cato/agents/{your-agent}/skills/` and restart Cato. The context builder injects active skills into every turn.

---

## Architecture

Cato is intentionally flat. Every module does exactly one thing:

| File | Lines | Purpose |
|------|-------|---------|
| [`cato/vault.py`](cato/vault.py) | ~150 | AES-256-GCM credential store, Argon2id KDF |
| [`cato/budget.py`](cato/budget.py) | ~170 | Spend cap enforcement, call-level cost tracking |
| [`cato/config.py`](cato/config.py) | ~90 | YAML config with safe defaults, first-run detection |
| [`cato/core/context_builder.py`](cato/core/context_builder.py) | ~160 | 7,000-token context assembly with priority stack |
| [`cato/core/memory.py`](cato/core/memory.py) | ~210 | SQLite + BM25 + sentence-transformer hybrid memory |
| [`cato/cli.py`](cato/cli.py) | ~260 | `init`, `start`, `stop`, `migrate`, `doctor`, `status` |

No orchestration magic. No hidden event loops. Read it in a coffee break.

### ASCII Architecture Diagram

```
  User message
       |
       v
+------+--------+      +-----------+
| Telegram /    |      |  Gateway  |
| WhatsApp /    +----->|  (auth +  |
| WebChat       |      | delivery) |
+---------------+      +-----+-----+
                              |
                              v
                    +---------+--------+
                    |   ContextBuilder  |
                    | (7,000-tok budget)|
                    | SOUL + AGENTS +   |
                    | USER + MEMORY +   |
                    | skills + log      |
                    +---------+--------+
                              |
                              v
                    +---------+--------+
                    |    Agent Loop     |
                    | plan / tools /    |
                    | reflect / respond |
                    +----+---------+----+
                         |         |
              model call |         | allowlisted actions
                         v         v
              +----------+--+   +--+----------------+
              | Model Policy |   | Shell / Browser / |
              | cost + risk  |   | File / Integrations|
              +------+-------+   +----------+---------+
                     |                      |
                     v                      v
              +------+-------+       +------+-------+
              | Anthropic API |       | Memory +     |
              | direct only   |       | Budget Guard |
              +--------------+       +--------------+
```

---

## Known Limitations

- **Memory at scale**: The hybrid BM25+semantic search loads all chunks for each query.
  Works well up to ~5,000 memory chunks. For larger memory stores, an ANN index
  (faiss/hnswlib) will be added in v0.2.

---

## Contributing

Pull requests welcome. The bar is: does it fit in a coffee break?

### Principles
- Keep modules small and single-purpose (target < 250 lines each)
- No new required dependencies without strong justification
- No dedicated product telemetry; document every newly introduced outbound path
- Prefer the vault for credentials and document any transitional environment-file use

### Adding a new tool

1. Create `cato/tools/mytool.py` implementing the `BaseTool` interface from `cato/tools/base.py`
2. Register it in `cato/tools/__init__.py`
3. Add a row to the capabilities table in this README

### Adding a new adapter (messaging channel)

1. Create `cato/adapters/myadapter.py` subclassing `BaseAdapter`
2. Register it in `cato/adapters/__init__.py`
3. Add the enable flag to `CatoConfig` in `cato/config.py`

### Adding a built-in skill

1. Create a SKILL.md in `cato/skills/` with a `# Title` and `## Instructions` section
2. List the capabilities it requires in the frontmatter
3. Add a row to the Built-in Skills table in this README

---

## CLI Reference

```bash
cato init                              # first-run wizard
cato start                             # start daemon (WebChat)
cato start --channel telegram          # telegram only
cato start --channel all               # all channels
cato stop                              # graceful shutdown
cato status                            # running state + budget summary
cato doctor                            # audit token budget per workspace
cato migrate --from-openclaw           # migrate OpenClaw / ClawdBot / MoltBot agents
cato migrate --from-openclaw --dry-run # preview migration (no files written)
cato vault set KEY value               # store an API key in the encrypted vault
```

---

## Configuration

All config lives in the Cato data directory (Windows: `%APPDATA%\cato\config.yaml`, macOS/Linux: `~/.cato/config.yaml`):

```yaml
agent_name: cato
default_model: claude-sonnet-5  # legacy display/config field; policy owns execution
monthly_cap: 20.0
session_cap: 1.0
conduit_enabled: true
swarmsync_enabled: true
swarmsync_api_url: https://api.swarmsync.ai/v1/chat/completions
telegram_enabled: false
whatsapp_enabled: false
webchat_port: 8080
max_planning_turns: 2
context_budget_tokens: 7000
log_level: INFO
```

---

## Security Model

- **Vault**: AES-256-GCM, Argon2id (64 MiB, 3 iterations, 4 threads), nonce-per-encryption
- **Key storage**: Derived key lives in process memory only — never written to disk
- **Credentials**: `cato vault set` is the intended path; existing installations may still use plaintext environment files until migrated
- **Telemetry**: No dedicated telemetry client was found in the audited source; enabled integrations can contact their configured services
- **Canary key**: Synthetic `sk-cato-canary-*` key detects accidental credential leaks

Cato has no documented Cato-operated telemetry endpoint. Review configuration and
the exact dependency/build graph to determine every outbound connection.

---

## License

MIT. Do whatever you want. Attribution appreciated.

---

## Also known as: the OpenClaw alternative / ClawdBot replacement / MoltBot successor

If you found this repo searching for:
- **openclaw alternative** — you're in the right place
- **openclaw replacement** — `cato migrate --from-openclaw` provides a migration path; timing and completeness depend on the workspace
- **clawdbot alternative** — ClawdBot was an earlier name for OpenClaw; same migration command
- **moltbot alternative** — MoltBot was the original name; same directory structure, same SKILL.md format
- **openclaw security issues** — see the [Why Not OpenClaw](#why-not-openclaw-clawdbot-or-moltbot) section above
- **openclaw telemetry** — verify the behavior of the exact upstream release; Cato has no dedicated telemetry client in the audited source
- **credential storage** — Cato provides an encrypted vault, but operators must verify that their active installation has migrated secrets into it

---

*Cato model execution uses the direct Anthropic API under deterministic policy.*
