# CHUNK_4_ASK_E4L: Wire Ask-E4L chat to the Retrieval Contract (citations, contradiction surfacing, refusal path) and pass the 10-question Phoenix eval bar

## Summary

Phase C, part 2. This chunk builds the Ask-E4L conversational surface inside Cato's existing chat
UI, implementing every row of the master spec's §9 Retrieval Contract table against the index
Chunk 3 built: citation format, superseded filtering, contradiction surfacing (two active notes
disagreeing are BOTH returned, flagged — never averaged), freshness/staleness banners, hybrid
ranking, and the refusal path (zero chunks above threshold → structured "no vault answer," the
LLM is never called to guess). It closes Phase C with the acceptance gate the dead spec defined
and the master spec kept: a 10-question Phoenix eval set at ≥8/10 correct+cited, 0
confidently-wrong. Phoenix may be down; this chunk must degrade to local eval logging, not fail.

## Acceptance Criteria

- [ ] Ask-E4L answers cite sources in the exact format
      `{vault-relative-path}#{heading-anchor}` (e.g. `knowledge/finance/entity-structure.md#the-entity-map`),
      verifiable by opening the cited file at that heading.
- [ ] Superseded chunks are excluded from default answers; a query explicitly asking for history
      can retrieve them, clearly labeled superseded.
- [ ] Two `status: active` notes disagreeing on a fact are both surfaced as a flagged contradiction
      in the answer — never silently averaged or ranked apart.
- [ ] A query with zero chunks above the retrieval threshold returns the structured "no vault
      answer found" refusal — the LLM is not invoked to guess an answer in that case.
- [ ] Answers carry a staleness flag when `index_updated_at` (from Chunk 3) predates the vault
      tree's latest known change.
- [ ] A 10-question Phoenix eval set (drawn from real E4L knowledge, e.g. "What did we decide
      about the XPO liquidation timing?") is run: ≥8/10 answers correct+cited, 0
      confidently-wrong answers. If Phoenix is unreachable, the eval still runs and logs results
      to a local file (`.ralph/context-log.md` or a dedicated eval log) instead of failing the
      chunk.
- [ ] All tests pass with zero failures.

## Endpoints / Interfaces

No new external HTTP endpoints — Ask-E4L is a chat surface inside the existing Cato desktop/
Telegram UI, calling the Chunk 3 index locally in-process.

## Database Changes

No schema changes in this chunk (reads Chunk 3's populated `kg_nodes`/`kg_edges`; writes only eval
result logs, not vault or index state).

## Test Scenarios

- **Happy path**: a real E4L knowledge question returns a cited, correct answer with no staleness
  flag when the index is fresh.
- **Edge case**: a question whose answer depends on two contradicting active notes returns both,
  flagged as a contradiction, not a single averaged answer.
- **Failure case**: a question with no matching vault content returns the refusal path, not a
  hallucinated answer — this is the "0 confidently-wrong" bar and must be tested explicitly with
  an out-of-scope question in the eval set.
- **Integration**: this chunk closes Phase C; Chunk 5 (Finance view) and Chunk 6 (Work Inbox nav)
  both assume Ask-E4L exists as a working nav item to fold into the reorganized 9-item sidebar.

## Dependencies

- **Requires**: CHUNK_3_VAULT_INDEX.
- **Blocks**: CHUNK_6_WORK_INBOX (the nav reorg absorbs Chat/Memory-search into Ask E4L, which
  must exist first).

## Completion Promise

<promise>CHUNK COMPLETE: CHUNK_4_ASK_E4L</promise>
