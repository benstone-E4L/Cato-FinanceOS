# Flow: conduitscore-revenue-loop

Reference implementation for the ConduitScore **audit-as-cold-open** pipeline inside Cato Clawflows.

## Setup

1. Copy `examples/flows/conduitscore-revenue-loop.yaml` to `%APPDATA%\cato\flows\`.
2. Fill placeholders in `docs/conduitscore-asset-map.md` and `docs/night-shift-policy.yaml`.
3. Set `dry_run: false` only after **G1** on `docs/loop-proof-card.md`.

## Placeholders

| Key | Meaning |
|-----|---------|
| `prospect_manifest` | CSV/JSON path for one or many prospects |
| `url` | Prospect website URL for fidelity audit |
| `artifact_url` | Public verify URL for signed audit |

Pass via `flow.run` args or trigger_context.

## Run

```text
cato flow run conduitscore-revenue-loop
```

Or schedule via `%APPDATA%\cato\schedules\` with `skill: flow:conduitscore-revenue-loop`.

## Budget

`budget_cap: 500` = 500 cents ($5.00) max per run. Each step reserves against global daily/monthly caps too.

## Manual parity (Phase 1)

| Manual step | Flow step |
|-------------|-----------|
| P1-004 audit | genesis analyst |
| Draft email | genesis email |
| P1-005 send | send_email (requires Telegram approve — P2-CATO-008) |
