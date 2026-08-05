"""
cato/context/volatility_map.py — Volatility priors by domain type (Skill 6).
"""
from __future__ import annotations
import re

_DOMAIN_VOLATILITY: dict[str, float] = {
    "github_issues":    0.9,
    "github_code":      0.5,
    "email_inbox":      0.9,
    "news_rss":         0.95,
    "arxiv_paper":      0.1,
    "web_page_article": 0.5,
    "api_endpoint":     0.5,
    "local_file":       0.1,
}

_URL_PATTERNS: list[tuple[str, str]] = [
    (r"github\.com/.+/issues",     "github_issues"),
    (r"github\.com",               "github_code"),
    (r"arxiv\.org",                "arxiv_paper"),
    (r"rss|feed|atom",             "news_rss"),
    (r"mail\.|inbox\.|email\.",    "email_inbox"),
    (r"api\.|/api/",               "api_endpoint"),
    (r"^(file://|/|[A-Za-z]:)",   "local_file"),
]


def classify_url(url: str) -> str:
    """Classify a URL into a domain type."""
    for pattern, domain_type in _URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return domain_type
    return "web_page_article"


class VolatilityMap:
    """Maps URL/resource types to volatility scores (0.0-1.0)."""

    def __init__(self, overrides: dict[str, float] | None = None) -> None:
        self._map = dict(_DOMAIN_VOLATILITY)
        if overrides:
            self._map.update(overrides)

    def get_volatility(self, url: str) -> float:
        """Return volatility score for a URL."""
        domain_type = classify_url(url)
        return self._map.get(domain_type, 0.5)

    def set_override(self, domain_type: str, volatility: float) -> None:
        self._map[domain_type] = volatility
