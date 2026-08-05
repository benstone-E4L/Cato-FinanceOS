# DARKMIRROR TACTICAL ROADMAP: Weeks 1-2 MVP Plan

**Scope:** Implement Positions 1 + 3 + 4 (Infrastructure + Cost + Resilience)
**Timeline:** 2 weeks
**Success Metric:** All validation tests pass; 3 engineering teams using MVP

---

## WEEK 1: Core MVP (Infrastructure + Cost + Fallback)

### Day 1-2: Daemon Foundation

**Objective:** Daemon listens on :8080 and exposes simple HTTP API

**Tasks:**
```
1. Start Cato daemon without UI
2. Expose: GET /health → {"status": "ok"}
3. Expose: POST /run → accepts workflow + params, returns task_id + cost_estimate
4. Test with curl
```

**Files to Modify/Create:**
- `cato/api/routes.py` — Add `/health` and `/run` endpoints
- `cato/api/websocket_handler.py` — Verify existing WS handler works
- `tests/test_api_endpoints.py` (NEW) — Test both endpoints

**Example Request:**
```bash
curl -X POST http://localhost:8080/run \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": "code-review",
    "repo": "foo/bar",
    "pr": 123
  }'

# Response:
# {
#   "task_id": "task_abc123",
#   "cost_estimate": 1.50,
#   "status": "queued"
# }
```

**Success Criteria:**
- Daemon starts without UI
- GET /health returns 200 < 100ms
- POST /run accepts valid workflows
- At least one workflow runnable via API

---

### Day 3: GitHub Webhook Integration

**Objective:** GitHub PR webhook triggers Cato review workflow

**Tasks:**
```
1. Implement: POST /webhook/github
2. Parse GitHub webhook (PR opened event)
3. Look up workflow config for "code-review"
4. Execute workflow with PR data
5. Post result as GitHub comment (via GitHub API)
```

**Files to Modify/Create:**
- `cato/api/routes.py` — Add `/webhook/github` endpoint
- `cato/orchestrator/github_adapter.py` (NEW) — Convert webhook → workflow params
- `cato/integrations/github_poster.py` (NEW) — Post comment back to PR
- `tests/test_github_integration.py` (NEW) — Mock webhook, verify response

**Example Workflow File (workflows/code-review.yaml):**
```yaml
name: Code Review
agent_type: coding
timeout: 60s
inputs:
  - repo: required
  - pr: required
fallback:
  - model: claude-opus
    timeout: 30s
  - model: gemini-2
    timeout: 30s
outputs:
  post_to_github: true
  github_token_env: GITHUB_TOKEN
```

**Success Criteria:**
- GitHub webhook fires (check Cato logs)
- Workflow executes within 30s
- Review comment appears on PR
- Comment contains meaningful feedback

**Test Script:**
```bash
# 1. Set up GitHub webhook:
#    Repo settings → Webhooks
#    Payload URL: http://localhost:8080/webhook/github
#    Content type: application/json
#    Events: Pull requests
#    Active: checked

# 2. Create test PR
git checkout -b feature/test
echo "function bad() { console.log(1) }" > test.js
git push origin feature/test
# Open PR on GitHub

# 3. Check Cato logs
tail -20 ~/.cato/logs/cato.log
# Should see: "Webhook received from GitHub"
# Should see: "Executing workflow: code-review"
# Should see: "Posting comment to PR #123"

# 4. Verify comment appears on PR (within 30s)
```

---

### Day 4: Cost Tracking + Budget Enforcement

**Objective:** Track cost of every invocation; refuse tasks that exceed budget

**Tasks:**
```
1. Load budget config from YAML
2. Before every agent run, check: spent + estimated_cost > remaining?
3. If true, refuse with clear message
4. Log every execution with actual cost
5. CLI command: cato budget status
```

**Files to Modify/Create:**
- `cato/config.py` — Extend to load `[budget]` section
- `cato/budget.py` — Enhance runtime enforcement (extends existing module)
- `tests/test_budget_enforcement.py` (NEW) — Test refusal + logging

**Example Config (~/.cato/config.yaml):**
```yaml
budget:
  monthly: 500.00
  by_workflow:
    code-review: 100.00
    research: 200.00
    design: 200.00

api:
  host: localhost
  port: 8080

auth:
  api_key: sk_test_xyz
```

**Runtime Logic:**
```python
# Before running workflow:
if (spent_this_month + estimated_cost) > monthly_budget:
    return {
        "status": "refused",
        "reason": "Budget exceeded",
        "spent": spent_this_month,
        "remaining": monthly_budget - spent_this_month,
        "task_cost": estimated_cost
    }
```

**CLI Usage:**
```bash
$ cato budget status
Monthly Budget: $500.00
Spent: $250.00 (50%)
Remaining: $250.00

By Workflow:
  code-review:    $80 / $100
  research:       $170 / $200
  design:         $0 / $200
```

**Success Criteria:**
- Budget config loads from YAML
- Task refuses when over budget
- Cost logged accurately (±5% of actual)
- CLI displays remaining budget correctly

**Test Script:**
```bash
# 1. Set monthly budget to $50
cato config set budget.monthly 50

# 2. Run 10 code-review tasks (each ~$3)
for i in {1..10}; do
  curl -X POST http://localhost:8080/run \
    -d '{"workflow":"code-review","repo":"test/repo","pr":'$i'}'
done
# After task 16, should see REFUSED

# 3. Check budget status
cato budget status
# Should show: "Spent: $45 / $50"

# 4. Try --max-cost flag
curl -X POST http://localhost:8080/run \
  -d '{"workflow":"expensive","max_cost":2}'
# Should refuse because expensive > $2
```

---

### Day 5: Graceful Fallback + Early Termination

**Objective:** Multi-model fallback chain; timeout early; always get a result

**Tasks:**
```
1. Implement: Claude → Gemini → local fallback
2. If Claude slow (>25s), return partial + move to Gemini
3. Log which model was used + why
4. Update audit trail with fallback chain
```

**Files to Modify/Create:**
- `cato/orchestrator/cli_invoker.py` — Extend to fallback on timeout
- `cato/orchestrator/early_terminator.py` — Trigger fallback at cost checkpoint
- `tests/test_fallback_chain.py` (NEW) — Test fallback triggering

**Example Config:**
```yaml
workflows:
  code-review:
    fallback:
      - model: claude-opus
        timeout: 30s
      - model: gemini-2
        timeout: 30s
      - model: local-llama-13b
        timeout: 10s

degradation_modes:
  best_quality:
    model: claude-opus
    timeout: 60s
  balanced:
    model: gemini-2
    timeout: 30s
  cheapest:
    model: local-llama-13b
    timeout: 10s
```

**Runtime Logic:**
```python
# Try Claude with 30s timeout
result = await invoke_with_timeout(
    model="claude-opus",
    task=task,
    timeout=30,
    on_timeout=lambda: trigger_fallback(model="gemini-2")
)

# Audit log shows:
# {
#   "task_id": "xyz",
#   "model_chain": ["claude-opus: TIMEOUT", "gemini-2: SUCCESS (8s)"],
#   "cost": 0.30,  # Reduced from $2.00 estimate
#   "quality": "good"
# }
```

**Success Criteria:**
- Fallback happens seamlessly (user sees no error)
- Result still appears (via fallback model)
- Audit log shows model chain
- Cost reflects actual model used (not estimate)

**Test Script:**
```bash
# 1. Artificially timeout Claude
cato config set workflows.code-review.fallback[0].timeout 2s

# 2. Run workflow
curl -X POST http://localhost:8080/run \
  -d '{"workflow":"code-review","repo":"test/repo","pr":1}'

# 3. Watch logs:
#    [claude-opus] timeout after 2s
#    [gemini-2] started
#    [gemini-2] SUCCESS (8s, $0.30)

# 4. Check audit log
curl http://localhost:8080/api/audit?task=xyz
# Should show:
# {
#   "model_chain": ["claude-opus: TIMEOUT (2s)", "gemini-2: SUCCESS (8s, $0.30)"]
# }
```

---

### Day 6: Audit Trail + Comprehensive Logging

**Objective:** Every invocation logged; queryable by user/workflow/date

**Tasks:**
```
1. Create audit log table (SQLite or Postgres)
2. Log: user_id, workflow, model_used, cost, timestamp, status
3. CLI command: cato audit --workflow code-review --user alice
4. API endpoint: GET /api/audit?workflow=X&user=Y
```

**Files to Modify/Create:**
- `cato/audit.py` — Enhance with model choice + fallback chain logging
- Database schema: `CREATE TABLE invocations(...)`
- `tests/test_audit_logging.py` (NEW) — Test audit entries

**Example Audit Table:**
```sql
CREATE TABLE invocations (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  workflow TEXT,
  repo TEXT,
  pr INTEGER,
  model_used TEXT,
  model_chain TEXT,  -- JSON: ["claude-opus", "gemini-2"]
  cost FLOAT,
  estimated_cost FLOAT,
  status TEXT,       -- "success", "refused", "timeout"
  timestamp DATETIME,
  reason TEXT        -- "budget exceeded", "timeout", etc.
);
```

**Example Queries:**
```bash
# All code-reviews by user alice
cato audit --workflow code-review --user alice

# All refusals in last 24 hours
cato audit --status refused --since 24h

# Cost breakdown by workflow (this month)
cato audit --group-by workflow --since 30d

# API query
curl 'http://localhost:8080/api/audit?workflow=code-review&user=alice'
```

**Success Criteria:**
- Every run creates audit log entry
- Entries queryable by user/workflow/date
- `cato audit` command works
- API returns JSON

---

### Day 7: Documentation + End-to-End Validation

**Objective:** Full integration test; someone new can set up in 15 min

**Tasks:**
```
1. Write README.md explaining MVP
2. Document GitHub webhook setup
3. Create E2E validation test
4. Verify all tests pass (100%)
```

**Files to Create:**
- `README_MVP.md` — Quick start guide
- `docs/SETUP_GITHUB_WEBHOOK.md` — Step-by-step
- `tests/test_e2e_integration.py` (NEW) — Full E2E test

**README_MVP.md Structure:**
```markdown
# Cato MVP: Agent Infrastructure for Teams

## What This Is
A daemon that runs agents reliably, with cost tracking and budget enforcement.

## Quick Start (5 min)
1. Install: pip install cato-daemon
2. Start: cato start
3. Test: curl http://localhost:8080/health

## GitHub Integration (10 min)
1. Create GitHub webhook pointing to localhost:8080/webhook/github
2. Open a PR
3. Within 30s, Cato posts a review comment

## Cost Control (5 min)
1. Set budget: cato config set budget.monthly 500
2. Check status: cato budget status
3. Tasks refuse to run if budget exceeded

## Validation Tests
All tests pass: pytest tests/ -v
```

**E2E Test Checklist:**
```
✓ Daemon starts without UI
✓ GET /health responds
✓ GitHub webhook fires
✓ Review comment posts to PR
✓ Cost tracked with ±5% accuracy
✓ Budget enforcement works (refuses over-budget)
✓ Fallback to Gemini on Claude timeout
✓ Audit log has 100% coverage
✓ `cato audit` command works
✓ `cato budget status` shows correct breakdown
```

---

## WEEK 2: Marketplace + Cost Dashboard

### Day 8-9: Workflow Registry

**Objective:** Community can install + publish workflows

**Tasks:**
```
1. Create GitHub org cato-workflows
2. Create 3 official workflows
3. Create simple registry index
4. Implement: cato workflow add official/code-review@v1.0.0
5. Implement: cato workflow publish --name my-review
```

**Example Workflows:**
- `cato-workflows/code-review` (basic PR review)
- `cato-workflows/research-summary` (gather + summarize)
- `cato-workflows/content-outline` (outline blog post)

**Registry Structure:**
```
cato-workflows/ (org)
  .index.json
    {
      "workflows": [
        {
          "name": "official/code-review",
          "version": "1.0.0",
          "repo": "cato-workflows/code-review",
          "description": "Review code for quality + security",
          "installs": 150,
          "rating": 4.8,
          "last_updated": "2026-03-01"
        }
      ]
    }
  code-review/ (repo)
    .cato.yaml
    README.md
    tests/
```

**CLI Usage:**
```bash
# List available workflows
cato workflow list
# Shows: official/code-review v1.0.0, official/research-summary v1.2.1, etc.

# Install workflow
cato workflow add official/code-review@v1.0.0
# Downloads .cato.yaml to ~/.cato/workflows/

# Run workflow
cato run official/code-review --repo=foo/bar --pr=1

# Publish your own
cato workflow publish \
  --dir ./my-code-review \
  --name my-code-review \
  --version 1.0.0
# Creates PR to cato-workflows/.index.json
```

**Success Criteria:**
- Download + install workflow < 10s
- User can fork + customize < 30 min
- Publish validated + merged < 1 hour
- Discovery (search) finds new workflows

---

### Day 10-11: Cost Dashboard

**Objective:** Real-time spend breakdown; budget alerts

**Tasks:**
```
1. API endpoint: GET /api/metrics
2. HTML dashboard showing:
   - Total spent this month
   - Spend by workflow
   - Spend by user
   - Trending spend (7-day, 30-day avg)
3. Slack integration: post alerts at 75%, 90%, 100% of budget
```

**Files to Create:**
- `cato/api/metrics_handler.py` (NEW)
- `cato/ui/metrics_dashboard.html` (NEW)
- `cato/integrations/slack_alerts.py` (NEW)
- `tests/test_metrics_dashboard.py` (NEW)

**Example API Response (GET /api/metrics):**
```json
{
  "period": "2026-03-01 to 2026-03-31",
  "budget": {
    "monthly": 500,
    "spent": 250,
    "remaining": 250,
    "percent_used": 50
  },
  "by_workflow": {
    "code-review": {
      "spent": 80,
      "budget": 100,
      "runs": 40,
      "cost_per_run": 2.00
    },
    "research": {
      "spent": 170,
      "budget": 200,
      "runs": 85,
      "cost_per_run": 2.00
    }
  },
  "by_user": {
    "alice": {
      "spent": 100,
      "runs": 50
    },
    "bob": {
      "spent": 150,
      "runs": 75
    }
  },
  "trending": {
    "7_day_avg": 35.71,
    "30_day_avg": 8.33,
    "projected_monthly": 250
  }
}
```

**Dashboard Display:**
```
Cato Cost Dashboard
================

Budget Overview
  Monthly: $500.00
  Spent:   $250.00 (50%)
  Remaining: $250.00

By Workflow
  code-review    $80 / $100 (40 runs)
  research       $170 / $200 (85 runs)
  design         $0 / $200 (0 runs)

By User
  alice    $100 (50 runs)
  bob      $150 (75 runs)

Trending
  7-day avg: $35.71/day → $1,071/month
  30-day avg: $8.33/day → $250/month
  Trend: stable
```

**Success Criteria:**
- API response < 1s
- Dashboard renders correctly
- Slack alert fires at 75%, 90%, 100%
- Metrics accurate to ±1%

---

### Day 12: Enterprise Readiness (Optional)

**Objective:** Multi-user with role-based access

**Tasks:**
```
1. Implement role system: Admin, Operator, Viewer
2. Enforce permissions at API level
3. Filter audit log by user
4. Test: Admin sees all, Operator sees own runs, Viewer is read-only
```

**Files to Modify/Create:**
- `cato/auth.py` — Add role-based permission checks
- `tests/test_rbac.py` (NEW) — Test role enforcement

**Example Roles:**
```
Admin
  - View all invocations
  - Configure workflows
  - Set budgets
  - View all audit logs

Operator
  - Run workflows
  - View own invocations
  - View own cost
  - Cannot modify workflows or budgets

Viewer
  - View-only access to dashboard
  - Cannot trigger workflows
  - Cannot view sensitive cost data (only aggregates)
```

**Success Criteria:**
- Role enforcement works
- Audit log filters by user
- Permission denied appears for lower roles

---

## VALIDATION TESTS (All Weeks)

### Test 1: GitHub Integration End-to-End
```bash
# Expected flow:
# 1. Open PR on GitHub
# 2. GitHub webhook fires within 5s
# 3. Cato log shows "Webhook received"
# 4. Workflow executes
# 5. Comment appears on PR within 30s
# 6. Cost logged in audit

# Pass criteria: All steps complete within timeline
```

### Test 2: Budget Cap
```bash
# Expected flow:
# 1. Set budget to $50/month
# 2. Run 15 tasks at $3 each = $45 spent
# 3. Task 16 should REFUSE with "Budget exceeded"
# 4. Dashboard shows $45 / $50 (90%)

# Pass criteria: Task refuses; cost exact
```

### Test 3: Fallback Chain
```bash
# Expected flow:
# 1. Artificially timeout Claude (2s)
# 2. Run workflow
# 3. Logs show: "[claude] TIMEOUT → [gemini] SUCCESS (8s)"
# 4. Audit shows model_chain: ["claude", "gemini"]
# 5. Cost reflects Gemini (not Claude estimate)

# Pass criteria: Fallback seamless; audit complete
```

### Test 4: Marketplace
```bash
# Expected flow:
# 1. cato workflow list → shows official workflows
# 2. cato workflow add official/code-review@v1.0.0
# 3. Workflow installed < 10s
# 4. cato run official/code-review --repo=test/sample --pr=1
# 5. Review comment appears

# Pass criteria: Install fast; workflow works immediately
```

### Test 5: Cost Dashboard
```bash
# Expected flow:
# 1. Run 5 workflows
# 2. cato budget status → shows accurate breakdown
# 3. GET /api/metrics → JSON is correct
# 4. HTML dashboard loads and renders
# 5. Slack alert posted at 75%, 90%

# Pass criteria: All metrics accurate
```

---

## SUCCESS METRICS (End of Week 2)

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Daemon uptime | 99.9% | Run for 7 days; check logs |
| API latency | < 500ms | `curl localhost:8080/health`; time it |
| Webhook latency | < 30s | PR → comment time |
| Cost accuracy | ±5% | Compare logged vs actual bill |
| Budget enforcement | 100% refusal | Try exceed budget; verify refusal |
| Fallback reliability | 100% (always result) | Timeout Claude; verify Gemini result |
| Workflow install | < 10s | Time `cato workflow add` |
| Test pass rate | 100% | `pytest tests/ -v` |

---

## GO-TO-MARKET NEXT STEPS (Week 3)

**Message:**
> "Cato: The open-source agent infrastructure for teams. Cost-aware. Integrated. Yours to control."

**First 10 Customers:**
- Reach out to 5 engineering teams running 10+ daily agent tasks
- Reach out to 5 DevOps/platform teams
- Ask: "Would you use an open-source agent daemon?"

**Content:**
- Blog: "Why We Built Cato: Agent Infrastructure, Not Another Desktop App"
- HN post: Explain infrastructure-first positioning
- Demo video: GitHub webhook → PR review (30 seconds)
- GitHub discussions: Engage early adopters

