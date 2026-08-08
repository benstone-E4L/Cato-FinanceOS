"""
tests/test_vault_ingest.py — CHUNK_3_VAULT_INDEX

Ingesting the E4L knowledge vault's markdown tree into Cato's existing
memory engine (MemorySystem's `chunks` + `kg_nodes` tables). Uses a small
fixture vault subtree under tmp_path — never touches the real vault.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from cato.core.memory import MemorySystem
from cato.core.vault_ingest import (
    IngestReport,
    chunk_markdown_file,
    index_is_stale,
    ingest_vault,
    iter_vault_markdown_files,
)


@pytest.fixture()
def memory(tmp_path: Path) -> MemorySystem:
    mem = MemorySystem(agent_id="vault-ingest-test", memory_dir=tmp_path / "memdb")
    yield mem
    mem.close()


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Chunking / ID stability
# ---------------------------------------------------------------------------

def test_canonical_ids_are_stable_across_reindex_of_unchanged_content() -> None:
    body = "# Top Heading\n\nSome content here.\n\n## Sub Heading\n\nMore content.\n"
    first = chunk_markdown_file("knowledge/finance/entity-structure.md", body)
    second = chunk_markdown_file("knowledge/finance/entity-structure.md", body)

    assert [c.canonical_id for c in first] == [c.canonical_id for c in second]
    assert [c.content_sha256 for c in first] == [c.content_sha256 for c in second]
    assert first[0].canonical_id == "knowledge/finance/entity-structure.md#top-heading@0"
    assert first[1].canonical_id == "knowledge/finance/entity-structure.md#sub-heading@1"


def test_preamble_content_before_first_heading_is_not_dropped() -> None:
    body = "This line has no heading above it.\n\n# First Heading\n\nBody.\n"
    chunks = chunk_markdown_file("notes/x.md", body)
    assert chunks[0].heading_slug == "preamble"
    assert "no heading above it" in chunks[0].content


# ---------------------------------------------------------------------------
# Happy path: fixture vault subtree
# ---------------------------------------------------------------------------

def test_happy_path_ingest_fixture_vault(tmp_path: Path, memory: MemorySystem) -> None:
    vault_root = tmp_path / "vault"
    _write(
        vault_root,
        "knowledge/finance/entity-structure.md",
        (
            "---\n"
            "entity: E4L\n"
            "type: decision\n"
            "status: active\n"
            "updated: 2026-08-01\n"
            "---\n\n"
            "# The Entity Map\n\n"
            "E4L Inc. is the parent entity.\n"
        ),
    )

    report = ingest_vault(memory, vault_root)

    assert report.files_scanned == 1
    assert report.chunks_created == 1
    assert report.chunks_unchanged == 0
    assert report.warnings == []

    chunks = memory.list_vault_chunks()
    assert len(chunks) == 1
    meta = chunks[0]
    assert meta["canonical_id"] == "knowledge/finance/entity-structure.md#the-entity-map@0"
    assert meta["entity"] == "E4L"
    assert meta["type"] == "decision"
    assert meta["status"] == "active"
    assert meta["updated"] == "2026-08-01"
    assert "content_sha256" in meta

    # Re-running ingestion on unchanged content is a no-op.
    report2 = ingest_vault(memory, vault_root)
    assert report2.chunks_created == 0
    assert report2.chunks_updated == 0
    assert report2.chunks_unchanged == 1
    assert memory.chunk_count() == 1  # no duplicate rows


def test_reindex_after_edit_updates_not_duplicates(tmp_path: Path, memory: MemorySystem) -> None:
    vault_root = tmp_path / "vault"
    path = _write(
        vault_root,
        "notes/x.md",
        "---\ntype: rule\nstatus: active\n---\n\n# Heading\n\nOriginal text.\n",
    )
    ingest_vault(memory, vault_root)
    assert memory.chunk_count() == 1

    path.write_text(
        "---\ntype: rule\nstatus: active\n---\n\n# Heading\n\nEdited text is different now.\n",
        encoding="utf-8",
    )
    report = ingest_vault(memory, vault_root)

    assert report.chunks_updated == 1
    assert report.chunks_created == 0
    assert memory.chunk_count() == 1  # replaced, not duplicated

    [meta] = memory.list_vault_chunks()
    chunk_results = memory.search_vault_chunks("Edited text", top_k=1)
    assert chunk_results
    assert "Edited" in chunk_results[0]["content"]


# ---------------------------------------------------------------------------
# Edge case: superseded exclusion
# ---------------------------------------------------------------------------

def test_superseded_chunk_indexed_but_excluded_from_default_retrieval(
    tmp_path: Path, memory: MemorySystem
) -> None:
    vault_root = tmp_path / "vault"
    _write(
        vault_root,
        "decisions/2026-08-01-old-call.md",
        "---\ntype: decision\nstatus: superseded\n---\n\n# Old Call\n\nWe picked plan A.\n",
    )
    _write(
        vault_root,
        "decisions/2026-08-05-new-call.md",
        (
            "---\ntype: decision\nstatus: active\nsupersedes: [2026-08-01-old-call]\n---\n\n"
            "# New Call\n\nWe picked plan B instead.\n"
        ),
    )

    report = ingest_vault(memory, vault_root)
    assert report.chunks_created == 2

    default_chunks = memory.list_vault_chunks()
    assert len(default_chunks) == 1
    assert default_chunks[0]["status"] == "active"

    all_chunks = memory.list_vault_chunks(include_superseded=True)
    assert len(all_chunks) == 2

    default_search = memory.search_vault_chunks("plan", top_k=5)
    assert all(r["metadata"].get("status") != "superseded" for r in default_search)

    history_search = memory.search_vault_chunks("plan", top_k=5, include_superseded=True)
    assert any(r["metadata"].get("status") == "superseded" for r in history_search)


# ---------------------------------------------------------------------------
# Failure case: malformed frontmatter never aborts the run
# ---------------------------------------------------------------------------

def test_malformed_frontmatter_does_not_abort_ingestion(
    tmp_path: Path, memory: MemorySystem
) -> None:
    vault_root = tmp_path / "vault"
    _write(
        vault_root,
        "broken/bad.md",
        "---\nentity: [unterminated\n---\n\n# Heading\n\nBody text.\n",
    )
    _write(
        vault_root,
        "good/fine.md",
        "---\ntype: entity\nstatus: active\n---\n\n# Fine\n\nGood body text.\n",
    )

    report = ingest_vault(memory, vault_root)

    assert report.files_scanned == 2
    assert report.chunks_created == 2  # both files still indexed
    assert len(report.warnings) == 1
    assert "bad.md" in report.warnings[0]

    bad_chunk = memory.get_vault_chunk_metadata("broken/bad.md#heading@0")
    assert bad_chunk is not None
    assert bad_chunk.get("entity") is None  # degraded to null metadata, not crashed


def test_missing_frontmatter_indexes_with_defaults(tmp_path: Path, memory: MemorySystem) -> None:
    vault_root = tmp_path / "vault"
    _write(vault_root, "plain.md", "# No Frontmatter\n\nJust a note.\n")

    report = ingest_vault(memory, vault_root)
    assert report.chunks_created == 1
    assert report.warnings == []


# ---------------------------------------------------------------------------
# Never writes to the vault
# ---------------------------------------------------------------------------

def test_ingestion_never_writes_to_the_vault(tmp_path: Path, memory: MemorySystem) -> None:
    vault_root = tmp_path / "vault"
    path = _write(vault_root, "notes/x.md", "# Heading\n\nContent.\n")
    before = path.read_text(encoding="utf-8")
    before_mtime = path.stat().st_mtime

    ingest_vault(memory, vault_root)

    assert path.read_text(encoding="utf-8") == before
    assert path.stat().st_mtime == before_mtime
    # No stray files created anywhere under the vault root.
    all_files = sorted(p.relative_to(vault_root).as_posix() for p in vault_root.rglob("*") if p.is_file())
    assert all_files == ["notes/x.md"]


# ---------------------------------------------------------------------------
# Nested-repo exclusion
# ---------------------------------------------------------------------------

def test_nested_git_repo_is_excluded_from_the_walk(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    _write(vault_root, "knowledge/note.md", "# Note\n\nVault content.\n")
    nested = vault_root / "projects" / "some-app" / "repo"
    (nested / ".git").mkdir(parents=True)
    _write(vault_root, "projects/some-app/repo/README.md", "# Not vault content\n")

    files = iter_vault_markdown_files(vault_root)
    rels = sorted(p.relative_to(vault_root).as_posix() for p in files)
    assert rels == ["knowledge/note.md"]


# ---------------------------------------------------------------------------
# Staleness signal
# ---------------------------------------------------------------------------

def test_index_is_stale_true_after_vault_edit_post_index(
    tmp_path: Path, memory: MemorySystem
) -> None:
    vault_root = tmp_path / "vault"
    path = _write(vault_root, "notes/x.md", "# Heading\n\nOriginal.\n")

    ingest_vault(memory, vault_root)
    assert index_is_stale(memory, vault_root) is False

    time.sleep(0.05)
    path.write_text("# Heading\n\nChanged after indexing, not yet re-ingested.\n", encoding="utf-8")
    # Force a newer mtime than the index timestamp even on coarse filesystems.
    future = time.time() + 5
    import os
    os.utime(path, (future, future))

    assert index_is_stale(memory, vault_root) is True


def test_index_is_stale_returns_none_when_nothing_indexed(tmp_path: Path, memory: MemorySystem) -> None:
    vault_root = tmp_path / "vault"
    _write(vault_root, "notes/x.md", "# Heading\n\nContent.\n")
    assert index_is_stale(memory, vault_root) is None
