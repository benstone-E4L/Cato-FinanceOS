# Genesis dispatch ungating — why it stays agent-level, and what Genesis-Agents must expose to change that

**Repo:** Cato (this repo). **Status:** decision record + requirements spec.
**Date:** 2026-08-22. **Task:** `t6-genesis-read-usability`.
**Verdict:** **(B) — pair-level ungating is NOT safe today.** The largest safe
subset remains agent-level. `operation` is now advertised so the existing
agent-level read path is reachable; nothing was widened.

Nothing in this document authorises an edit to the Genesis-Agents repository.
It states what that repository would have to publish for Cato to safely tier a
dispatch on the *(agent, operation)* pair. That is a separate repo with a
separate remote and a separate decision.

---

## 1. The question

Cato can already classify a *(agent, operation)* pair entirely on its own side:
`cato/xero_scope.py::operation_allowed()` over the closed enum
`OPERATION_SCOPE_FAMILY`, backed by
`cato/accounting/XERO_SCOPE_TO_AGENT_MAP.yaml`. So Cato *can* compute
"`genesis-e4l-controller` + `get_trial_balance` is a read".

The question is not whether Cato can compute a label. It is whether that label
**binds the actor**. It does not.

## 2. Evidence that the label does not bind

| # | Evidence | Source |
|---|---|---|
| E1 | Specialists hold their **own scoped Xero credentials** and literally post. "Genesis never holds Xero HTTP client" is explicitly marked obsolete. | `docs/AMENDMENT_2026-08-22_POSTING_MODEL.md`, four-role table + "Obsolete phrases" |
| E2 | An ungated dispatch still ships **model-written `task` prose** and `params` to an external host (SwarmSync / Render). Cato's authorization never reads `task` — but the remote specialist does, and the remote is what decides to post. | `cato/tools/genesis.py::_execute_inner` (envelope carries `task`, `params`) |
| E3 | The scope grant Cato injects, `allowed_xero_operations`, was computed **per agent, not per call**. For `genesis-e4l-ap` it contained `create_draft_bill` even on a dispatch that declared `operation=get_trial_balance`. So even a remote that perfectly honoured the injected list would still have been authorised to post. | `cato/xero_scope.py::build_dispatch_scope_params` (pre-change) |
| E4 | **No remote-side enforcement of the declared operation exists.** There is no capability-card fetch, no `.well-known` agent card, no per-operation credential exchange, and no VerifyAPI *pre-flight* client in Cato. `cato/tools/swarmsync_proof.py` talks to AuditProof/VerifyAPI as a **proof-record** API (`source_type`, delivery attestation), not as an authorisation boundary before the write. `probe_live_agents()` proves reachability only. | grep of `cato/` for `verify_api`, `agent_card`, `.well-known`, `xero_scoped_invoke` |
| E5 | The map's own override for the controller **affirms write capability**: `genesis-e4l-controller: writes: policy_conflict_resolution_only`. Cato must not model it as read-only. | `XERO_SCOPE_TO_AGENT_MAP.yaml::specialist_overrides` |

**Conclusion.** Ungating a write-capable specialist on a Cato-side operation
label would mean: Cato skips the operator, sends model-written prose to a remote
that holds live Xero write credentials, and relies on a label that nothing on
the remote reads. That is trusting a label that does not bind the actor. It is
the same failure class the module header of `cato/core/approval_policy.py`
records as a previously-fixed live bug, only with a structured token in place of
a substring.

## 3. What *is* non-forgeable and binding today

One signal, and it is agent-level:

> `specialist_writes_forbidden(slug)` — a Cato-side declaration, in
> `XERO_SCOPE_TO_AGENT_MAP.yaml`, that the credential the remote specialist
> holds carries **no Xero write scope at all**.

- **Non-forgeable by the model.** The model chooses *which* slug from a closed
  set (`FAIL_CLOSED_ACCOUNTING_ALLOWLIST`); it cannot author the write-capability
  declaration attached to that slug.
- **Binding on the actor.** The bound is the *credential*, not the instruction.
  Whatever prose reaches the remote, a credential without write scope cannot
  post. Blast radius is bounded by capability, not by intent.

Exactly one slug qualifies: `genesis-e4l-fs-integrity`
(`writes_forbidden: true`, constitution test `fs_integrity_write`).

**Residual risk, stated plainly (assumption A1).** This is still Cato asserting
what credential the remote holds. Cato cannot verify it. A capability card
(section 5) is what would turn A1 from an operator assertion into evidence.
Ungating fs-integrity is the pre-existing, separately-reviewed decision recorded
in `tests/test_genesis_subaction_tiering.py`; this task did not change it.

## 4. Why `genesis-e4l-controller` specifically cannot ungate

The scope map is **internally contradictory** about the controller, and the
contradiction is load-bearing:

- Derived view: the controller appears in **zero** `primary_write` lists across
  the whole map, and `allowed_operations("genesis-e4l-controller")` returns
  **five read operations and no write operation**.
- Declared view: `specialist_overrides.genesis-e4l-controller.writes:
  policy_conflict_resolution_only` — it may write, conditionally.

A fail-closed engine resolves that contradiction toward the *stronger*
capability claim. Treating "absent from every `primary_write` list" as proof of
read-only would ungate an agent the map itself says can write, and the condition
under which it writes ("policy conflict resolution") is precisely the
judgement-driven case where model-written prose decides. The controller gates.
Ben's instruction is the same: *"Controller must still gate on writes."*

The same trap catches two more: `genesis-e4l-cogs-cm` and
`genesis-e4l-commissions` have no write operation inside the closed enum, yet
both hold `primary_write` scope families in the map (`projects`,
`accounting.contacts`). "No write op in the enum" is not "no write capability".

## 5. What Genesis-Agents would have to expose for pair-level ungating

Ranked by strength. **Option 3 alone is sufficient; options 1 and 2 are not.**

### Option 1 — Signed capability card (necessary, not sufficient)

A per-slug document served by the Genesis host and **signed by a key Cato pins
out of band**, not by the caller:

```jsonc
{
  "slug": "genesis-e4l-controller",
  "issued_at": "2026-08-22T00:00:00Z",
  "expires_at": "2026-09-22T00:00:00Z",
  "xero_scopes_held": ["accounting.reports.trialbalance.read"],
  "write_scopes_held": [],
  "operations": {"get_trial_balance": "read", "create_draft_bill": "write"},
  "sig": "<ed25519 over the canonical JSON; key id pinned in Cato config>"
}
```

Requirements: signature verified against a pinned key (an unsigned or
unverifiable card is treated as absent, therefore gates); `expires_at` honoured
(expired gates); fetched over TLS; and the response can never *widen* beyond
`XERO_SCOPE_TO_AGENT_MAP.yaml` — the effective grant is the **intersection** of
card and map. It upgrades assumption A1 to evidence, and it still only supports
**agent-level** ungating, because a card describes the agent, not the call.

### Option 2 — Per-call scoped declaration echo (insufficient on its own)

The remote echoes `declared_xero_operation` and refuses anything outside it.
Cato now ships that field (section 6). Worth having as defence in depth, but an
echo is not enforcement: it is the same actor that would violate the constraint
telling Cato it did not. It cannot justify ungating.

### Option 3 — Per-operation credential scoping (sufficient)

The specialist obtains a Xero credential **scoped to the declared operation for
that dispatch** — a short-lived, per-call token minted by a broker that neither
Cato's model nor the specialist's model controls. Then the label binds, because
the credential cannot exceed it. Concretely, either:

- a token-exchange step where Cato's dispatch (agent + operation) is exchanged
  for a downscoped credential the specialist must present; or
- distinct read-only slugs — e.g. `genesis-e4l-controller-readonly` holding a
  credential with no write scope. This makes pair-level ungating unnecessary:
  it converts the problem back into the agent-level signal Cato already trusts,
  and is by far the cheapest path to a genuinely ungated controller read.

**Recommendation:** ship Option 3 in its second form (read-only sibling slugs)
plus Option 1 to make the claim verifiable. Option 2 is a nice-to-have.

### Acceptance tests Cato adds when that lands

1. Card signature invalid / key unpinned / expired / absent → **gate**.
2. Card claims read-only but `XERO_SCOPE_TO_AGENT_MAP.yaml` grants a write
   family → **gate** (intersection, never union).
3. Card claims a write scope not in the map → the grant does **not** widen.
4. `MONEY_DOMAIN_AGENTS` / `IMMUTABLE_DENIED_AGENTS` remain denied regardless of
   any card they present.
5. A read-only sibling slug ungates; its write-capable parent still gates.

## 6. What this task changed in Cato

1. **`operation` is advertised** in `GENESIS_TOOL_SCHEMA` as a closed enum
   sourced from `OPERATION_SCOPE_FAMILY`. Previously the parameters object was
   `additionalProperties: false` and never named `operation`, so a top-level
   declaration was schema-illegal and the model was never told the key existed —
   the sub-action tiering path was dead code. Reach in practice was 0 of 14.
2. **The outbound grant is narrowed, never widened.** When a dispatch declares
   an operation that is already on the specialist's computed
   `allowed_xero_operations`, Cato ships `allowed_xero_operations: [that one]`
   plus `declared_xero_operation`. This closes E3 on Cato's side and is the hook
   Option 2/3 would consume. It changes no approval decision.
3. **No tiering logic changed.** Q1 (`specialist_writes_forbidden`) remains
   load-bearing; `operation` is still consulted only after Q1 has already proved
   the call cannot write, so it can gate an otherwise-ungated call and never the
   reverse.

## 7. Reach — before / after

Declared read operation, one of the seven `*.read`-family operations in the
enum. "Reachable" means the model can actually emit the declaration.

| Specialist | Cato-side write capability | Before (as shipped) | Before (if the model guessed `params.operation`) | After |
|---|---|---|---|---|
| `genesis-e4l-fs-integrity` | none (`writes_forbidden: true`) | GATE — unreachable | ungates 7/7 | **UNGATES 7/7** |
| `genesis-e4l-controller` | `writes: policy_conflict_resolution_only` | GATE | GATE | GATE |
| `genesis-e4l-ap` | `create_draft_bill`, `attach_file_to_bill` | GATE | GATE | GATE |
| `genesis-e4l-ar` | `create_draft_invoice`, `attach_file_to_invoice` | GATE | GATE | GATE |
| `genesis-e4l-cash` | `create_bank_transaction` | GATE | GATE | GATE |
| `genesis-e4l-treasury` | `create_bank_transaction` | GATE | GATE | GATE |
| `genesis-e4l-stripe` | `create_bank_transaction` | GATE | GATE | GATE |
| `genesis-e4l-journals` | `create_draft_manual_journal` | GATE | GATE | GATE |
| `genesis-e4l-intercompany` | `create_draft_manual_journal` | GATE | GATE | GATE |
| `genesis-e4l-close` | `create_draft_manual_journal` | GATE | GATE | GATE |
| `genesis-e4l-revenue` | `create_draft_invoice` | GATE | GATE | GATE |
| `genesis-e4l-shopify` | `create_draft_invoice` | GATE | GATE | GATE |
| `genesis-e4l-cogs-cm` | `primary_write` on `projects` | GATE | GATE | GATE |
| `genesis-e4l-commissions` | `primary_write` on `accounting.contacts` | GATE | GATE | GATE |
| **Total ungating** | | **0 of 14** | 1 of 14 | **1 of 14** |

Read that honestly: **the ungated set did not grow.** What changed is that the
one member of it is now reachable by the model instead of being dead code. The
other thirteen are blocked by a capability fact, not by a missing feature —
section 5 is the only thing that moves them.

The `after` column is regenerated mechanically by
`tests/test_genesis_operation_declaration.py::TestReachTable`, so this table
cannot silently drift from the code.

## 8. Adjacent finding (not fixed here)

Cato's own Xero tooling (`cato/tools/xero_mcp.py`) has **no row in the approval
policy at all**, so every Cato-side Xero call — including a pure
`get_trial_balance` — resolves `unknown_tool_default_require` and gates. Routing
genuine reads to Cato's own credential is therefore not an available workaround
today. Adding those rows is a separate, deliberate widening decision and was out
of scope for this task.
