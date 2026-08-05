# Incident and Recovery Runbook

One operator. No pager, no rotation, no alerting. These are the things that go
wrong and what you do about each one, at a terminal, by yourself.

Verified 2026-08-03 against Cato commit `8731f21`. Every command here is
confirmed to exist. Anything not executed is marked **UNVERIFIED**.

---

## 0. First moves for any incident

**Stop the bleeding without destroying evidence.**

```
type nul > "%APPDATA%\cato\STOP"
```

The STOP file is checked at gate 2 of the guarded dispatch path
(`cato/agent_loop.py:2400-2410`), ahead of everything else, and is honoured even
on the post-approval replay path. It halts dispatch while leaving the process up
and the ledger intact. That is almost always what you want — killing the daemon
mid-action is how you *create* the orphaned-INTENT problem in §1.

Then, in this order:

```
.venv\Scripts\python.exe -m cato status
.venv\Scripts\python.exe -m cato verify-ledger
.venv\Scripts\python.exe -m cato ledger show --last 30
```

**Confirm which Windows account you are in before you trust any of that output.**
`cato status` prints the resolved config path. If it does not match the account
whose problem you are investigating, you are reading a different machine's worth
of state. See §7.

Resume by deleting the STOP file.

---

## 1. Unresolved INTENT after a crash

**The most serious recoverable incident in this system.** An unresolved INTENT
means the process died between "I am about to do this" and "I did / did not do
it". The real-world side effect is **unknown**.

### Symptom

On restart, this appears in the log at CRITICAL (`cato/agent_loop.py:2354-2364`):

```
LEDGER RECOVERY: N unresolved INTENT(s) found at startup — a previous run died
mid-action and the real-world effect is UNKNOWN. Reconcile with
ledger.record_recovery(). Actions: <tool>@<timestamp>(action=<action_id>)
```

### Why it happens

Gate 7 commits a ledger `INTENT` **durably, before dispatch**
(`cato/audit/ledger.py:863` `recorded_action`). If `INTENT` cannot be written the
body never executes. Exiting the block without a terminal entry writes `FAILED`.
A hard kill (`taskkill /F`, power loss, BSOD) bypasses that, leaving an `INTENT`
with no `CONFIRMED` / `FAILED` / `DENIED` / `RECOVERED` sibling.

### Find them

There is **no CLI command for this.** Do not go looking for `cato ledger
recover` — it does not exist. Use the Python API:

```python
from cato.audit.ledger import LedgerQuery
q = LedgerQuery()
for r in q.unresolved_intents():
    print(r.action_id, r.tool_name, r.timestamp, r.agent_session_id)
q.close()
```

`LedgerQuery.unresolved_intents()` is verified at `cato/audit/ledger.py:1115`.
`LedgerQuery` defaults to `get_data_dir()/cato.db` for the current account
(`:1040-1043`) — pass `db_path=` explicitly if you need the other tree.

Also check the related class of problem:

```python
q.unreconciled_indeterminate()
```

Verified at `cato/audit/ledger.py:1124`. These are actions already marked
`INDETERMINATE` and not yet reconciled. Same rule applies.

### Reconcile — the part that requires you, not the software

**Do not re-run the action. Do not restart the daemon expecting it to sort
itself out.** Re-running is precisely how one approved action becomes two real
side effects. The ledger comment says so directly (`ledger.py:1000-1006`).

For each orphaned `action_id`:

1. **Go to the external system and look.** Did the email send? Did the file get
   written? Did the API call land? The ledger cannot tell you — that is the whole
   point of the state. Check the counterparty, not Cato.
2. **Record what you found:**

   ```python
   from cato.audit.ledger import LedgerMiddleware
   m = LedgerMiddleware()
   m.record_recovery(action_id="<the action_id>", outcome="<what you established>")
   ```

   `record_recovery` is verified at `cato/audit/ledger.py:840`. Signature:
   keyword-only `action_id`, `outcome`, and optional `tool_name` /
   `agent_session_id` (both auto-filled from the prior INTENT when omitted). It
   writes a terminal `RECOVERED` entry.

   `outcome` is a free-text string, not an enum — write a sentence a future
   reader can act on. "Confirmed sent, message ID abc123, seen in Gmail Sent at
   14:32" beats "ok".

3. **Re-verify the chain:**

   ```
   .venv\Scripts\python.exe -m cato verify-ledger
   ```

4. Only then resume normal operation.

### Prevention

Use `cato stop` or the STOP file. Reserve `taskkill /F` for a genuinely wedged
process, and expect this incident when you use it.

### The idempotency guard, and its limit

`recorded_action` accepts an `idempotency_key` and raises `DuplicateActionError`
if the key was already used, "so a post-crash replay cannot repeat a side effect"
(`ledger.py:875-879`). `cato/agent_loop.py:2330` derives that key per
(session, tool call).

**This protects the ledger, not the counterparty.** If the side effect landed
remotely and Cato died before recording it, the guard cannot know. You still have
to look. See `LIMITATIONS.md` on idempotency above the model call.

---

## 2. Ledger chain verification failure

### Symptom

```
.venv\Scripts\python.exe -m cato verify-ledger
```

returns something other than `VALID (...)`, and exits non-zero.

### What it means

The ledger is a hash chain. Every write is committed with `synchronous=FULL` and
**read back before the call returns**; if the row is not there, `LedgerWriteError`
is raised and the caller aborts (`cato/audit/ledger.py:593-600`). So a verify
failure is not a routine flake. It means one of:

- the database file was edited, truncated or restored out of band,
- storage corruption,
- two processes wrote to one `cato.db` with mismatched assumptions,
- the file was replaced from a backup taken mid-write.

### Do this

1. **Stop the daemon.** `cato stop`. Do not keep appending to a chain you cannot
   verify — every subsequent record inherits the doubt.

2. **Copy the database before touching anything.**

   ```
   copy "%APPDATA%\cato\cato.db" "%APPDATA%\cato\cato.db.broken-YYYYMMDD-HHMM"
   ```

3. **Find where it breaks.**

   ```
   .venv\Scripts\python.exe -m cato ledger show --last 50
   ```

   Compare the tail against your backup from `RUNBOOK.md` §6. The break point
   tells you roughly when it happened, which usually identifies the cause.

4. **Decide, and write the decision down.** There is no repair tool, and you
   should not want one — a ledger you can silently repair is not an audit trail.
   Your options are: restore a verified-good backup and accept the gap, or keep
   the broken file as evidence and start a fresh chain. Either way, record which
   you chose and why, outside the database.

5. **If the daemon runs with `audit_enabled: true` and the ledger cannot be
   opened, dispatch refuses outright** (`cato/agent_loop.py:2527-2534`, error
   `[LEDGER] ...`, `ledger_denied: true`). That is correct: an operator who asked
   for auditing gets no un-audited actions. A broken ledger is a stop, not a
   warning.

### Known non-incident

`VALID (0 records, empty chain)` on the `Work` tree is correct — that ledger has
never been written to. `C:\Users\benst\.cato\cato.db` has **no `ledger_records`
table at all** (it predates the Causal Action Ledger), so `verify-ledger` run as
`benst` will report on a chain that has just been created by schema migration.
That is expected, not corruption.

---

## 3. Approval ticket problems

### Symptom A — everything high-stakes is denied, no ticket ever appears

You never see an approval request. Tools return `safety_denied`. Nothing reaches
Telegram.

**At commit `8731f21` this is the expected behaviour of the shipped
configuration, not a fault.** With `safety_mode: strict` and no TTY,
`SafetyGuard.check_and_confirm` denies at gate 3 before the approval gate at gate
6 ever runs. See `RUNBOOK.md` §4 for the full explanation and the decision you
have to make.

**First, establish which version you are on:**

```
grep -n "_defers_to_approval_gate" cato\safety.py
```

No match → the behaviour above; it is configuration, not a fault. A match → the
deferral fix has landed, policy-gated tools should now reach the approval gate,
and a blanket denial **is** a fault worth investigating.

Confirm it is this and not something else — the log line is distinctive:

```
Safety check: non-interactive context, denying <tool> by default.
```

Resolution is a configuration decision, not a fix: either run interactively so
there is a TTY to answer the prompt, or set `safety_mode: off` and let gates 4, 5
and 6 do the work. Do not do the latter until `RUNBOOK.md` §8 is closed.

### Symptom B — a ticket exists but fails to verify

Tickets bind to a SHA-256 over the canonical JSON of (canonical tool name,
redacted args). Three causes, in order of likelihood:

1. **The arguments changed after approval.** By design — "approve a payload, not
   an intent" (`cato/core/approval_policy.py:29-32`). Re-approve against the
   actual arguments. This is the system working.

2. **Split signing keys.** If the daemon and the API run as separate processes
   against one `cato.db` and `CATO_APPROVAL_SIGNING_KEY` is unset, each derives
   its own HMAC key and neither can verify the other's tickets
   (`cato/core/outbound_approval.py:143-147`). Set the same hex value in both
   process environments. **Currently unset on this machine.**

3. **Clock skew or expiry.** Tickets are single-use with a 24h TTL and 60s
   symmetric skew tolerance. A ticket stamped slightly in the future is accepted
   within tolerance and rejected beyond it, so a rolled-back clock cannot mint an
   immortal ticket. If the machine's clock jumped, expect failures — fix the
   clock, re-approve.

Single-use is absolute: a redeemed ticket cannot be replayed. If you need the
action again, approve it again.

### Symptom C — a tool you expected to be free is being gated

The policy is **fail-closed**. A tool absent from `docs/approval-policy.yaml`
requires approval; an unknown tier is coerced to `critical`. If a tool is
unexpectedly gated, it is almost certainly not in the policy, or its name is not
normalising onto the row you think it is.

Check the policy file and the alias lists. Do not "fix" this by deleting a policy
row — deleting a row makes a tool *more* restricted, never less
(`approval_policy.py:9-12`).

### Symptom D — an unclassified tool is denied even with `safety_mode: off`

Working as designed (`cato/safety.py:331-341`):

```
Unclassified tool '<name>' blocked even in safety_mode=off:
add it to cato.safety._TOOL_TIER or the approval policy first.
```

Turning the gates off is a statement about tools you have reviewed. It is not
consent for a capability nobody ever classified. Classify the tool, then retry.

Likewise `shell` / `shell.exec` / `shell.run` stay blocked in `off` mode unless
`shell_exec_allowed: true` is set in config.

---

## 4. Genesis outage or cold start

### Diagnose

```
.venv\Scripts\python.exe -m cato genesis health
curl -s -o /dev/null -w "status=%{http_code} total=%{time_total}s\n" https://swarmsync-agents.onrender.com/health
```

Healthy, measured 2026-08-03: `Status: 200`,
`{"status":"ok","service":"swarmsync-agent-gateway"}`, 0.36s.

### Interpreting what you get

| Result | Meaning | Action |
|---|---|---|
| 200, under 1s | Warm and healthy. | Problem is elsewhere. |
| 200, 10-20s | Warm but slow. Measured 13.44s on `/.well-known/agents.json`. | Normal for Render free tier. Expect timeouts on any call whose own work pushes past the 30s proxy limit. |
| Long hang then 502/504 | Render proxy timeout (30s) or cold start. | Wait and retry once. See below. |
| Connection refused / DNS failure | Local network, or Render is down. | Check your own connectivity first, then Render status. |

### Cold start — UNVERIFIED, and this matters

**Cold start has never been measured.** Nobody has observed Genesis waking from
idle on this deployment. On Render's free tier a slept instance can take tens of
seconds to boot, and the proxy timeout is 30s — so it is entirely plausible that
**the first call after an idle period always fails**, and the second succeeds.

Treat a single 502/504 after a quiet period as "probably a cold start", retry
once, and only escalate if the second call also fails.

To close this gap, measure it: leave Genesis untouched through its idle window,
then run the `curl -w "%{time_total}"` above and record the number in
`RUNBOOK.md` §10. Until someone does, retry advice here is a guess and is labelled
as one.

### What still works while Genesis is down

Genesis is a remote HTTP dependency, not part of the local process. Local tools,
the ledger, the approval store and the safety gates are unaffected. Cato itself
does not need Genesis to start.

### What you must not do

Do not set `GENESIS_DEPLOYMENT_PROFILE=swarmsync-marketplace` while debugging an
outage. That is the sole switch that enables escrow (`escrow_guard.py:64`), and it
has nothing to do with reachability. Unset blocks; leave it unset.

---

## 5. Anthropic outage or rate limiting

### Symptom

Model calls fail or hang. The agent loop wraps model calls in
`asyncio.wait_for` (`cato/agent_loop.py:1955`), so you will see timeouts rather
than an indefinite hang.

### Escalation is bounded — check whether you hit the cap

`cato/model_policy.py` maps Anthropic `stop_reason` values onto escalation
triggers (`:497`) and caps escalation at `MAX_ESCALATIONS = 2` (`:482`). Hitting
the cap raises a dedicated exception (`:506-510`) rather than looping.

**A task that fails loudly at the escalation cap has not been rate-limited — it
has been escalated twice and still not completed.** Those are different problems.
Read the error before assuming provider trouble.

### Do this

1. Rate limiting is the provider's, not Cato's. There is no local rate limiter to
   tune. Wait it out.
2. Confirm `ANTHROPIC_API_KEY` is actually visible to the process. `cato start`
   loads `.env` **from the current working directory** (`cato/cli.py:483-492`).
   Started from the wrong directory, the daemon has no key and the failure looks
   like an outage. This is a common self-inflicted version of this incident.
3. Check spend before blaming the provider — a budget stop looks similar from the
   outside:
   ```
   .venv\Scripts\python.exe -m cato status
   ```
4. Genesis has its own separate model configuration (`LLM_API_KEY`,
   `LLM_API_URL`, `GENESIS_LLM_MODEL`, and optionally
   `GENESIS_ALLOW_OPENROUTER_FALLBACK`). An Anthropic problem on the Cato side
   does not necessarily affect Genesis, and vice versa.

### The 2026-08-31 cliff

Sonnet 5 introductory pricing ($2/$10 per MTok) ends 2026-08-31; from
2026-09-01 it is $3/$15 (`cato/model_policy.py:129-130`). That is a 50% cost
increase encoded as a dated price band, so it takes effect **on its own, with no
deploy**. On 2026-09-01, budget caps that were comfortable will start biting
roughly a third sooner, and the symptom will present as "budget exceeded"
(§6), not as a pricing change. If that is your incident on or after that date,
this is why.

---

## 6. Budget exceeded

### Symptom

Model calls refuse. Budget caps are enforced before every LLM call.

### Diagnose

```
.venv\Scripts\python.exe -m cato status
.venv\Scripts\python.exe -m cato doctor
```

`status` reads the caps from `CatoConfig`; `doctor` reads them from
`BudgetManager`.

**Expect these two to disagree right now, and know why.** Verified output on a
clean tree: `status` reports `$50.00 / $100.00`, `doctor` reports `$3.00 /
$20.00`. Both are correct — no `config.yaml` exists, so `doctor` falls back to
`BudgetManager` defaults ($3 daily / $20 monthly) while `status` shows the
`CatoConfig` dataclass defaults ($50 / $100). Once you create a config they should
agree.

**If they disagree with a `config.yaml` present, you may have hit the bug at
`cato/cli.py:901`** — see `LIMITATIONS.md` §4. At commit `8731f21` that call site
passes a config object where `BudgetManager` expects `session_cap: float`, so it
silently falls back to $3/$20 defaults instead of your configured caps. Check:

```
grep -n "BudgetManager(cfg)" cato\cli.py
```

A match means the defect is present and `cato night-shift status` budget figures
are wrong. No match means it has been fixed and the disagreement is something
else.

### Understand which cap actually stopped you

From `cato/budget.py:111-116`, in the class docstring:

- `session_cap` — **accepted for backward compatibility but NOT enforced.** It is
  logged at INFO and persisted as an informational field only. Do not tune it
  expecting an effect.
- `daily_cap` — the canonical short-horizon guard. Default $3.
- `monthly_cap` — the long-horizon backstop. Default $20.

If you set `session_cap` and nothing changed, that is why.

### Resolve

Raise `daily_cap` / `monthly_cap` in `%APPDATA%\cato\config.yaml`, or wait for the
window to roll. Cost ceilings also exist per risk band
(`cato/model_policy.py:413-417`): `NONE` $0.50, `LOW` $0.50, `MEDIUM` $1.50,
`HIGH` $5.00, `CRITICAL` $10.00 — a single high-risk task can consume a
meaningful slice of a $3 daily cap on its own.

---

## 7. Wrong Windows user — symptom and recovery

**Expect this one. It is the most likely confusing incident in the system**,
because nothing announces it.

### Symptoms

Any of these, with no error message:

- Sessions, memory, workspace files or audit history that were there yesterday
  are gone.
- `cato status` shows `Daemon: STOPPED` while a Cato process is visibly running.
- `cato stop` says `Cato is not running.` but something is clearly alive.
- The ledger is empty when you know actions were taken.
- Credentials appear missing despite `.env` being present and correct.
- Two `cato.db` files with wildly different content.

### Why

There is no `CATO_HOME`. State resolves two ways, both derived from the launching
account's Windows profile:

- `get_data_dir()` → `%APPDATA%\cato` — config, `cato.db`, vault, PID, port, STOP
  file, workspace.
- `Path.home()` → `%USERPROFILE%\.cato` — 46 call sites across 23 `.py` files.

Change the account, change every path. A daemon started by Task Scheduler as
SYSTEM, or by a wrapper script running as a different user, uses a completely
different state tree from your interactive shell — and neither will complain.

### Diagnose

```
whoami
.venv\Scripts\python.exe -m cato status
```

Compare the `Config:` line against the account you expect. Then check all four
candidate trees:

```
powershell -Command "Test-Path 'C:\Users\benst\.cato'"                    # True
powershell -Command "Test-Path 'C:\Users\benst\AppData\Roaming\cato'"     # False
powershell -Command "Test-Path 'C:\Users\Work\.cato'"                     # False
powershell -Command "Test-Path 'C:\Users\Work\AppData\Roaming\cato'"      # True
```

All four verified 2026-08-03. Find the running process and see who owns it:

```
powershell -Command "Get-Process python | Select-Object Id, Path, StartTime"
```

### Recover

1. **Do not copy state between trees to 'fix' it.** `cato.db` is a hash-chained
   ledger. Merging two chains produces a chain that will not verify, and you will
   have turned a confusing incident into §2.
2. Decide which tree is authoritative — `benst` for production, `Work` for
   development.
3. Stop everything. Relaunch as the correct account.
4. Verify the resolved paths with `cato status` **before** doing any work.
5. If a real action was recorded in the wrong tree, leave it there as evidence and
   note it. Do not try to relocate it.

### Prevent

Always confirm the `Config:` line before working. Before using any launcher in the
repo (`start_daemon.ps1`, `launch_daemon.ps1`, `start_cato.bat`, `cato_service.py`,
`install_autostart.py`, `scripts\watchdog.py` — **none reviewed or executed for
this documentation**), read it and confirm which account it runs as.

---

## 8. Corrupt config

### Symptom

`cato status` or `cato doctor` errors on load, or reports values you never set.

### Current baseline

**There is no `config.yaml` on this machine for either account** (verified). Cato
runs entirely on `CatoConfig` dataclass defaults, and `cato doctor` reports
`Config  NOT FOUND — run 'cato init' to create config`. That message is the
correct, healthy output today — it is not the incident.

### Recover

1. `%APPDATA%\cato\config.yaml` is plain YAML. Move it aside:

   ```
   move "%APPDATA%\cato\config.yaml" "%APPDATA%\cato\config.yaml.bad"
   ```

2. Run `cato status`. If it comes up on defaults, the config was the problem.
3. Regenerate with `cato init` (**UNVERIFIED — never run on this machine**), or
   hand-edit a corrected copy back into place.
4. Re-check with `cato doctor` and confirm `Config NOT FOUND` is gone.

### Approval policy corruption is handled differently — and safely

A missing or unparseable `docs/approval-policy.yaml` **never widens the gate**. It
falls back to the built-in policy (`cato/core/approval_policy.py:9-13`). An
unknown tier is coerced to `critical`. So a corrupt policy fails toward more
restriction, and the symptom is "everything needs approval", not "nothing does".

If you need to point at a different policy file, set `CATO_APPROVAL_POLICY`
(`approval_policy.py:611`).

### If the vault password is wrong

You will find out when the vault fails to open. Note the current state: **no
`vault.enc` exists anywhere**, so there is nothing to unlock, and
`CATO_VAULT_PASSWORD`'s live value is published in two git-tracked files. See
`RUNBOOK.md` §8 CRITICAL-3 before treating a vault problem as a routine incident.

---

## 9. Escalation — when to stop and get help

You are alone. "Escalate" means: stop, write down what you know, and do not
improvise. Stop and get a second pair of eyes for:

- Any ledger chain verification failure you cannot explain (§2).
- An unresolved INTENT on a **financial** tool where the external system's state
  is genuinely ambiguous after you looked (§1). Guessing here is how one approved
  payment becomes two.
- Evidence that a credential was used by an account that should not have it —
  which the ACLs in `RUNBOOK.md` §8 make plausible today.
- Anything that suggests the `benst` production `cato.db` or
  `conduit_identity.key` was modified by the `Work` account (CRITICAL-2).

In every one of those cases: create the STOP file, do not restart, do not retry,
and preserve the database files exactly as they are.
