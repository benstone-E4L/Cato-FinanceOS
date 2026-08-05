# Web Search Plus
**Version:** 2.0.0
**Capabilities:** web.search, web.code, web.news, academic.arxiv, academic.semantic_scholar, academic.pubmed

## Overview
Multi-engine search with automatic query classification, fallback chains, confidence scoring, and result caching.

## Query Types
- **code** — GitHub, StackOverflow, docs, APIs, errors → uses [exa, brave, searxng, ddg]
- **news** — Breaking news, announcements → uses [tavily, brave, searxng, ddg]
- **academic** — Papers, journals, citations → uses [semantic_scholar, arxiv, exa]
- **general** — Everything else → uses [brave, searxng, ddg]

<!-- COLD -->
## Search Backends
| Engine | Key in Vault | Notes |
|--------|-------------|-------|
| DuckDuckGo Instant Answer | none | Always available fallback |
| Brave Search | `brave_api_key` | General + news |
| Exa AI | `exa_api_key` | Code + academic |
| Tavily | `tavily_api_key` | News-optimized |
| arXiv | none | Academic papers |
| Semantic Scholar | `semantic_scholar_api_key` (optional) | Academic papers |
| PubMed/NCBI | none | Medical/biomedical (3 req/s) |
| SearXNG | `searxng_url` in config | Self-hosted metasearch |
| Perplexity | `perplexity_api_key` | Deep-mode only |

## CLI Usage
```bash
cato search "Python asyncio tutorial" --engine code
cato search "CRISPR gene editing 2024" --engine academic
cato search "OpenAI latest news" --engine news --depth deep
```

## Tool Actions
Registered in `agent_loop.py`:
- `web.search` — general web search
- `web.code` — code-focused search
- `web.news` — news search
- `academic.arxiv` — arXiv papers
- `academic.semantic_scholar` — Semantic Scholar papers
- `academic.pubmed` — PubMed articles

## Confidence Scoring
Results are scored by:
1. Rank decay (rank 0 = 0.85, rank 9 = ~0.40)
2. Domain authority bonus (.edu/.gov +0.10, .org +0.05)
3. Freshness (year >= 2023 in snippet +0.05)
4. Keyword overlap (+0.02 per matching token, max +0.10)
5. Cross-engine agreement (+0.05 per additional engine confirming URL)
