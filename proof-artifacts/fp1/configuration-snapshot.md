# Outreach + Cato configuration snapshot (no secrets)

**Date:** 2026-06-02

## Brevo / SMTP (ConduitScore outreach pipeline)

| Setting | Value |
|---------|--------|
| Config file | `Desktop/ConduitScore/conduit_outreach_pipeline/.env` (gitignored) |
| SMTP host | `smtp-relay.brevo.com` |
| SMTP port | `587` (STARTTLS) |
| SMTP login | `ad5b9e001@smtp-brevo.com` (redacted in git) |
| From name | `Ben` |
| From email | `bstone@surfacescore.com` |
| Daily cap (SMTP account JSON) | 40 (safety ratio may lower effective cap in code) |
| Auth test | See `smtp-auth-test-2026-06-02.log` |

## Unsubscribe

| Setting | Value |
|---------|--------|
| `UNSUBSCRIBE_BASE_URL` | `https://conduitscore.com/unsubscribe` |
| HTTP check | 200 OK — see `unsubscribe-url-check.txt` |
| Pipeline behavior | `List-Unsubscribe` + `List-Unsubscribe-Post: One-Click` when URL and per-row token exist (`gmail_sender.py`) |
| Token storage | SQLite `unsubscribe_tokens` in outreach DB |

## Cato night-shift (unchanged — no live outreach)

| Gate | Value |
|------|--------|
| `live_outreach_enabled` (config) | `false` |
| `g1_manual_loop_proven` (policy) | `false` |
| Forbidden From domains | `conduitscore.com`, `www.conduitscore.com` |
| Outreach engine path (policy) | `ConduitScore/conduit_outreach_pipeline` |

## Compliance docs

- `conduit_outreach_pipeline/ETHICS_AND_COMPLIANCE.md` — CAN-SPAM, unsubscribe, no deliverability guarantee
