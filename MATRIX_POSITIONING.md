# CATO POSITIONING MATRIX

**Version:** 1.0
**Date:** 2026-03-06
**Purpose:** Systematic exploration of Cato's product positioning across 5 key dimensions

---

## MORPHOLOGICAL MATRIX (5 Dimensions × 5 Options Each)

### Dimension 1: Target Segment
| # | Segment | Characteristics | Cato Fit |
|---|---------|-----------------|----------|
| 1.1 | Individual users (Claw X profile) | Solo devs, creators, independent researchers | HIGH — existing positioning |
| 1.2 | Teams/small companies (2-20 people) | Workgroups needing shared agents/credentials | MEDIUM — requires team features |
| 1.3 | Enterprises (100+ employees) | Complex governance, audit, multi-tenant | LOW — Cato is lightweight |
| 1.4 | Developers/integrators | Build agents as-a-service, sell skills | HIGH — SKILL.md is portable |
| 1.5 | Industry specialists (ops, support, marketing) | Domain-specific agents (Zendesk, HubSpot, Slack) | MEDIUM — requires templates |

---

### Dimension 2: Deployment Model
| # | Model | Characteristics | Cato Fit |
|---|-------|-----------------|----------|
| 2.1 | Desktop app (Claw X model) | macOS/Windows/Linux native, no server | HIGH — current position |
| 2.2 | Cloud/SaaS (hosted) | Multi-user, zero setup, web UI | LOW — contrary to Cato values |
| 2.3 | Hybrid (on-prem + cloud sync) | Local execution + optional cloud backup | MEDIUM — future possibility |
| 2.4 | Edge/local-first (device + optional cloud) | Runs fully offline, cloud for sync only | HIGH — aligns with Cato principles |
| 2.5 | Serverless/managed (AWS Lambda, etc.) | Invocation-based, auto-scaling | LOW — no infrastructure expertise |

---

### Dimension 3: Competitive Moat
| # | Moat | Characteristics | Cato Strength |
|---|------|-----------------|----------------|
| 3.1 | Simplicity (Claw X owns) | Easy to learn, few moving parts | MEDIUM — Cato simplicity is in code, not UX |
| 3.2 | Scalability | Multi-agent orchestration, distributed | LOW — not current focus |
| 3.3 | Privacy/on-device (Cato owns) | No telemetry, encrypted vault, local browser | HIGH — core differentiator |
| 3.4 | Industry customization | Pre-built templates, domain knowledge | LOW — not yet differentiated |
| 3.5 | Developer tooling (Cato can own) | Extensible architecture, SKILL.md standard, CLI | MEDIUM-HIGH — competitive advantage |

---

### Dimension 4: Revenue Model
| # | Model | Characteristics | Viability |
|---|-------|-----------------|-----------|
| 4.1 | Free (Claw X model) | Open-source, zero revenue | VIABLE — aligns with ethos, builds community |
| 4.2 | Freemium | Free tier + paid features (storage, analytics) | VIABLE — could monetize without compromising core |
| 4.3 | Subscription (per-user, per-agent, per-execution) | Recurring revenue, simple billing | VIABLE — but contradicts privacy positioning |
| 4.4 | Usage-based (pay for compute) | Metered by API calls or token usage | LOW — users already pay LLMs directly |
| 4.5 | Enterprise licensing + marketplace | License Cato + sell pre-built skills | VIABLE — future revenue (requires marketplace) |

---

### Dimension 5: Core Differentiator
| # | Differentiator | What it is | Cato Strength |
|---|---|---|---|
| 5.1 | Multi-user orchestration | Teams using shared agents, role-based access | LOW — not current |
| 5.2 | Distributed agent networks | Agents that spawn sub-agents | LOW — out of scope |
| 5.3 | On-device AI (no external APIs) | Run LLMs locally, zero API calls | LOW — uses external LLMs |
| 5.4 | Advanced analytics/audit (Cato owns) | Hash-chained logs, receipts, tamper detection | HIGH — Conduit is unique |
| 5.5 | Industry templates | Pre-built skills for specific domains | MEDIUM — achievable with marketplace |

---

## KEY CONSTRAINTS & DATA ACCESS

### Privacy Tier (Hard Constraint)
- **Tier 1:** Zero external connections except LLM APIs
- **Tier 2:** Optional cloud sync for agents/skills (encrypted)
- **Tier 3:** Analytics sent to Cato servers (anonymized)

**Cato's Position:** Tier 1. Any concept using Tier 2+ requires explicit opt-in + encryption.

### Development Effort (T-shirt sizing)
- **S:** 1-2 weeks (config, template, documentation)
- **M:** 1-2 months (new tool, new adapter, marketplace MVP)
- **L:** 3-6 months (new deployment model, cloud infrastructure)
- **XL:** 6+ months (full rewrite, new architecture)

### Data Access (What's needed)
- **Vault passwords:** User-controlled, never stored
- **Audit logs:** Local SQLite, tamper-evident
- **Skills:** User-owned, optionally shared
- **Agent memory:** Local semantic search, no external embedding storage

---

## POSITIONING SPACE MAP

```
AUTONOMY (user control) ▲
                        │
     5.4 Advanced       │
     Audit ─────────────┼─────── 3.3 Privacy
   5.2 Networks         │          (Cato)
                        │
        Local Apps ─────┼───────┬─ Team Cloud
        (2.1, 4.1)      │       │
                        │     3.2 Scalability
                        │
                        └──────────────────────► MARKET SIZE / SIMPLICITY
                                (Claw X)
```

- **Upper-left:** Privacy-focused, audit-obsessed, individual users (Cato's natural space)
- **Upper-right:** Privacy + teams = hard problem (Cato future, requires investment)
- **Lower-left:** Simple, free, individual (Claw X's current monopoly)
- **Lower-right:** Enterprise, cloud, SaaS (not for Cato)

---

## VALIDATION CRITERIA

For each concept, score these dimensions (1-5 scale):

| Criterion | Definition |
|-----------|-----------|
| **Effort** | Dev time to MVP (1=S, 5=XL) |
| **Uniqueness** | How different from Claw X (1=copy, 5=new territory) |
| **Data Access** | Feasibility to collect input/output data (1=hard, 5=easy) |
| **Sales Simplicity** | Time to first paying customer (1=complex, 5=obvious) |
| **Moat Strength** | Defensibility vs competitors (1=weak, 5=strong) |
| **Privacy Alignment** | Fits Cato's zero-telemetry values (1=terrible, 5=perfect) |

**Scoring Logic:**
- **Effort score:** How much engineering. Higher = harder/longer
- **Uniqueness:** How different from Claw X. Higher = more novel
- **Data Access:** How easy to validate product-market fit. Higher = easier signals
- **Sales Simplicity:** How obvious the value prop. Higher = shorter sales cycle
- **Moat Strength:** How hard to copy. Higher = more defensible
- **Privacy:** Does concept require compromising Tier 1? Higher = more aligned

---

## NEXT SECTION: COMBOS.md

See **COMBOS.md** for 12 generated concept combinations with scores and winner selection.
