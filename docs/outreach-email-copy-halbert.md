# Outreach email copy — Halbert rules (sales email)

**Format:** Cold **sales email** (first touch = highest scrutiny)  
**From:** `bstone@surfacescore.com` · **Ben** at SurfaceScore  
**Mechanism (R10):** **Representation Fidelity Check** — we scanned their site; the score is the hook  
**Send via:** Brevo SMTP or `conduit_outreach_pipeline` (plain `body_text` preferred for G1 seeds)  
**Variables:** Match `render_engine.build_context` — paste into Jinja templates or Brevo with merge tags

**Halbert rules applied:** R2 subject curiosity · R3 I→you voice · R6 their real score · R10 named mechanism · R11 proof = their scan · R12 soft risk reversal · R16 one CTA · R17 plain voice · **No** ALL CAPS subjects · **No** image-heavy HTML for tests

**CAN-SPAM footer (every send):** physical address + unsubscribe (pipeline adds `List-Unsubscribe` when `UNSUBSCRIBE_BASE_URL` is set)

---

## Shared blocks

### Signature (plain text)

```
— Ben
SurfaceScore · AI visibility & Representation Fidelity checks
{{ rescan_link }}

P.S. If this isn’t useful, reply “pass” and I won’t follow up.

SurfaceScore
2038 S Bullrush Pkwy, Lehi, UT 84043
```

### Signature (minimal HTML — one link only)

```html
<p>— Ben<br>
SurfaceScore · AI visibility checks<br>
<a href="{{ rescan_link }}">View your scan</a></p>
<p style="font-size:12px;color:#666;">Reply “pass” to opt out of follow-ups from me.</p>
```

### Preheader (optional; 40–90 chars)

Use under subject in Brevo if the field exists:

| Track | Preheader |
|-------|-----------|
| A | I ran your site through an AI visibility scan — one issue stood out. |
| B | Quick client-site check — score + the one fix I’d prioritize. |
| C | Your site scored well — one gap that still costs you citations. |

---

## TRACK A — Low score (0–39) · default B2B/SaaS

*Job: shock + specificity without insulting. They need to see themselves in the gap.*

### Touch 1 — Audit as cold open

**Subject:** `{{ domain }} — what AI is telling people about you ({{ ai_visibility_score }}/100)`

**Body (plain text):**

```
Hi {{ greeting_name }},

I’m Ben — I run SurfaceScore. I’m not writing to sell you software.

I ran {{ domain }} through what we call a Representation Fidelity Check: can tools like ChatGPT and Perplexity actually see your site, and are they likely to describe you accurately?

Your score came back {{ ai_visibility_score }}/100.

The first thing I’d fix: {{ top_issue }}.
{% if issue_description %}{{ issue_description[:220] }}{% endif %}

You can re-run the scan free (takes about a minute):
{{ rescan_link }}

If the score looks wrong, reply and tell me — I’ll delete this thread.

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

**CTA (R16):** one link — `rescan_link` only.

---

### Touch 2 — One fix + snippet

**Subject:** `The one fix I’d do first on {{ domain }}`

**Body (plain text):**

```
Hi {{ greeting_name }},

Following up on your {{ ai_visibility_score }}/100 scan.

Main gap: {{ top_issue }}.

{% if recommended_fix %}Short version: {{ recommended_fix[:180] }}{% endif %}

{% if code_snippet %}Copy-paste starter (trimmed for email):

{{ code_snippet[:400] }}
{% endif %}

Re-scan after you patch — most teams see movement on the second pass:
{{ rescan_link }}

Reply if you want me to sanity-check what you changed.

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 3 — Benchmark gap

**Subject:** `{{ ai_visibility_score }}/100 vs roughly {{ industry_avg }} for {{ benchmark_label }}`

**Body (plain text):**

```
Hi {{ greeting_name }},

Quick benchmark context for {{ domain }}:

Your scan: {{ ai_visibility_score }}/100
Rough average for {{ benchmark_label }}: about {{ industry_avg }}/100

{{ benchmark_note }}

Not a verdict on your whole business — just “are machines reading you correctly?”

Fresh scan:
{{ rescan_link }}

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 4 — Why it matters now

**Subject:** `AI answers are already a traffic lane for {{ domain }}`

**Body (plain text):**

```
Hi {{ greeting_name }},

{{ estimated_ai_traffic_impact }}

That’s why we bother scoring AI visibility separately from classic SEO.

Your site today: {{ ai_visibility_score }}/100 — still anchored on {{ top_issue }}.

Free re-check:
{{ rescan_link }}

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 5 — Close the loop

**Subject:** `Last note on {{ domain }} — no pressure`

**Body (plain text):**

```
Hi {{ greeting_name }},

Last email from me unless you reply.

Your Representation Fidelity Check for {{ domain }} is still here if you want it:
{{ rescan_link }}

If this isn’t on your roadmap, reply “pass” — done.

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

## TRACK B — Mid score (40–69) · agencies & services

*Job: make the agency look smart to their client — proof they can bring a deliverable.*

### Touch 1

**Subject:** `{{ company_name or domain }} — client-ready AI visibility score ({{ ai_visibility_score }}/100)`

**Body (plain text):**

```
Hi {{ greeting_name }},

Ben here — SurfaceScore.

If you manage sites for clients, this is an easy pre-call deliverable: we scan a URL and return an AI visibility score (how well ChatGPT-class tools can cite the site) plus the top fix.

I ran {{ domain }} as an example:

Score: {{ ai_visibility_score }}/100
Priority issue: {{ top_issue }}

Free re-scan link you can forward:
{{ rescan_link }}

If it’s off, tell me — I’ll correct or drop the thread.

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 2

**Subject:** `Agency shortcut: one fix for {{ domain }}`

**Body (plain text):**

```
Hi {{ greeting_name }},

For {{ company_name or domain }} — top issue from the scan: {{ top_issue }}.

{% if recommended_fix %}{{ recommended_fix[:200] }}{% endif %}

{% if code_snippet %}{{ code_snippet[:350] }}{% endif %}

Re-scan (good before/after for a client email):
{{ rescan_link }}

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 3

**Subject:** `Benchmark for agency sites — {{ ai_visibility_score }}/100`

**Body (plain text):**

```
Hi {{ greeting_name }},

{{ domain }} scored {{ ai_visibility_score }}/100.

For {{ benchmark_label }}, we usually see ~{{ industry_avg }}/100 — {{ benchmark_note }}

Handy slide for a QBR.

Updated scan:
{{ rescan_link }}

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 4

**Subject:** `Quarterly AI visibility check — worth 15 minutes?`

**Body (plain text):**

```
Hi {{ greeting_name }},

Teams are adding a quarterly “can AI describe this client correctly?” check next to SEO reports.

Your example scan ({{ domain }}) still flags {{ top_issue }}.

Run it again free:
{{ rescan_link }}

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 5

**Subject:** `Closing the loop — {{ company_name or domain }}`

**Body (plain text):**

```
Hi {{ greeting_name }},

No more pings from me unless you want them.

Keep the scanner link for any client URL:
{{ rescan_link }}

Reply “pass” anytime.

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

## TRACK C — High score (70+) · e-commerce / DTC

*Job: congratulate + one sharp gap — badge angle without sounding cheesy.*

### Touch 1

**Subject:** `{{ domain }} scored {{ ai_visibility_score }}/100 — one gap left`

**Body (plain text):**

```
Hi {{ greeting_name }},

Ben — SurfaceScore.

Good news: {{ domain }} scored {{ ai_visibility_score }}/100 on AI visibility (how shopping/compare answers cite your catalog).

Most stores don’t clear 70.

Still one item worth fixing before peak season: {{ top_issue }}.

Free re-scan:
{{ rescan_link }}

If you want the badge-style summary for your site, reply “badge” and I’ll point you to it.

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 2

**Subject:** `One catalog fix for {{ domain }}`

**Body (plain text):**

```
Hi {{ greeting_name }},

Your scan’s top issue: {{ top_issue }}.

{% if recommended_fix %}{{ recommended_fix[:200] }}{% endif %}

{% if code_snippet %}{{ code_snippet[:350] }}{% endif %}

Re-scan:
{{ rescan_link }}

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 3

**Subject:** `You vs typical ecom — {{ ai_visibility_score }}/100`

**Body (plain text):**

```
Hi {{ greeting_name }},

{{ domain }}: {{ ai_visibility_score }}/100
Typical ecom in our set: ~{{ industry_avg }}/100

{{ benchmark_note }}

Verify anytime:
{{ rescan_link }}

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 4

**Subject:** `AI shopping answers — {{ domain }}`

**Body (plain text):**

```
Hi {{ greeting_name }},

{{ estimated_ai_traffic_impact }}

Your storefront scan is still live here:
{{ rescan_link }}

Top remaining issue: {{ top_issue }}.

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

### Touch 5

**Subject:** `Last note — re-scan {{ domain }} anytime`

**Body (plain text):**

```
Hi {{ greeting_name }},

Last note from me.

Re-scan when you push catalog changes:
{{ rescan_link }}

Reply “pass” if you’re set.

— Ben
SurfaceScore
[YOUR POSTAL ADDRESS]
```

---

## Brevo / mail-tester send (G1 plain test)

Use **Track A Touch 1** with a real `{{ domain }}` and score filled in. Example manual test:

**Subject:** `acme.com — what AI is telling people about you (34/100)`

**Body:** 6–8 short sentences, no images, one link, normal-case subject.

---

## `render_engine.SUBJECTS` — drop-in replacement (Jinja)

Optional Python dict update for `conduit_outreach_pipeline`:

```python
SUBJECTS = {
    "A": {
        1: "{{ domain }} — what AI is telling people about you ({{ ai_visibility_score }}/100)",
        2: "The one fix I'd do first on {{ domain }}",
        3: "{{ ai_visibility_score }}/100 vs roughly {{ industry_avg }} for {{ benchmark_label }}",
        4: "AI answers are already a traffic lane for {{ domain }}",
        5: "Last note on {{ domain }} — no pressure",
    },
    "B": {
        1: "{{ company_name or domain }} — client-ready AI visibility score ({{ ai_visibility_score }}/100)",
        2: "Agency shortcut: one fix for {{ domain }}",
        3: "Benchmark for agency sites — {{ ai_visibility_score }}/100",
        4: "Quarterly AI visibility check — worth 15 minutes?",
        5: "Closing the loop — {{ company_name or domain }}",
    },
    "C": {
        1: "{{ domain }} scored {{ ai_visibility_score }}/100 — one gap left",
        2: "One catalog fix for {{ domain }}",
        3: "You vs typical ecom — {{ ai_visibility_score }}/100",
        4: "AI shopping answers — {{ domain }}",
        5: "Last note — re-scan {{ domain }} anytime",
    },
}
```

---

## Halbert diagnostic (Touch 1, Track A — self-check)

**Verdict:** Strong cold open — curiosity subject uses their domain + score; voice is I→you; proof is the scan; one CTA; soft opt-out.

**Top 3 rules landed:** R2 subject · R6 specific score · R16 single rescan link

**Quickest win for seeds:** Send **plain text** only until ≥18/20 inbox, then optionally light HTML.
