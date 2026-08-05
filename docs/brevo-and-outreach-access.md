# Brevo and outreach access (Cato + ConduitScore pipeline)

Secrets stay **out of git**. Two places hold them:

1. **ConduitScore** `conduit_outreach_pipeline/.env` (local, gitignored) — used when you run the pipeline directly.
2. **Cato vault** `%APPDATA%\cato\vault.enc` — used when Cato or the agent runs `outreach.run` (vault overrides `.env` for the same key names).

## Keys to store

| Key | Purpose |
|-----|---------|
| `BREVO_SMTP_LOGIN` | Brevo SMTP user (e.g. `…@smtp-brevo.com`) |
| `BREVO_SMTP_KEY` | Brevo SMTP password (xsmtpsib-…) |
| `BREVO_API_KEY` | Optional — REST API for template/list edits in Brevo UI automation |
| `SMTP_HOST` | Usually `smtp-relay.brevo.com` |
| `SMTP_PORT` | Usually `587` |
| `SENDER_EMAIL` | Verified sender, e.g. `bstone@surfacescore.com` |
| `SENDER_NAME` | e.g. `Ben` |
| `CANSPAM_POSTAL_ADDRESS` | `2038 S Bullrush Pkwy, Lehi, UT 84043` |
| `CONDUITSCORE_API_KEY` | Live scans for scores in email |
| `CONDUITSCORE_API_BASE` | API host — **`https://conduitscore.com`** (not surfacescore.com) |

## One-time setup (you)

With vault unlocked (`CATO_VAULT_PASSWORD` set when starting Cato):

```text
cato vault set BREVO_SMTP_LOGIN
cato vault set BREVO_SMTP_KEY
cato vault set SENDER_EMAIL
cato vault set CANSPAM_POSTAL_ADDRESS
cato vault set CONDUITSCORE_API_KEY
```

Paste each value at the prompt (nothing is echoed).

Check without exposing values:

```text
cato outreach status
cato vault list
```

## Brevo web UI (templates & automation)

- **Login** stays on your Brevo account — agents do not need your Brevo password in the repo.
- **SMTP** sends the HTML/text the pipeline already rendered (Jinja **1.2-halbert**). You only need Brevo UI changes if you switch to Brevo-hosted templates or workflows.
- **Optional REST**: store `BREVO_API_KEY` in vault if you later add scripts to update Brevo templates via API; not required for current SMTP sends.

## Pipeline `.env` mirror

Keep the same variables in:

`C:\Users\Administrator\Desktop\ConduitScore\conduit_outreach_pipeline\.env`

so manual runs (`python run_batch.py`, tests) work without starting Cato. Cato subprocesses load that file then apply vault overrides.

## Safety (night-shift)

- `live_outreach_enabled` / G1 gates still block autonomous live sends until proof artifacts are done.
- `outreach.run` defaults to **dry_run=true**.
- Real sends need approval + policy (see `docs/night-shift-policy.yaml`).

## DNS / deliverability

Sending domain: **surfacescore.com**, From **bstone@surfacescore.com**. Row 1 proof checklist: `proof-artifacts/fp1/` and `docs/loop-proof-card.md`.
