# RALPH PLANNING MODE

You are ralph-wiggum-loop operating in PLANNING mode.

## Your Only Job This Iteration

Read the specs and produce IMPLEMENTATION_PLAN.md.
Do NOT write any application code. Do NOT write any tests.
Do NOT create any files other than IMPLEMENTATION_PLAN.md.

## Project Context

Project: e4l-assistant-buildout-ralph
Stack: Python 3.11+ (aiohttp/websockets daemon) + Tauri v2/React 19 desktop + SQLite
Repo: C:\Users\Work\Desktop\vault\projects\My Github\Cato (this workstream's ONLY scope — do not
touch e4l-work-os, Genesis Agents, Coordination Ledger, or FinanceOS repos)
Output directory: current working directory

## Read These Files First

1. AGENTS.md — build commands and validation gate
2. specs/*.md — one file per chunk (read all 6 of them, in order 01-06)
3. .ralph/guardrails.md — known risks, scope exclusions, and the Genesis 21-slug / WhatsApp /
   O2O-FOS-1 decision points

## Produce: IMPLEMENTATION_PLAN.md

Format:
```
# IMPLEMENTATION_PLAN.md

## Chunk Order
{List chunks in order with one-sentence descriptions}

## Chunk {N}: {chunk_id}
### Tasks (in order)
1. {specific file/function to create or modify}
2. {next task}
...
### Validation
- Command: {validation gate from AGENTS.md}
- Expected: exit 0, all tests green
### Promise
<promise>CHUNK COMPLETE: {chunk_id}</promise>
```

## Rules

- Every chunk from specs/ must appear in the plan (all 6: HYGIENE, VAULT, VAULT_INDEX, ASK_E4L,
  FINANCE_VIEW, WORK_INBOX).
- Tasks must be specific enough that a junior developer could execute them without clarification.
- Do not include tasks outside the specs. Scope creep is forbidden — this is a Cato-only
  workstream; do not plan any task that requires editing e4l-work-os, Genesis Agents, the
  Coordination Ledger, or FinanceOS repos.
- CHUNK_2_VAULT's task list must explicitly separate the manual operator step (Ben rotates the
  Telegram token and chooses a new CATO_VAULT_PASSWORD) from the code/tooling tasks — do not plan
  a task that has the agent invent or silently pick new secret values.
- Do not generate code. Generate task descriptions only.
- When done writing IMPLEMENTATION_PLAN.md, stop. Do not proceed to build.

## Completion Signal

When IMPLEMENTATION_PLAN.md is written, append to .ralph/progress.md:
```
[{ISO_TIMESTAMP}] Planning complete — IMPLEMENTATION_PLAN.md written (6 chunks, {M} tasks)
<promise>PLANNING_COMPLETE</promise>
```
Then also output the same promise tag and stop. Use the underscore form exactly as written above.
