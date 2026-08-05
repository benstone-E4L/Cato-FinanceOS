"""
cato/skill_validator.py — SKILL.md validation for CATO.

Validates all SKILL.md files found in agent skill directories.
Checks YAML frontmatter, required heading structure, valid semver,
and known tool capability references.

CLI: `cato doctor --skills`

Blocks broken skills from loading at runtime (instead of failing
silently mid-session).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known valid tool capabilities (as declared in skills)
# ---------------------------------------------------------------------------

KNOWN_CAPABILITIES: frozenset[str] = frozenset({
    "shell",
    "browser",
    "browser.navigate",
    "browser.click",
    "browser.type",
    "browser.screenshot",
    "browser.search",
    "browser.snapshot",
    "browser.extract",
    "browser.pdf",
    "file",
    "file.read",
    "file.write",
    "file.list",
    "memory",
    "memory.search",
    "memory.store",
    "conduit",
    "conduit.navigate",
    "conduit.click",
    "conduit.type",
    "conduit.extract",
    "conduit.screenshot",
})

# Semver pattern (flexible: 1.0.0, 1.0, 1)
_SEMVER_RE = re.compile(r"^\d+(\.\d+){0,2}(-[\w.]+)?(\+[\w.]+)?$")

# Required heading patterns
_H1_RE = re.compile(r"^#\s+\S", re.MULTILINE)
_H2_INSTRUCTIONS_RE = re.compile(r"^##\s+(Instructions|Usage)\b", re.MULTILINE | re.IGNORECASE)

# YAML frontmatter block
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    path: Path
    code: str        # SHORT_CODE like "MISSING_TITLE"
    message: str
    severity: str    # "error" | "warning"


@dataclass
class SkillValidationResult:
    path: Path
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    skill_name: str = ""
    version: str = ""
    capabilities: list[str] = field(default_factory=list)

    @property
    def skill_path(self) -> Path:
        """Alias for .path — used by audit/CLI callers."""
        return self.path


# ---------------------------------------------------------------------------
# SkillValidator
# ---------------------------------------------------------------------------

class SkillValidator:
    """
    Validates SKILL.md files against Cato's skill specification.

    Rules enforced:
    1. File must have a level-1 heading (# Title)
    2. File must have ## Instructions or ## Usage section
    3. YAML frontmatter is REQUIRED — missing frontmatter is an error
    4. If YAML frontmatter present: Version must be valid semver
    5. If Capabilities declared: each must be in KNOWN_CAPABILITIES
    6. File must be readable UTF-8

    Two construction styles::

        # Style 1 — pass dir at construction time:
        validator = SkillValidator(skills_dir)
        results = validator.validate_all()          # uses stored dir

        # Style 2 — pass dir at call time:
        validator = SkillValidator()
        results = validator.validate_all(agents_dir)

        for r in results:
            if not r.valid:
                print(f"FAIL: {r.skill_path.name} — {[e.message for e in r.errors]}")
    """

    def __init__(self, default_dir: Optional[Path] = None) -> None:
        self._default_dir: Optional[Path] = default_dir

    def validate_file(self, skill_path: Path) -> SkillValidationResult:
        """
        Validate one SKILL.md file and return a SkillValidationResult.

        Does not raise — all issues are captured in result.errors / result.warnings.
        """
        result = SkillValidationResult(path=skill_path, valid=True)

        # 1. Read file
        try:
            text = skill_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = skill_path.read_text(encoding="utf-8", errors="replace")
                result.warnings.append(ValidationError(
                    path=skill_path,
                    code="ENCODING_WARNING",
                    message="File contains non-UTF-8 bytes — read with replacement",
                    severity="warning",
                ))
            except OSError as exc:
                result.valid = False
                result.errors.append(ValidationError(
                    path=skill_path,
                    code="UNREADABLE",
                    message=f"Cannot read file: {exc}",
                    severity="error",
                ))
                return result
        except OSError as exc:
            result.valid = False
            result.errors.append(ValidationError(
                path=skill_path,
                code="UNREADABLE",
                message=f"Cannot read file: {exc}",
                severity="error",
            ))
            return result

        # 2. Parse YAML frontmatter (REQUIRED — absence is an error)
        frontmatter: dict = {}
        body = text
        fm_match = _FRONTMATTER_RE.match(text)
        if fm_match:
            try:
                frontmatter = yaml.safe_load(fm_match.group(1)) or {}
                body = text[fm_match.end():]
            except yaml.YAMLError as exc:
                result.valid = False
                result.errors.append(ValidationError(
                    path=skill_path,
                    code="FRONTMATTER_PARSE_ERROR",
                    message=f"YAML frontmatter parse error: {exc}",
                    severity="error",
                ))
        else:
            # Frontmatter is required per Cato skill spec
            result.valid = False
            result.errors.append(ValidationError(
                path=skill_path,
                code="MISSING_FRONTMATTER",
                message="Missing required YAML frontmatter block (--- ... ---)",
                severity="error",
            ))

        # 3. Extract metadata from frontmatter or inline **Bold:** fields
        version = str(frontmatter.get("version", frontmatter.get("Version", "")))
        if not version:
            # Check inline pattern: **Version:** 1.0.0
            m = re.search(r"\*\*Version:\*\*\s*([\w.\-+]+)", text, re.IGNORECASE)
            if m:
                version = m.group(1).strip()

        raw_caps = frontmatter.get("capabilities", frontmatter.get("Capabilities", ""))
        if not raw_caps:
            m2 = re.search(r"\*\*Capabilities:\*\*\s*(.+)", text, re.IGNORECASE)
            if m2:
                raw_caps = m2.group(1).strip()

        result.version = version
        result.capabilities = [c.strip() for c in str(raw_caps).split(",") if c.strip()] if raw_caps else []

        # Extract skill name from first H1
        h1_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        result.skill_name = h1_match.group(1).strip() if h1_match else skill_path.stem

        # 4. Check required headings
        if not _H1_RE.search(body):
            result.valid = False
            result.errors.append(ValidationError(
                path=skill_path,
                code="MISSING_TITLE",
                message="Missing required level-1 heading (# My Skill Name)",
                severity="error",
            ))

        if not _H2_INSTRUCTIONS_RE.search(body):
            result.valid = False
            result.errors.append(ValidationError(
                path=skill_path,
                code="MISSING_INSTRUCTIONS",
                message="Missing required ## Instructions or ## Usage section",
                severity="error",
            ))

        # 5. Validate semver if version present
        if version and not _SEMVER_RE.match(version):
            result.warnings.append(ValidationError(
                path=skill_path,
                code="INVALID_SEMVER",
                message=f"Version '{version}' is not valid semver (expected e.g. 1.0.0)",
                severity="warning",
            ))

        # 6. Validate capability names
        for cap in result.capabilities:
            if cap and cap not in KNOWN_CAPABILITIES:
                result.warnings.append(ValidationError(
                    path=skill_path,
                    code="UNKNOWN_CAPABILITY",
                    message=f"Unknown capability '{cap}' — not in KNOWN_CAPABILITIES list",
                    severity="warning",
                ))

        return result

    def validate_all(self, agents_dir: Optional[Path] = None) -> list[SkillValidationResult]:
        """
        Validate all SKILL.md and skills/*.md files under *agents_dir*.

        If *agents_dir* is omitted, uses the directory passed to __init__.

        Scans (in order, deduplicating):
          1. {agents_dir}/*.md         — flat skill files (e.g. test suites)
          2. {agents_dir}/*/SKILL.md   — canonical per-agent skill files
          3. {agents_dir}/*/skills/*.md — per-agent skills directories

        Returns a list of SkillValidationResult (one per file found).
        """
        target = agents_dir or self._default_dir
        if target is None:
            raise ValueError(
                "validate_all() requires an agents_dir argument or a dir passed to __init__"
            )

        results: list[SkillValidationResult] = []
        target = target.expanduser().resolve()

        if not target.exists():
            logger.debug("SkillValidator: agents_dir does not exist: %s", target)
            return results

        seen: set[Path] = set()

        def _add(skill_file: Path) -> None:
            rp = skill_file.resolve()
            if rp not in seen:
                seen.add(rp)
                results.append(self.validate_file(skill_file))

        # Flat *.md files directly inside the directory
        for skill_file in sorted(target.glob("*.md")):
            _add(skill_file)

        # Top-level SKILL.md files one level down
        for skill_file in sorted(target.glob("*/SKILL.md")):
            _add(skill_file)

        # Per-agent skills directories
        for skill_file in sorted(target.glob("*/skills/*.md")):
            _add(skill_file)

        return results

    def format_report(self, results: list[SkillValidationResult]) -> str:
        """Format validation results as a human-readable text report."""
        if not results:
            return "No SKILL.md files found."

        lines: list[str] = ["Skill Validation Report", "=" * 50]
        passed = sum(1 for r in results if r.valid)
        failed = len(results) - passed

        for r in results:
            status = "PASS" if r.valid else "FAIL"
            name = r.skill_name or r.path.stem
            ver = f" v{r.version}" if r.version else ""
            lines.append(f"  [{status}] {name}{ver}  ({r.path.name})")
            for e in r.errors:
                lines.append(f"          ERROR  {e.code}: {e.message}")
            for w in r.warnings:
                lines.append(f"          warn   {w.code}: {w.message}")

        lines.append("-" * 50)
        lines.append(f"  {passed}/{len(results)} skills valid   {failed} failed")
        return "\n".join(lines)
