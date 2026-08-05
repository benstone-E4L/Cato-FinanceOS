# Cato as Genesis Meta-Agent — Technical Design
**Date:** 2026-03-13
**Status:** Draft v1.0
**Scope:** Genesis skill file, MCP client integration, task routing table,
`invoke_for_genesis_phase`, and state management extension.

---

## 1. Goals and Non-Goals

### Goals
- Give Cato a first-class skill file (`genesis-pipeline.md`) that makes it
  the orchestrator of the Genesis pipeline without rewriting existing
  `pipeline/` machinery.
- Connect Cato to the Windows MCP server as an MCP *client* so it gains the
  same Windows app control Claude Desktop has.
- Define a canonical routing table that maps each Genesis phase to the best
  available CLI worker and explains the reasoning.
- Add `invoke_for_genesis_phase(phase, context, business_id)` to
  `cli_invoker.py` so callers never hard-code phase-to-CLI decisions.
- Extend the existing `PipelineStore` (SQLite) and `EmpireRun` model to carry
  Genesis-style checkpoint data alongside the existing empire-run rows.

### Non-Goals
- Replacing `EmpireRuntime` or any `pipeline/` class.
- Rewriting `cli_invoker.py`; only one new function is added.
- Building a new Windows MCP server; we connect to the existing one at
  `https://github.com/CursorTouch/Windows-MCP`.
- Parallelising phases that are intentionally sequential (phases 5-7).

### Constraints and Assumptions
- Python 3.11+, asyncio, Windows-only deployment.
- `mcp` Python SDK (Anthropic) is available; the Windows MCP server runs
  as a stdio subprocess (`node windows_mcp/index.js`).
- Existing `PipelineStore` schema must not break; new columns use
  `ALTER TABLE ... ADD COLUMN ... DEFAULT NULL`.
- Budget caps enforced by `cato/budget.py` apply to every worker call.
- The Vault (`cato/vault.py`) is the only source of secrets; no plain-text
  credentials in skill files or config.

---

## 2. Socratic Design Questions and Answers

The four HMW questions from `cato-genesis-matrix/HMW.md` frame every
decision below.

**Q-A: Windows app interaction without rebuilding Windows MCP?**
Answer: Bridge. Connect to the existing stdio Windows MCP server as an MCP
client using the `mcp` Python SDK. A thin `WindowsMCPClient` wrapper translates
tool calls into tool results over a long-lived `stdio` transport. No new server
code needed.

**Q-B: Route each phase to the right CLI without state loss?**
Answer: A static routing table in `cli_invoker.py` + a per-phase prompt
assembler in the skill file. The existing `PhaseRouter` in `pipeline/runtime.py`
is the right pattern; `invoke_for_genesis_phase` follows the same shape but
lives in `cli_invoker.py` so it is available without importing the full
`EmpireRuntime`.

**Q-C: Non-blocking asyncio communication?**
Answer: Every CLI call already uses `asyncio.create_subprocess_exec` inside
`cli_invoker.py`. The MCP stdio transport runs in a background task managed by
`asyncio.create_task`. No additional threading is needed.

**Q-D: Resume mid-phase after crash?**
Answer: Extend `empire_runs` with a `checkpoint_json` column. Write a checkpoint
after each phase completes and after each requirement script runs. On resume,
load the checkpoint and skip completed work.

---

## 3. Approach Options

Three approaches were considered for each major decision.

### 3.1 Genesis Skill File Placement

| Option | Location | Pros | Cons |
|--------|----------|------|------|
| A | `~/.cato/skills/genesis-pipeline.md` | Matches existing skills pattern; auto-loaded by `ContextBuilder` | Outside repo; harder to version-control |
| B | `cato/skills/genesis-pipeline.md` (in-repo) | Version-controlled with code | Not auto-loaded by the same path; requires config change |
| C | `~/.claude/skills/genesis-pipeline/SKILL.md` | Available to Claude CLI directly | Wrong daemon; only useful for Claude Code, not Cato |

**Recommended: Option A.**
The daemon's `ContextBuilder` already reads `~/.cato/skills/`. The file can be
symlinked or copied during install. Version-control it in `cato/skills/` and
install it via a setup step in `start_cato.bat`.

### 3.2 MCP Client Transport

| Option | Transport | Pros | Cons |
|--------|-----------|------|------|
| A | stdio (subprocess) | Direct; works on Windows; no network port needed | Process must be managed by Cato |
| B | HTTP (SSE) | Works with remote server | Windows MCP server is stdio-only |
| C | In-process import | Zero overhead | Couples Python to Node.js; not viable |

**Recommended: Option A.**
The Windows MCP server is a Node.js stdio server. The `mcp` Python SDK's
`stdio_client` context manager exactly matches this pattern.

### 3.3 State Management Extension

| Option | Mechanism | Pros | Cons |
|--------|-----------|------|------|
| A | New `checkpoints` table | Clean separation | Schema migration required |
| B | Add `checkpoint_json` column to `empire_runs` | Single-table access; compatible with existing queries | JSON blob limits query-ability |
| C | Separate checkpoint files on disk (like Genesis `scripts/checkpoint_system/`) | Matches existing Genesis scripts | Adds another source of truth |

**Recommended: Option B + Option C in tandem.**
Write `checkpoint_json` to the `empire_runs` row for fast resume reads, and
also write a `checkpoints/phase-N.json` file to disk so Genesis scripts that
expect file-based checkpoints continue to work. The checkpoint file format
matches `scripts/checkpoint_system/` output.

---

## 4. Architecture

```
 ┌─────────────────────────────────────────────────────────────┐
 │  Cato Daemon (asyncio, port 8080 / 8081)                    │
 │                                                             │
 │  agent_loop.py                                              │
 │    └── parses "run genesis" / "build <idea>" intent         │
 │         │                                                   │
 │         ▼                                                   │
 │  skills/genesis-pipeline.md  (loaded by ContextBuilder)     │
 │    └── gives Cato identity: "You are Genesis orchestrator"  │
 │         │                                                   │
 │         ▼                                                   │
 │  pipeline/runtime.py (EmpireRuntime)                        │
 │    ├── create_business_scaffold(idea)                       │
 │    └── execute_phase(slug, phase)  ──────────────────────┐  │
 │                                                          │  │
 │  orchestrator/cli_invoker.py                             │  │
 │    └── invoke_for_genesis_phase(phase, ctx, biz_id)  ◄───┘  │
 │         │                                                   │
 │         ├── Phase 1,2,4,5,7,8,9  → claude CLI              │
 │         ├── Phase 3              → gemini CLI (stdin)       │
 │         └── Phase 6              → codex CLI (exec)        │
 │                                                             │
 │  mcp/windows_client.py  (NEW)                               │
 │    └── WindowsMCPClient                                     │
 │         └── asyncio stdio transport to windows_mcp server  │
 │              └── tools: click, type, screenshot, etc.      │
 │                                                             │
 │  pipeline/store.py (PipelineStore, extended)                │
 │    ├── empire_runs (+ checkpoint_json column)               │
 │    └── empire_tasks (unchanged)                             │
 └─────────────────────────────────────────────────────────────┘
           │
           ▼
  ~/.cato/businesses/<slug>/
    ├── manifest.json
    ├── checkpoints/phase-N.json    ← file-based checkpoints
    ├── phase_1_outputs/
    ├── phase_3_outputs/
    ├── website/
    └── deployment/
```

---

## 5. Component: Genesis Skill File

**File:** `~/.cato/skills/genesis-pipeline.md`
(source version: `C:/Users/Administrator/Desktop/Cato/cato/skills/genesis-pipeline.md`)

The skill file follows the exact two-section pattern of `coding_agent.md`:
a hot section above the `<!-- COLD -->` separator for fast context, and a cold
section with full instructions loaded only when the skill is invoked.

### 5.1 Hot Section (always loaded)

```markdown
# Genesis Pipeline
**Version:** 1.0.0
**Capabilities:** pipeline.run, pipeline.resume, pipeline.status

## Trigger Phrases
"build a business", "run genesis", "start pipeline", "create <idea>",
"resume phase", "pipeline status", "what phase are we on"

## Quick Reference

| Phase | Name | Worker | Key Output |
|-------|------|--------|------------|
| 1 | Market Research | claude | WINNER_SPEC.md |
| 2 | SEO + Marketing | claude | SEO_STRATEGY.json |
| 3 | Design System | gemini | DESIGN_SYSTEM.md |
| 4 | Technical Spec | claude | BUILD_PLAN.md |
| 5 | Construction | claude | website/ |
| 6 | Test + Fix | codex | TEST_REPORT.md |
| 7 | Deploy | claude | live_url.txt |
| 8 | Marketing Automation | claude | LAUNCH_SEQUENCE.json |
| 9 | Long-Term Health | claude | health_report.md |

## Tool Calls

```
pipeline.run:    business_id=<slug>  start_phase=1  through_phase=7
pipeline.resume: business_id=<slug>  from_phase=<N>
pipeline.status: business_id=<slug>
```
```

### 5.2 Cold Section (full instructions)

Key rules encoded in the skill file:

1. **Identity.** "You are Cato acting as Genesis meta-agent. You orchestrate
   business creation through 9 phases. You do not write code yourself; you
   route tasks to the correct CLI worker and track state."

2. **Phase gating.** Each phase must produce its `required_outputs` before the
   next phase starts. Check `checkpoints/phase-N.json` exists and has
   `verified: true` before advancing.

3. **User gates.** Stop at phase 7 for explicit approval before phase 8.
   Emit a `AWAITING_APPROVAL` status message to the user and wait.

4. **Worker selection.** Always use `invoke_for_genesis_phase` — never
   call `invoke_claude_api` or `invoke_codex_cli` directly with a phase
   context. The routing table is canonical.

5. **Budget awareness.** Before each phase, call `budget.check_and_deduct`.
   If budget is exceeded, emit a warning and pause.

6. **Windows MCP.** For phases that require GUI interaction (e.g., Vercel
   dashboard during phase 7, Porkbun DNS during phase 6a), use
   `windows_mcp.call_tool("screenshot")` and `windows_mcp.call_tool("click")`
   rather than Playwright/Conduit. This is Cato's preferred path for Windows
   app control.

---

## 6. Task Routing Table

This table is the canonical source of truth for worker assignment.
It is encoded in `invoke_for_genesis_phase` and must match
`PhaseRouter.DEFAULT_PHASE_WORKERS` in `pipeline/runtime.py`.

| Phase | Name | Primary Worker | Fallback | Rationale |
|-------|------|---------------|---------|-----------|
| 1 | Market Research | `claude` | none | Claude Code has deep-research skill + web search tools; ideation requires nuanced synthesis |
| 2 | SEO + Marketing | `claude` | none | Atlas-Luna subagent pattern is Claude Code invoking another Claude prompt; no file writes |
| 3 | Design System | `gemini` | `claude` | Gemini's 1M context handles large reference libraries; design is description-heavy not code-heavy. Gemini stdin-pipe mode works reliably |
| 4 | Technical Spec | `claude` | `codex` | Claude Code excels at structured document generation with tool use (file writes, schema introspection); Codex handles hard backend architecture sub-tasks |
| 5 | Construction (Ralph Loop) | `claude` | `codex` | Ralph loop controller logic requires Claude Code's multi-tool orchestration; Codex drives chunk implementation inside the loop |
| 6 | Test + Fix | `codex` | `claude` | Codex `--full-auto` owns the fix loop; it runs tests, reads failures, writes patches without human confirmation. Claude reviews if Codex degrades |
| 7 | Deploy + Validate | `claude` | none | Deployment requires Vault secret access, multi-tool sequencing (Vercel + Porkbun + Stripe), and the approval-gate logic — all native to Claude Code |
| 8 | Marketing Automation | `claude` | none | Post-deploy automation is orchestration-heavy, not code-heavy; Claude Code's task coordination is the right shape |
| 9 | Long-Term Health | `claude` | none | Health review is read-only analysis; Claude's summarization is sufficient |

**Decision basis for gemini on phase 3:**
The existing `coding_agent.md` skill confirms: "Design systems / visual → gemini (stdin pipe only)."
`GeminiWorkerAdapter` in `workers.py` already uses `-p` flag which matches
the working `gemini -p` invocation pattern. The fallback to `claude` triggers
when `gemini` binary is missing or returns a degraded response.

---

## 7. New Function: `invoke_for_genesis_phase`

**File:** `C:/Users/Administrator/Desktop/Cato/cato/orchestrator/cli_invoker.py`

Add this function after the existing `invoke_subagent` function. It does not
modify any existing function.

```python
# Genesis phase routing table — source of truth.
# Must stay in sync with pipeline/runtime.py PhaseRouter.DEFAULT_PHASE_WORKERS.
_GENESIS_PHASE_ROUTING: dict[int, tuple[str, str | None]] = {
    # phase: (primary_worker, fallback_worker | None)
    1: ("claude",  None),
    2: ("claude",  None),
    3: ("gemini",  "claude"),
    4: ("claude",  "codex"),
    5: ("claude",  "codex"),
    6: ("codex",   "claude"),
    7: ("claude",  None),
    8: ("claude",  None),
    9: ("claude",  None),
}

# Per-phase timeout overrides (seconds).  Phases with long iterative loops
# get generous timeouts; quick-output phases use the default.
_GENESIS_PHASE_TIMEOUTS: dict[int, float] = {
    1: 180.0,   # deep research
    2: 120.0,   # SEO generation
    3: 120.0,   # design system
    4: 150.0,   # technical spec
    5: 600.0,   # Ralph loop construction (multiple sub-calls)
    6: 300.0,   # test + fix loop
    7: 240.0,   # deploy + validate
    8: 120.0,   # marketing automation
    9:  60.0,   # health review
}


async def invoke_for_genesis_phase(
    phase: int,
    context: str,
    business_id: str,
    *,
    worker_override: Optional[str] = None,
) -> Dict:
    """
    Route a Genesis pipeline phase to the correct CLI worker.

    This is the canonical entry point for all Genesis phase execution.
    Never call invoke_claude_api / invoke_codex_cli / invoke_gemini_cli
    directly for a Genesis phase — always go through this function.

    Args:
        phase:           Genesis phase number (1-9).
        context:         Full prompt bundle text (from PhasePromptBundle.prompt).
        business_id:     Business slug, embedded in the task label for tracing.
        worker_override: Force a specific worker (used by tests and manual retries).

    Returns:
        Same dict shape as invoke_subagent: model, response, confidence,
        latency_ms, degraded, source.

    Raises:
        ValueError: If phase is outside 1-9.
    """
    if phase not in _GENESIS_PHASE_ROUTING:
        raise ValueError(
            f"Genesis phase must be 1-9, got {phase!r}. "
            f"Valid phases: {sorted(_GENESIS_PHASE_ROUTING)}"
        )

    primary, fallback = _GENESIS_PHASE_ROUTING[phase]
    worker = worker_override or primary
    timeout = _GENESIS_PHASE_TIMEOUTS.get(phase, 120.0)
    task_label = f"genesis-phase-{phase}-{business_id}"

    logger.info(
        "Genesis phase %d routing to worker=%r (fallback=%r) business=%r",
        phase, worker, fallback, business_id,
    )

    result = await invoke_subagent(context, task_label, backend=worker)  # type: ignore[arg-type]

    if result.get("degraded") and fallback:
        logger.warning(
            "Genesis phase %d primary worker %r degraded, trying fallback %r",
            phase, worker, fallback,
        )
        fallback_result = await invoke_subagent(context, task_label, backend=fallback)  # type: ignore[arg-type]
        if not fallback_result.get("degraded"):
            fallback_result["fallback_used"] = True
            fallback_result["original_worker"] = worker
            return fallback_result
        # Both degraded — return primary result with fallback_attempted flag.
        result["fallback_attempted"] = True

    return result
```

**Integration note:** `invoke_subagent` already dispatches to
`invoke_claude_api`, `invoke_codex_cli`, `invoke_gemini_cli`, or
`invoke_cursor_cli` based on the backend string. The timeout parameter is not
yet threaded through `invoke_subagent` — the process pool and subprocess calls
use their own internal timeouts (60s / 120s). For phases that need longer
timeouts (phase 5 at 600s), the `EmpireRuntime.execute_phase` caller already
passes `timeout_sec` to `WorkerAdapter.run` via `WorkerAssignment`. The
`_GENESIS_PHASE_TIMEOUTS` table is included here for documentation and can be
wired to `WorkerAssignment.timeout_sec` in a follow-up.

---

## 8. MCP Client Integration

### 8.1 New File: `cato/mcp/windows_client.py`

The Windows MCP server (`CursorTouch/Windows-MCP`) is a Node.js stdio server.
Cato connects to it as an MCP client using the `mcp` Python SDK's
`StdioServerParameters` + `stdio_client` transport.

```
File: C:/Users/Administrator/Desktop/Cato/cato/mcp/windows_client.py
```

```python
"""
cato/mcp/windows_client.py — MCP client for the Windows-MCP stdio server.

Gives Cato the same Windows app control that Claude Desktop has via the
CursorTouch/Windows-MCP server, but driven from Python asyncio instead of
Claude Desktop.

Usage:
    client = WindowsMCPClient()
    await client.start()
    result = await client.call_tool("screenshot", {})
    await client.stop()

Or as an async context manager:
    async with WindowsMCPClient() as client:
        result = await client.call_tool("click", {"x": 100, "y": 200})
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import — mcp may not be installed in all environments.
try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


def _find_windows_mcp_server() -> list[str]:
    """
    Locate the Windows-MCP Node.js server entry point.

    Looks in order:
    1. WINDOWS_MCP_PATH environment variable
    2. ~/.cato/windows-mcp/index.js  (local install)
    3. windows_mcp/index.js relative to this file's parent package

    Returns:
        ["node.exe", "/path/to/windows_mcp/index.js"] suitable for
        StdioServerParameters.args.

    Raises:
        FileNotFoundError if no server is found.
    """
    import os
    node = shutil.which("node") or shutil.which("node.exe")
    if node is None:
        raise FileNotFoundError("node.js not found on PATH — required for Windows MCP")

    candidates = [
        Path(os.environ.get("WINDOWS_MCP_PATH", "")),
        Path.home() / ".cato" / "windows-mcp" / "index.js",
        Path(__file__).parent.parent.parent / "windows-mcp" / "index.js",
    ]
    for candidate in candidates:
        if candidate.exists():
            return [node, str(candidate)]
    raise FileNotFoundError(
        "Windows MCP server not found. "
        "Set WINDOWS_MCP_PATH or install to ~/.cato/windows-mcp/index.js"
    )


class WindowsMCPClient:
    """
    Async client for the Windows-MCP stdio server.

    Manages the server subprocess lifetime and exposes call_tool() for
    individual tool invocations from Cato's agent loop.
    """

    def __init__(self) -> None:
        if not _MCP_AVAILABLE:
            raise ImportError(
                "mcp package is required for WindowsMCPClient. "
                "Run: pip install mcp"
            )
        self._session: ClientSession | None = None
        self._exit_stack: Any = None
        self._available_tools: list[str] = []

    async def start(self) -> None:
        """Start the Windows MCP server subprocess and open a client session."""
        from contextlib import AsyncExitStack
        server_cmd = _find_windows_mcp_server()
        params = StdioServerParameters(
            command=server_cmd[0],
            args=server_cmd[1:],
        )
        self._exit_stack = AsyncExitStack()
        read, write = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()
        tools_response = await self._session.list_tools()
        self._available_tools = [t.name for t in tools_response.tools]
        logger.info(
            "Windows MCP client connected. Available tools: %s",
            self._available_tools,
        )

    async def stop(self) -> None:
        """Close the client session and stop the server subprocess."""
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None
            self._available_tools = []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """
        Call a tool on the Windows MCP server.

        Args:
            tool_name:  Tool identifier (e.g., "screenshot", "click", "type").
            arguments:  Tool argument dict.

        Returns:
            Tool result content (varies by tool).

        Raises:
            RuntimeError:  If the client is not started.
            ValueError:    If the tool is not available.
        """
        if self._session is None:
            raise RuntimeError("WindowsMCPClient is not started. Call await client.start() first.")
        if self._available_tools and tool_name not in self._available_tools:
            raise ValueError(
                f"Tool {tool_name!r} not available. "
                f"Available: {self._available_tools}"
            )
        result = await self._session.call_tool(tool_name, arguments)
        return result.content

    @property
    def tools(self) -> list[str]:
        """List of tool names exposed by the connected server."""
        return list(self._available_tools)

    async def __aenter__(self) -> "WindowsMCPClient":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()
```

### 8.2 Lifecycle Integration

The `WindowsMCPClient` is not a singleton. It is instantiated on-demand when
a Genesis phase needs Windows app interaction. Two usage patterns:

**Pattern A — Phase-scoped (recommended for phase 7 Vercel/Porkbun):**
```python
async with WindowsMCPClient() as win:
    screenshot = await win.call_tool("screenshot", {})
    await win.call_tool("click", {"x": 400, "y": 300})
```

**Pattern B — Daemon-scoped (for long-running tasks):**
Register a single `WindowsMCPClient` instance on `CatoConfig` during daemon
startup and shut it down in the `stop()` lifecycle hook. Add to
`cato_svc_runner.py` alongside the existing gateway startup.

The recommended integration point for daemon-scoped lifetime is
`cato/gateway.py` — add a `_windows_mcp: WindowsMCPClient | None` attribute
and start/stop it in the gateway's `start()` and `stop()` methods.

### 8.3 Tool Name Mapping

The Windows MCP server exposes these tools (from CursorTouch/Windows-MCP docs).
The mapping shows which Genesis phases use each tool:

| MCP Tool | Cato Phase | Use Case |
|----------|-----------|---------|
| `screenshot` | 7 | Verify Vercel deploy dashboard |
| `click` | 7 | Click "Deploy" / confirm DNS in Porkbun |
| `type` | 7 | Enter domain name in registration form |
| `key_press` | any | Keyboard shortcuts in desktop apps |
| `get_screen_text` | 7 | Read live URL from Vercel dashboard |
| `open_application` | any | Launch desktop app for interaction |

---

## 9. State Management Extension

### 9.1 Schema Migration

Add one column to `empire_runs` using an `ALTER TABLE` migration that is
safe to run multiple times (the `IF NOT EXISTS` on column add requires
SQLite 3.37+; use a try/except for compatibility):

```python
# In pipeline/store.py, add to _SCHEMA after existing CREATE TABLE statements:

_SCHEMA_MIGRATIONS = [
    """
    ALTER TABLE empire_runs ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}';
    """,
    """
    ALTER TABLE empire_runs ADD COLUMN genesis_phase_map TEXT NOT NULL DEFAULT '{}';
    """,
]
```

`checkpoint_json` stores a dict keyed by phase number:
```json
{
  "1": {
    "verified": true,
    "score": 95,
    "agent": "deep-research-agent",
    "deliverables": ["phase1_discovery.yaml", "MARKET_RESEARCH.json", "WINNER_SPEC.md"],
    "completed_at": 1741827600.0
  },
  "3": {
    "verified": false,
    "score": 72,
    "error": "DESIGN_SYSTEM.md missing",
    "completed_at": null
  }
}
```

`genesis_phase_map` stores the per-phase worker assignment used (for
retrospective analysis and resume logic):
```json
{
  "1": "claude",
  "3": "gemini",
  "6": "codex"
}
```

### 9.2 Checkpoint Write (new `PipelineStore` method)

```python
def write_phase_checkpoint(
    self,
    run_id: str,
    phase: int,
    *,
    verified: bool,
    score: int,
    agent: str,
    deliverables: list[str],
    error: str = "",
) -> None:
    """Write a Genesis checkpoint for a completed phase into the DB row
    and to the file system under <business_dir>/checkpoints/phase-N.json."""
    import time as _time
    run = self.get_run(run_id)
    checkpoint_data = json.loads(run.metadata.get("checkpoint_json", "{}") or "{}")
    checkpoint_data[str(phase)] = {
        "verified": verified,
        "score": score,
        "agent": agent,
        "deliverables": deliverables,
        "error": error,
        "completed_at": _time.time() if verified else None,
    }
    # Update DB
    self._conn.execute(
        "UPDATE empire_runs SET checkpoint_json = ?, updated_at = ? WHERE run_id = ?",
        (json.dumps(checkpoint_data), _time.time(), run_id),
    )
    self._conn.commit()

    # Write file-based checkpoint for Genesis script compatibility
    checkpoint_dir = run.business_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = checkpoint_dir / f"phase-{phase}.json"
    checkpoint_file.write_text(
        json.dumps({
            "phase": phase,
            "verified": verified,
            "score": score,
            "agent": agent,
            "deliverables": deliverables,
            "error": error,
            "completed_at": checkpoint_data[str(phase)]["completed_at"],
        }, indent=2),
        encoding="utf-8",
    )
```

### 9.3 Resume Logic

`EmpireRuntime.execute_phase` checks the checkpoint before dispatching:

```python
def _phase_is_complete(self, run: EmpireRun, phase: int) -> bool:
    """Return True if this phase already has a verified checkpoint."""
    # Check DB
    cp_data = json.loads(run.metadata.get("checkpoint_json", "{}") or "{}")
    cp = cp_data.get(str(phase))
    if cp and cp.get("verified"):
        return True
    # Check file-system fallback
    cp_file = run.business_dir / "checkpoints" / f"phase-{phase}.json"
    if cp_file.exists():
        try:
            data = json.loads(cp_file.read_text(encoding="utf-8"))
            return bool(data.get("verified"))
        except (OSError, json.JSONDecodeError):
            pass
    return False
```

The `run_pipeline` method gains a `skip_completed=True` parameter. When set,
each phase calls `_phase_is_complete()` and skips dispatch if it returns True.

---

## 10. File Structure

New and modified files:

```
cato/
  skills/
    genesis-pipeline.md          NEW — source file; install to ~/.cato/skills/
  mcp/
    __init__.py                  existing
    runtime.py                   existing (Cato as MCP server)
    windows_client.py            NEW — Cato as Windows MCP client
  orchestrator/
    cli_invoker.py               MODIFIED — add invoke_for_genesis_phase()
  pipeline/
    store.py                     MODIFIED — add checkpoint_json column migration
                                           + write_phase_checkpoint()
    runtime.py                   MODIFIED — add _phase_is_complete()
                                           + skip_completed param to run_pipeline()
    models.py                    unchanged
    workers.py                   unchanged
    phase_library.py             unchanged

~/.cato/skills/
  genesis-pipeline.md            INSTALLED — symlink or copy of cato/skills/genesis-pipeline.md
```

---

## 11. Error Handling

| Failure Mode | Detection | Recovery |
|-------------|-----------|---------|
| CLI worker not installed | `FileNotFoundError` in `_resolve_cli` | Fallback worker per routing table; log warning |
| Phase times out | `asyncio.TimeoutError` in `_run_cli` | Mark task `failed`; emit `AWAITING_RETRY` run status; do not advance phase |
| Both primary and fallback degraded | `degraded=True` on both | Set run status `FAILED`; write checkpoint with `verified=false`; surface error to user |
| MCP server not found | `FileNotFoundError` in `_find_windows_mcp_server` | Log warning; skip Windows MCP steps; use Conduit/Playwright fallback for browser tasks |
| Checkpoint file corrupt | `json.JSONDecodeError` | Fall back to DB checkpoint; if DB also missing, re-run phase |
| Budget exceeded | `BudgetExceeded` from `budget.py` | Surface to user immediately; pause pipeline at current phase |
| Phase 7 approval gate | Intentional pause | Emit `AWAITING_APPROVAL`; resume only on explicit `pipeline.resume` tool call |

---

## 12. Testing Plan

### Unit Tests

**`tests/orchestrator/test_genesis_routing.py`**
- `test_invoke_for_genesis_phase_routes_correctly`: For each phase 1-9,
  mock `invoke_subagent` and assert the correct backend is called.
- `test_invoke_for_genesis_phase_uses_fallback`: Set gemini to return
  `degraded=True`; assert phase 3 retries with `claude`.
- `test_invoke_for_genesis_phase_invalid_phase`: Assert `ValueError` for
  phase 0 and phase 10.

**`tests/mcp/test_windows_client.py`**
- `test_windows_client_no_mcp_package`: Monkeypatch `_MCP_AVAILABLE=False`;
  assert `ImportError` on construction.
- `test_windows_client_server_not_found`: Monkeypatch `_find_windows_mcp_server`
  to raise `FileNotFoundError`; assert `start()` propagates it.
- `test_call_tool_before_start`: Assert `RuntimeError` from `call_tool` when
  session is `None`.

**`tests/pipeline/test_checkpoint_extension.py`**
- `test_write_phase_checkpoint_writes_db`: Write a checkpoint; read back via
  `get_run`; assert `checkpoint_json` key is present.
- `test_write_phase_checkpoint_writes_file`: Assert file at
  `<business_dir>/checkpoints/phase-N.json` is created.
- `test_phase_is_complete_reads_db`: Write verified checkpoint; assert
  `_phase_is_complete` returns `True`.
- `test_phase_is_complete_falls_back_to_file`: Delete DB row's
  `checkpoint_json`; assert file-based check still returns `True`.

### Integration Tests

**`tests/pipeline/test_genesis_skill_integration.py`**
- Start a real `EmpireRuntime` with `PipelineStore` in a temp dir.
- Mock `WorkerAdapter.run` to return synthetic responses with correct file
  outputs.
- Run phases 1-3 with `skip_completed=True`; assert phases are not
  re-dispatched after `write_phase_checkpoint` is called.

### Manual Smoke Tests

1. Start Cato daemon: `CATO_VAULT_PASSWORD=<pw> python cato_svc_runner.py`
2. Send: `POST /chat {"message": "build a business: AI tutoring for kids"}`
3. Confirm genesis-pipeline.md skill is loaded (log: `Loaded skill genesis-pipeline`)
4. Confirm phase 1 routes to `claude` (log: `Genesis phase 1 routing to worker='claude'`)
5. Confirm phase 3 routes to `gemini` (log: `Genesis phase 3 routing to worker='gemini'`)
6. Kill daemon mid-phase 2; restart; confirm resume skips phase 1 checkpoint

---

## 13. Milestones

| Milestone | Deliverables | Estimated Effort |
|-----------|-------------|-----------------|
| M1 — Routing + Invoker | `invoke_for_genesis_phase` added; routing tests passing | 2-3 hours |
| M2 — Checkpoint Extension | `PipelineStore` migration + `write_phase_checkpoint`; resume tests passing | 3-4 hours |
| M3 — Skill File | `cato/skills/genesis-pipeline.md` written; install step in `start_cato.bat` | 2 hours |
| M4 — Windows MCP Client | `cato/mcp/windows_client.py` written; unit tests passing | 3-4 hours |
| M5 — Integration Smoke Test | Full phase 1-3 smoke test with mocked workers; checkpoint resume verified | 2 hours |

---

## 14. Open Questions

1. **Windows MCP server install location.** Should the server be bundled in
   the Cato repo (`windows-mcp/`) or documented as a separate prerequisite?
   Current design assumes `~/.cato/windows-mcp/index.js` with a setup
   step in `install_autostart.py`.

2. **Cursor worker for Genesis.** The routing table does not assign Cursor to
   any phase. Is there a phase where Cursor's "auto" model router would
   outperform Claude or Codex? Candidate: phase 6 (test + fix) as a second
   fallback after Codex.

3. **Parallel business builds.** `EmpireRuntime` and `PipelineStore` are
   already per-run-id safe. The Windows MCP client is not thread-safe for
   concurrent use. If multiple businesses run phase 7 simultaneously, they
   will contend for the single Windows MCP session. A simple lock
   (`asyncio.Lock`) on the daemon-scoped client resolves this.

4. **`PhaseRouter.DEFAULT_PHASE_WORKERS` sync.** The routing table exists in
   two places: `pipeline/runtime.py` (integer keys 1-9) and
   `cli_invoker.py` (`_GENESIS_PHASE_ROUTING`). A shared constant module
   (e.g., `pipeline/routing_constants.py`) would eliminate the duplication.
   Deferred to a follow-up to keep this change minimal.
