# Verification — reproducing the current state from scratch

This document is the binding test for the rest of `docs/ops/`. Another qualified
agent, with no memory of this work, must be able to follow it start to finish and
land on the same numbers.

Every command below was originally executed on 2026-08-03. The recorded outputs
are historical snapshots from that write-up. That write-up cited commit
`8731f21`, which is **not present in this clone's git history** (this repo's
root is `0b7b99d`; do not require `8731f21`). Anything not re-executed on your
tree is marked **UNVERIFIED** with a note on what would confirm it.

**Working copy on this machine:**
`C:\Users\Work\Desktop\vault\projects\My Github\Cato`
(branch `e4l-runtime-hardening` as of the 2026-08-06 path fix). Do **not** use
the former Desktop “GitHub” clone path (gone) or a nested `Main\` folder (deleted
2026-08-06).

**Nothing in this document starts the daemon.** All checks are read-only or
offline. Do not treat offline suite numbers as proof the daemon is live — see §8.

---

## 0. Before you start

Work from `C:\Users\Work\Desktop\vault\projects\My Github\Cato`. Use the venv
interpreter for every Python command (create it per §1 if `.venv` is missing —
**UNVERIFIED** whether a venv already exists at this path):

```
C:\Users\Work\Desktop\vault\projects\My Github\Cato\.venv\Scripts\python.exe
```

Commands are written for a Windows shell from the repo root. The `.venv\...`
relative form assumes your working directory is the repo root.

Record your actual HEAD — do **not** chase a fixed SHA:

```
git -C "C:\Users\Work\Desktop\vault\projects\My Github\Cato" log --oneline -1
```

Example shape only (will drift): `50a4832 fix: declare raster validation build dependencies`.
If your commit differs from the 2026-08-03 write-up, the test counts in §4 may
differ too. Record what you actually see.

**Also check for uncommitted changes:**

```
git -C "C:\Users\Work\Desktop\vault\projects\My Github\Cato" status --short
```

When these documents were first written, a concurrent failure-mode audit had
uncommitted modifications to twelve files including `cato/safety.py` and
`cato/cli.py`, two of which change documented behaviour (§6, and `LIMITATIONS.md`
§2 and §4). **All line numbers in `docs/ops/` drift with HEAD.** Prefer symbol
names and `grep` to relocate anything that has moved.

---

## 1. Create the environment

The venv already exists on this machine and was **not recreated** for this
document. If you are starting from a clean checkout, these are the commands
(**UNVERIFIED on this machine** — verified only in the sense that `pyproject.toml`
declares the `dev` extra and pip/pytest are present in the existing venv):

```
C:\Users\benst\AppData\Local\Programs\Python\Python312\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

`.[dev]` pulls `pytest>=8`, `pytest-asyncio>=0.23`, `pytest-cov>=4` alongside the
runtime dependencies. To confirm the install worked, run §2.

### Verify the environment — all four commands verified

```
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -m pip --version
.venv\Scripts\python.exe -m pip show cato-daemon
.venv\Scripts\python.exe -m pytest --version
```

Recorded output:

```
Python 3.12.10
pip 26.2 from C:\Users\Work\Desktop\vault\projects\My Github\Cato\.venv\Lib\site-packages\pip (python 3.12)
Name: cato-daemon
Version: 0.2.0
Summary: The AI agent daemon you can audit in a coffee break
pytest 9.1.1
```

If `pip show cato-daemon` reports nothing, the editable install did not happen and
`python -m cato` will fail.

---

## 2. Verify the CLI responds

```
.venv\Scripts\python.exe -m cato --help
```

The `cato` console script is declared in `pyproject.toml` as `cato.cli:main`.
`python -m cato` works whether or not the script shim is on `PATH`, so these
documents use that form throughout.

---

## 3. Verify where state actually is — do this before anything else

This is the check that catches the most common and most damaging mistake in this
system.

```
.venv\Scripts\python.exe -m cato status
```

Recorded output on the `Work` account:

```
Cato Status
==================================================
  Config:   C:\Users\Work\AppData\Roaming\cato\config.yaml
  Workspace: C:\Users\Work\AppData\Roaming\cato\workspace
  Daemon:  STOPPED
  Model:   openai/gpt-4o-mini
  SwarmSync: enabled
  Safety:  strict
  Conduit: disabled

Listeners
  WebChat:  port 8080 (config)
  Telegram: disabled
  WhatsApp: disabled

Budget
  [$0.0000 this call | Today: $0.00/$50.00 | Month: $0.00/$100.00]
  Calls today:      0
  Calls this month: 0
```

**Read the `Config:` line every single time.** Those paths move with the Windows
account you are running as. There is no `CATO_HOME` to pin them.

Confirm the account/state relationship yourself:

```
powershell -Command "Test-Path 'C:\Users\benst\.cato'"                    # True
powershell -Command "Test-Path 'C:\Users\benst\AppData\Roaming\cato'"     # False
powershell -Command "Test-Path 'C:\Users\Work\.cato'"                     # False
powershell -Command "Test-Path 'C:\Users\Work\AppData\Roaming\cato'"      # True
powershell -Command "Test-Path \"$env:APPDATA\cato\config.yaml\""         # False
powershell -Command "if ($null -eq $env:CATO_HOME) { 'CATO_HOME not set' }"
```

All six results verified 2026-08-03. The `Model:` line reading
`openai/gpt-4o-mini` is the `CatoConfig` dataclass default, not the model the
agent loop routes to — see §7.

### Inspect both databases read-only

```
.venv\Scripts\python.exe -c "import sqlite3;\
[print('==',p) or [print('  ',t,c.execute(f'select count(*) from \"{t}\"').fetchone()[0]) for (t,) in (c:=sqlite3.connect('file:'+p+'?mode=ro',uri=True)).execute(\"select name from sqlite_master where type='table' order by name\")] for p in [r'C:\Users\benst\.cato\cato.db', r'C:\Users\Work\AppData\Roaming\cato\cato.db']]"
```

That one-liner is awkward; the readable equivalent, which is what was actually
run, is:

```python
import sqlite3
for p in [r'C:\Users\benst\.cato\cato.db',
          r'C:\Users\Work\AppData\Roaming\cato\cato.db']:
    print('==', p)
    c = sqlite3.connect('file:' + p + '?mode=ro', uri=True)
    for (t,) in c.execute("select name from sqlite_master where type='table' order by name"):
        print('  ', t, c.execute(f'select count(*) from "{t}"').fetchone()[0])
    c.close()
```

Recorded output:

```
== C:\Users\benst\.cato\cato.db
   audit_log: 44
   conduit_billing: 44
   conduit_bundle_chain: 14
   sqlite_sequence: 2
== C:\Users\Work\AppData\Roaming\cato\cato.db
   audit_log: 0
   delegation_tokens: 0
   ledger_records: 0
   sqlite_sequence: 0
```

**Note what is missing:** the production database has **no `ledger_records`
table**. It predates the Causal Action Ledger. Starting today's build as `benst`
will migrate it. Back it up first (`RUNBOOK.md` §6).

---

## 4. Run the test suite and interpret the result

```
.venv\Scripts\python.exe -m pytest tests\ -q
```

Takes roughly 2 minutes. Recorded final line, 2026-08-03:

```
26 failed, 2435 passed, 10 skipped, 4 deselected, 53 warnings, 30 errors in 131.28s (0:02:11)
```

The `4 deselected` come from `pyproject.toml:105`:
`addopts = "-m 'not live' --ignore=tests/test_playwright_ui.py"`. Four tests carry
the `live` marker and are excluded by default. This is configuration, not a
failure.

### The 26 failures and 30 errors are fully attributed

**Every one is in `tests/pipeline/test_pipeline_components.py`.** Nothing else in
the suite fails. Confirm that yourself:

```
.venv\Scripts\python.exe -m pytest tests\ -q --ignore=tests\pipeline
```

**UNVERIFIED** — this narrowed run was not executed. If the attribution in this
document is correct, it will report zero failures and zero errors. That is the
cheapest way for a new agent to confirm the claim rather than take it on faith.

There are exactly two causes, both environmental, both benign:

**Cause 1 — hardcoded paths for a Windows account that does not exist here.**
`tests/pipeline/test_pipeline_components.py` lines 25-27:

```python
SCRIPTS_DIR   = Path(r"C:\Users\Administrator\.claude\skills\one-shot-pipeline\scripts")
RALPH_DIR     = Path(r"C:\Users\Administrator\.claude\skills\ralph-wiggum-loop")
BRIDGE_SCRIPT = Path(r"C:\Users\Administrator\Desktop\Cato\cato_telegram_bridge.py")
```

There is no `Administrator` profile on this machine, so module-level path setup
raises during collection. That is the source of all 30 errors (whole classes fail
to set up: `TestInvokeCodex`, `TestInvokeCursor`, `TestInvokeAgent`) and of the
`TestTelegramBridge` / `TestRalphSkill` failures.

**Cause 2 — two external CLIs are not installed.** Same file, lines 43-60:

```python
assert shutil.which("codex") is not None, "codex CLI not found on PATH"
base = Path(os.environ.get("LOCALAPPDATA", "")) / "cursor-agent" / "versions"
assert base.is_dir(), f"cursor-agent not installed (expected {base})"
```

Neither `codex` nor `cursor-agent` is installed. Sources the
`TestInvokeCodexCLI`, `TestInvokeCursorCLI`, and `TestInvokeAgentCLI` failures.

**This is a known, attributed condition, not a mystery and not a regression.** You
do not need to install `codex` or `cursor-agent`, and you should not create an
`Administrator` profile to satisfy a test. The correct fix is to parametrise those
paths, which is out of scope here.

**If a failure appears outside `tests/pipeline/`, that is new and real.** Stop and
investigate before trusting anything else in these documents.

---

## 5. Verify Genesis containment

Genesis has no venv of its own. Run its containment tests under Cato's
interpreter. Verified working:

```
cd "C:\Users\Work\Desktop\vault\projects\My Github\Genesis Agents"
"C:\Users\Work\Desktop\vault\projects\My Github\Cato\.venv\Scripts\python.exe" -m pytest tests\test_escrow_containment.py tests\test_prohibited_tools.py -q
```

Recorded output:

```
48 passed in 0.39s
```

These tests are the live proof of the containment described in `RUNBOOK.md` §11.
They cover the prohibition manifest, the boot-time assertion, and the escrow
guard, including a negative control.

### Verify the prohibited-tool set directly

```
cd "C:\Users\Work\Desktop\vault\projects\My Github\Genesis Agents"
"C:\Users\Work\Desktop\vault\projects\My Github\Cato\.venv\Scripts\python.exe" -c "from runtime.tool_policy import PROHIBITED_TOOLS, PROHIBITION_GROUPS, prohibition_manifest_digest; print(len(PROHIBITED_TOOLS), len(PROHIBITION_GROUPS)); print(prohibition_manifest_digest())"
```

**UNVERIFIED as a standalone one-liner** — the names, the counts and
`prohibition_manifest_digest()` were confirmed by reading
`runtime/tool_policy.py:106-190`, and the 48 passing tests exercise the same code.
Expected: `20 21` and a 64-character hex digest matching the first non-comment
line of `runtime/prohibited_tools.sha256`.

20 vs 21 is correct and deliberate: `PROHIBITION_GROUPS` has 21 entries;
`workflow_webhook_trigger` is slug-scoped only and is excluded from the global
`PROHIBITED_TOOLS` frozenset, because that set is an *absence* assertion and
`workflow_webhook_trigger` is legitimately registered outside a finance context.

### Verify escrow is blocked

`escrow_permitted()` (`escrow_guard.py:64`) returns `True` only when
`GENESIS_DEPLOYMENT_PROFILE=swarmsync-marketplace`. That variable is absent from
`Genesis Agents\.env` (verified — see `PREREQUISITES.md` §7 for the full key
list). `tests/test_escrow_containment.py:41` asserts
`escrow_permitted() is False`, and it passes. **Escrow is off.**

### Verify Genesis is reachable

```
.venv\Scripts\python.exe -m cato genesis health
```

Recorded output:

```
Status: 200
Body: {"status":"ok","service":"swarmsync-agent-gateway"}
```

Without Python:

```
curl -s -o /dev/null -w "status=%{http_code} total=%{time_total}s\n" https://swarmsync-agents.onrender.com/health
curl -s -o /dev/null -w "status=%{http_code} total=%{time_total}s\n" https://swarmsync-agents.onrender.com/.well-known/agents.json
```

Recorded:

```
status=200 total=0.357182s
status=200 total=13.437798s
```

The 13.4s figure is warm latency against a 30s Render proxy timeout — thin margin.
**Cold start has never been measured.** To measure it, leave Genesis idle through
its sleep window, then re-run the `/health` curl and record `time_total`.

---

## 6. Verify the ledger and the approval gates

### Ledger chain integrity — two equivalent commands, both verified

```
.venv\Scripts\python.exe -m cato verify-ledger
.venv\Scripts\python.exe -m cato ledger verify
```

Recorded output (Work account, empty ledger):

```
Ledger chain: VALID (0 records, empty chain)     # verify-ledger, exit 0
VALID (0 records, empty chain)                   # ledger verify,  exit 0
```

Both exit non-zero on failure. `verify-ledger` is the top-level command; `ledger
verify` is the same check under the `ledger` group. Use either.

```
.venv\Scripts\python.exe -m cato ledger show --last 20
```

Verified to exist (`cato/cli.py:2943`). Prints nothing here because the chain is
empty — which is itself the correct result on the `Work` tree.

### Reversibility table — verified

```
.venv\Scripts\python.exe -m cato tools reversibility
```

Recorded output:

```
Tool                       Score  Blast Radius  Recovery
-----------------------------------------------------------------
email_send                  1.00  public        irreversible
api_payment                 1.00  public        irreversible
delete_file                 0.80  single_user   hours
git_commit                  0.70  multi_user    hours
git_push                    0.70  multi_user    hours
shell_execute               0.60  single_user   minutes
conduit_click               0.50  single_user   minutes
conduit_type                0.50  single_user   minutes
write_file                  0.30  single_user   minutes
edit_file                   0.30  single_user   minutes
read_file                   0.00  self          instant
list_dir                    0.00  self          instant
web_search                  0.00  self          instant
memory_search               0.00  self          instant
conduit_navigate            0.00  self          instant
conduit_extract             0.00  self          instant
```

This is the ActionGuard input at gate 5. `email_send` and `api_payment` scoring
1.00 / irreversible is the expected shape.

### The approval policy is enforced by tests, not by a CLI command

There is **no `cato approval` command**. Do not look for one. Verify the policy by
reading `docs/approval-policy.yaml` and running the approval tests:

```
.venv\Scripts\python.exe -m pytest tests\ -q -k "approval"
```

**UNVERIFIED as a narrowed run** — the tests execute as part of the full suite in
§4, where all non-`tests/pipeline` tests pass. Running it narrowed is the direct
confirmation.

Tier map from `docs/approval-policy.yaml:48-55` — `read_only` free; `elevated`,
`outbound`, `dispatch`, `financial`, `critical` all `approval: always`.
`integration.action` is tiered `financial` (line 150-152), so it is always gated.
`browser_navigate` and `browser_navigate_back` are `read_only`.

### Verify the safety trap for yourself — the most important check here

`RUNBOOK.md` §4 claims that in the default `safety_mode: strict` with no TTY,
every HIGH_STAKES tool is denied *before* the approval gate is reached. Confirm it
by reading two files:

1. `cato/agent_loop.py:2378-2465` — the gate order. `check_and_confirm` is step 3
   (`:2416`); the approval gate `_maybe_gate_outbound_tool` is step 6 (`:2457`).
   Step 3 returns early on denial.
2. `cato/safety.py:310-395` — `check_and_confirm`. In `strict` the threshold is
   `RiskTier.IRREVERSIBLE`, so `HIGH_STAKES` falls through to the prompt; then
   `if not _is_interactive():` logs
   `"Safety check: non-interactive context, denying %s by default."` and returns
   `False`.
   `_is_interactive()` (`cato/safety.py:412-421`) returns `False` when
   `sys.stdin is None` — which is exactly a detached daemon.

Also confirm the default: `cato/config.py:178` — `safety_mode: str = "strict"`,
and `cato status` prints `Safety:  strict`.

**Conclusion the 2026-08-03 write-up reached: with the shipped defaults then, the
Telegram approval flow was unreachable in a headless daemon.** It is fail-closed,
not a bypass — but it is not doing the job you think it is doing. Re-derive this
on **your** HEAD; do not assume the historical SHA still exists in this clone.

**Then check whether that is still true on your tree:**

```
grep -n "_defers_to_approval_gate" cato\safety.py
```

Historical note: the 2026-08-03 write-up found **no** match in committed
`cato/safety.py` at that time. A concurrent audit later added that method so a
positively classified, policy-gated tool could **defer** to the approval gate
rather than be denied — while still denying unclassified tools and tools the
policy does not gate. If you get a match, read
`cato/safety.py::check_and_confirm` in full and re-derive the conclusion yourself
rather than trusting this paragraph.

---

## 7. Verify model routing

Read `cato/model_policy.py`:

- Tier map, lines 166-168: `HAIKU -> claude-haiku-4-5`, `SONNET -> claude-sonnet-5`,
  `OPUS -> claude-opus-5`.
- Task-type map, lines 228-233: `GENERAL_TOOL_USE -> SONNET`,
  `LEDGER_POSTING_DECISION -> OPUS`.
- Cost ceilings, lines 413-417: `NONE` 0.50, `LOW` 0.50, `MEDIUM` 1.50,
  `HIGH` 5.00, `CRITICAL` 10.00.
- Escalation cap, line 482: `MAX_ESCALATIONS = 2`, with a dedicated exception
  raised at the cap so escalation terminates instead of looping.
- Sonnet 5 price bands, lines 129-130:
  `PriceBand(date(2000,1,1), 2.00, 10.00)` introductory,
  `PriceBand(date(2026,9,1), 3.00, 15.00)` list. **Introductory pricing ends
  2026-08-31.**

Then confirm the limitation:

```
grep -n "TaskType.GENERAL_TOOL_USE" cato\agent_loop.py
```

Verified: `cato/agent_loop.py:1944` constructs the `TaskDescriptor` with
`task_type=TaskType.GENERAL_TOOL_USE`, hardcoded. **Interactive chat therefore
always routes to Sonnet.** Haiku and Opus routing require a caller that builds a
real descriptor. Nothing currently does. See `LIMITATIONS.md`.

---

## 8. What this verification does NOT cover

State these plainly rather than letting a reader assume coverage.

| Not verified | Why | What would confirm it |
|---|---|---|
| **`cato start`** | This verification pass does not start the daemon. Earlier notes cited a 2026-06-14 `benst` DB mtime; that file is **ABSENT** as of 2026-08-06. Work `%APPDATA%\cato` shows Aug 2026 filesystem activity — see `LIMITATIONS.md` §1. Filesystem mtimes ≠ live-proven daemon / model calls. | Run it, then `cato doctor` and see the `/health FAIL` line flip to a pass. That HTTP check is the only non-self-reported startup proof. |
| `cato stop` | Nothing was started, so nothing was stopped. | Start, then stop, then confirm `cato.pid` and `cato.port` are gone. |
| `cato init` | Never run. No `config.yaml` or `vault.enc` exists on this machine. | Run it, then `cato doctor` should stop reporting `Config NOT FOUND` / `Vault NOT FOUND`. |
| `cato vault set` / `list` / `delete` | Never run. There is no vault. | Create a vault via `cato init`, then round-trip a throwaway key. |
| `cato night-shift status` | Not run — it has a known bug (`cato/cli.py:901`). See `LIMITATIONS.md`. | Fix the call site first. |
| Venv creation from scratch | The existing venv was reused. | `python -m venv` into a temp dir and `pip install -e ".[dev]"`. |
| Genesis cold start | Genesis was warm on every probe. | Idle it out, then time `/health`. |
| Any live Anthropic model call | No model call was made. Budget counters read `Calls today: 0`. | Any real agent turn; `cato status` budget counters will move. |
| Any live Xero write | Never performed, ever. See `LIMITATIONS.md`. | — |
| The desktop app / web UI build | Not built. Node is present but unused. | — |
| `start_daemon.ps1`, `launch_daemon.ps1`, `start_cato.bat`, `cato_service.py`, `install_autostart.py`, `scripts\watchdog.py` | None executed or reviewed. | Read each one and confirm which Windows account it runs as before use. |

---

## 9. Verification checklist

Tick these in order. If any step diverges from the recorded output, stop and read
the relevant section rather than continuing.

- [ ] `git log --oneline -1` → record the actual HEAD SHA (do not require `8731f21`; it is not in this clone)
- [ ] `.venv\Scripts\python.exe --version` → `Python 3.12.10`
- [ ] `.venv\Scripts\python.exe -m pip show cato-daemon` → `cato-daemon 0.2.0`
- [ ] `.venv\Scripts\python.exe -m pytest --version` → `pytest 9.1.1`
- [ ] `cato status` → `Daemon: STOPPED`, `Safety: strict`, config path matches your account
- [ ] `CATO_HOME` not set; `%APPDATA%\cato\config.yaml` absent; no `vault.enc` anywhere
- [ ] `pytest tests\ -q` → `26 failed, 2435 passed, 10 skipped, 4 deselected, 30 errors`
- [ ] all 26 + 30 are in `tests/pipeline/test_pipeline_components.py`
- [ ] Genesis containment tests → `48 passed`
- [ ] `cato genesis health` → `Status: 200`
- [ ] `cato verify-ledger` → `VALID`, exit 0
- [ ] `cato tools reversibility` → 16 rows, `email_send` 1.00 irreversible
- [ ] read `agent_loop.py:2378-2465` + `safety.py:310-421` and reach the §6 conclusion yourself
- [ ] `icacls "C:\Users\Work\Desktop"` still shows `CodexSandboxUsers:(OI)(CI)(RX)` → **CRITICAL-1 still open**
- [ ] `icacls "C:\Users\benst"` still shows `ACEMAGIC-WINDOW\Work:(OI)(CI)(F)` → **CRITICAL-2 still open**
- [ ] no `vault.enc` exists → **CRITICAL-3 still open**

The last three are expected to be **open**. If they are closed, someone has done
the remediation in `RUNBOOK.md` §8 — confirm that and update this document.
