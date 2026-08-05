# Cato Cloud: REST API + Webhooks — Effort Assessment

## Current State (What You Have)

- ✅ `gateway.py`: Central message bus with `ingest()` and `send()` methods
- ✅ `aiohttp` HTTP server foundation (websocket_handler.py)
- ✅ `agent_loop.py`: Core execution engine (run, budget, memory, tools)
- ✅ `LaneQueue`: Per-session FIFO serialization
- ✅ Budget enforcement + audit logging
- ✅ Config system with YAML + encrypted vault
- ✅ 390/390 tests passing

**What's Missing for "Cato Cloud":**
- REST endpoints (POST /agents, POST /sessions, GET /results)
- Webhook callback infrastructure
- API authentication (API keys)
- Rate limiting
- Request/response schemas (OpenAPI)
- Cloud deployment docs (Railway, Render, Vercel)

---

## MVP Scope (6 Weeks)

### Phase 1: REST API Layer (Weeks 1-3)

**Files to create/modify:**

1. `cato/api/rest_endpoints.py` (NEW) — 200-300 lines
   - POST /api/v1/agents/{agent_id}/execute (submit job)
   - GET /api/v1/jobs/{job_id} (poll results)
   - DELETE /api/v1/jobs/{job_id} (cancel)
   - GET /health (liveness)

2. `cato/api/auth.py` (NEW) — 100-150 lines
   - API key validation (from config.vault)
   - Rate limiting decorator (@rate_limit)

3. `cato/api/routes.py` (MODIFY) — Add 10-15 lines
   - Register new REST endpoints alongside existing WS routes

4. `cato/api/schemas.py` (NEW) — 100-150 lines
   - Request/response models (JSON serializable)
   - OpenAPI schema generation

**Effort:** 3-4 days (one engineer)
**Risk:** Low (you already have gateway.ingest/send)
**Tests:** 15-20 unit tests (existing test infra)

---

### Phase 2: Webhook Callbacks (Weeks 2-3)

**Files to create:**

1. `cato/api/webhooks.py` (NEW) — 150-200 lines
   - Register webhook URL in session config
   - POST to webhook when job completes (async)
   - Retry logic (exponential backoff)

2. `cato/gateway.py` (MODIFY) — Add 5-10 lines
   - On `send()`, check if webhook registered
   - Fire webhook async (don't block)

**Effort:** 2-3 days
**Risk:** Low (standard webhook pattern)
**Tests:** 8-10 unit tests

---

### Phase 3: Cloud Deployment & Docs (Weeks 4-6)

**Files to create:**

1. `docs/CATO_CLOUD.md` — 500 lines
   - API reference (examples for each endpoint)
   - Webhook specification
   - Deployment to Railway/Render

2. `docker/Dockerfile` (MODIFY if exists)

3. `examples/cato_cloud_client.py` — 150 lines
   - Python SDK for Cato Cloud API

4. `examples/webhook_receiver.py` — 50 lines
   - Demo webhook endpoint

**Effort:** 3-4 days (mostly docs + examples)

---

## Code Estimate Breakdown

| Component | Lines | Effort | Risk |
|-----------|-------|--------|------|
| REST endpoints | 300 | 3 days | 🟢 Low |
| Auth + rate limiting | 150 | 2 days | 🟢 Low |
| Webhook callbacks | 200 | 2 days | 🟢 Low |
| Schemas + validation | 150 | 1 day | 🟢 Low |
| Tests | 400-500 | 2 days | 🟢 Low |
| Docs + examples | 800 | 2 days | 🟢 Low |
| **TOTAL** | **~2,000** | **~12-14 days** | **🟢 Low** |

---

## Implementation Path (Week by Week)

### Week 1: REST Endpoints

- Monday: Implement POST /api/v1/agents/{agent_id}/execute
- Tuesday: Implement GET /api/v1/jobs/{job_id} + status tracking
- Wednesday: Add API auth layer + tests
- Thursday: Implement DELETE /api/v1/jobs/{job_id} (cancellation)
- Friday: Integration test + code review

**Deliverable:** REST API MVP (functional but minimal docs)

### Week 2: Webhooks

- Monday: Implement webhook registration + storage
- Tuesday: Fire webhook on job completion (async)
- Wednesday: Implement retry logic + exponential backoff
- Thursday: Tests (success, timeout, invalid URL)
- Friday: Integration test

**Deliverable:** Webhooks working end-to-end

### Week 3: Polish + Docs

- Monday: OpenAPI schema + Swagger UI
- Tuesday: Write API reference + examples
- Wednesday: Write webhook spec
- Thursday: Create Python SDK
- Friday: Final tests + cleanup

**Deliverable:** Public-ready API with documentation

### Weeks 4-6: Cloud Deployment

- Deploy to Railway (or Render/Vercel)
- Create deployment guide
- Set up CI/CD for cloud
- Monitoring + alerting

**Deliverable:** Cato Cloud running at https://cato-cloud.example.com

---

## Reuse Existing Code (Free Wins)

You don't have to rewrite anything:

- ✅ `gateway.ingest()` — Already handles message routing
- ✅ `agent_loop.run()` — Already processes jobs
- ✅ `LaneQueue` — Already serializes by session
- ✅ `budget.py` — Already enforces spend caps
- ✅ `audit.py` — Already logs everything
- ✅ `config.py` — Already loads API keys from vault

**Your task:** Wrap these in HTTP endpoints. That's it.

---

## What You'll Need to Add (Dependencies)

Already have:
- ✅ aiohttp (websocket_handler uses it)
- ✅ asyncio
- ✅ json

May need:
- `pydantic` — For schema validation (optional, add later)
- `openapi-schema-to-json-schema` — For OpenAPI generation (optional)

**Decision:** Ship MVP without Pydantic (use dicts). Add later if needed.

---

## Testing Strategy (Already Have Framework)

You have pytest + conftest. Just add:

```python
# tests/test_rest_api.py
@pytest.mark.asyncio
async def test_post_execute(client):
    resp = await client.post('/api/v1/agents/default/execute',
                             json={"prompt": "hello"})
    assert resp.status == 202  # Accepted
    job_id = (await resp.json())["job_id"]
    assert len(job_id) > 0

@pytest.mark.asyncio
async def test_get_job_status(client):
    # Create job
    resp = await client.post('/api/v1/agents/default/execute',
                             json={"prompt": "test"})
    job_id = (await resp.json())["job_id"]

    # Poll status
    resp = await client.get(f'/api/v1/jobs/{job_id}')
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] in ["pending", "running", "completed"]
```

**Effort:** 15-20 tests, ~1-2 days

---

## MVP Success Criteria

- ✅ POST /api/v1/agents/{agent_id}/execute returns 202 + job_id
- ✅ GET /api/v1/jobs/{job_id} returns status + result
- ✅ Webhooks fire on completion
- ✅ API key auth works
- ✅ Rate limiting enforced
- ✅ 100% test pass rate
- ✅ Docs + examples complete

---

## Deployment Target (Pick One)

| Platform | Setup | Cost | DevOps |
|----------|-------|------|--------|
| **Railway.app** | 5 min | $5/mo | Super simple |
| **Render.com** | 10 min | Free tier | Simple |
| **Vercel** | 10 min | Free tier | Simple (but stateless) |
| **DigitalOcean App** | 15 min | $5-12/mo | Simple |

**Recommendation:** Railway.app (Easiest, cheapest, Python-native)

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| API design needs rework post-launch | Medium | Medium | Start with simple schema, iterate based on user feedback |
| Rate limiting too aggressive | Low | Low | Conservative limits initially (100 req/min), adjust based on usage |
| Webhook delivery fails silently | Medium | Medium | Implement dead-letter queue + retry logging |
| Authentication issues in production | Low | High | Thoroughly test API key rotation, add monitoring |

---

## Timeline Summary

```
Week 1: REST API (3-4 days) ...................... Ready to test
Week 2: Webhooks (2-3 days) ...................... End-to-end working
Week 3: Docs + polish (2-3 days) ................ MVP ready
Week 4-6: Deploy + iterate ...................... Live at cato-cloud.example.com

Total: 12-14 engineering days + 1 week deploy/monitor
```

---

## "Lighter" Version (2-Week MVP)

If you want to ship faster, cut:
- Webhook retries (just fire once)
- Swagger UI (just curl + README)
- Python SDK (users write their own)
- Deployment docs (hand-wavy)

Result: **Working REST API in 2 weeks, but rough edges**

---

## Budget

Assuming 1 engineer, $150/hr:
- MVP (2 weeks): 12-14 days × 8 hr/day × $150 = **$14,400-16,800**
- With deployment/docs (6 weeks): +20-25 days = **$28,000-30,000 all-in**

Or: **3-4 weeks full-time for a junior engineer** (cheaper)

---

## Bottom Line

**Is it hard?** No. You already have the hard part (agent execution).

**Is it much work?** ~2 weeks for a solid MVP. 4-6 weeks if you want polish + docs.

**Risk level?** Very low. You're wrapping existing code in HTTP endpoints.

**Recommendation:** Launch REST API MVP (Week 1) + Webhooks (Week 2), then deploy to Railway (day 1) and validate with users before adding more features.
