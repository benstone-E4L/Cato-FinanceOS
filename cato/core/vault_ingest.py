"""
cato/core/vault_ingest.py — CHUNK_3_VAULT_INDEX: ingest the E4L knowledge
vault's markdown tree into Cato's existing memory engine.

This module does NOT build a new index engine — ``cato/core/memory.py``
(BM25 + MiniLM embeddings + hnswlib + ``kg_nodes``/``kg_edges`` over SQLite)
already exists and works. This module is purely the ingestion pipeline: walk
the vault tree, parse YAML frontmatter, split each file into heading-based
chunks, compute canonical chunk IDs, and call
:meth:`~cato.core.memory.MemorySystem.upsert_vault_chunk` for each one.

Read-only against the vault: this module never writes to any file under
*vault_root*. The vault stays the source of truth; the index is disposable
and rebuildable at any time by re-running :func:`ingest_vault`.

Canonical chunk ID format (stable across re-indexes of unchanged content)::

    {vault-relative-path}#{heading-slug}@{chunk-index}

e.g. ``knowledge/finance/entity-structure.md#the-entity-map@0``
"""

from __future__ import annotations

import datetime
import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# Scoping — what to walk
# ---------------------------------------------------------------------------

# Directory names that stop a walk from descending further (independent
# nested repos, tooling noise). A directory containing its own `.git` is
# always treated as a separate codebase's knowledge system, not vault notes
# — e.g. `projects/e4l-financeOS/repo/` is git-ignored by the vault itself
# and has its own CLAUDE.md making it authoritative for its own content.
_SKIP_DIR_NAMES = frozenset({
    ".git", ".obsidian", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".pytest_cache",
})

_CHUNK_WORD_TARGET = 350
_CHUNK_WORD_OVERLAP = 60


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_FIELDS = ("entity", "type", "status", "updated", "supersedes")


@dataclass
class ParsedFile:
    frontmatter: dict[str, Any]
    body: str
    warning: Optional[str] = None


def _parse_frontmatter(text: str, *, rel_path: str) -> ParsedFile:
    """Parse a leading ``---\\n...\\n---`` YAML block, if present.

    Malformed or missing frontmatter never raises — it degrades to an empty
    metadata dict plus a warning, and ingestion continues with the full text
    as the body (per CHUNK_3_VAULT_INDEX's failure-case requirement).
    """
    if not text.startswith("---"):
        return ParsedFile(frontmatter={}, body=text)

    lines = text.splitlines()
    end_idx: Optional[int] = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return ParsedFile(
            frontmatter={},
            body=text,
            warning=f"{rel_path}: unterminated frontmatter block — treated as body text",
        )

    raw_block = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1:])
    try:
        parsed = yaml.safe_load(raw_block) or {}
        if not isinstance(parsed, dict):
            return ParsedFile(
                frontmatter={},
                body=body,
                warning=f"{rel_path}: frontmatter is not a mapping — ignored",
            )
    except yaml.YAMLError as exc:
        return ParsedFile(
            frontmatter={},
            body=body,
            warning=f"{rel_path}: malformed frontmatter YAML ({exc}) — indexed with null metadata",
        )

    frontmatter = {
        k: _json_safe(parsed.get(k)) for k in _FRONTMATTER_FIELDS if k in parsed
    }
    return ParsedFile(frontmatter=frontmatter, body=body)


def _json_safe(value: Any) -> Any:
    """Coerce a YAML-parsed value into something json.dumps can handle.

    PyYAML auto-converts unquoted ISO dates (``updated: 2026-08-01``) into
    ``datetime.date``/``datetime.datetime`` objects — stringify those (and
    anything nested inside a list) rather than let a perfectly normal
    frontmatter value crash ingestion.
    """
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# Heading-based chunking
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _slugify(heading: str) -> str:
    """GitHub/Obsidian-style heading slug: lowercase, hyphenated, alnum only."""
    slug = heading.strip().lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug or "section"


@dataclass
class HeadingSection:
    slug: str
    text: str


def _split_by_heading(body: str) -> list[HeadingSection]:
    """Split *body* into sections at each markdown heading boundary.

    Content preceding the first heading (if any) becomes a ``"preamble"``
    section so it is never silently dropped.
    """
    lines = body.splitlines()
    sections: list[HeadingSection] = []
    current_slug = "preamble"
    current_lines: list[str] = []
    seen_slugs: dict[str, int] = {}

    def _flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            slug = current_slug
            if slug in seen_slugs:
                seen_slugs[slug] += 1
                slug = f"{slug}-{seen_slugs[current_slug]}"
            else:
                seen_slugs[slug] = 0
            sections.append(HeadingSection(slug=slug, text=text))

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            _flush()
            current_slug = _slugify(m.group(2))
            current_lines = [line]
        else:
            current_lines.append(line)
    _flush()
    return sections


def _word_chunk(text: str) -> list[str]:
    """Sub-chunk one heading section's text if it is long, word-window style
    (mirrors MemorySystem's own chunker so vault chunks stay a comparable
    size to everything else in the index)."""
    words = text.split()
    if len(words) <= _CHUNK_WORD_TARGET:
        return [text] if text.strip() else []
    out: list[str] = []
    step = _CHUNK_WORD_TARGET - _CHUNK_WORD_OVERLAP
    start = 0
    while start < len(words):
        end = min(start + _CHUNK_WORD_TARGET, len(words))
        piece = " ".join(words[start:end])
        if piece.strip():
            out.append(piece)
        if end >= len(words):
            break
        start += step
    return out


@dataclass
class VaultChunk:
    canonical_id: str
    heading_slug: str
    chunk_index: int
    content: str
    content_sha256: str


def chunk_markdown_file(rel_path: str, body: str) -> list[VaultChunk]:
    """Split one file's body into canonical, ID-stable chunks."""
    chunks: list[VaultChunk] = []
    idx = 0
    for section in _split_by_heading(body):
        for piece in _word_chunk(section.text):
            canonical_id = f"{rel_path}#{section.slug}@{idx}"
            sha = hashlib.sha256(piece.encode("utf-8")).hexdigest()
            chunks.append(VaultChunk(
                canonical_id=canonical_id,
                heading_slug=section.slug,
                chunk_index=idx,
                content=piece,
                content_sha256=sha,
            ))
            idx += 1
    return chunks


# ---------------------------------------------------------------------------
# File walking
# ---------------------------------------------------------------------------

def iter_vault_markdown_files(vault_root: Path) -> list[Path]:
    """Return every ``.md`` file under *vault_root*, skipping nested
    independent repos and tooling-noise directories. Never writes anything."""
    root = Path(vault_root)
    if not root.is_dir():
        return []

    out: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _SKIP_DIR_NAMES:
                    continue
                if (entry / ".git").exists() and entry != root:
                    # Independent nested repo boundary — has its own
                    # knowledge system and its own CLAUDE.md; not vault notes.
                    continue
                stack.append(entry)
            elif entry.is_file() and entry.suffix.lower() == ".md":
                out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Staleness signal
# ---------------------------------------------------------------------------

def vault_tree_latest_change(vault_root: Path) -> Optional[float]:
    """Best-effort epoch timestamp of the vault tree's most recent change.

    Prefers the latest git commit timestamp (accurate, ignores mtimes of
    files git hasn't touched); falls back to a plain mtime scan when the
    vault root is not a git repo or git is unavailable.
    """
    root = Path(vault_root)
    git_dir = root / ".git"
    if git_dir.exists():
        try:
            proc = subprocess.run(
                ["git", "log", "-1", "--format=%ct"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return float(proc.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    latest: Optional[float] = None
    for path in iter_vault_markdown_files(root):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if latest is None or mtime > latest:
            latest = mtime
    return latest


def index_is_stale(memory: Any, vault_root: Path) -> Optional[bool]:
    """True if the index predates the vault tree's latest known change.

    Returns None when there isn't enough information to judge (nothing
    indexed yet, or the vault tree is empty/unreadable) rather than guessing.
    """
    index_ts = memory.vault_index_updated_at()
    tree_ts = vault_tree_latest_change(vault_root)
    if index_ts is None or tree_ts is None:
        return None
    return index_ts < tree_ts


# ---------------------------------------------------------------------------
# Top-level ingestion entrypoint
# ---------------------------------------------------------------------------

@dataclass
class IngestReport:
    files_scanned: int = 0
    chunks_created: int = 0
    chunks_updated: int = 0
    chunks_unchanged: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def chunks_total(self) -> int:
        return self.chunks_created + self.chunks_updated + self.chunks_unchanged


def ingest_vault(memory: Any, vault_root: Path) -> IngestReport:
    """Walk *vault_root* and upsert every chunk into *memory*.

    *memory* is a :class:`~cato.core.memory.MemorySystem` instance (or
    anything implementing ``upsert_vault_chunk``). Read-only against the
    vault; idempotent; safe to re-run at any time (a cron job, an operator
    command, or a watchdog reacting to :func:`index_is_stale`).
    """
    report = IngestReport()
    root = Path(vault_root)

    for path in iter_vault_markdown_files(root):
        report.files_scanned += 1
        rel_path = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report.warnings.append(f"{rel_path}: could not read file ({exc})")
            continue

        parsed = _parse_frontmatter(text, rel_path=rel_path)
        if parsed.warning:
            report.warnings.append(parsed.warning)

        for chunk in chunk_markdown_file(rel_path, parsed.body):
            metadata = dict(parsed.frontmatter)
            metadata["vault_path"] = rel_path
            metadata["heading_slug"] = chunk.heading_slug
            metadata["chunk_index"] = chunk.chunk_index
            try:
                outcome = memory.upsert_vault_chunk(
                    canonical_id=chunk.canonical_id,
                    content=chunk.content,
                    content_sha256=chunk.content_sha256,
                    metadata=metadata,
                )
            except Exception as exc:  # never abort the whole run on one bad chunk
                report.warnings.append(
                    f"{chunk.canonical_id}: ingestion failed ({type(exc).__name__}: {exc})"
                )
                continue
            if outcome == "created":
                report.chunks_created += 1
            elif outcome == "updated":
                report.chunks_updated += 1
            else:
                report.chunks_unchanged += 1

    return report
