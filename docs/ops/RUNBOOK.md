# Cato + Genesis Operations Runbook

Audience: one solo operator. There is no team, no on-call rotation, no monitoring
stack. Everything here is something you do yourself at a terminal.

Written against Cato at commit `8731f21`. Verified on Windows 11 Pro
(ACEMAGIC-WINDOW), 2026-08-03.

> ### Concurrency notice — read before trusting a line number
>
> A failure-mode audit was running in this repository while these documents were
> written. At the time of writing, the working tree had **uncommitted
> modifications** to `cato/agent_loop.py`, `cato/anthropic_client.py`,
> `cato/audit/ledger.py`, `cato/budget.py`, `cato/cli.py`, `cato/config.py`,
> `cato/core/approval_policy.py`, `cato/core/outbound_approval.py`,
> `cato/safety.py`, `cato/tools/genesis.py`, `tests/test_dispatch_gates.py` and
> `tests/test_ledger_failclosed.py`.
>
> **These documents describe committed state at `8731f21`.** Two facts have
> uncommitted fixes in flight, and both are flagged inline where they appear:
> §0 Fact 3 (the `safety_mode` trap) and `LIMITATIONS.md` §4 (the `BudgetManager`
> call site). **Line numbers cited anywhere in `docs/ops/` are as-of-`8731f21`
> and will drift.** Prefer the symbol names — `SafetyGuard.check_and_confirm`,
> `_guarded_dispatch`, `record_recovery` — and use `grep` to relocate them.
>
> Establish which version you have before acting:
> ```
> git -C "C:\Users\Work\Desktop\GitHub\Cato" status --short
> git -C "C:\Users\Work\Desktop\GitHub\Cato" log --oneline -1
> ```

---

## 0. Read this first — four facts that change how you operate

### Fact 1: The daemon has not been started during this remediation

**The last time Cato actually ran was 2026-06-14.** Evidence:
`C:\Users\benst\.cato\cato.db` has a last-write time of 2026-06-14 15:25:18.
Nothing in this remediation cycle started the daemon.

Every startup instruction in Section 3 is therefore **UNVERIFIED**. The commands
exist (verified — see `VERIFICATION.md`), the code paths were read, but nobody
has watched `cato start` come up and serve traffic since June. Treat the first
real start as an experiment, not a routine.

### Fact 2: Which Windows account you launch as decides which state tree is used

Cato has **no `CATO_HOME` environment variable**. Verified: zero matches for
`CATO_HOME` anywhere under `cato/`. State location is derived from the process
owner's Windows profile, two different ways:

| Resolver | Path on Windows | Used for |
|---|---|---|
| `cato.platform.get_data_dir()` | `%APPDATA%\cato` | `config.yaml`, `cato.db`, `vault.enc`, `cato.pid`, `cato.port`, the `STOP` file, `workspace`, `businesses` |
| `Path.home()` | `%USERPROFILE%\.cato` | scattered call sites — 46 occurrences across 23 `.py` files, including `gateway.py` (5), `ui/server.py` (8), `api/memory_routes.py` (3), `pipeline/phase_library.py` (3), `migrate.py` (3) |

So Cato writes to **two roots on the same machine**, and both move when the
launching account changes. This is the single most important operational fact in
the system.

What that looks like right now, verified:

```
C:\Users\benst\.cato\                      <- legacy production tree, last write 2026-06-14
    cato.db          (audit_log 44 rows, conduit_billing 44, conduit_bundle_chain 14)
    conduit_identity.key   (32 bytes)
    sessions\        (EMPTY - 0 entries)
    workspace\
    browser_profile\
    session_count.txt
    NO skills\ subdirectory
    NO vault.enc

C:\Users\benst\AppData\Roaming\cato\       <- DOES NOT EXIST
C:\Users\Work\.cato\                       <- DOES NOT EXIST

C:\Users\Work\AppData\Roaming\cato\        <- active dev tree, created 2026-08-01
    cato.db          (audit_log 0, delegation_tokens 0, ledger_records 0)
    flow_runs.db, routing_log.sqlite3, daemon.token
    workspace\, businesses\, flows\, logs\, memory\, uploads\, browser_profile\
    NO config.yaml
```

Two things follow that you must internalise:

1. **`C:\Users\benst` and `C:\Users\Work` are separate Windows profiles, not
   junctions.** Work is where development happens; benst is the production home.
2. **The production `cato.db` has no `ledger_records` table at all.** It predates
   the Causal Action Ledger. If you start today's build as `benst`, it will
   migrate that database. Back it up first (Section 6).

### Fact 3: At `8731f21`, the approval system is unreachable in the default configuration

With `safety_mode: strict` (the default) and a daemon with no TTY, **every
HIGH_STAKES tool is denied before the approval-ticket gate is ever reached.**
This is fail-closed behaviour, not a bypass — but it means the Telegram approval
flow you may believe is protecting you is never actually exercised. See
Section 4. You must make an explicit decision here before the daemon does
anything useful.

> **An uncommitted fix for this is in the working tree.** The concurrent audit
> added `SafetyGuard._defers_to_approval_gate`, which lets a *positively
> classified* tool that the declarative policy says requires an approval ticket
> **defer** to the approval gate instead of being denied, while still denying
> unclassified tools and tools the policy does not gate. If that lands, the
> approval flow becomes reachable without setting `safety_mode: off`, and the
> §4 decision changes shape.
>
> Determine which behaviour you have:
> ```
> grep -n "_defers_to_approval_gate" cato\safety.py
> ```
> No match → trap present, §4 applies as written. Match → the deferral fix is
> present; re-read `cato/safety.py::check_and_confirm` before relying on §4.

### Fact 4: Credentials are plaintext, and there are three open critical items

No `vault.enc` exists anywhere on this machine (verified: absent from
`C:\Users\benst\.cato\`, `C:\Users\Work\.cato\`, and the repo root). Every
credential lives in plaintext in `.env`, protected only by filesystem ACLs — and
those ACLs are currently wrong. See Section 8. **Do not start the daemon before
resolving those three items.**

---

## 1. What the two systems are

**Cato** is a local Python daemon on this Windows box. It runs an agent loop
against the Anthropic API, dispatches tools through a chain of safety gates, and
records every action in a hash-chained SQLite ledger. Entry point: `cato.cli:main`,
installed as the `cato` console script.

**Genesis** is a remote HTTP gateway at `https://swarmsync-agents.onrender.com`,
hosted on Render's free tier. Cato calls it; it is not part of the local process.
Source at `C:\Users\Work\Desktop\GitHub\Genesis Agents`.

Together they are intended to act as an E4L runtime — Cato as the local
gated executor, Genesis as the remote agent/tool surface. The E4L FinanceOS
integration itself is **not built**; see `LIMITATIONS.md`.

---

## 2. Where state lives

| What | Path (as the launching user) | Notes |
|---|---|---|
| Config | `%APPDATA%\cato\config.yaml` | **Does not currently exist for either user.** Cato runs on dataclass defaults. |
| Audit + ledger DB | `%APPDATA%\cato\cato.db` | SQLite. `audit_log`, `ledger_records`, `delegation_tokens`. |
| Vault | `%APPDATA%\cato\vault.enc` | **Does not exist.** Encryption is not in use. |
| PID / port files | `%APPDATA%\cato\cato.pid`, `cato.port` | Written by `cato start`, removed by `cato stop`. |
| Emergency STOP file | `%APPDATA%\cato\STOP` | Create this file to halt all gated dispatch. |
| Workspace | `%APPDATA%\cato\workspace` | Per `cato status`. |
| Legacy home tree | `%USERPROFILE%\.cato\` | Written by the 46 `Path.home()` call sites. |
| Secrets (Cato) | `C:\Users\Work\Desktop\GitHub\Cato\.env` | Gitignored (verified: `.gitignore:11`). |
| Secrets (Genesis) | `C:\Users\Work\Desktop\GitHub\Genesis Agents\.env` | |
| Approval policy | `C:\Users\Work\Desktop\GitHub\Cato\docs\approval-policy.yaml` | Override path with `CATO_APPROVAL_POLICY`. |

To see the resolved paths for whatever account you are logged in as, run:

```
.venv\Scripts\python.exe -m cato status
```

Verified output on the Work account:

```
  Config:   C:\Users\Work\AppData\Roaming\cato\config.yaml
  Workspace: C:\Users\Work\AppData\Roaming\cato\workspace
  Daemon:  STOPPED
  Model:   openai/gpt-4o-mini
  Safety:  strict
```

Note the `Model:` line reads `openai/gpt-4o-mini`. That is the `CatoConfig`
dataclass default (`cato/config.py:83`), not what the agent loop actually routes
to. Real routing is deterministic and Anthropic-direct — see Section 7.

---

## 3. Startup — UNVERIFIED

> **The daemon has not been started during this remediation cycle. Everything in
> this section is derived from reading `cato/cli.py`, not from observing a
> running system.** The commands are confirmed to exist and to be spelled
> correctly. Their runtime behaviour is not confirmed.

### 3.1 Decide which account you are starting as

This is the first decision, not an afterthought (Fact 2). Log in as, or run as,
the account whose `.cato` / `%APPDATA%\cato` tree you intend to be authoritative.

- **Production intent →** `benst`. Its `.cato` tree holds `conduit_identity.key`
  and the 44-row audit history. Back it up first (Section 6) — today's build will
  migrate a database that has no `ledger_records` table.
- **Development / rehearsal →** `Work`. Empty ledger, no production identity, safe
  to break.

There is no environment variable that overrides this. Switching accounts silently
switches every path in Section 2.

### 3.2 Pre-flight

Run from `C:\Users\Work\Desktop\GitHub\Cato` (this is the only interpreter for
Cato work — see `PREREQUISITES.md`):

```
.venv\Scripts\python.exe -m cato doctor
.venv\Scripts\python.exe -m cato status
.venv\Scripts\python.exe -m cato verify-ledger
.venv\Scripts\python.exe -m cato genesis health
```

All four are verified to run. Expected results on a clean tree, verified:

- `doctor` → `Config NOT FOUND`, `Vault NOT FOUND`, `Daemon STOPPED`, `/health FAIL`.
  All four are correct for a stopped daemon with no config. Exit code 0.
- `status` → `Daemon: STOPPED`, `Safety: strict`.
- `verify-ledger` → `Ledger chain: VALID (0 records, empty chain)`, exit 0.
- `genesis health` → `Status: 200`, `Body: {"status":"ok","service":"swarmsync-agent-gateway"}`.

> `doctor` reports the budget as `$3.00 / $20.00` while `status` reports
> `$50.00 / $100.00`. Both are correct: `doctor` falls back to `BudgetManager`
> defaults because no `config.yaml` exists, `status` reads the `CatoConfig`
> dataclass defaults. Once you create a `config.yaml` they should agree. If they
> ever disagree *with* a config file present, see `LIMITATIONS.md` — there is a
> real bug of this shape at `cato/cli.py:901`.

### 3.3 Create a config (recommended, UNVERIFIED)

```
.venv\Scripts\python.exe -m cato init
```

`cato init` is verified to exist (`cato/cli.py:142`). It has not been run. It is
expected to create `%APPDATA%\cato\config.yaml` and a vault. Running it will
change the `Config: NOT FOUND` line in `doctor` — that is the confirmation.

### 3.4 Start

```
.venv\Scripts\python.exe -m cato start
```

Options, all verified present in `cato/cli.py:472`:

- `--agent <name>` — agent workspace name. Default `default`.
- `--channel webchat|telegram|whatsapp|all` — default `webchat`. The web UI
  (HTTP/WS) always starts on `webchat_port` (config default 8080) regardless.
- `--browser default|conduit` — `conduit` enables per-action billing.

What `cato start` does, read from source:

1. Loads `.env` from the **current working directory** via `python-dotenv`. Start
   from the repo root or the daemon will not see your credentials.
2. Loads `CatoConfig`.
3. Refuses to start if `cato.pid` names a live process — it prints
   `Cato already running (PID N). Use 'cato stop' first.`
4. Writes its own PID to `%APPDATA%\cato\cato.pid`.
5. Installs signal handlers, then runs the Gateway with the configured adapters.

Foreground process. It does not daemonise itself.

### 3.5 Confirm it is up

From a second terminal:

```
.venv\Scripts\python.exe -m cato status
.venv\Scripts\python.exe -m cato doctor
```

`status` should flip to running. `doctor` performs a real HTTP GET against
`http://127.0.0.1:<port>/health` and should flip from `/health FAIL` to a pass.
That HTTP check is the only startup proof that is not self-reported by the CLI —
**treat it as the definition of "started".**

### 3.6 Startup wrappers in the repo (UNVERIFIED, use with care)

`start_daemon.ps1`, `launch_daemon.ps1`, `start_cato.bat`, `cato_service.py`,
`cato_svc_runner.py`, `install_autostart.py`, and `scripts\watchdog.py` all exist
at the repo root. **None were executed or reviewed for this runbook.** Before
using any of them, read it and confirm which Windows account it will run as —
a wrapper that runs as SYSTEM or as a scheduled task under a different user will
silently pick a different state tree (Fact 2). Prefer the explicit
`cato start` above until you have read the wrapper.

---

## 4. The `safety_mode` decision — required before productive use

You must make this call consciously. It is the difference between a daemon that
refuses everything interesting and one whose approval gates are actually live.

> **Applies to committed state at `8731f21`.** Check
> `grep -n "_defers_to_approval_gate" cato\safety.py` first — see §0 Fact 3. If
> that symbol exists, the deferral fix has landed and the "only `off` reaches the
> approval flow" conclusion below no longer holds. Everything else in this
> section — the gate order, the STOP file, the `off`-mode residual protections —
> is unaffected.

### What happens

The guarded dispatch path (`cato/agent_loop.py:2378`) runs gates in this order:

```
1. name resolution              (caller)
2. STOP file                    (SafetyGuard, always honoured — even post-approval)
3. risk classification          (SafetyGuard.check_and_confirm)
4. authorization                (TokenChecker / delegation token)
5. reversibility                (ActionGuard)
6. approval                     (approval policy + ticket store)
7. ledger INTENT                (durably committed BEFORE dispatch)
8. dispatch
9. ledger CONFIRMED / FAILED
```

Every refusal at steps 2–6 writes a ledger `DENIED` entry first.

`SafetyGuard.check_and_confirm` (`cato/safety.py:310`) is step 3. In
`safety_mode: strict` its threshold is `IRREVERSIBLE`, so both `IRREVERSIBLE` and
`HIGH_STAKES` tools fall through to a confirmation prompt. It then checks
`_is_interactive()`. A daemon has no TTY — `sys.stdin` is `None` under `pythonw`
or a service wrapper — so:

```
logger.warning("Safety check: non-interactive context, denying %s by default.")
return False
```

**Denied at step 3. Steps 4, 5 and 6 never run. The approval ticket is never
minted, so the Telegram approval flow is never reached.**

Anything unrecognised is classified `HIGH_STAKES` (`UNCLASSIFIED_TIER`), so this
catches more tools than you would guess.

### Your two options

| Option | What you get | What you give up |
|---|---|---|
| **Leave `strict`** | Nothing high-stakes can execute headlessly, at all. Maximum safety. | The approval system is dead weight. Every gated tool returns `safety_denied`. Anything that matters must be run in an interactive terminal where you can answer `y/N`. |
| **Set `safety_mode: off`** | Step 3 short-circuits to allow, and dispatch proceeds to steps 4, 5 and 6 — the approval ticket gate, ActionGuard reversibility, and the delegation-token check all become live. This is how the Telegram approval flow becomes reachable. | You lose the coarse tier-based prompt. You are now relying entirely on the policy file, ActionGuard, and approval tickets. |

`off` is not "gates off". Reading `cato/safety.py:317-341`, even in `off` mode:

- `shell` / `shell.exec` / `shell.run` are still blocked unless
  `shell_exec_allowed: true` is set in config.
- An **unclassified** tool is still denied, with a warning telling you to add it
  to `cato.safety._TOOL_TIER` or the approval policy first. Turning the gates off
  is treated as a statement about tools you have reviewed, not consent for a
  capability nobody ever classified.

`permissive` is the third value: threshold rises to `HIGH_STAKES`, so
`IRREVERSIBLE` tools stop prompting but `HIGH_STAKES` still does — which in a
headless daemon still means denied. It does not solve the problem.

### Recommendation

Do not change `safety_mode` until the three critical security items in Section 8
are closed. Once they are: if you want a working approval workflow, `off` is the
only value that reaches it, and you should verify the approval path end to end
(see `VERIFICATION.md` §6) before trusting it with anything financial.

### The kill switch works in every mode

Create an empty file at `%APPDATA%\cato\STOP`. The STOP check is step 2, ahead of
everything, and is honoured even on the post-approval replay path — an operator
who already approved an action can still stop it. Delete the file to resume.

---

## 5. Approval gates — what is actually enforced

Policy file: `docs/approval-policy.yaml`. Override the path with
`CATO_APPROVAL_POLICY` (`cato/core/approval_policy.py:611`).

Design properties, read from `cato/core/approval_policy.py`:

- **Fail closed.** A tool absent from the policy *requires* approval. Deleting a
  row makes that tool more restricted, never less. An unparseable policy falls
  back to the built-in policy and never widens the gate. An unknown tier is
  coerced to `critical`.
- **The model does not vote.** Nothing in the tool `args` can remove an approval
  requirement. `dry_run`, `draft_only`, `_approval_granted` are treated as
  model-supplied evidence of intent, never as authority.
- **Identity before policy.** `send_email`, `send-email`, `sendEmail` and
  `email.send` normalise to one policy row. No substring matching.
- **Approve a payload, not an intent.** Tickets bind to a SHA-256 over the
  canonical JSON of (canonical tool name, redacted args). Change the arguments
  after approval and the ticket no longer verifies.
- Tickets are HMAC-signed, single-use, 24h TTL, with 60s symmetric clock-skew
  tolerance.

Tier table from `docs/approval-policy.yaml`:

| Tier | Approval |
|---|---|
| `read_only` | free |
| `reversible` | see policy |
| `elevated` | always |
| `outbound` | always |
| `dispatch` | always |
| `financial` | always |
| `critical` | always |

Concretely: `file.read` and `browser.navigate` are `read_only` and run free.
`file.write`, `file.delete`, `browser.eval` are always gated.
`integration.action` — the single entry point to every registered integration —
is tiered `financial` and is always gated.

**If the daemon and the API run as separate processes against one `cato.db`, set
`CATO_APPROVAL_SIGNING_KEY` (hex) in both.** Without it each process derives its
own signing key and tickets minted by one will not verify in the other
(`cato/core/outbound_approval.py:143-147`).

---

## 6. Backup

Before any first start as `benst`, before any migration, before any config change:

```
copy "C:\Users\benst\.cato\cato.db" "C:\Users\benst\.cato\cato.db.bak-YYYYMMDD"
copy "C:\Users\benst\.cato\conduit_identity.key" "<somewhere off this machine>"
```

`conduit_identity.key` is 32 bytes and is not regenerable from anything else in
the tree. Losing it loses the Conduit identity. It currently sits in a directory
that a second Windows account has Full Control over (Section 8, item 2).

There is no `cato backup` command. Do not invent one — copy the files.

---

## 7. Model routing and cost

Routing is **deterministic from a `TaskDescriptor`**, not model-chosen. Direct
Anthropic; SwarmSync has been removed from the model path.

| Task type | Model |
|---|---|
| `ledger_posting_decision`, `financial_reasoning`, `policy_interpretation`, `audit_synthesis` | `claude-opus-5` |
| `reconciliation_analysis`, `general_tool_use` | `claude-sonnet-5` |
| `invoice_line_extraction`, `document_classification` | `claude-haiku-4-5` |

Risk floors override upward — a task can be promoted to a stronger model, never
demoted below its floor. Escalation is bounded: `MAX_ESCALATIONS = 2`, and hitting
the cap raises rather than looping.

Cost ceilings by risk band (`cato/model_policy.py:413-417`):
`NONE` $0.50, `LOW` $0.50, `MEDIUM` $1.50, `HIGH` $5.00, `CRITICAL` $10.00.

**Limitation you will hit immediately:** the agent loop hardcodes
`TaskType.GENERAL_TOOL_USE` (`cato/agent_loop.py:1943-1944`). Interactive chat
therefore always lands on Sonnet. Haiku and Opus routing only happen when an E4L
caller constructs a real descriptor — which nothing currently does. See
`LIMITATIONS.md`.

**Pricing change:** Sonnet 5 introductory pricing ($2/$10 per MTok) ends
2026-08-31. From 2026-09-01 it is $3/$15. This is already encoded in
`cato/model_policy.py:129-130` as a dated price band, so cost estimates will
change on their own — your budget caps will bite ~50% sooner. Plan for it.

Budget caps are enforced before every LLM call. Check them with
`cato status` or `cato doctor`.

---

## 8. OUTSTANDING CRITICAL SECURITY ITEMS

**All three are open. All three are awaiting operator action. Do not start the
daemon with real credentials until they are closed.**

### CRITICAL-1 — A sandbox group can read both `.env` files

Verified 2026-08-03:

```
> icacls "C:\Users\Work\Desktop"
C:\Users\Work\Desktop ACEMAGIC-WINDOW\CodexSandboxUsers:(OI)(CI)(RX)
                      NT AUTHORITY\SYSTEM:(I)(OI)(CI)(F)
                      BUILTIN\Administrators:(I)(OI)(CI)(F)
                      ACEMAGIC-WINDOW\Work:(I)(OI)(CI)(F)

> icacls "C:\Users\Work\Desktop\GitHub\Cato\.env"
...  ACEMAGIC-WINDOW\CodexSandboxUsers:(I)(RX)

> net localgroup CodexSandboxUsers
Members: CodexSandboxOffline, CodexSandboxOnline
```

`(OI)(CI)(RX)` on `Desktop` is inherited onto both `Cato\.env` and
`Genesis Agents\.env`. Two sandbox accounts can read every credential in
`PREREQUISITES.md`.

**Remediation** (run elevated, then re-verify with the same `icacls` commands):

```
icacls "C:\Users\Work\Desktop" /remove:g "ACEMAGIC-WINDOW\CodexSandboxUsers"
```

If the sandbox genuinely needs a subtree, grant it on that subtree explicitly
rather than on `Desktop`.

### CRITICAL-2 — The `Work` account has Full Control of the entire `benst` profile

Verified 2026-08-03:

```
> icacls "C:\Users\benst"
C:\Users\benst NT AUTHORITY\SYSTEM:(OI)(CI)(F)
               BUILTIN\Administrators:(OI)(CI)(F)
               ACEMAGIC-WINDOW\benst:(OI)(CI)(F)
               ACEMAGIC-WINDOW\Work:(OI)(CI)(F)      <-- this
```

`(OI)(CI)(F)` propagates to every file under the production profile, including
`C:\Users\benst\.cato\conduit_identity.key` and `C:\Users\benst\.cato\cato.db`.
The dev account can read, alter or delete the production Conduit identity and the
production audit history.

**Remediation** (run elevated as an administrator, then re-verify):

```
icacls "C:\Users\benst" /remove:g "ACEMAGIC-WINDOW\Work"
```

Do this from an elevated shell that is **not** running as `Work`, or you may lock
yourself out of the path you are standing in. Confirm `benst` can still log in
and reach its own profile before you walk away.

### CRITICAL-3 — `CATO_VAULT_PASSWORD` is a published value, and there is no vault

Two independent problems, one root cause.

**3a.** The live value of `CATO_VAULT_PASSWORD` in `Cato\.env` appears verbatim in
**two git-tracked files** in this repository. Verified by comparing the `.env`
value against every tracked file without printing it:

```
TRACKED FILES CONTAINING THE LIVE VAULT PASSWORD: 2
CLAUDE.md
PROJECT_BLACKBOX_AUDIT.md
```

`PROJECT_BLACKBOX_AUDIT.md:23` even describes it as a known problem. The value is
13 characters. Anyone with repository access has the vault password.

**3b.** There is no vault to protect. Verified absent:
`C:\Users\benst\.cato\vault.enc`, `C:\Users\Work\.cato\vault.enc`,
`C:\Users\Work\Desktop\GitHub\Cato\vault.enc` — all `False`. `cato doctor`
confirms: `Vault  NOT FOUND`.

**Net effect: every credential is plaintext in `.env`, protected only by the ACLs
in CRITICAL-1 and CRITICAL-2, both of which are broken.**

**Remediation, in this order:**

1. Fix CRITICAL-1 and CRITICAL-2 first. Rotating secrets into a filesystem two
   other accounts can read accomplishes nothing.
2. Rotate `CATO_VAULT_PASSWORD` to a new high-entropy value. Do not reuse it
   anywhere.
3. Purge the old value from `CLAUDE.md` and `PROJECT_BLACKBOX_AUDIT.md`, and
   treat it as compromised in git history — a plain edit does not remove it from
   past commits.
4. Create the vault and migrate credentials off plaintext:
   ```
   .venv\Scripts\python.exe -m cato init
   .venv\Scripts\python.exe -m cato vault set <KEY_NAME>
   .venv\Scripts\python.exe -m cato vault list
   ```
   `cato init`, `cato vault set`, `cato vault list` and `cato vault delete` are
   all verified to exist (`cato/cli.py:142, 318, 332, 349`). **None have been
   run — this migration path is UNVERIFIED.** Confirm success by re-running
   `cato doctor` and seeing `Vault` stop reporting `NOT FOUND`.
5. Rotate every other credential in `PREREQUISITES.md`. They have been readable
   by the sandbox accounts for an unknown period.

---

## 9. Shutdown

```
.venv\Scripts\python.exe -m cato stop
```

Verified to exist (`cato/cli.py:633`). Behaviour, read from source: reads the PID
file, sends `SIGTERM`, removes `cato.pid` and `cato.port`. If the PID is stale or
`os.kill` fails it prints `Could not stop process N: ...` and removes both files
anyway, so a stale PID file cannot wedge you permanently.

If `stop` reports `Cato is not running.` but the process is clearly alive, the PID
file was removed out from under it — find and kill the process by hand:

```
Get-Process python | Where-Object { $_.Path -like "*Cato*" }
```

For an emergency halt that does **not** kill the process, use the STOP file
(Section 4). That stops dispatch while leaving the daemon up and the ledger
intact, which is almost always what you want mid-incident.

---

## 10. Health checks

| Check | Command | Verified good output |
|---|---|---|
| Local daemon + config + budget | `.venv\Scripts\python.exe -m cato doctor` | Config/Vault present, `Daemon RUNNING`, `/health` pass |
| Running state, ports, caps | `.venv\Scripts\python.exe -m cato status` | `Daemon: RUNNING` |
| Ledger chain integrity | `.venv\Scripts\python.exe -m cato verify-ledger` | `Ledger chain: VALID (N records...)`, exit 0 |
| Recent ledger entries | `.venv\Scripts\python.exe -m cato ledger show --last 20` | one line per record |
| Genesis reachability | `.venv\Scripts\python.exe -m cato genesis health` | `Status: 200`, `{"status":"ok",...}` |
| Genesis, no Python | `curl https://swarmsync-agents.onrender.com/health` | `{"status":"ok","service":"swarmsync-agent-gateway"}` |
| Gate enforcement table | `.venv\Scripts\python.exe -m cato tools reversibility` | 16-row table, `email_send`/`api_payment` at 1.00 irreversible |
| Night-shift gates + budget + pending approvals | `.venv\Scripts\python.exe -m cato night-shift status` | see `LIMITATIONS.md` — this path has a bug |

All verified to run on 2026-08-03 except `night-shift status`.

### Genesis latency expectations, measured 2026-08-03

```
GET /health                        200 in 0.36s
GET /.well-known/agents.json       200 in 13.44s
```

Render free tier. The documented proxy timeout is 30s. Warm latency on
`/marketplace/search` and `/.well-known/agents.json` reaches ~15s, which is close
enough to the 30s ceiling that a slow day will produce timeouts.

**Cold start has never been measured.** Nobody has observed Genesis waking from
idle. Assume it is slower than 13s and may exceed the 30s proxy timeout on first
call after a quiet period. To measure it: leave Genesis untouched for its idle
window, then run `curl -w "%{time_total}"` against `/health` and record the
result here.

---

## 11. Genesis containment — what is enforced remotely

20 finance tools are `PERMANENTLY_PROHIBITED`. Verified: `PROHIBITION_GROUPS` in
`runtime/tool_policy.py` has 21 entries, of which `workflow_webhook_trigger` is
slug-scoped only, leaving 20 in the global `PROHIBITED_TOOLS` frozenset.

Governing rule, quoted from the source: *automation may PREPARE, a human PAYS,
automation RECORDS.*

Six enforcement layers (`runtime/tool_policy.py:106-124`):

1. **Deletion** — function bodies, schemas and `register_tool` lines removed from
   `tools/*.py`. Absence beats denial.
2. **`assert_prohibitions_intact()`** at gateway startup, before the app accepts
   traffic. A re-registered prohibited tool means a process that refuses to
   start, not a request that gets denied.
3. **Frozen manifest** at `runtime/prohibited_tools.sha256` — a SHA-256 over the
   canonical sorted list of all 21 names. Editing the list alone breaks boot.
4. **Dispatcher pre-check** in `agent_runtime.py`, independent of the risk table.
5. **Tests** including a negative control.
6. **Gateway 403** before any LLM call, so a prohibited name never enters a prompt.

Escrow is contained behind `escrow_permitted()` (`escrow_guard.py:64`), which
returns `True` only when `GENESIS_DEPLOYMENT_PROFILE=swarmsync-marketplace`.
**Unset blocks.** That variable is currently absent from `Genesis Agents\.env`, so
escrow is off.

Contract: `Genesis Agents\docs\FINANCE-TOOL-CONTRACTS.md`.

Verify containment yourself in under a second — see `VERIFICATION.md` §5.

---

## 12. Daily operating loop

There is no schedule to keep. This is the sequence when you sit down to work:

1. `cato status` — is anything running, and as which account?
2. `cato verify-ledger` — did the chain survive whatever happened last?
3. `cato genesis health` — is the remote up?
4. Do the work.
5. `cato ledger show --last 20` — what did it actually do?
6. `cato stop` when finished.

If step 2 fails, stop and go to `INCIDENTS.md` §2 before doing anything else. A
broken ledger chain means the audit trail is no longer trustworthy, and every
claim the system makes after that point is unverifiable.
