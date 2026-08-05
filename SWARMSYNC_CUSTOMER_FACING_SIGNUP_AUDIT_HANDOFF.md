# SwarmSync Customer-Facing Signup Audit Handoff for Cato

This package gives Cato what it needs to execute the new customer-facing registration/login audit from:

`C:\Users\Administrator\Desktop\SwarmSync\Testing suites\SwarmSync_New_User_Registration_Login_Audit.md`

Use Cato as the execution agent. Do not invoke Kraken as a separate agent for this run. If Cato needs the Kraken reality-check persona/style, load the persona file at:

`C:\Users\Administrator\.codex\agents\Kraken.md`

## 1. Environment and URLs

Preferred test target: **local/staging**, not production, because the audit creates users, agents, API keys, wallets, duplicate signups, failed login attempts, and abuse-control attempts.

Known SwarmSync URLs:

- Production web: `https://swarmsync.ai`
- Production API: `https://api.swarmsync.ai`
- Production agents gateway: `https://swarmsync-agents.onrender.com`
- Local web: `http://localhost:3000`
- Local API: `http://localhost:4000`

Repo location:

`C:\Users\Administrator\Desktop\SwarmSync`

Recommended environment for this run:

- `SWARMSYNC_TEST_ENV=local`
- `SWARMSYNC_WEB_BASE_URL=http://localhost:3000`
- `SWARMSYNC_API_BASE_URL=http://localhost:4000`

Only run against production if explicitly approved and if test-account cleanup is acceptable.

## 2. Access and Credentials

No production secrets or admin passwords are included in this handoff.

Cato can execute the normal customer-facing portion with public UI/API access:

- Human signup via `/register` and API `POST /auth/register`
- Agent signup via `/register?type=agent` and API `POST /auth/register-agent`
- Login via `/login` and API `POST /auth/login`
- Logout via API `POST /auth/logout`
- Password reset via `/forgot-password`, `/reset-password`, API `POST /auth/forgot-password`, `POST /auth/reset-password`

For privileged wallet/funding/payment-state checks, Cato needs one of these before claiming full completion:

- A staging supervisor/admin account with permission to create users, inspect users, adjust wallets, and verify escrow/payment states.
- Or a staging/bootstrap API key with permission to create test users/agents, fund test wallets, force payment/escrow/refund/failure states, and inspect API key scopes.
- Or local database access through the SwarmSync `.env` and Prisma client, with permission to seed and clean up test records.

If none of those is provided, Cato must mark privileged checks as **not proven** and the final verdict cannot exceed `SAFE WITH LIMITS`.

## 3. Kraken Agent Interface

There is no separate Kraken HTTP endpoint for this audit.

Kraken is a persona/agent brief file, not a product API to call:

`C:\Users\Administrator\.codex\agents\Kraken.md`

If Cato is asked to take on the Kraken-style reality-check posture, Cato should read that file and apply its evidence-first standard, but Cato remains the executing agent. Do not look for `POST /kraken/run-e2e`; it is not part of SwarmSync.

## 4. Wallet and Billing Model

Current known repo facts:

- New agent registration uses `POST /auth/register-agent`.
- Agent wallet type options are `managed` or `own`.
- For `managed`, SwarmSync creates/manages the wallet.
- For `own`, the request must include an EVM address matching `0x` + 40 hex characters.
- New agent registrations are intended to receive sandbox credits.
- Canonical sandbox credit amount: `REGISTRATION_SANDBOX_CREDIT_USD = 50`.
- Source: `C:\Users\Administrator\Desktop\SwarmSync\packages\config\src\billing.ts`

Test-card/payment state notes:

- Stripe is present in the platform, but no Stripe secret/test card credentials are included here.
- If a staged Stripe test mode is configured, use Stripe test cards only in staging/local.
- If no payment test credentials are available, Cato must still verify UI copy, route access, role boundaries, and API key scope, but must mark escrow/refund/payout/payment-failure state checks as **blocked by missing privileged payment controls**.

Minimum balances for this audit:

- Agent signup sandbox balance expected: `$50` / `50 USD sandbox credits`.
- Insufficient-balance checks should attempt an operation above available test balance or use a privileged balance override if provided.
- Do not infer production money movement from sandbox credits.

## 5. Actual Auth/API Surface to Use

API base path is the API origin plus these NestJS auth routes:

- `GET /auth/check-username?username=<name>`
- `POST /auth/register`
- `POST /auth/register-agent`
- `POST /auth/login`
- `POST /auth/login/mfa`
- `POST /auth/logout`
- `POST /auth/refresh`
- `POST /auth/forgot-password`
- `POST /auth/reset-password`
- `POST /auth/verify-email`
- `POST /auth/resend-verification`
- `POST /auth/magic-link/request`
- `POST /auth/magic-link/consume`
- `POST /auth/session/exchange`

Human registration body:

```json
{
  "email": "test.human.buyer+signup-audit@test.swarm",
  "displayName": "Test Human Buyer",
  "password": "<secure test password>",
  "userType": "HUMAN"
}
```

Agent registration body:

```json
{
  "email": "test.agent.operator+signup-audit@test.swarm",
  "password": "<secure test password>",
  "username": "invoice_risk_review",
  "walletType": "managed",
  "agentDisplayName": "Invoice Risk Review Agent",
  "description": "Reviews vendor invoices and flags duplicate invoices, changed bank details, and payment risk before approval."
}
```

Important mismatch to test: the audit brief asks for username `invoice-risk-review-agent-signup-audit`, but the current API DTO only accepts lowercase letters, numbers, and underscores, max 20 chars. The API-compatible username above is `invoice_risk_review`.

## 6. Commands

Start local SwarmSync:

```powershell
cd C:\Users\Administrator\Desktop\SwarmSync
npm run dev
```

Frontend only:

```powershell
cd C:\Users\Administrator\Desktop\SwarmSync\apps\web
npm run dev
```

Backend only:

```powershell
cd C:\Users\Administrator\Desktop\SwarmSync\apps\api
npm run dev
```

Validation commands:

```powershell
cd C:\Users\Administrator\Desktop\SwarmSync
npm run lint
npm run typecheck
npm run test
cd apps\web
npm run test:e2e
```

Do not run `npm run build` locally on Windows for this repo; project docs say it times out locally.

## 7. Required Evidence Cato Must Return

Cato must return:

- Target environment and exact URLs tested.
- Whether a privileged admin/API/bootstrap path was available.
- Screenshots and/or Playwright traces for human signup, agent signup, login/logout, CTA routing, and protected-route checks.
- API request/response summaries for registration, login, logout, duplicate signup, username check, API key issuance, and forbidden admin/customer access attempts.
- Created human account email and resulting dashboard route.
- Created agent account username/email and resulting dashboard/profile route.
- Whether agent API credentials are issued immediately.
- Proof that any issued key is scoped and cannot access admin/customer routes.
- List of blocked checks caused by missing credentials, staging, email inbox, wallet admin, or payment controls.
- Final verdict exactly one of:
  - `SAFE TO PROMOTE`
  - `SAFE WITH LIMITS`
  - `NOT SAFE YET`

No final verdict is valid without actual test evidence.

## 8. Files in This Handoff

- `C:\Users\Administrator\Desktop\Cato\SWARMSYNC_CUSTOMER_FACING_SIGNUP_AUDIT_HANDOFF.md`
- `C:\Users\Administrator\Desktop\Cato\SWARMSYNC_CATO_AUDIT_PROMPT.md`
- `C:\Users\Administrator\Desktop\Cato\swarmsync_signup_audit.env.example`
- `C:\Users\Administrator\Desktop\Cato\swarmsync_signup_audit_test_data.json`
- Original source audit:
  `C:\Users\Administrator\Desktop\SwarmSync\Testing suites\SwarmSync_New_User_Registration_Login_Audit.md`
