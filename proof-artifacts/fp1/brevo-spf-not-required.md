# Brevo SPF — not required (shared plan)

**Date:** 2026-06-02  
**Operator confirmation:** Brevo domain authentication for `surfacescore.com` shows **no SPF line**.

## What that means

On Brevo’s **shared** SMTP relay (`smtp-relay.brevo.com`):

- The **Return-Path** (envelope sender) is a **Brevo-owned** domain, not `surfacescore.com`.
- Mailbox providers check **Brevo’s SPF** for that hop — not your domain’s SPF TXT.
- **DMARC alignment** for your mail relies on **DKIM** signing as `bstone@surfacescore.com`, which you already published (`brevo1` / `brevo2` CNAMEs).

So adding `include:sendinblue.com` to IONOS is **optional** and often **not shown** by Brevo — it does not fix alignment on shared plans.

## What you already have (local DNS check)

| Record | Status |
|--------|--------|
| `brevo-code` TXT | Present — domain verified in Brevo |
| DKIM `brevo1` / `brevo2` CNAME | Present |
| DMARC `_dmarc` | Present (`p=none`) |
| SPF `@` | `v=spf1 include:_spf-us.ionos.com ~all` — for **inbound/IONOS mail**, not Brevo envelope |

## What to do instead of SPF edit

1. In Brevo → **surfacescore.com** → confirm **DKIM** and **DMARC** show **authenticated** (screenshot → `brevo-domain-auth-YYYY-MM-DD.png`).
2. Run **mail-tester** + **20 seed test** per `OPERATOR-STEPS.md`.
3. Do **not** add a second SPF TXT record “just in case” — one SPF per domain is enough.

## Exception (later)

If you buy a **dedicated IP** and Brevo uses **your** domain on Return-Path, Brevo will then show an SPF record — add that exact string in IONOS at that time.
