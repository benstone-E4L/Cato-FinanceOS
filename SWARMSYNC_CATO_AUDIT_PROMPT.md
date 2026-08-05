# Prompt for Cato

You are Cato executing a customer-facing SwarmSync signup/login audit. Do not invoke Kraken as a separate agent. If you need the Kraken reality-check persona, read:

`C:\Users\Administrator\.codex\agents\Kraken.md`

Primary audit file:

`C:\Users\Administrator\Desktop\SwarmSync\Testing suites\SwarmSync_New_User_Registration_Login_Audit.md`

Handoff/context file:

`C:\Users\Administrator\Desktop\Cato\SWARMSYNC_CUSTOMER_FACING_SIGNUP_AUDIT_HANDOFF.md`

Environment template:

`C:\Users\Administrator\Desktop\Cato\swarmsync_signup_audit.env.example`

Test data:

`C:\Users\Administrator\Desktop\Cato\swarmsync_signup_audit_test_data.json`

Execute the audit end-to-end against the configured target. Prefer local/staging. Do not test destructive payment, escrow, refund, payout, or wallet mutation states against production unless explicitly approved and using test-mode credentials.

Your goal is to determine whether a brand-new human user and a brand-new agent/operator can register, log in, access the right product areas, and avoid unsafe access to the wrong areas.

Evidence rules:

- Every pass/fail claim needs evidence: screenshot, Playwright trace, API response summary, command output summary, or file/line reference.
- If credentials or privileged tooling are missing, mark that scope `blocked`, not `passed`.
- Do not soften the final verdict.
- The final verdict must be exactly one of `SAFE TO PROMOTE`, `SAFE WITH LIMITS`, or `NOT SAFE YET`.

Minimum run:

1. Confirm top-nav routes: `Log In -> /login`, `Sign Up -> /register`.
2. Test `/register`, `/register?type=human`, `/register?type=agent`, URL sync, card selection, back/refresh behavior, copy, and fields.
3. Register the human test account and validate duplicate, weak password, invalid email, password mismatch, missing required fields, and terms if present.
4. Register the agent test account and validate duplicate username, invalid email, invalid endpoint or wallet fields, missing required fields, and script-like payloads.
5. Confirm whether agent API credentials are issued, shown once, scoped, and unable to access admin/customer APIs.
6. Test `/login`, logout, wrong password, nonexistent account, repeated failed attempts, refresh/session behavior, protected routes, and browser-back after logout.
7. Verify public/human/agent/admin permission matrix as far as available credentials allow.
8. Verify wallet/payment/escrow states only if staging admin/bootstrap/payment controls are available.
9. Return files changed or tests added if you create automation.
10. Return exact commands run and evidence artifact paths.

Use the API surface documented in the handoff. Note this current API constraint: agent usernames are lowercase letters, numbers, and underscores only, max 20 chars. Use `invoice_risk_review` as the API-compatible username if the UI/API rejects the longer hyphenated username from the source audit.
