# G1 Row 1 — Operator steps (deliverability)

**Do not** enable Cato live outreach or bulk autonomous sends.

---

## 0. Brevo domain auth (no SPF line = OK)

If Brevo shows **no SPF** for `surfacescore.com`, you do **not** need to edit IONOS SPF for Brevo. See `brevo-spf-not-required.md`.

1. Brevo → **Domains** → **surfacescore.com**.
2. Confirm **DKIM** and **DMARC** are green / authenticated.
3. Screenshot → `proof-artifacts/fp1/brevo-domain-auth-YYYY-MM-DD.png`.

Only edit IONOS SPF if Brevo **explicitly** shows an SPF record (dedicated IP setups).

---

## 1. mail-tester.com

1. Go to [https://www.mail-tester.com](https://www.mail-tester.com) and copy the test address shown.
2. Send **one** plain test email **from** `bstone@surfacescore.com` through Brevo (Brevo UI “Send a test” or outreach pipeline **dry-run off** for this single message only).
3. Subject: `FP1 mail-tester seed`
4. Return to mail-tester and open the score page.
5. Save screenshot as `proof-artifacts/fp1/mail-tester-YYYY-MM-DD.png`.
6. **Pass target:** score **≥ 8/10** (or document score if lower and fix issues listed).

---

## 2. Google Postmaster Tools

1. Go to [https://postmaster.google.com](https://postmaster.google.com) with a Google account you use for operations.
2. **Add property** → domain `surfacescore.com`.
3. Verify domain (DNS TXT record Google provides — add in IONOS).
4. After verification, screenshot **Domain reputation** and **SPF/DKIM/DMARC** status.
5. Save as `proof-artifacts/fp1/postmaster-domain-status.png`.

---

## 3. Twenty seed inboxes (≥18 inbox)

Use real addresses you control across providers (Gmail, Outlook, Yahoo, iCloud, etc.) — **20 total**.

1. Create `proof-artifacts/fp1/seed-test-manifest.json` (template provided).
2. Send **one** personalized test per seed (manual approval each — not Cato autonomous).
3. For each seed, record: provider, inbox vs spam, date.
4. Save 2–3 screenshots of inbox placement as `proof-artifacts/fp1/seed-inbox-samples-YYYY-MM-DD.png`.
5. **Pass:** ≥ **18/20** in **Inbox** (not Promotions-only unless you accept that as inbox per your standard).

---

## 4. Update loop proof card

1. Open `docs/loop-proof-card.md` Row 1.
2. Set **Sending domain** to `surfacescore.com`.
3. Set **Evidence** to `proof-artifacts/fp1/` (list files).
4. Set **Status** to `PASS` only when checklist R1-05, R1-10/11, and R1-12 are satisfied.

---

## 5. What not to do yet

- Do not set `g1_manual_loop_proven: true` until rows 1–6 pass.
- Do not set `live_outreach_enabled: true` in Cato config.
- Do not run 25-canary bulk until Row 1 is PASS.
