# CHUNK_3_VAULT_INDEX: Index the E4L vault into Cato's existing memory engine per the Retrieval Contract's canonical chunk ID and metadata rules

## Summary

Phase C, part 1. Cato's `core/memory.py` (BM25 + MiniLM embeddings + hnswlib + `kg_nodes`/
`kg_edges` over SQLite) already exists and works — this chunk does not build a new index engine,
it builds the ingestion pipeline that walks `C:\Users\Work\Desktop\vault\` and feeds it into that
engine using the exact chunking/ID/metadata rules the master spec's §9 Retrieval Contract table
defines. This is read-only against the vault (the vault stays the source of truth; the index is
disposable and rebuildable). It hands off a populated, queryable local index to Chunk 4, which
builds the Ask-E4L chat surface on top of it.

## Acceptance Criteria

- [ ] An ingestion job walks the vault's markdown tree and produces chunks with canonical IDs in
      the exact format `{vault-relative-path}#{heading-path}@{chunk-index}` plus `content_sha256`,
      stable across re-indexes of unchanged content (re-running ingestion on an unchanged file
      produces byte-identical chunk IDs).
- [ ] Each chunk's YAML frontmatter (`entity`, `type`, `status`, `updated`, `supersedes`) is parsed
      and stored as filterable metadata on the corresponding `kg_nodes` row (or equivalent), not
      discarded.
- [ ] Chunks with `status: superseded` are indexed but excluded from default retrieval — a
      dedicated filter flag allows retrieving them "when explicitly asked for history."
- [ ] The index records `index_updated_at`; a watchdog check can compare it against the vault
      tree's latest git commit/mtime and flag staleness (this chunk builds the staleness signal;
      Chunk 4 surfaces it in the UI).
- [ ] Ingestion is idempotent and re-runnable (re-indexing after a vault edit updates only the
      changed file's chunks, not the whole index) and never writes to the vault itself.
- [ ] All tests pass with zero failures.

## Endpoints / Interfaces

No HTTP endpoints — internal service layer only (ingestion pipeline + memory engine writes).

## Database Changes

- `kg_nodes` / `kg_edges` (existing Cato SQLite tables): no schema change, but a new class of
  nodes (vault knowledge chunks) is populated with the frontmatter fields above as node metadata.
- No new tables — this chunk is data population against `core/memory.py`'s existing schema, not a
  new schema.

## Test Scenarios

- **Happy path**: ingesting a small fixture vault subtree produces the expected chunk IDs,
  correct `content_sha256`, and correctly parsed frontmatter metadata.
- **Edge case**: a note with `supersedes: [old-slug]` and the old note's `status: superseded` —
  confirm the superseded note is indexed but excluded from a default (non-history) retrieval call.
- **Failure case**: a markdown file with malformed/missing frontmatter must not crash ingestion —
  it indexes with `null`/default metadata and logs a warning, it does not abort the whole run.
- **Integration**: Chunk 4's Ask-E4L retrieval calls query this index directly — its acceptance
  bar (≥8/10 correct+cited) is only reachable if this chunk's chunk IDs and metadata are correct.

## Dependencies

- **Requires**: CHUNK_2_VAULT (running daemon, initialized vault — the ingestion job runs inside
  the daemon process).
- **Blocks**: CHUNK_4_ASK_E4L.

## Completion Promise

<promise>CHUNK COMPLETE: CHUNK_3_VAULT_INDEX</promise>
