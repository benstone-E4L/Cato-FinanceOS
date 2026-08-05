# Known Limitations and Deferred Work

What this system does not do, cannot currently do, or does differently from how it
reads. Written so an operator finds the gap here rather than in production.

## Current launch boundary (2026-08-05)

- The supported product surface is the Tauri desktop application. The legacy
  loopback dashboard remains an operator/debug surface, not a second canonical
  FinanceOS product.
- No signed installer or published release is currently tied to the audited
  GitHub commit. Local tests do not establish production parity.
- The legacy dashboard exchanges its single-use CLI handoff for an expiring,
  HttpOnly, SameSite browser session. The daemon token is not rendered into its
  HTML or JavaScript and is not placed in its WebSocket URL.
- UI status colors are informational only. A status label does not prove an
  external integration is healthy unless the associated runtime check says so.

Verified 2026-08-03 against Cato commit `8731f21`.

**A runbook that hides a gap is worse than no runbook.** Everything below is a
gap.

> **Concurrency notice.** A failure-mode audit was modifying this repository while
> these documents were written. These notes describe **committed** state at
> `8731f21`. Two limitations (§2, §4) have uncommitted fixes in flight and are
> flagged as such. Line numbers will drift — prefer symbol names and `grep`. See
> `RUNBOOK.md` for the full list of modified files.

---

## 1. The daemon has never been started during this remediation

**Last actual run: 2026-06-14.** Evidence: `C:\Users\benst\.cato\cato.db` last
write 2026-06-14 15:25:18. Nothing in this remediation cycle started it.

That means:

- No startup sequence in `RUNBOOK.md` §3 has been observed working.
- `cato start`, `cato stop` and `cato init` are verified to **exist** in
  `cato/cli.py` (lines 472, 633, 142) and their source was read — but none has
  been executed.
- No model call has been made. Budget counters read `Calls today: 0`,
  `Calls this month: 0`.
- No end-to-end path — gate → dispatch → ledger `CONFIRMED` — has been exercised
  by a running daemon at this commit.

Everything verified in `VERIFICATION.md` is offline or read-only: the test suite,
CLI read commands, database inspection, source reading, and one live HTTP call to
Genesis. **That is a real and important scope limit. Do not read "2435 tests
passed" as "the system runs."**

The first real start is an experiment. Treat it as one.

---

## 2. Approval gates are unreachable in the shipped configuration

> **Status: uncommitted fix in flight.** At committed `8731f21` this limitation is
> real — verified: `git show HEAD:cato/safety.py` contains no
> `_defers_to_approval_gate`. The concurrent audit has added that method in the
> working tree so that a positively classified, policy-gated tool **defers** to
> the approval gate rather than being denied, while unclassified and un-gated
> tools are still denied outright. Check with
> `grep -n "_defers_to_approval_gate" cato\safety.py` — a match means this
> limitation is being retired.

With `safety_mode: "strict"` (the default, `cato/config.py:178`) and a headless
daemon, `SafetyGuard.check_and_confirm` denies **any** HIGH_STAKES tool at gate 3,
before the approval-ticket gate at gate 6 is ever reached
(`cato/agent_loop.py:2416` vs `:2457`; `cato/safety.py:383-390`).

**The Telegram approval flow is only reachable when an operator sets
`safety_mode: "off"`.**

This is fail-closed, not a bypass — nothing dangerous executes. But it means the
approval system you may believe is protecting you has, in this configuration,
never been exercised in production. A gate that never fires is not a tested gate.

Compounding it: anything unrecognised is classified `HIGH_STAKES`
(`UNCLASSIFIED_TIER`), so the deny surface is wider than the explicit tier table
suggests.

This is an **operator decision, not a bug**. `RUNBOOK.md` §4 spells out the
tradeoff. Nobody has made the decision yet.

---

## 3. Model routing only ever selects Sonnet

The routing policy in `cato/model_policy.py` is a real, deterministic,
descriptor-driven design: three tiers, task-type mapping, risk floors that
override upward, per-band cost ceilings, and escalation capped at 2.

**None of it is reachable from the agent loop**, because
`cato/agent_loop.py:1943-1944` constructs its `TaskDescriptor` with
`task_type=TaskType.GENERAL_TOOL_USE`, hardcoded. `GENERAL_TOOL_USE` maps to
`SONNET` (`model_policy.py:228`).

So:

- Interactive chat always lands on `claude-sonnet-5`.
- `claude-haiku-4-5` routing (`invoice_line_extraction`, `document_classification`)
  is **never exercised**.
- `claude-opus-5` routing (`ledger_posting_decision`, `financial_reasoning`,
  `policy_interpretation`, `audit_synthesis`) is **never exercised**.

Reaching the other tiers requires an E4L caller that builds a real descriptor.
Nothing currently does — which is the same as saying the FinanceOS integration in
§8 is what would use it.

Related cosmetic confusion: `cato status` prints `Model: openai/gpt-4o-mini`. That
is the `CatoConfig` dataclass default at `cato/config.py:83`, not what routing
selects. Do not read it as the live model.

---

## 4. `cato/cli.py:901` — BudgetManager gets a config object where a float is expected

> **Status: FIXED in the working tree, not yet committed.** Verified both ways:
> `git show HEAD:cato/cli.py | sed -n '901p'` still returns
> `budget = BudgetManager(cfg)`, while the working-tree copy now passes
> `session_cap=`, `monthly_cap=`, `daily_cap=` keywords with an explanatory
> comment. The description below documents the committed defect. Confirm which
> you have with `grep -n "BudgetManager(cfg)" cato\cli.py` — no match means the
> fix is present.

Verified at commit `8731f21`. `cato/cli.py:901`, inside `cato night-shift status`:

```python
budget = BudgetManager(cfg)
```

`BudgetManager.__init__` (`cato/budget.py:119-125`) is:

```python
def __init__(
    self,
    session_cap: float = 3.00,
    monthly_cap: float = 20.00,
    daily_cap: float = 3.00,
    budget_path: Optional[Path] = None,
) -> None:
```

The `CatoConfig` object binds to `session_cap`. Because `session_cap` is
**accepted for backward compatibility but not enforced** (`budget.py:112-114` —
"logged at INFO and persisted as an informational field"), the bad argument is
swallowed silently. `monthly_cap` and `daily_cap` fall back to their defaults.

**Consequence: `cato night-shift status` reports budget against $3 daily / $20
monthly regardless of what you configured.** No error, no warning. The number is
simply wrong.

For contrast, every other call site does it correctly — `cato/cli.py:534`
(the daemon), `:267`, `:802`, `:1761`, and `cato/doctor.py:242-246` all pass
explicit keyword arguments.

**Not fixed here.** These are documentation-only changes and another agent is
running a failure-mode audit in this repo concurrently. The one-line fix is to
pass the same keywords the other five call sites use.

Operational workaround: do not trust `cato night-shift status` budget figures. Use
`cato status`, which reads `CatoConfig` directly.

---

## 5. Proof bundles are currently unsigned

`CONDUIT_INVOICE_SECRET` is read at `Genesis Agents\conduit_verifier.py:83` and is
**absent from `Genesis Agents\.env`**. When unset, `conduit_verifier.py:668-674`
falls back to a plain SHA-256 content hash and logs:

```
CONDUIT_INVOICE_SECRET not set — using unsigned SHA-256 digest for proof sig
```

A content hash proves **integrity** (the bytes did not change). It does not prove
**origin** (that this system produced them). Anyone who can compute SHA-256 can
produce a matching "signature" for content they wrote themselves.

Do not present current proof bundles as cryptographically attributable. Set
`CONDUIT_INVOICE_SECRET` if you need that property.

---

## 6. No vault; credentials are plaintext

No `vault.enc` exists anywhere (verified absent from `C:\Users\benst\.cato\`,
`C:\Users\Work\.cato\`, and the repo root). `cato doctor` reports
`Vault  NOT FOUND`.

Every credential in `PREREQUISITES.md` §6 and §7 is plaintext in a `.env` file,
protected only by filesystem ACLs — and those ACLs are currently wrong in two
distinct ways. The live `CATO_VAULT_PASSWORD` value is additionally present
verbatim in two git-tracked files.

**All three items are OUTSTANDING and awaiting operator action.** Full detail,
verification commands and remediation commands are in `RUNBOOK.md` §8. Summary:

1. `ACEMAGIC-WINDOW\CodexSandboxUsers` has `(OI)(CI)(RX)` on
   `C:\Users\Work\Desktop`, inherited onto both `.env` files. Members:
   `CodexSandboxOffline`, `CodexSandboxOnline`.
2. `ACEMAGIC-WINDOW\Work` has `(OI)(CI)(F)` on the entire `C:\Users\benst`
   profile, reaching `conduit_identity.key` and `cato.db`.
3. `CATO_VAULT_PASSWORD`'s live value appears in `CLAUDE.md` and
   `PROJECT_BLACKBOX_AUDIT.md`, both git-tracked, and no vault exists to protect.

The vault migration path (`cato init`, `cato vault set`) is **UNVERIFIED** — those
commands exist but have never been run on this machine.

---

## 7. No `CATO_HOME`; the launching account silently decides everything

There is no environment variable that pins Cato's state root. Verified: zero
matches for `CATO_HOME` under `cato/`. State resolves two different ways, both
from the launching Windows profile:

- `cato.platform.get_data_dir()` → `%APPDATA%\cato`
- `Path.home()` → `%USERPROFILE%\.cato` — 46 occurrences across 23 `.py` files

So Cato writes to **two roots**, and both move with the account. A daemon started
by a scheduled task, a service wrapper, or a different console session will use a
different state tree from your interactive shell, with no error and no warning.

Current split, verified:

- `C:\Users\benst\.cato\` — production, last write 2026-06-14,
  `cato.db` with `audit_log` 44 / `conduit_billing` 44 / `conduit_bundle_chain` 14,
  **and no `ledger_records` table at all.**
- `C:\Users\benst\AppData\Roaming\cato\` — **does not exist**, which proves this
  build of Cato has never been imported under the `benst` account
  (`get_data_dir()` calls `mkdir(exist_ok=True)` on every import).
- `C:\Users\Work\.cato\` — does not exist.
- `C:\Users\Work\AppData\Roaming\cato\` — active dev tree, created 2026-08-01,
  ledger empty.

`INCIDENTS.md` §7 covers the symptoms and recovery. There is no clean fix short of
introducing an explicit state-root variable, which is a code change and is not
made here.

---

## 8. E4L FinanceOS integration — NOT BUILT

**Reconnaissance only.** No code has been written, no endpoint called, no
credential issued. Everything below is what a future implementer must design
around. It is recorded here because each item is a trap, not because any of it
works.

> The FinanceOS repository was **not opened** during this work, by instruction.
> This section is second-hand and should be re-verified against the source before
> anyone builds against it.

### Shape

HTTP API plus a worker. **There is no CLI.** Any integration is HTTP.

### Auth — the unresolved blocker

Authentication uses a **capability token bound to one `intent_id`**, signed with
`AGENT_CAPABILITY_SIGNING_SECRET`.

**No mint endpoint exists.** There is no discovered way to obtain a capability
token programmatically. Until token issuance is resolved, no integration can
authenticate. This is the single item that blocks the rest.

### Idempotency — a success that looks like a failure

- **There is no `Idempotency-Key` header.**
- Duplicate suppression returns **HTTP 503** with the body
  `"That request is already queued."`
- **That 503 means SUCCESS.** The request was accepted and deduplicated.

Any HTTP client with conventional retry-on-5xx logic will treat this as a
transient failure and retry — which is exactly the behaviour the deduplication
exists to prevent. **Special-case this string before writing any retry loop.**

### Money representation

Money is `numeric(14,2)` in the database and is **returned as strings** over the
wire. Parse to a decimal type. Do not parse to a float, and do not do arithmetic
on the strings.

### Approvals — E4L owns them

**E4L owns approvals. Cato relays. Cato never approves.** Cato's own approval
system governs Cato's tools; it has no authority over an E4L decision.

### A 202 is not an applied decision

`src/modules/index.ts` **does not exist**, so decision jobs terminate in the
`deferred` state. A `202 Accepted` means the job was queued and then deferred — it
does **not** mean the decision was applied.

**Confirm outcomes by polling `GET /api/intents/:id`.** Never infer an applied
decision from the 202.

### Deferred work required before any of this can be built

1. Resolve capability-token issuance. Nothing else can start until this is done.
2. Build a client that treats `503 "That request is already queued."` as success.
3. Enforce idempotency above the model call (see §9).
4. Construct real `TaskDescriptor`s so financial work routes to Opus rather than
   the hardcoded Sonnet path (§3).
5. Poll `GET /api/intents/:id` for terminal state; never trust the 202.
6. Decimal handling end to end.

---

## 9. Idempotency above the model call is declared but not enforced

The ledger has genuine idempotency: `recorded_action` accepts an
`idempotency_key` and raises `DuplicateActionError` if the key was already used,
"so a post-crash replay cannot repeat a side effect"
(`cato/audit/ledger.py:875-879`). `cato/agent_loop.py:2330` derives that key per
(session, tool call).

**That protects the ledger, not the counterparty.** There is no idempotency
enforcement above the model call — nothing prevents the same logical request being
issued twice through two different tool calls, or the same intent being retried
after a crash where the remote side effect already landed but Cato died before
recording it.

Combined with the FinanceOS 503-means-success behaviour (§8), this is the highest
risk area in any future financial integration. Design for it explicitly. Do not
assume the ledger's key gives you end-to-end exactly-once.

---

## 10. No live Xero write has ever occurred

Never, at any point. There is no evidence of a successful write to Xero from this
system, and no verification in `VERIFICATION.md` touches it. Any claim that Xero
integration works is unsupported.

---

## 11. Test baseline: 26 failures and 30 errors, fully attributed

```
26 failed, 2435 passed, 10 skipped, 4 deselected, 53 warnings, 30 errors in 131.28s
```

Every failure and error is in `tests/pipeline/test_pipeline_components.py`. Two
causes, both environmental:

1. Hardcoded `C:\Users\Administrator\...` paths at lines 25-27, for a Windows
   profile that does not exist on this machine.
2. Missing external CLIs — `codex` (not on `PATH`) and `cursor-agent` (not in
   `%LOCALAPPDATA%\cursor-agent\versions`).

The `4 deselected` are the `live`-marked tests excluded by
`pyproject.toml:105` (`addopts = "-m 'not live' --ignore=tests/test_playwright_ui.py"`).

**This is a known, attributed condition — not a regression and not a mystery.** It
is nonetheless a real limitation: 56 tests provide no signal, and the pipeline
components they cover are effectively untested here. The proper fix is to
parametrise those paths and skip cleanly when the external CLIs are absent. Not
done — documentation-only scope.

**A failure outside `tests/pipeline/` is new and real.** Investigate it.

---

## 12. Genesis operating constraints

- **Render free tier.** 30s proxy timeout. Warm latency up to ~15s on
  `/marketplace/search` and `/.well-known/agents.json` — measured 13.44s on
  `/.well-known/agents.json`, 0.36s on `/health`, 2026-08-03. Thin margin.
- **Cold start has NEVER been measured.** Nobody has observed Genesis waking from
  idle. It may routinely exceed the 30s proxy timeout on the first call after a
  quiet period. Retry advice in `INCIDENTS.md` §4 is explicitly a guess until
  someone measures it.
- **Genesis has no venv.** Its tests run under Cato's interpreter. Convenient, but
  it means Genesis has no independently pinned dependency set on this machine.
- **Escrow is off and should stay off.** `escrow_permitted()` requires
  `GENESIS_DEPLOYMENT_PROFILE=swarmsync-marketplace`; the variable is unset, so it
  returns `False`. This is the intended safe state, verified by
  `tests/test_escrow_containment.py:41`.

---

## 13. Things that do not exist — do not go looking for them

Saving the next reader an hour:

| Does not exist | Use instead |
|---|---|
| `CATO_HOME` environment variable | Nothing. Control it by choosing the launching account. |
| `cato backup` | `copy` the database files by hand (`RUNBOOK.md` §6). |
| `cato ledger recover` | `LedgerMiddleware.record_recovery()` in Python (`INCIDENTS.md` §1). |
| `cato approval` command group | Read `docs/approval-policy.yaml`; verify via the test suite. |
| A ledger repair tool | Deliberate. Restore a backup or start a fresh chain, and write down which. |
| `%APPDATA%\cato\config.yaml` | Not present for either account. Create with `cato init` (UNVERIFIED). |
| `vault.enc` | Not present anywhere. See §6. |
| `C:\Users\benst\.cato\skills\` | Not present. |
| `ledger_records` table in the production `cato.db` | Not present. That DB predates the Causal Action Ledger. |
| A FinanceOS CLI | HTTP API and worker only (§8). |
| A FinanceOS capability-token mint endpoint | Unresolved blocker (§8). |
| `Idempotency-Key` header on FinanceOS | 503-means-success instead (§8). |
| `src/modules/index.ts` in FinanceOS | Absent — decision jobs terminate `deferred` (§8). |

---

## 14. Scope of this documentation

Written from: reading source at commit `8731f21`, running the test suite, running
read-only CLI commands, inspecting both SQLite databases read-only, checking
filesystem ACLs, and one live HTTP probe of Genesis.

Not written from: a running daemon, a live model call, a live Xero write, a
FinanceOS call, an executed startup wrapper, or the FinanceOS source tree (which
was not opened, by instruction).

Where a command was not executed, `VERIFICATION.md` §8 says so and names what
would confirm it. Where a fact could not be established, these documents say
**UNVERIFIED** rather than guessing.
