"""Static regressions for the two shipped Cato UI surfaces."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UI_FILES = [
    ROOT / "cato" / "ui" / "dashboard.html",
    *sorted((ROOT / "desktop" / "src").rglob("*.css")),
    *sorted((ROOT / "desktop" / "src").rglob("*.tsx")),
]

PROHIBITED_WORDS = re.compile(r"(?i)\b(green|emerald|lime|teal)(?:-\d+)?\b")
PROHIBITED_COLORS = re.compile(
    r"(?i)#(?:22c55e|16a34a|15803d|14532d|166534|86efac|4ade80|"
    r"10b981|059669|047857|06ffa5)\b"
)


def test_shipped_ui_has_no_prohibited_green_family_tokens():
    violations: list[str] = []
    for path in UI_FILES:
        text = path.read_text(encoding="utf-8")
        if PROHIBITED_WORDS.search(text) or PROHIBITED_COLORS.search(text):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == [], f"prohibited green-family UI tokens: {violations}"


def test_legacy_dashboard_does_not_reference_daemon_token_or_query_auth():
    source = (ROOT / "cato" / "ui" / "dashboard.html").read_text(encoding="utf-8")
    assert "__CATO_TOKEN__" not in source
    assert "/ws?token=" not in source


def test_legacy_dashboard_escapes_dynamic_html_values():
    source = (ROOT / "cato" / "ui" / "dashboard.html").read_text(encoding="utf-8")
    assert "function esc(str)" in source
    assert ".replace(/&/g,'&amp;')" in source
    assert '<div class="msg-text">${esc(m.text)}</div>' in source


def test_readme_qualifies_launch_and_security_claims():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "**Verification status:**" in readme
    assert "[Known Limitations](docs/ops/LIMITATIONS.md)" in readme
    assert "Cato never calls home" not in readme
    assert "gets you running in 60 seconds" not in readme
    assert "Every outbound connection is one you configured" not in readme
