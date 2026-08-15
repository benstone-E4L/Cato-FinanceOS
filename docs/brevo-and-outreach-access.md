# Brevo and outreach access (Cato + ConduitScore pipeline)

Secrets stay **out of git**. Cato uses one authority:

1. **Cato vault** `%APPDATA%\cato\vault.enc` — the only credential source when Cato or the agent runs `outreach.run`.

The external pipeline may retain a legacy local `.env` for manual, non-Cato runs. Cato
does not read it, merge it, or copy values from it. The Cato bridge sends a versioned
one-shot credential envelope through inherited stdin; the child holds it in process
memory, skips dotenv loading, and consumes/clears it after the run.

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

## Cato-to-pipeline channel

`run_batch.py` is reserved for the Cato bridge and requires the inherited stdin
credential envelope. Missing, malformed, unknown-key, or incomplete envelopes fail
before pipeline work. Credential values never travel in environment variables,
command-line arguments, or files.

Manual pipeline commands remain external to Cato's credential boundary and must not
be used as evidence for Cato runtime acceptance.

## Safety (night-shift)

- `live_outreach_enabled` / G1 gates still block autonomous live sends until proof artifacts are done.
- `outreach.run` defaults to **dry_run=true**.
- Real sends need approval + policy (see `docs/night-shift-policy.yaml`).

## DNS / deliverability

Sending domain: **surfacescore.com**, From **bstone@surfacescore.com**. Row 1 proof checklist: `proof-artifacts/fp1/` and `docs/loop-proof-card.md`.
