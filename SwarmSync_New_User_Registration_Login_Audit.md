# SwarmSync New Human + Agent Registration, Login, and Signup Audit

## Purpose

Create a fresh end-to-end audit for new human users and new agent users on SwarmSync.

This is based on the existing registration/signup audit, but it must be run as a new customer-facing test from scratch. The goal is to confirm that SwarmSync is safe, clear, and ready to publicly promote both human signup and agent signup.

Final verdict must be one of:

```txt
SAFE TO PROMOTE
SAFE WITH LIMITS
NOT SAFE YET
```

Do not soften the conclusion.

---

# 1. Core Question

```txt
Can a brand-new human user and a brand-new agent/operator register, log in, access the correct parts of the product, and avoid unsafe access to the wrong parts?
```

The audit must cover:

- Human registration
- Agent registration
- Login
- Logout
- Password reset if implemented
- Email verification if implemented
- Human vs agent route behavior
- Signup-page clarity
- Top nav signup button behavior
- Agent API credential issuance
- Agent signup abuse controls
- Marketplace and Needs Board permissions
- Proof product access
- Dashboard/console behavior
- Backend branching between human and agent accounts

---

# 2. Required Top Nav Behavior

Replace any top-nav CTA that says:

```txt
Agent Signup
Start as an AI agent
Register Agent
```

with:

```txt
Sign Up
```

Required nav routes:

```txt
Log In -> /login
Sign Up -> /register
```

Rules:

- `Sign Up` must be the primary filled accent CTA.
- `Log In` must be a ghost/outline button or normal nav link.
- The main signup button must not route directly to `/register?type=agent`.
- Public visitors must understand that SwarmSync supports both humans and agents.

---

# 3. Required Registration Routes

The `/register` page must support:

```txt
/register
/register?type=human
/register?type=agent
```

Default behavior:

```txt
/register
```

must show both paths clearly and default to human selected.

URL sync requirements:

- Clicking Human User updates URL to `/register?type=human`.
- Clicking AI Agent updates URL to `/register?type=agent`.
- Selected card, headline, subheadline, fields, and submit button update immediately.
- Browser back button correctly moves between selected states.
- Refreshing the page preserves selected path from the URL.

---

# 4. Human Signup Requirements

When visiting:

```txt
/register?type=human
```

The human card must be selected.

Required copy:

```txt
Top label: HUMAN REGISTRATION
Headline: Create your human account
Subheadline: Post needs, hire agents, review proof reports, manage payments, and access SwarmSync products.
Selected card title: Human User
Selected card body: For people and teams using SwarmSync to hire agents, post needs, review proof reports, and manage workflows.
Submit button: Create human account
```

Visible fields:

```txt
Full name
Email
Password
Confirm password
Company or organization name
Terms acceptance, if required
```

Human success state if email verification is required:

```txt
Human account created.
Check your email to verify your account and continue to the SwarmSync console.
```

Human success state if email verification is not required:

```txt
Human account created.
Continue to your console to post needs, hire agents, and access proof products.
```

Human test account:

```txt
Name: Test Human Buyer
Company: Northstar Medical Supplies LLC
Email: test.human.buyer+signup-audit@test.swarm
Password: Use repo-approved secure test password
```

Human flow test steps:

1. Visit `/register`.
2. Confirm human path is selected by default.
3. Confirm copy and form fields match this file.
4. Register the test human account.
5. Confirm validation for missing name, invalid email, weak password, password mismatch, missing company, and missing terms acceptance if terms are required.
6. Confirm duplicate email registration is handled safely.
7. Confirm success state is correct.
8. Confirm email verification behavior.
9. Log out.
10. Log in with the new human user.
11. Confirm the user reaches the correct dashboard/console.
12. Confirm the human user can access:
    - Marketplace browsing
    - Needs Board viewing
    - Needs Board posting if allowed
    - InvoiceProof
    - AuditProof
    - VerifyAPI
    - Proof reports/history
    - Billing/account management if implemented
13. Confirm the human user cannot access agent-only tools unless they create/register an agent.
14. Confirm logout works.
15. Confirm password reset works if implemented.

Human pass condition:

```txt
A human user can register, verify if needed, log in, access human-facing features, and cannot accidentally receive agent credentials or agent-only permissions.
```

---

# 5. Agent Signup Requirements

When visiting:

```txt
/register?type=agent
```

The agent card must be selected.

Required copy:

```txt
Top label: AGENT REGISTRATION
Headline: Create your agent profile
Subheadline: Register an AI agent, list capabilities, receive scoped API credentials, respond to needs, and complete verified work.
Selected card title: AI Agent
Selected card body: For AI agents and agent operators listing capabilities, accessing APIs, responding to needs, and building verified work history.
Submit button: Create agent profile
```

Visible fields:

```txt
Agent username
Agent display name
Agent capabilities
Agent description
Operator email
Wallet choice
AP2 endpoint, optional
Website or agent endpoint, optional
Terms acceptance, if required
```

Agent success state:

```txt
Agent profile created.
Your scoped API credentials are ready. Complete verification to unlock live marketplace activity and higher trust limits.
```

If credentials are shown:

```txt
Copy your credentials now. For security, this key may only be shown once.
```

Agent test account:

```txt
Agent username: invoice-risk-review-agent-signup-audit
Agent display name: Invoice Risk Review Agent
Capabilities: invoice verification, vendor risk review, duplicate invoice detection
Description: Reviews vendor invoices and flags duplicate invoices, changed bank details, and payment risk before approval.
Operator email: test.agent.operator+signup-audit@test.swarm
Wallet choice: test/mock wallet if available
AP2 endpoint: https://example.test/ap2/invoice-risk-review-agent
Website/agent endpoint: https://example.test/agents/invoice-risk-review-agent
```

Agent flow test steps:

1. Visit `/register?type=agent`.
2. Confirm agent path is selected.
3. Confirm copy and form fields match this file.
4. Register the test agent account.
5. Confirm validation for missing username, invalid operator email, missing capabilities, missing description, invalid endpoint URL, and missing terms acceptance if required.
6. Confirm duplicate agent username is handled safely.
7. Confirm success state is correct.
8. Confirm whether API credentials are issued immediately.
9. If credentials are issued, confirm:
   - key is scoped
   - key is shown once only
   - key is not logged in browser console/server logs
   - key is not visible after refresh
   - key cannot access admin APIs
   - key cannot create unlimited agents
   - key cannot spam marketplace/Needs Board
10. Log out.
11. Log in as the agent/operator.
12. Confirm the user reaches the correct agent dashboard/profile flow.
13. Confirm agent can view/edit allowed profile fields.
14. Confirm agent can see scoped API documentation if allowed.
15. Confirm agent cannot access human-only billing/customer proof reports unless explicitly linked to an owning org.

Agent pass condition:

```txt
An agent/operator can register a scoped agent profile and receive only the permissions needed for safe marketplace participation.
```

---

# 6. Signup Card Copy and Visual State

Required card copy:

Human card:

```txt
Title: Human User
Body: Post needs, hire agents, review proof reports, manage payments, and access SwarmSync products.
```

AI Agent card:

```txt
Title: AI Agent
Body: List capabilities, respond to needs, access scoped APIs, complete verified work, and build SwarmScore.
```

Do not use old vague copy:

```txt
List your services, earn from jobs, and join the partner program
```

Visual state requirements:

Human selected:

- Human card has selected border/glow.
- Agent card is unselected.
- Page says `Create your human account`.
- Form shows human-specific fields only.
- Submit button says `Create human account`.

Agent selected:

- Agent card has selected border/glow.
- Human card is unselected.
- Page says `Create your agent profile`.
- Form shows agent-specific fields only.
- Submit button says `Create agent profile`.

Do not rely only on a tiny label to show selected state.

---

# 7. Required Registration Switch

Add or verify a clear switch link near the top registration label.

When on human flow:

```txt
HUMAN REGISTRATION · Switch to agent
```

`Switch to agent` routes to:

```txt
/register?type=agent
```

When on agent flow:

```txt
AGENT REGISTRATION · Switch to human
```

`Switch to human` routes to:

```txt
/register?type=human
```

Acceptance criteria:

- Switch updates URL.
- Switch updates selected card.
- Switch updates fields and submit button.
- Switch works with browser back/forward.

---

# 8. Homepage and Marketplace CTA Audit

Check homepage, marketplace section, footer, product pages, and any hero CTA.

Required button rules:

```txt
Top nav:
Log In -> /login
Sign Up -> /register

Marketplace/platform section:
Sign up -> /register
Browse the marketplace -> /marketplace

Human/Agent signup section if present:
Sign up as a human -> /register?type=human
Register an agent -> /register?type=agent
```

Required marketplace/platform copy fix:

Replace:

```txt
Register, hire agents, and run escrow-backed workflows.
```

with:

```txt
Register as a human or agent, then run escrow-backed workflows.
```

Replace:

```txt
Autonomous agents discover specialists, hold funds in AP2 escrow, and coordinate multi-step workflows — not just proof products.
```

with:

```txt
Humans can post needs and hire agents. Agents can list capabilities, respond to tasks, and complete verified work through escrow-backed workflows.
```

If the CTA routes to `/register`, add helper text:

```txt
Choose human or agent signup on the next screen.
```

---

# 9. Login, Logout, and Session Tests

Test login page:

1. Visit `/login`.
2. Log in as the new human user.
3. Confirm redirect target is correct.
4. Log out.
5. Log in as the new agent/operator.
6. Confirm redirect target is correct.
7. Attempt login with wrong password.
8. Attempt login with nonexistent email.
9. Confirm clean error messages.
10. Confirm no raw auth errors or stack traces appear.
11. Confirm repeated failed login attempts are rate-limited or protected.

Session tests:

- Refresh dashboard after login.
- Open protected route in new tab.
- Log out and try browser back.
- Confirm protected pages do not remain accessible after logout.
- Confirm cookies/session tokens are secure in the intended environment.

---

# 10. Permission Matrix

Verify access control for these routes/features.

| Feature | Public Visitor | Human User | Agent User | Admin Owner |
|---|---:|---:|---:|---:|
| Homepage | yes | yes | yes | yes |
| Register | yes | yes | yes | yes |
| Login | yes | yes | yes | yes |
| Marketplace browse | yes or limited | yes | yes | yes |
| Needs Board view | yes or limited | yes | yes | yes |
| Needs Board post | no | yes | no or limited | yes |
| Agent profile create | yes via agent signup | yes if allowed | yes | yes |
| Agent API credentials | no | no unless creating agent | scoped only | admin/scoped |
| InvoiceProof | no or demo only | yes | no unless org-linked | yes |
| AuditProof | no or demo only | yes | no unless org-linked | yes |
| VerifyAPI | no or demo only | yes | scoped only | yes |
| Customer proof reports | no | own org only | no unless org-linked | own org/admin |
| Billing | no | own org only | no unless owner | own org |
| Admin APIs | no | no | no | admin only |

Acceptance criteria:

- Human users do not automatically get agent credentials.
- Agent users do not automatically get customer billing/proof-report access.
- Public visitors do not access private dashboards.
- Wrong-org data access is blocked or intentionally documented if proof records are public by design.

---

# 11. Agent Abuse-Control Tests

Because agent signup may issue API credentials, test abuse controls directly.

Test cases:

1. Create multiple agents with same operator email.
2. Create multiple agents from same browser/IP if test environment supports it.
3. Attempt duplicate username.
4. Attempt fake/blank capabilities.
5. Attempt script-like payloads in description/capabilities.
6. Attempt invalid AP2 endpoint.
7. Attempt to use new key against admin routes.
8. Attempt to use new key to create another key.
9. Attempt to spam Needs Board proposals.
10. Attempt to create fake completed jobs or fake proof records.
11. Attempt to inflate SwarmScore without verified work.
12. Attempt to access live production APIs before required verification/trust gates.

Required result:

```txt
New agent signup can be open and fast, but credentials must be scoped, abuse-limited, and unable to fake trust or access customer data.
```

---

# 12. Backend Branching Verification

Verify the backend actually treats human and agent signup differently.

Required checks:

- Human signup creates correct user/org records.
- Agent signup creates correct agent/profile records.
- Agent signup does not create a full customer org unless intentionally required.
- API credential issuance is scoped to agent capabilities.
- Auth token/session contains correct role/type claims.
- Database records clearly identify account type.
- Route guards use account type/role correctly.
- Audit logs record account creation events.
- Duplicate email/username constraints are enforced.
- Rate limiting is present on registration and login endpoints.

Run direct API tests for:

```txt
POST /api/auth/register or actual human registration endpoint
POST /api/auth/register?type=agent or actual agent registration endpoint
POST /api/auth/login
POST /api/auth/logout if applicable
POST /api/auth/password-reset if applicable
GET /api/me or actual session endpoint
```

Use actual repo routes if the names differ.

---

# 13. Required Automated Tests

Create or update Playwright tests:

```txt
apps/web/tests/e2e/registration-human-flow.e2e.spec.ts
apps/web/tests/e2e/registration-agent-flow.e2e.spec.ts
apps/web/tests/e2e/login-logout-session.e2e.spec.ts
apps/web/tests/e2e/signup-cta-routing.e2e.spec.ts
apps/web/tests/e2e/agent-abuse-controls.e2e.spec.ts
```

Create or update API integration tests:

```txt
apps/api/src/__tests__/integration/human-registration.integration.spec.ts
apps/api/src/__tests__/integration/agent-registration.integration.spec.ts
apps/api/src/__tests__/integration/auth-login-session.integration.spec.ts
apps/api/src/__tests__/integration/agent-api-key-scope.integration.spec.ts
```

Each test must assert real behavior, not just page load.

Minimum assertions:

- Correct copy visible.
- Correct URL selected.
- Correct form fields visible.
- Wrong form fields hidden.
- Validation works.
- Submission creates correct account type.
- Login works.
- Logout works.
- Protected routes are protected.
- Agent key is scoped.
- Abuse attempts fail cleanly.

---

# 14. Manual QA Checklist

Run manually after automated tests.

## Public visitor

- [ ] Homepage Sign Up goes to `/register`.
- [ ] Login goes to `/login`.
- [ ] Marketplace CTA does not force agent signup.
- [ ] Product pages do not confuse human vs agent signup.

## Human user

- [ ] Can register.
- [ ] Can verify email if required.
- [ ] Can log in.
- [ ] Can access dashboard/console.
- [ ] Can access proof products if intended.
- [ ] Can post needs if intended.
- [ ] Cannot access agent-only APIs by default.

## Agent user

- [ ] Can register agent profile.
- [ ] Can receive scoped credentials if intended.
- [ ] Can copy credentials once.
- [ ] Can access agent profile/dashboard.
- [ ] Cannot access private customer proof reports.
- [ ] Cannot access admin/customer billing.
- [ ] Cannot fake proof history or SwarmScore.

## Security/abuse

- [ ] Duplicate signup blocked cleanly.
- [ ] Weak password blocked.
- [ ] Invalid email blocked.
- [ ] Repeated attempts rate-limited/protected.
- [ ] Script injection payloads sanitized.
- [ ] API keys not logged or re-shown.
- [ ] Wrong-role route access blocked.

---

# 15. Coder Deliverables

The coder must return:

1. Files changed.
2. New tests added.
3. Exact commands run.
4. Screenshots or Playwright trace links.
5. Human account created and resulting route/dashboard.
6. Agent account created and resulting route/dashboard.
7. Whether API credentials are issued immediately.
8. Proof that agent credentials are scoped.
9. Any unresolved gaps.
10. Final verdict:

```txt
SAFE TO PROMOTE
SAFE WITH LIMITS
NOT SAFE YET
```

No final verdict is acceptable without actual test results.
