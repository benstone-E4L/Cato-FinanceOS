# How outreach personalizes company name and score

Cato does **not** guess the company name or AI visibility score in email copy. The **ConduitScore outreach pipeline** builds each row from your prospect list plus a live scan.

## What you put in (CSV or Google Sheet)

| Column | Role |
|--------|------|
| `domain` | Site to scan (required) |
| `receiver_email` | Who receives the email |
| `first_name` / `company_name` | Greeting and subject lines (`{{ company_name or domain }}`) |
| `icp_tag`, `industry_vertical` | Pick sequence track **A**, **B**, or **C** |
| `sequence_override` | Force A/B/C if set |

**Company name** comes from your sheet/CSV. The API does not rename the business — only you (or your list vendor) set `company_name`.

## API host (not the same as your sending domain)

| Purpose | Host |
|---------|------|
| **Scans + scores** (`POST /api/scan`) | `CONDUITSCORE_API_BASE` — production is **`https://conduitscore.com`** (see `CLAUDE.md`, `conduit_outreach_pipeline/.env.example`, extension `constants.ts`) |
| **Outreach email From** | `bstone@surfacescore.com` (Brevo) — **not** the API host |
| **Staging** | `https://staging.conduitscore.com` is documented for dev only; DNS is not live on this machine |
| **Local dev** | `http://localhost:3000` when running `npm run dev` in the ConduitScore repo |

Cato vault should set `CONDUITSCORE_API_BASE=https://conduitscore.com`. Cato does not
load or merge the outreach `.env`; it supplies vault values to `run_batch.py` once over
inherited stdin. Rescan links in emails use the same base (`links.py`).

## What the pipeline fetches automatically

1. **`scan_domain_cached(domain)`** calls ConduitScore `POST {CONDUITSCORE_API_BASE}/api/scan` (needs `CONDUITSCORE_API_KEY`).
2. **`overallScore`** from the scan becomes **`ai_visibility_score`** in the sheet and in templates as `{{ ai_visibility_score }}`.
3. **Top issue / fix / snippet** come from scan categories (`pick_top_issue`, `pick_top_fix`, `select_dynamic_snippet`).
4. **`classify_sequence()`** chooses track A (direct brand), B (agency), or C (ecommerce) from company name + tags — unless you override.
5. **`render_engine.build_context()`** + Jinja templates under `templates/sequences/{A|B|C}/1-5.html.j2` produce subject and HTML body (Halbert-style copy as of template version **1.2-halbert**).
6. **Send** uses Brevo SMTP when `SMTP_ACCOUNTS` / `BREVO_SMTP_*` are set (`gmail_sender.py`), else Gmail OAuth.

## What Cato does

- Tool **`outreach.run`** (dry-run by default) can spawn the pipeline CLI when G1 gates allow live sends.
- Before subprocess, Cato builds an allowlisted envelope from the **vault only** via `cato/core/outreach_credentials.py`. It sends that envelope through inherited stdin, while the child receives a minimal non-secret environment and skips dotenv loading.
- **`cato outreach status`** shows which keys are configured (never prints values).

## Changing copy vs changing data

| Want to change… | Where |
|-----------------|--------|
| Wording / tone | Edit `.j2` templates or `render_engine.SUBJECTS` in `conduit_outreach_pipeline` |
| Score or issues | Re-run scan (new API result); or wait for cache TTL |
| Company name in email | Update your CSV/sheet `company_name` column |
| Physical address in footer | `CANSPAM_POSTAL_ADDRESS` in Cato vault for Cato runs |
| Brevo templates in UI | Brevo dashboard (optional); pipeline sends rendered HTML/text from Jinja, not Brevo drag-and-drop templates |

## Related docs

- `docs/outreach-email-copy-halbert.md` — subject/body reference
- `docs/brevo-and-outreach-access.md` — Brevo + vault setup for Cato and automation
