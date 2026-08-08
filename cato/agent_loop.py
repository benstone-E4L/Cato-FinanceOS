"""
cato/agent_loop.py — Agentic message-processing loop for CATO.

Processes one inbound message per session:
  1. Build context (ContextBuilder)
  2. Retrieve memory chunks
  3. Check budget before every LLM call (BudgetManager.check_and_deduct)
  4. Call LLM via ModelRouter (deterministic policy -> Anthropic direct)
  5. Parse tool calls and dispatch them
  6. Loop until final answer (max_planning_turns before forced answer)
  7. Persist JSONL transcript at ~/.cato/{agent_id}/sessions/{session_id}.jsonl
  8. Store final response in memory (memory.astore)
  9. Return (final_text, cost_footer)

Compaction:
  - Triggered when history tokens > COMPACT_TOKEN_THRESHOLD (9000) or
    total turns > COMPACT_TURN_THRESHOLD (30).
  - Old turns are distilled via Distiller (heuristic, no LLM call) and
    stored in the distilled_summaries SQLite table.
  - The transcript is then truncated to the last HISTORY_WINDOW turns.
  - The distilled summary is injected into the system prompt via
    ContextBuilder.build_system_prompt(distilled_summary=...).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .audit import AuditLog
from .auth.token_checker import TokenChecker
from .budget import BudgetExceeded, BudgetManager
from .config import CatoConfig
from .core.context_builder import ContextBuilder
from .core.memory import MemorySystem
from .platform import get_data_dir
from .progress import ProgressCallback, ProgressEmitter
from .router import ModelRouter
from .safety import SafetyGuard
from .anthropic_client import AnthropicAPIError, RetryClass
from .model_policy import (
    CostGateExceeded,
    EscalationExhausted,
    TaskDescriptor,
    TaskType,
)
from .tools.genesis import GENESIS_TOOL_SCHEMA
from .vault import Vault

logger = logging.getLogger(__name__)

_BUDGET_BYPASS_PHRASES = (
    "continue anyway",
    "bypass budget",
    "override budget",
    "ignore budget",
    "proceed anyway",
    "keep going",
)


def _budget_bypass_requested(message: str, config: Optional[Any] = None) -> bool:
    if config is not None and getattr(config, "unattended_mode", False):
        return False
    text = message.lower()
    return any(phrase in text for phrase in _BUDGET_BYPASS_PHRASES)

_CATO_DIR       = get_data_dir()
_CHARS_PER_TOKEN = 4
_MAX_RETRIES    = 3
_RETRY_BASE_DELAY = 1.5  # seconds; doubles each retry

# ---------------------------------------------------------------------------
# Compaction constants
# ---------------------------------------------------------------------------

# Number of recent turns kept live after compaction
HISTORY_WINDOW: int = 12
# Trigger compaction when history token cost exceeds this threshold
COMPACT_TOKEN_THRESHOLD: int = 9000
# Trigger compaction when total turn count exceeds this threshold
COMPACT_TURN_THRESHOLD: int = 30


# ---------------------------------------------------------------------------
# Tool call model and registry
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""
    error: str = ""
    raw: Optional[dict[str, Any]] = None


# Chunk 4 registers real handlers here via register_tool()
_TOOL_REGISTRY: dict[str, Callable] = {}

# Tool schemas: OpenAI-format function definitions for structured tool calling.
# Registered alongside handlers so the model receives proper JSON Schema per tool.
_TOOL_SCHEMAS: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Built-in tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------
_BUILTIN_SCHEMAS: dict[str, dict] = {
    "shell": {
        "type": "function",
        "function": {
            "name": "shell",
            "description": (
                "Execute a shell command on the local system. "
                "Returns stdout, stderr, and exit code.\n\n"
                "Default allowlist (always permitted): ls, cat, head, tail, grep, find, wc, "
                "echo, printf, python, python3, git, mkdir, cp, mv, chmod, pwd, env, which, "
                "date, sort, uniq, sed, awk, tr, cut, tee, touch, rm, "
                "powershell, powershell.exe, pwsh, pwsh.exe, cmd, cmd.exe.\n\n"
                "NOT in the default allowlist (blocked unless added to exec-approvals.json): "
                "curl, wget, pip, pip3, npm, node.\n\n"
                "PowerShell mode: powershell runs in gateway mode by default (cwd clamped to workspace). "
                "Full unrestricted mode only activates when powershell_full_mode=true is set in config.yaml.\n\n"
                "IMPORTANT — reading or editing files on the system:\n"
                "  Do NOT construct complex PowerShell -Command strings for file access. "
                "Use the `file` tool with root='absolute' instead — it handles all paths without quoting issues:\n"
                "    file(action='read',  path='C:\\full\\path\\file.py', root='absolute')\n"
                "    file(action='patch', path='C:\\full\\path\\file.py', root='absolute', "
                "old_string='...', new_string='...')\n"
                "  Reserve shell for running programs (python, git, npm) and commands that produce stdout output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 300)"},
                    "cwd": {"type": "string", "description": "Working directory for the command"},
                    "mode": {"type": "string", "enum": ["gateway", "sandbox", "full"], "description": "Execution mode. gateway=allowlist enforced (default). sandbox=most restrictive. full=unrestricted, and asking for it here does NOT grant it: full mode requires a human-approved execution ticket (or the operator's powershell_full_mode config opt-in for PowerShell), otherwise the call is refused."},
                },
                "required": ["command"],
            },
        },
    },
    "file": {
        "type": "function",
        "function": {
            "name": "file",
            "description": (
                "Read, write, patch, list, or delete files. "
                "Supports two path modes:\n"
                "  - root='workspace' (default): scoped to ~/.cato/workspace/{agent_id}/. Use relative paths.\n"
                "  - root='absolute': access ANY path on the system (e.g. C:\\Users\\...\\script.py). "
                "Use an absolute path string.\n\n"
                "IMPORTANT — editing files outside the workspace:\n"
                "  Use action='patch' with root='absolute' instead of PowerShell. "
                "This avoids all PowerShell quoting/escaping issues.\n"
                "  Workflow for editing any file:\n"
                "    1. file(action='read', path='C:\\full\\path', root='absolute') — read exact current content\n"
                "    2. file(action='patch', path='C:\\full\\path', root='absolute', "
                "old_string='...exact text...', new_string='...replacement...') — apply surgical edit\n"
                "  patch fails with a clear error if old_string is not found (no silent no-ops).\n"
                "  patch fails if old_string appears multiple times unless replace_all=true.\n\n"
                "Actions: read, write, append, patch, list, delete, exists, roots"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "append", "patch", "list", "delete", "exists", "roots"],
                        "description": "File operation. Use 'patch' for surgical edits (find-replace).",
                    },
                    "path": {
                        "type": "string",
                        "description": "Relative path within workspace (root='workspace'), or absolute system path (root='absolute').",
                    },
                    "root": {
                        "type": "string",
                        "enum": ["workspace", "absolute"],
                        "description": "Path mode. 'absolute' allows editing any file on the system without PowerShell.",
                    },
                    "content": {"type": "string", "description": "Content to write (for write/append action)"},
                    "old_string": {"type": "string", "description": "Exact text to find and replace (for patch action). Must match the file exactly."},
                    "new_string": {"type": "string", "description": "Replacement text (for patch action). Omit or set to '' to delete old_string."},
                    "replace_all": {"type": "boolean", "description": "Replace every occurrence of old_string (patch action). Default false — fails if old_string appears more than once."},
                    "recursive": {"type": "boolean", "description": "Recursive listing (for list action)"},
                    "encoding": {"type": "string", "description": "File encoding (default utf-8)"},
                },
                "required": ["action", "path"],
            },
        },
    },
    "browser": {
        "type": "function",
        "function": {
            "name": "browser",
            "description": (
                "Browser automation: navigate to URLs, take screenshots, click elements, "
                "type text, search the web, extract page content.\n\n"
                "Restrictions:\n"
                "  - Only http:// and https:// URLs are allowed.\n"
                "  - localhost, 127.0.0.1, and private/RFC-1918 IPs (10.x, 192.168.x, 172.16-31.x) "
                "are blocked — cannot be used for local server testing.\n"
                "  - The 'search' action uses DuckDuckGo only (not Google or Bing).\n\n"
                "For local server testing, use shell(command='python -m http.server ...') to inspect "
                "output, or file(action='read', root='absolute') to read files directly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["navigate", "snapshot", "click", "type", "fill", "screenshot", "pdf", "search", "eval", "extract_main", "scroll", "wait", "key_press", "hover", "navigate_back", "console_messages", "network_requests", "accessibility_snapshot"], "description": "Browser action to perform"},
                    "url": {"type": "string", "description": "URL to navigate to (for navigate action)"},
                    "selector": {"type": "string", "description": "CSS selector or text to target an element"},
                    "text": {"type": "string", "description": "Text to type or fill"},
                    "query": {"type": "string", "description": "Search query (for search action)"},
                    "expression": {"type": "string", "description": "JavaScript expression (for eval action)"},
                    "direction": {"type": "string", "enum": ["up", "down"], "description": "Scroll direction"},
                    "filename": {"type": "string", "description": "Output filename (for pdf/screenshot)"},
                },
                "required": ["action"],
            },
        },
    },
    "memory": {
        "type": "function",
        "function": {
            "name": "memory",
            "description": "Store or search agent memory. Actions: store (save a fact/note), search (retrieve relevant memories).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["store", "search"], "description": "Memory operation"},
                    "text": {"type": "string", "description": "Text to store or search query"},
                    "source": {"type": "string", "description": "Source label for stored memory"},
                },
                "required": ["action", "text"],
            },
        },
    },
    "web.search": {
        "type": "function",
        "function": {
            "name": "web.search",
            "description": "Search the web and return relevant results with titles, URLs, and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Maximum results to return (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    "web.code": {
        "type": "function",
        "function": {
            "name": "web.code",
            "description": "Search for code examples and programming solutions on the web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Code-related search query"},
                    "language": {"type": "string", "description": "Programming language filter"},
                },
                "required": ["query"],
            },
        },
    },
    "web.news": {
        "type": "function",
        "function": {
            "name": "web.news",
            "description": "Search for recent news articles on a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "News search query"},
                    "max_results": {"type": "integer", "description": "Maximum results (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    "python.exec": {
        "type": "function",
        "function": {
            "name": "python.exec",
            "description": (
                "Execute Python code in a subprocess sandbox and return stdout/stderr/returncode.\n\n"
                "Standard library and pip-installed packages are available. "
                "Standard file I/O (open(), pathlib.Path.read_text/write_text, etc.) is fully allowed — "
                "use this for file manipulation instead of constructing PowerShell commands.\n\n"
                "Blocked patterns (raise SandboxViolationError immediately):\n"
                "  os.remove, shutil.rmtree, subprocess.run, subprocess.call, socket.connect.\n\n"
                "If you need to delete files, use file(action='delete', root='absolute'). "
                "If you need network calls, use web.search or browser instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {"type": "integer", "description": "Execution timeout in seconds (default 30, max 300)"},
                },
                "required": ["code"],
            },
        },
    },
    "graph.query": {
        "type": "function",
        "function": {
            "name": "graph.query",
            "description": "Query the knowledge graph. Returns nodes reachable from a given label within max_hops.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Starting node label"},
                    "max_hops": {"type": "integer", "description": "Maximum traversal depth (default 2)"},
                },
                "required": ["label"],
            },
        },
    },
    "graph.related": {
        "type": "function",
        "function": {
            "name": "graph.related",
            "description": "Find related concepts in the knowledge graph by label.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Concept label to find relations for"},
                    "max_hops": {"type": "integer", "description": "Maximum traversal depth (default 2)"},
                },
                "required": ["label"],
            },
        },
    },
    # genesis: single source of truth lives in cato/tools/genesis.py
    # to avoid schema drift between the tool module and the agent loop.
    "genesis": GENESIS_TOOL_SCHEMA,
}


def register_tool(name: str, fn: Callable, schema: Optional[dict] = None) -> None:
    """Register an async tool handler and optional schema."""
    _TOOL_REGISTRY[name] = fn
    if schema:
        _TOOL_SCHEMAS[name] = schema
    elif name in _BUILTIN_SCHEMAS:
        _TOOL_SCHEMAS[name] = _BUILTIN_SCHEMAS[name]


def _sanitize_tool_name(name: str) -> str:
    """Return a provider-safe name for OpenAI API compatibility.

    OpenAI requires tool names to match ``^[a-zA-Z0-9_-]+$``.
    Cato uses dotted names internally (e.g. ``web.search``).
    Dots become ``__`` so ``foo.bar`` cannot collide with ``foo_bar``.
    """
    safe = (name or "cato_tool").replace(".", "__")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", safe)
    return safe[:64] or "cato_tool"


def _anthropic_tool_defs(openai_tools: list[dict]) -> list[dict]:
    """Convert OpenAI-style function tool defs to the Anthropic tool schema."""
    out: list[dict] = []
    for t in openai_tools or []:
        fn = t.get("function", t) if isinstance(t, dict) else {}
        out.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _sanitize_tool_defs(defs: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Return (sanitized_defs, reverse_map) for OpenAI-compatible tool names.

    reverse_map maps sanitized_name → original_name so we can dispatch
    tool calls returned by the model back to the correct handler.
    """
    sanitized: list[dict] = []
    reverse_map: dict[str, str] = {}
    import copy
    for d in defs:
        fn = d.get("function", {})
        orig = fn.get("name", "")
        clean = _sanitize_tool_name(orig)
        if clean != orig:
            d2 = copy.deepcopy(d)
            d2["function"]["name"] = clean
            sanitized.append(d2)
            reverse_map[clean] = orig
        else:
            sanitized.append(d)
    return sanitized, reverse_map


def _repair_tool_call_pairing(messages: list[dict]) -> list[dict]:
    """Repair message sequence to satisfy the OpenAI/MiniMax tool-call contract.

    BH-007 — When the agent loop trims conversation history (``_recent_turns``
    slices ``lines[-HISTORY_WINDOW:]`` and ``_maybe_compact`` rewrites the
    transcript) it can sever an ``assistant(tool_calls=[X])`` →
    ``tool(tool_call_id=X)`` pair.  If the assistant message is dropped but
    the tool result is preserved, the provider rejects the request with
    HTTP 400::

        Invalid parameter: messages with role 'tool' must be a response to
        a preceeding message with 'tool_calls'.

    The API masks this rejection as an empty completion, the agent loop
    falls back to ``_stream_collect`` with the same broken history, all
    retries return empty, and the user sees::

        The model returned no readable content after multiple attempts.

    Repair rules (conservative — never invent data):
      1. Drop any ``tool`` message whose ``tool_call_id`` was not promised
         by the most recent ``assistant`` with ``tool_calls`` still pending.
      2. When the active assistant's pending ``tool_calls`` are not all
         satisfied before the next non-tool message, drop the unfulfilled
         ``tool_call`` entries from that assistant.  If that empties the
         ``tool_calls`` field *and* the assistant has no visible content,
         drop the assistant message entirely.

    The function is idempotent: ``_repair(_repair(x)) == _repair(x)``.
    Pure — does not mutate the input list or its dicts.
    """
    out: list[dict] = []
    pending: set[str] = set()  # tool_call_ids the latest assistant still owes
    asst_idx: int = -1         # position in `out` of that assistant

    def flush_pending() -> None:
        """Strip unfulfilled tool_calls from the latest assistant in `out`."""
        nonlocal asst_idx, pending
        if asst_idx < 0 or not pending:
            asst_idx = -1
            pending = set()
            return
        msg = out[asst_idx]
        kept = [
            tc for tc in (msg.get("tool_calls") or [])
            if tc.get("id") not in pending
        ]
        new_msg = dict(msg)
        if kept:
            new_msg["tool_calls"] = kept
            out[asst_idx] = new_msg
        else:
            new_msg.pop("tool_calls", None)
            if not (new_msg.get("content") or "").strip():
                # Assistant has nothing left to say — drop entirely.
                del out[asst_idx]
            else:
                out[asst_idx] = new_msg
        asst_idx = -1
        pending = set()

    for msg in messages:
        role = msg.get("role")
        if role == "tool":
            tcid = msg.get("tool_call_id")
            if tcid and tcid in pending:
                pending.discard(tcid)
                out.append(msg)
            # else: orphan tool result — silently drop
            continue

        # Any non-tool message finalises the previous assistant's pending ids
        flush_pending()
        out.append(msg)
        if role == "assistant" and msg.get("tool_calls"):
            ids = [tc.get("id") for tc in msg["tool_calls"] if tc.get("id")]
            if ids:
                pending = set(ids)
                asst_idx = len(out) - 1

    flush_pending()
    return out


def _sanitize_messages_for_api(messages: list[dict]) -> list[dict]:
    """Sanitize tool names in message history for API compatibility.

    When tool_calls in assistant messages reference hallucinated or dotted
    names, the API rejects subsequent tool result messages.  This function
    normalises all tool-call function names to match the sanitized tool
    definitions we send to the API.

    Two passes:
    1. Replace dots with double underscores (``web.search`` → ``web__search``)
    2. Resolve hallucinated short names via the alias table
       (``shell`` → ``shell__exec``)

    BH-007: After name normalisation, run :func:`_repair_tool_call_pairing`
    so any orphan ``tool`` messages or unfulfilled ``tool_calls`` left over
    from history truncation are stripped before the request hits the API.
    """
    import copy
    # Build alias lookup: short name → sanitized registered name
    _api_aliases: dict[str, str] = {}
    for alias, real in _TOOL_ALIASES.items():
        _api_aliases[alias] = _sanitize_tool_name(real)
    # Also map every registered tool to its sanitized form
    for name in _TOOL_REGISTRY:
        san = _sanitize_tool_name(name)
        if san != name:
            _api_aliases[name] = san
            # Backward compatibility for transcripts written by older builds
            # that collapsed dotted names with a single underscore.
            _api_aliases[name.replace(".", "_")] = san

    def _resolve_for_api(name: str) -> str:
        san = _sanitize_tool_name(name)
        return _api_aliases.get(san, _api_aliases.get(name, san))

    clean: list[dict] = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            m = copy.deepcopy(msg)
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                if "name" in fn:
                    fn["name"] = _resolve_for_api(fn["name"])
            clean.append(m)
        else:
            clean.append(msg)
    # BH-007: defence-in-depth — repair pairing before API submission.
    return _repair_tool_call_pairing(clean)


def _openai_tool_definition(name: str, schema: dict) -> dict:
    """Normalize legacy flat schemas to OpenAI ``type: function`` shape."""
    if schema.get("type") == "function" and isinstance(schema.get("function"), dict):
        return schema
    fn_name = str(schema.get("name") or name)
    return {
        "type": "function",
        "function": {
            "name": fn_name,
            "description": str(schema.get("description") or f"Execute the {fn_name} tool."),
            "parameters": schema.get("parameters")
            or {"type": "object", "properties": {}},
        },
    }


def get_tool_definitions() -> list[dict]:
    """Return OpenAI-format tool definitions for all registered tools."""
    defs = []
    for name in sorted(_TOOL_REGISTRY):
        if name in _TOOL_SCHEMAS:
            defs.append(_openai_tool_definition(name, _TOOL_SCHEMAS[name]))
        else:
            # Auto-generate a minimal schema for unregistered tools
            defs.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"Execute the {name} tool.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            })
    return defs


def register_all_tools(register_tool_fn: Callable[[str, Any], None], config: Optional[Any] = None) -> None:
    """Public API: register all available tools via a provided register_tool function."""
    _register_web_search_tools()
    _register_python_executor_tools()
    _register_shell_tools()
    _register_file_tools()
    _register_browser_tools()
    _register_github_tools()
    _register_conduit_tools()
    _register_integration_tools()
    _register_clawflow_tools()


# ---------------------------------------------------------------------------
# Web-Search-Plus tool registrations (Skill 6)
# ---------------------------------------------------------------------------

def _register_web_search_tools(vault: Any = None) -> None:
    """Register web.search / web.code / web.news / academic.* tool actions."""
    try:
        from .tools.web_search import WebSearchTool
    except ImportError:
        return

    tool = WebSearchTool(vault=vault)

    async def _web_search(args: dict) -> str:
        results = await tool.search(query=args.get("query", ""), query_type="general")
        return "\n".join(f"[{r.rank+1}] {r.title}\n    {r.url}\n    {r.snippet}" for r in results[:5])

    async def _web_code(args: dict) -> str:
        results = await tool.search(query=args.get("query", ""), query_type="code")
        return "\n".join(f"[{r.rank+1}] {r.title}\n    {r.url}\n    {r.snippet}" for r in results[:5])

    async def _web_news(args: dict) -> str:
        results = await tool.search(query=args.get("query", ""), query_type="news")
        return "\n".join(f"[{r.rank+1}] {r.title}\n    {r.url}\n    {r.snippet}" for r in results[:5])

    async def _academic_arxiv(args: dict) -> str:
        results = await tool._search_arxiv(args.get("query", ""))
        return "\n".join(f"[{r.rank+1}] {r.title}\n    {r.url}\n    {r.snippet}" for r in results[:5])

    async def _academic_semantic_scholar(args: dict) -> str:
        results = await tool._search_semantic_scholar(args.get("query", ""))
        return "\n".join(f"[{r.rank+1}] {r.title}\n    {r.url}\n    {r.snippet}" for r in results[:5])

    async def _academic_pubmed(args: dict) -> str:
        results = await tool._search_pubmed(args.get("query", ""))
        return "\n".join(f"[{r.rank+1}] {r.title}\n    {r.url}\n    {r.snippet}" for r in results[:5])

    register_tool("web.search", _web_search)
    register_tool("web.code", _web_code)
    register_tool("web.news", _web_news)
    register_tool("academic.arxiv", _academic_arxiv)
    register_tool("academic.semantic_scholar", _academic_semantic_scholar)
    register_tool("academic.pubmed", _academic_pubmed)


def _register_shell_tools() -> None:
    """Register shell.exec tool action — PowerShell and general shell execution."""
    try:
        from .tools.shell import ShellTool
    except ImportError:
        return

    tool = ShellTool()

    async def _shell_exec(args: dict) -> str:
        return await tool.execute(args)

    register_tool("shell.exec", _shell_exec)


def _register_python_executor_tools() -> None:
    """Register python.execute tool action (Skill 7)."""
    try:
        from .tools.python_executor import PythonExecutor, SandboxViolationError
    except ImportError:
        return

    executor = PythonExecutor()

    async def _python_execute(args: dict) -> str:
        code = args.get("code", "")
        timeout = float(args.get("timeout_sec", 30.0))
        try:
            result = await executor.execute(code, timeout_sec=timeout)
            parts = []
            if result.stdout:
                parts.append(f"stdout:\n{result.stdout}")
            if result.stderr:
                parts.append(f"stderr:\n{result.stderr}")
            parts.append(f"returncode: {result.returncode}")
            return "\n".join(parts)
        except SandboxViolationError as exc:
            return f"[sandbox violation: {exc}]"

    register_tool("python.execute", _python_execute)


def _register_memory_tools(memory: Any) -> None:
    """Register memory.search and memory.federated tool actions (Skill 4 / QMD)."""
    try:
        from .core.retrieval import HybridRetriever
    except ImportError:
        return

    retriever = HybridRetriever(memory=memory)

    async def _memory_search(args: dict) -> str:
        query = args.get("query", "")
        top_k = int(args.get("top_k", 5))
        results = await retriever.search(query, top_k=top_k)
        return "\n".join(
            f"[{r.get('source', '?')}] {r.get('text', '')[:200]}" for r in results
        )

    async def _memory_federated(args: dict) -> str:
        query = args.get("query", "")
        top_k = int(args.get("top_k", 10))
        results = await retriever.federated_search(query, top_k=top_k)
        return "\n".join(
            f"[{r.get('source', '?')}] {r.get('text', '')[:200]}" for r in results
        )

    register_tool("memory.search", _memory_search)
    register_tool("memory.federated", _memory_federated)


def _register_clawflow_tools(agent_loop: Any = None) -> None:
    """Register flow dispatch tool action (Skill 5).

    ``agent_loop`` owns the gate chain. When it is absent the engine still
    registers, but every step it would dispatch fails closed — see
    ``FlowGateUnavailable`` in cato/orchestrator/clawflows.py.
    """
    try:
        from .orchestrator.clawflows import FlowEngine
    except ImportError:
        return

    engine = FlowEngine(agent_loop=agent_loop)

    async def _flow_run(args: dict) -> str:
        name = args.get("flow", args.get("name", ""))
        if not name:
            return "[flow: name required]"
        result = await engine.run_flow(name, trigger_context=args)
        return f"flow={name} status={result.status} steps={len(result.step_outputs)}"

    register_tool("flow.run", _flow_run)


def _register_graph_tools(memory: Any) -> None:
    """Register graph.query and graph.related tool actions (Skill 9)."""

    async def _graph_query(args: dict) -> str:
        label = args.get("label", "")
        depth = int(args.get("depth", 3))
        if not label:
            return "[graph.query: label required]"
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, memory.query_graph, label, depth)
        if not results:
            return f"[graph.query: no nodes reachable from '{label}']"
        lines = [
            f"depth={r['depth']} {r['label']} ({r['type']}) via {r['relation_type']} w={r['weight']:.1f}"
            for r in results
        ]
        return "\n".join(lines)

    async def _graph_related(args: dict) -> str:
        label = args.get("label", "")
        max_hops = int(args.get("max_hops", 2))
        if not label:
            return "[graph.related: label required]"
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, memory.related_concepts, label, max_hops)
        if not results:
            return f"[graph.related: no neighbours found for '{label}']"
        lines = [
            f"{r['label']} ({r['type']}) w={r['weight']:.1f} depth={r['depth']}"
            for r in results
        ]
        return "\n".join(lines)

    register_tool("graph.query", _graph_query)
    register_tool("graph.related", _graph_related)


# ---------------------------------------------------------------------------
# File tool registration
# ---------------------------------------------------------------------------

def _register_file_tools() -> None:
    """Register file.read / file.write / file.list / file.delete / file.exists tool actions."""
    try:
        from .tools.file import FileTool
    except ImportError:
        return

    tool = FileTool()

    async def _file_op(args: dict) -> str:
        return await tool.execute(args)

    register_tool("file", _file_op)


# ---------------------------------------------------------------------------
# Browser tool registration
# ---------------------------------------------------------------------------

def _register_browser_tools() -> None:
    """Register browser tool action — navigate, click, type, screenshot, search, etc."""
    try:
        from .tools.browser import BrowserTool
    except ImportError:
        return

    tool = BrowserTool()

    async def _browser_op(args: dict) -> str:
        return await tool.execute(args)

    register_tool("browser", _browser_op)


# ---------------------------------------------------------------------------
# GitHub tool registration (Skill 3)
# ---------------------------------------------------------------------------

_GITHUB_SCHEMAS: dict[str, dict] = {
    "github.pr_review": {
        "type": "function",
        "function": {
            "name": "github__pr_review",
            "description": "Run a 3-model AI review on a GitHub pull request. Returns synthesized review with confidence scores.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pr": {"type": "string", "description": "PR number or URL (e.g. '123' or 'https://github.com/org/repo/pull/123')"},
                },
                "required": ["pr"],
            },
        },
    },
    "github.issue_create": {
        "type": "function",
        "function": {
            "name": "github__issue_create",
            "description": "Create a new GitHub issue in the current repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Issue title"},
                    "body": {"type": "string", "description": "Issue body/description"},
                },
                "required": ["title"],
            },
        },
    },
    "github.issue_list": {
        "type": "function",
        "function": {
            "name": "github__issue_list",
            "description": "List open GitHub issues in the current repository.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    "github.pr_list": {
        "type": "function",
        "function": {
            "name": "github__pr_list",
            "description": "List open pull requests in the current repository.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
}


def _register_github_tools(vault: Any = None) -> None:
    """Register GitHub tool actions — pr_review, issue_create, issue_list, pr_list."""
    try:
        from .tools.github_tool import GitHubTool
    except ImportError:
        return

    tool = GitHubTool(vault=vault)

    async def _pr_review(args: dict) -> str:
        pr = args.get("pr", args.get("target", ""))
        if not pr:
            return "[github.pr_review: pr number or URL required]"
        try:
            return await tool.pr_review(pr)
        except Exception as exc:
            return f"[github.pr_review error: {exc}]"

    async def _issue_create(args: dict) -> str:
        title = args.get("title", "")
        body = args.get("body", "")
        if not title:
            return "[github.issue_create: title required]"
        try:
            return await tool.issue_create(title=title, body=body)
        except Exception as exc:
            return f"[github.issue_create error: {exc}]"

    async def _issue_list(args: dict) -> str:
        try:
            return await tool.issue_list()
        except Exception as exc:
            return f"[github.issue_list error: {exc}]"

    async def _pr_list(args: dict) -> str:
        try:
            out = await tool._run_gh(
                ["pr", "list", "--json", "number,title,state,url", "--limit", "20"],
                timeout_sec=20,
            )
            return out
        except Exception as exc:
            return f"[github.pr_list error: {exc}]"

    register_tool("github.pr_review", _pr_review, _GITHUB_SCHEMAS["github.pr_review"])
    register_tool("github.issue_create", _issue_create, _GITHUB_SCHEMAS["github.issue_create"])
    register_tool("github.issue_list", _issue_list, _GITHUB_SCHEMAS["github.issue_list"])
    register_tool("github.pr_list", _pr_list, _GITHUB_SCHEMAS["github.pr_list"])


# ---------------------------------------------------------------------------
# Builder integration tool registration
# ---------------------------------------------------------------------------

_INTEGRATION_SCHEMAS: dict[str, dict] = {
    "integration.status": {
        "type": "function",
        "function": {
            "name": "integration.status",
            "description": "Inspect supported builder integrations, available actions, and masked credential readiness. Does not perform network calls.",
            "parameters": {
                "type": "object",
                "properties": {
                    "integration": {
                        "type": "string",
                        "description": "Optional integration id, such as github, vercel, netlify, render, supabase, stripe, google_workspace, notion, slack, discord, or telegram.",
                    },
                },
            },
        },
    },
    "integration.action": {
        "type": "function",
        "function": {
            "name": "integration.action",
            "description": "Plan or execute a builder integration action. Defaults to dry_run=true. Write-like actions report approval_required and require approved=true before live execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "integration": {"type": "string", "description": "Integration id."},
                    "action": {"type": "string", "description": "Action name from integration.status."},
                    "params": {"type": "object", "description": "Action parameters."},
                    "dry_run": {"type": "boolean", "description": "Plan only by default. Set false to make a live HTTP call when supported."},
                    "approved": {"type": "boolean", "description": "Required for write-like live actions when dry_run=false."},
                    "timeout": {"type": "number", "description": "HTTP timeout in seconds for live calls."},
                },
                "required": ["integration", "action"],
            },
        },
    },
    "integration.setup": {
        "type": "function",
        "function": {
            "name": "integration.setup",
            "description": "Return setup/auth guidance for a builder integration. For OAuth integrations, can generate a user-opened authorization URL when client_id and redirect_uri are provided. Does not exchange tokens or return secrets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "integration": {"type": "string", "description": "Integration id."},
                    "params": {
                        "type": "object",
                        "description": "Optional setup params such as client_id, redirect_uri, state, and scopes for OAuth URL generation.",
                    },
                },
                "required": ["integration"],
            },
        },
    },
}


def _register_integration_tools(vault: Any = None) -> None:
    """Register builder integration status/action tools."""
    try:
        from .tools.integration_tool import IntegrationTool
    except ImportError:
        return

    tool = IntegrationTool(vault=vault)

    async def _integration_status(args: dict) -> str:
        return await tool.status(args)

    async def _integration_action(args: dict) -> str:
        return await tool.action(args)

    async def _integration_setup(args: dict) -> str:
        return await tool.setup(args)

    register_tool("integration.status", _integration_status, _INTEGRATION_SCHEMAS["integration.status"])
    register_tool("integration.action", _integration_action, _INTEGRATION_SCHEMAS["integration.action"])
    register_tool("integration.setup", _integration_setup, _INTEGRATION_SCHEMAS["integration.setup"])


# ---------------------------------------------------------------------------
# Conduit (browser + crawl + monitor) tool registration
# ---------------------------------------------------------------------------

_CONDUIT_SCHEMAS: dict[str, dict] = {
    "conduit.crawl": {
        "type": "function",
        "function": {
            "name": "conduit__crawl",
            "description": "Crawl a website breadth-first, respecting robots.txt. Returns discovered URLs and page content up to a depth/limit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Starting URL to crawl"},
                    "max_depth": {"type": "integer", "description": "Maximum crawl depth (default 2)"},
                    "limit": {"type": "integer", "description": "Maximum pages to visit (default 20)"},
                },
                "required": ["url"],
            },
        },
    },
    "conduit.monitor": {
        "type": "function",
        "function": {
            "name": "conduit__monitor",
            "description": "Fingerprint a web page for change detection. Returns SHA-256 hash of normalized page content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fingerprint"},
                    "previous_hash": {"type": "string", "description": "Previous fingerprint hash to compare against (optional)"},
                },
                "required": ["url"],
            },
        },
    },
}


def _register_conduit_tools() -> None:
    """Register conduit.crawl and conduit.monitor tool actions."""
    try:
        from .tools.conduit_crawl import ConduitCrawler
        from .tools.conduit_monitor import ConduitMonitor
        from .tools.browser import BrowserTool
        from .audit import AuditLog
    except ImportError:
        return

    browser = BrowserTool()
    audit = AuditLog()
    audit.connect()

    async def _crawl(args: dict) -> str:
        url = args.get("url", "")
        if not url:
            return "[conduit.crawl: url required]"
        max_depth = int(args.get("max_depth", 2))
        limit = int(args.get("limit", 20))
        session_id = args.get("session_id", "crawl")
        crawler = ConduitCrawler(browser, audit, session_id)
        try:
            pages = await crawler.crawl_site(url, max_depth=max_depth, limit=limit)
            results = []
            for p in pages[:limit]:
                results.append(f"URL: {p.get('url', '?')}\nTitle: {p.get('title', '?')}\nText: {(p.get('text', '') or '')[:500]}")
            return "\n---\n".join(results) or "[no pages crawled]"
        except Exception as exc:
            return f"[conduit.crawl error: {exc}]"

    async def _monitor(args: dict) -> str:
        url = args.get("url", "")
        if not url:
            return "[conduit.monitor: url required]"
        prev_hash = args.get("previous_hash", "")
        session_id = args.get("session_id", "monitor")
        monitor = ConduitMonitor(browser, audit, session_id)
        try:
            fp = await monitor.fingerprint(url)
            if prev_hash:
                changed = fp.get("fingerprint", "") != prev_hash
                fp["changed"] = changed
            return json.dumps(fp)
        except Exception as exc:
            return f"[conduit.monitor error: {exc}]"

    register_tool("conduit.crawl", _crawl, _CONDUIT_SCHEMAS["conduit.crawl"])
    register_tool("conduit.monitor", _monitor, _CONDUIT_SCHEMAS["conduit.monitor"])


# Alias map: model-hallucinated short names → registered tool names
_TOOL_ALIASES: dict[str, str] = {
    "shell": "shell.exec",
    "python": "python.execute",
    "search": "web.search",
    "browse": "browser",
    "navigate": "conduit_navigate",
    "extract": "conduit_extract",
    "read": "file",
    "write": "file",
    "memory": "memory.search",
    "github": "github.issue_list",
}


# Cato's dispatch names -> the names ReversibilityRegistry actually keys on.
# Without this the guard would look up "file" / "shell.exec" / "send_email",
# miss every time, and fall back to a flat 0.5 for everything — i.e. it would
# be wired but vacuous.
_REVERSIBILITY_ALIASES: dict[str, str] = {
    "shell": "shell_execute",
    "shell.exec": "shell_execute",
    "shell.run": "shell_execute",
    "python.execute": "shell_execute",
    "web.search": "web_search",
    "web.code": "web_search",
    "web.news": "web_search",
    "memory.search": "memory_search",
    "memory.federated": "memory_search",
    "graph.query": "memory_search",
    "graph.related": "memory_search",
    "conduit.crawl": "conduit_extract",
    "send_email": "email_send",
    "email.send": "email_send",
    "telegram.send": "email_send",
    "api.payment": "api_payment",
    "github.pr_review": "git_push",
    "github.issue_create": "git_push",
    "github.issue_list": "read_file",
    "github.pr_list": "read_file",
    "integration.status": "read_file",
}

# Sub-actions of the `file` / `browser` dispatcher tools.
_REVERSIBILITY_SUBACTIONS: dict[str, str] = {
    "file.read": "read_file",
    "file.list": "list_dir",
    "file.exists": "read_file",
    "file.roots": "list_dir",
    "file.write": "write_file",
    "file.append": "write_file",
    "file.patch": "edit_file",
    "file.delete": "delete_file",
    "browser.navigate": "conduit_navigate",
    "browser.navigate_back": "conduit_navigate",
    "browser.snapshot": "conduit_extract",
    "browser.screenshot": "conduit_extract",
    "browser.extract": "conduit_extract",
    "browser.extract_main": "conduit_extract",
    "browser.search": "conduit_extract",
    "browser.click": "conduit_click",
    "browser.type": "conduit_type",
    "browser.fill": "conduit_type",
    "browser.select_option": "conduit_type",
    "browser.key_press": "conduit_type",
}


def _reversibility_name(tool_name: str, args: Any) -> str:
    """Map a dispatch tool name to its ReversibilityRegistry key.

    Unmapped names are returned unchanged so the registry raises
    ``ToolNotRegistered`` and ActionGuard applies its conservative default —
    the fail-closed direction.
    """
    name = (tool_name or "").strip()
    if name in ("file", "browser") and isinstance(args, dict):
        action = args.get("action") or args.get("op") or args.get("operation")
        if isinstance(action, str) and action.strip():
            key = f"{name}.{action.strip().lower()}"
            return _REVERSIBILITY_SUBACTIONS.get(key, key)
    if name in _REVERSIBILITY_SUBACTIONS:
        return _REVERSIBILITY_SUBACTIONS[name]
    return _REVERSIBILITY_ALIASES.get(name, name)


def _reversibility_score(tool_name: str, args: Any) -> float:
    """Reversibility score recorded on the ledger entry (0.0 .. 1.0).

    Falls back to 1.0 — treat as irreversible — for anything unregistered,
    because an unknown action is not evidence that it can be undone.
    """
    try:
        from .audit.reversibility_registry import ReversibilityRegistry
        registry = ReversibilityRegistry.get_instance()
        return float(registry.get(_reversibility_name(tool_name, args)).reversibility)
    except Exception:
        return 1.0


def _resolve_tool_name(name: str) -> str:
    """Resolve model-hallucinated tool names to actual registry entries."""
    if name in _TOOL_REGISTRY:
        return name
    # Check aliases
    alias = _TOOL_ALIASES.get(name)
    if alias and alias in _TOOL_REGISTRY:
        logger.info("Tool alias: %r → %r", name, alias)
        return alias
    # Try adding common suffixes
    for suffix in (".exec", ".execute", ".search", "_execute"):
        candidate = name + suffix
        if candidate in _TOOL_REGISTRY:
            logger.info("Tool suffix match: %r → %r", name, candidate)
            return candidate
    return name  # unchanged — will fail in dispatch


async def _dispatch_tool(call: ToolCall) -> str:
    if call.error:
        return json.dumps({"error": call.error, "recoverable": True})
    if not call.name:
        return json.dumps({"error": "Tool call is missing a function name.", "recoverable": True})
    if not isinstance(call.args, dict):
        return json.dumps({
            "error": f"Tool '{call.name}' arguments must be a JSON object.",
            "recoverable": True,
        })
    handler = _TOOL_REGISTRY.get(call.name)
    if handler is None:
        return json.dumps({
            "error": f"Unknown tool '{call.name}'.",
            "recoverable": True,
            "available_tools": sorted(_TOOL_REGISTRY),
        })
    try:
        # BUG FIX BH-002: Per-tool timeout prevents one stuck tool from
        # consuming the entire 180s gateway budget.
        result = await asyncio.wait_for(handler(call.args), timeout=60)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=True)
    except asyncio.TimeoutError:
        logger.error("Tool %s timed out after 60s", call.name)
        return json.dumps({"error": f"Tool '{call.name}' timed out after 60 seconds.", "recoverable": True})
    except Exception as exc:
        logger.error("Tool %s raised: %s", call.name, exc)
        return json.dumps({"error": f"Tool '{call.name}' failed: {exc}", "recoverable": True})


class _ToolDispatchFailure(Exception):
    """A dispatch that did not succeed, carrying the model-facing result text.

    ``_dispatch_tool`` deliberately never propagates a handler exception: the
    model has to see a readable error string and keep going. That swallowing
    also hid the failure from ``ActionHandle.arun()``, which only writes a
    FAILED ledger entry when the awaited call raises — so a call that failed
    was recorded CONFIRMED/success. This exception carries the failure across
    the ledger boundary and is unwrapped immediately after, so the ledger sees
    the truth and the model still sees the error string.
    """

    def __init__(self, result_text: str, detail: str) -> None:
        super().__init__(detail)
        self.result_text = result_text
        self.detail = detail


def _audit_explicitly_disabled(config: Any) -> bool:
    """True only for an UNAMBIGUOUS opt-out of the action ledger.

    ``bool(getattr(config, "audit_enabled", True))`` treated a corrupt
    ``audit_enabled: 0`` / ``""`` / ``[]`` as consent to run every tool with no
    ledger record at all — the one config value where a malformed entry buys
    more capability instead of less. Turning the audit trail off is a decision
    that has to be stated as a boolean False or the literal string "false";
    anything else keeps the ledger required.
    """
    value = getattr(config, "audit_enabled", True)
    if value is False:
        return True
    if isinstance(value, str) and value.strip().lower() in ("false", "no", "off", "0"):
        return True
    if value is not True and not isinstance(value, str):
        logger.error(
            "config.audit_enabled is %r, which is not a boolean — keeping the "
            "action ledger REQUIRED (fail-closed).", value,
        )
    return False


class _ToolDispatchIndeterminate(Exception):
    """A dispatch whose real-world outcome is UNKNOWN, not failed.

    Raised when the tool result carries ``outcome_unknown: true`` — the request
    reached the wire and no answer came back, so the remote may have completed
    it. ``_dispatch_recorded`` converts this into a ledger INDETERMINATE entry
    instead of FAILED, and unwraps it so the model still sees the error string.
    """

    #: Read by cato.audit.ledger.ActionHandle._resolve_exception — makes the
    #: ledger write INDETERMINATE instead of FAILED for this exception.
    ledger_indeterminate = True

    def __init__(self, result_text: str, detail: str) -> None:
        super().__init__(detail)
        self.result_text = result_text
        self.detail = detail


def _tool_result_indeterminate(result_text: str) -> Optional[str]:
    """Return a reason when a dispatch result declares its outcome unknown.

    A tool that reaches an external system and then loses the answer MUST set
    ``outcome_unknown: true`` rather than let the caller infer "it failed" from
    the ``error`` field — that inference is what turns one approved action into
    two real-world effects when someone retries.
    """
    if not result_text:
        return None
    try:
        parsed = json.loads(result_text)
    except Exception:
        return None
    if not isinstance(parsed, dict) or not parsed.get("outcome_unknown"):
        return None
    reason = parsed.get("reason") or parsed.get("error") or "outcome_unknown"
    return str(reason)[:500]


def _tool_result_failure(result_text: str) -> Optional[str]:
    """Return the failure detail if a dispatch result is error-shaped, else None.

    Covers both cases a caller must not conflate with success: a handler that
    raised (``_dispatch_tool`` converts it to an ``{"error": ...}`` payload) and
    a handler that returned an error-shaped result of its own. An explicitly
    empty/null ``error`` is not a failure.
    """
    if not result_text:
        return None
    try:
        parsed = json.loads(result_text)
    except Exception:
        # Non-JSON output is a plain tool result, not an error envelope.
        return None
    if not isinstance(parsed, dict):
        return None
    error = parsed.get("error")
    if not error:
        return None
    return str(error)[:500]


# ---------------------------------------------------------------------------
# Path sanitization helpers
# ---------------------------------------------------------------------------

def _sanitize_path_component(s: str) -> str:
    """Strip any character that isn't alphanumeric, dash, underscore, or dot."""
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', s)[:64]


def _sanitize_agent_id(agent_id: str) -> str:
    """Sanitize agent_id for safe filesystem use — no path traversal possible."""
    # Allow only alphanumeric, hyphen, underscore, dot
    sanitized = re.sub(r'[^A-Za-z0-9._-]', '_', agent_id)
    sanitized = sanitized.replace('..', '_')
    sanitized = sanitized.strip('.')
    return sanitized[:64] or 'default'


# ---------------------------------------------------------------------------
# JSONL transcript helpers
# ---------------------------------------------------------------------------

def _transcript_path(agent_id: str, session_id: str) -> Path:
    agent_id = _sanitize_path_component(agent_id)
    session_id = _sanitize_path_component(session_id)
    p = _CATO_DIR / agent_id / "sessions" / f"{session_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _append_transcript(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


async def _aappend(path: Path, record: dict) -> None:
    await asyncio.get_running_loop().run_in_executor(None, _append_transcript, path, record)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _check_for_correction(
    user_message: str,
    prior_output: str,
    session_id: str,
    memory: Any,
) -> None:
    """
    Post-response hook: detect corrections and store them (Skill 1).
    Non-blocking fire-and-forget — errors are logged but never propagate.
    """
    try:
        from .orchestrator.skill_improvement_cycle import classify_correction, store_correction
        correction = classify_correction(user_message, prior_output)
        if correction is not None:
            store_correction(correction, session_id, memory)
    except Exception as exc:
        logger.debug("Correction check failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Tool call parsing
# ---------------------------------------------------------------------------

_TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_MINIMAX_TOOL_CALL_RE = re.compile(r"<minimax:tool_call>(.*?)</minimax:tool_call>", re.DOTALL)
_INVOKE_RE = re.compile(r'<invoke\s+name="([^"]+)">(.*?)</invoke>', re.DOTALL)
_PARAM_RE = re.compile(r'<parameter\s+name="([^"]+)">(.*?)</parameter>', re.DOTALL)

_LEGACY_TOOL_NAME_MAP = {
    "executor": "shell.exec",
}


# BH-011 — Human-readable label of an in-flight tool call for the activity
# indicator.  Kept short (≤ ~100 chars after the tool name) so the desktop
# pill stays one line.  Falls back to the bare tool name for unknown tools.
#
# The label is broadcast over every connected WebSocket client (UI tabs,
# MCP subscribers, etc.) so we must scrub anything that looks like a
# credential BEFORE it leaves the daemon process.  The reviewer flagged
# this as a real secret-leakage risk: a shell command like
# `curl -H "Authorization: Bearer ${SECRET}"` would otherwise reach every
# subscriber.  Patterns below are conservative — false-positive redactions
# in a UI label are cheap; leaking a real token is not.
_SECRET_SCRUB_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(x-api-key\s*[:=]\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(--(?:password|token|api[-_]?key|secret)[=\s]+)\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b([A-Z][A-Z0-9_]{2,}_(?:TOKEN|KEY|SECRET|PASSWORD|PASS)\s*=\s*)\S+"), r"\1[REDACTED]"),
    # Long opaque-looking blobs (32+ alnum/-/_ chars) — likely API tokens.
    (re.compile(r"\b([A-Za-z0-9_\-]{32,})\b"), "[REDACTED-TOKEN]"),
)


def _scrub_secrets(text: str) -> str:
    """Redact common credential patterns from a UI-bound string."""
    if not text:
        return text
    for pattern, replacement in _SECRET_SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _summarize_tool_call(tc: "ToolCall") -> str:
    name = tc.name or "tool"
    args = tc.args if isinstance(tc.args, dict) else {}

    def _clip(value: Any, limit: int = 60) -> str:
        text = str(value).replace("\n", " ").replace("\r", " ").strip()
        text = _scrub_secrets(text)
        return (text[:limit] + "…") if len(text) > limit else text

    if name in ("shell", "shell.exec"):
        return f"{name}({_clip(args.get('command', ''))})"
    if name == "file" or name.startswith("file."):
        action = args.get("action", "")
        path = args.get("path", "")
        return f"{name}({action} {_clip(path, 80)})".strip()
    if name in ("web.search", "web_search"):
        return f"{name}({_clip(args.get('query', ''))!r})"
    if name in ("python", "python.exec"):
        return f"{name}({_clip(args.get('code', ''), 60)})"
    if name.startswith("browser."):
        url = args.get("url") or args.get("href") or ""
        return f"{name}({_clip(url, 80)})" if url else name
    if name in ("memory.store", "memory.search"):
        return f"{name}({_clip(args.get('query') or args.get('content', ''), 60)!r})"
    return name


def _coerce_tool_args(raw_args: Any, tool_name: str) -> tuple[dict[str, Any], str]:
    if raw_args is None or raw_args == "":
        return {}, ""
    if isinstance(raw_args, dict):
        return raw_args, ""
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            return {}, f"Invalid JSON arguments for tool '{tool_name}': {exc.msg}"
        if isinstance(parsed, dict):
            return parsed, ""
        return {}, f"Arguments for tool '{tool_name}' must decode to a JSON object."
    return {}, f"Arguments for tool '{tool_name}' must be a JSON object or JSON string."


def _parse_legacy_invoke(name: str, body: str) -> ToolCall:
    args = {m.group(1): m.group(2).strip() for m in _PARAM_RE.finditer(body)}
    mapped_name = _LEGACY_TOOL_NAME_MAP.get(name, name)
    return ToolCall(name=mapped_name, args=args)


def _parse_tool_calls_text(text: str) -> list[ToolCall]:
    """Extract tool call blocks embedded in streaming text.

    Handles:
    - <tool_call>{...}</tool_call> (JSON format)
    - <minimax:tool_call><invoke name="...">...</invoke></minimax:tool_call>
    - bare <invoke name="...">...</invoke>
    """
    calls: list[ToolCall] = []
    consumed_spans: list[tuple[int, int]] = []

    # JSON tool_call blocks
    for m in _TOOL_CALL_RE.finditer(text):
        try:
            d = json.loads(m.group(1))
            name = d.get("name", "")
            args, error = _coerce_tool_args(d.get("args", d.get("arguments", {})), name)
            calls.append(ToolCall(
                name=name,
                args=args,
                error=error,
            ))
            consumed_spans.append((m.start(), m.end()))
        except json.JSONDecodeError as exc:
            calls.append(ToolCall(error=f"Invalid JSON in <tool_call>: {exc.msg}"))
            consumed_spans.append((m.start(), m.end()))

    # minimax:tool_call wrapper blocks
    for m in _MINIMAX_TOOL_CALL_RE.finditer(text):
        consumed_spans.append((m.start(), m.end()))
        for inv in _INVOKE_RE.finditer(m.group(1)):
            calls.append(_parse_legacy_invoke(inv.group(1), inv.group(2)))

    # bare <invoke> blocks not already consumed
    for m in _INVOKE_RE.finditer(text):
        if any(s <= m.start() and m.end() <= e for s, e in consumed_spans):
            continue
        calls.append(_parse_legacy_invoke(m.group(1), m.group(2)))

    return calls


def _parse_tool_calls_openai(msg: dict) -> list[ToolCall]:
    """Parse OpenAI tool_calls / legacy function_call into ToolCall objects."""
    calls: list[ToolCall] = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args, error = _coerce_tool_args(fn.get("arguments", "{}"), name)
        calls.append(ToolCall(
            name=name,
            args=args,
            call_id=tc.get("id", ""),
            error=error,
            raw=tc,
        ))
    fc = msg.get("function_call")
    if fc:
        name = fc.get("name", "")
        args, error = _coerce_tool_args(fc.get("arguments", "{}"), name)
        calls.append(ToolCall(name=name, args=args, error=error, raw={"function": fc}))
    return calls


def _strip_tool_call_blocks(text: str) -> str:
    text = _TOOL_CALL_RE.sub("", text)
    text = _MINIMAX_TOOL_CALL_RE.sub("", text)
    text = _INVOKE_RE.sub("", text)
    return text.strip()


def _ensure_tool_call_ids(calls: list[ToolCall], planning_turn: int) -> None:
    for idx, call in enumerate(calls):
        if not call.call_id:
            call.call_id = f"call_cato_{planning_turn}_{idx}"


def _api_safe_tool_name(name: str) -> str:
    """Return a provider-safe function name for transcript replay.

    Cato's internal tool names use dotted namespaces (for example
    ``shell.exec``), but OpenAI-compatible tool-call messages only allow
    letters, numbers, underscores, and dashes in function names.
    """
    return _sanitize_tool_name(name or "cato_tool")


def _tool_call_to_openai(call: ToolCall) -> dict[str, Any]:
    raw = dict(call.raw or {})
    fn = dict(raw.get("function") or {})
    fn["name"] = _api_safe_tool_name(call.name or fn.get("name", ""))
    if "arguments" not in fn:
        fn["arguments"] = json.dumps(call.args if isinstance(call.args, dict) else {}, ensure_ascii=True)
    raw["id"] = call.call_id
    raw["type"] = raw.get("type", "function")
    raw["function"] = fn
    return raw


def _assistant_message_with_tool_calls(text: str, calls: list[ToolCall]) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": text or ""}
    if calls:
        msg["tool_calls"] = [_tool_call_to_openai(call) for call in calls]
    return msg


def _tool_result_message(call: ToolCall, result: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call.call_id,
        "content": result,
    }


# ---------------------------------------------------------------------------
# LLM configuration check
# ---------------------------------------------------------------------------

def _check_llm_config(cfg: Any, vault: Any) -> bool:
    """Warn at startup if no ANTHROPIC_API_KEY is configured.

    Cato calls the Anthropic API directly; ANTHROPIC_API_KEY is the only
    credential the model-execution path needs.  Returns True when the LLM is
    ready to accept calls, False otherwise.  Called synchronously from
    AgentLoop.__init__ so the warning appears in the daemon log the moment the
    loop is constructed — before any user message arrives.
    """
    if not _anthropic_key_present(vault):
        logger.warning(
            "[AgentLoop] WARNING: ANTHROPIC_API_KEY is not configured. "
            "LLM calls will fail. Run 'cato vault set ANTHROPIC_API_KEY <key>'."
        )
        return False
    return True


def _anthropic_key_present(vault: Any) -> bool:
    """True when an Anthropic credential is reachable.  The value is never read
    into a log, message, or record — only its presence is reported."""
    import os as _os
    try:
        value = vault.get("ANTHROPIC_API_KEY") if vault is not None else None
    except Exception:
        value = None
    return bool(str(value or _os.environ.get("ANTHROPIC_API_KEY", "") or "").strip())


# ---------------------------------------------------------------------------
# AgentLoop
# ---------------------------------------------------------------------------

class AgentLoop:
    """
    Processes one message per session.  Construct once; share across sessions.
    Each call to run() is isolated by session_id.
    """

    def __init__(
        self,
        config: CatoConfig,
        budget: BudgetManager,
        vault: Vault,
        memory: MemorySystem,
        context_builder: ContextBuilder,
        audit_log: Optional[AuditLog] = None,
        safety_guard: Optional[SafetyGuard] = None,
        on_tool_progress: Optional[Callable[[str, str, str], Any]] = None,
        on_progress_event: Optional[ProgressCallback] = None,
    ) -> None:
        self._cfg = config
        self._budget = budget
        self._vault = vault
        # Strong references to fire-and-forget tasks so they are not GC'd
        self._bg_tasks: set[asyncio.Task] = set()
        self._memory = memory
        self._ctx = context_builder
        # BH-011 — Optional callback invoked around every tool dispatch.
        # Signature: `(tool_name, short_summary, status)` where `status` is
        # "start" or "end".  Used by Gateway to surface the in-flight tool
        # in the desktop activity indicator so the user can see what Cato
        # is actually doing during long-running calls (pip install, npm,
        # large greps, etc.) instead of just "Working".  Async or sync
        # callbacks both supported.
        self._on_tool_progress = on_tool_progress
        # Claude-Code-style streaming progress events.  Callback receives a
        # single dict per event and may be sync or async.  Construct a per-
        # session ProgressEmitter inside run() so concurrent sessions do not
        # share state.  When `on_progress_event` is None all emits are
        # cheap no-ops (the emitter checks the callback up-front).
        self._on_progress_event: Optional[ProgressCallback] = on_progress_event
        self._router = ModelRouter(
            vault=vault,
            preferred_model=config.default_model,
            max_output_tokens=getattr(config, "max_output_tokens", 16384),
        )
        # Audit log — initialise lazily if not provided and audit_enabled
        self._audit_log: Optional[AuditLog] = audit_log
        self._audit_verify_task: Optional[asyncio.Task] = None
        if self._audit_log is None and getattr(config, "audit_enabled", True):
            self._audit_log = AuditLog()
            self._audit_log.connect()

        # Action ledger. `_ledger_required` records whether the operator asked
        # for auditing: if they did and the ledger failed to open, dispatch must
        # refuse rather than run unrecorded actions. Explicitly disabling audit
        # is a choice we honour; a broken ledger is not.
        self._ledger = None
        self._ledger_required = _audit_explicitly_disabled(config) is False
        if self._ledger_required:
            try:
                from .audit.ledger import LedgerMiddleware
                self._ledger = LedgerMiddleware()
            except BaseException as exc:  # LedgerError derives from BaseException
                logger.error("LedgerMiddleware unavailable: %s", exc)

        # Safety guard
        self._safety = safety_guard or SafetyGuard(config={"safety_mode": getattr(config, "safety_mode", "strict")})

        # Pre-action reversibility guard. Its verdict binds in
        # `_guarded_dispatch`; it is not a dashboard ornament.
        #
        # No TokenChecker is passed on purpose: ActionGuard short-circuits to
        # `proceed=True` whenever a delegation token authorizes the tool, which
        # would let a token override the reversibility rules. Token
        # authorization is already a separate, earlier gate.
        self._action_guard = None
        try:
            from .audit.action_guard import ActionGuard
            self._action_guard = ActionGuard()
        except Exception as exc:  # pragma: no cover — defensive
            logger.error("ActionGuard unavailable: %s", exc)
        self._autonomy_level = float(getattr(config, "autonomy_level", 0.5) or 0.5)

        # Token-based authorization checker (T3)
        # Pull the per-call approval policy from config so the user can
        # extend the auto-approved list or force strict mode without
        # touching code.  CATO_STRICT_APPROVAL env var overrides config.
        self._token_checker = TokenChecker(
            auto_approved_tools=getattr(config, "auto_approved_tools", None) or [],
            strict_approval=bool(getattr(config, "strict_approval", False)),
        )

        # Register web-search tool actions (Skill 6)
        _register_web_search_tools(vault=vault)

        # Register Python executor tool action (Skill 7)
        _register_python_executor_tools()

        # Register shell execution tool action (shell.exec)
        _register_shell_tools()

        # Register file read/write/list/delete (file.*)
        _register_file_tools()

        # Register browser automation (browser.*)
        _register_browser_tools()

        # Register GitHub operations (github.pr_review, github.issue_*, github.pr_list)
        _register_github_tools(vault=vault)

        # Register Conduit crawl + monitor (conduit.crawl, conduit.monitor)
        _register_conduit_tools()

        # Register builder integration metadata/action planner
        _register_integration_tools(vault=vault)

        # Register memory fact tool actions (Skill 2)
        _register_memory_tools(memory=memory)

        # Register Clawflow tool action (Skill 5). `self` is the gate chain the
        # flow's steps must run through.
        _register_clawflow_tools(agent_loop=self)

        # Register Knowledge Graph tool actions (Skill 9)
        _register_graph_tools(memory=memory)

        # Startup LLM config check — warn early if the Anthropic key is
        # API key is present so the user knows immediately rather than sending
        # a message and getting no response.
        self._llm_ready = _check_llm_config(config, vault)

    def register_tool(self, name: str, fn: Callable) -> None:
        """Register a tool with the global registry."""
        register_tool(name, fn)

    async def _periodic_audit_verify(self) -> None:
        """Background task: verify audit chain integrity every hour."""
        while True:
            await asyncio.sleep(3600)
            if self._audit_log is not None:
                try:
                    self._audit_log.verify_recent_sessions(hours=24)
                except Exception as exc:
                    logger.critical("Audit chain verification failed: %s", exc)

    async def run(self, session_id: str, message: str, agent_id: str) -> tuple[str, str, str]:
        """
        Process *message* and return (final_text, cost_footer, model_used).

        Persists every turn to JSONL transcript.
        Raises BudgetExceeded if spend caps are breached.
        """
        self._continuation_retried = False  # reset per-invocation flag
        # Per-run nonce. Tool call ids restart at `call_cato_0_0` on every run,
        # so they are only unique when scoped to a run.
        self._run_id = uuid.uuid4().hex[:12]
        # Per-session progress emitter — gateway-supplied callback fans
        # the 8-event stream out over WebSocket.  When no callback was
        # configured all emits are cheap no-ops.
        self._progress = ProgressEmitter(
            session_id=session_id, on_event=self._on_progress_event
        )
        _planning_turns_completed = 0

        # Crash recovery: an INTENT with no terminal entry means a previous
        # process died mid-action. Surface it once per process, loudly.
        if not getattr(self, "_recovery_scanned", False):
            self._recovery_scanned = True
            self._surface_unresolved_intents()

        # Start periodic audit verification on first run
        if self._audit_verify_task is None or self._audit_verify_task.done():
            self._audit_verify_task = asyncio.create_task(
                self._periodic_audit_verify(), name="audit-verify"
            )
            self._bg_tasks.add(self._audit_verify_task)
            self._audit_verify_task.add_done_callback(self._bg_tasks.discard)

        safe_agent_id = _sanitize_agent_id(agent_id)
        tpath = _transcript_path(safe_agent_id, session_id)
        # Prefer the config-declared workspace_dir (e.g. ~/.cato/workspace).
        # Fall back to the legacy per-agent path so existing installs are not broken.
        _raw_ws = getattr(self._cfg, "workspace_dir", None)
        workspace = (
            Path(_raw_ws).expanduser().resolve()
            if _raw_ws
            else _CATO_DIR / safe_agent_id / "workspace"
        )
        daily_log = _CATO_DIR / safe_agent_id / "memory" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
        skills_dir = Path.home() / ".cato" / "skills"  # ~/.cato/skills
        # BUG FIX BH-004: Also scan ~/.claude/skills/ for skills installed via
        # the Claude ecosystem.  The context_builder supports skills_dirs (plural)
        # but we were only passing the singular ~/.cato/skills/ path.
        _claude_skills_dir = Path.home() / ".claude" / "skills"
        _all_skills_dirs = [
            d for d in [skills_dir, _claude_skills_dir] if d.exists()
        ]

        # Compact old turns before building context — fires when token or turn
        # thresholds are exceeded, storing distilled summary in SQLite.
        await self._maybe_compact(tpath, session_id)

        memory_chunks = await self._memory.asearch(message, top_k=4)

        # Load most recent distilled summary (if any) for this session so
        # ContextBuilder can inject it into the system prompt.
        distilled_summary = self._load_distilled_summary(session_id)

        system_prompt = self._ctx.build_system_prompt(
            workspace_dir=workspace,
            memory_chunks=memory_chunks,
            daily_log_path=daily_log if daily_log.exists() else None,
            skills_dir=skills_dir if skills_dir.exists() else None,
            skills_dirs=_all_skills_dirs if _all_skills_dirs else None,
            distilled_summary=distilled_summary,
        )

        # DEBUG: Confirm skills are in system prompt
        has_skills = "Available Skills" in system_prompt
        has_conduit = "conduit" in system_prompt.lower()
        logger.info("SYSTEM_PROMPT: skills_section=%s conduit=%s", has_skills, has_conduit)

        ctx_tokens  = self._ctx.count_tokens(system_prompt)
        history_len = self._history_len(tpath)
        complexity  = self._router.score_task(message, ctx_tokens, history_len)

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(self._recent_turns(tpath, limit=HISTORY_WINDOW))
        messages.append({"role": "user", "content": message})

        # Model selection — deterministic policy (cato/model_policy.py) chooses
        # the model from a descriptor built HERE, before dispatch.  Nothing the
        # model emits can change it.
        anthropic_key_present = _anthropic_key_present(self._vault)
        use_direct = anthropic_key_present

        # Return a user-visible error immediately when the Anthropic credential
        # is missing — prevents silent failures where the user sends a message
        # and receives no response at all.
        if not anthropic_key_present:
            _no_key_msg = (
                "⚠️ ANTHROPIC_API_KEY is not configured. "
                "Run: cato vault set ANTHROPIC_API_KEY <your-key>"
            )
            logger.warning("[AgentLoop] no ANTHROPIC_API_KEY — returning config error to user")
            await _aappend(tpath, {
                "ts": _now(), "role": "user",
                "content": message, "session_id": session_id,
            })
            await _aappend(tpath, {
                "ts": _now(), "role": "assistant",
                "content": _no_key_msg, "session_id": session_id,
            })
            return _no_key_msg, "", self._cfg.default_model
        # Sanitize tool names for API compatibility (no dots allowed)
        _tools_for_api: list[dict] = []
        _api_name_map: dict[str, str] = {}  # sanitized → original
        if use_direct:
            _tools_for_api, _api_name_map = _sanitize_tool_defs(get_tool_definitions())
        logger.info("session=%s direct_anthropic=%s", session_id, use_direct)
        # `model` is only the label used for budget accounting and transcript
        # metadata; the executed model comes from the routing decision.
        model = self._cfg.default_model if use_direct else self._router.select_model(complexity)

        await _aappend(tpath, {
            "ts": _now(), "role": "user",
            "content": message, "session_id": session_id,
        })

        # ---- Planning loop -----------------------------------------------
        planning_turns = 0
        final_text = ""
        total_cost = 0.0

        # Wrap the entire planning loop in try/finally so the progress
        # `session_end` fires on every exit path — success, BudgetExceeded,
        # asyncio.TimeoutError, or any other exception.  This is the
        # backend half of the "stuck on Working… forever" fix: without
        # the finally, an exception inside the loop would leave the
        # desktop pill amber until the next message.
        try:
            while True:
                if planning_turns >= self._cfg.max_planning_turns:
                    messages.append({
                        "role": "system",
                        "content": "Provide your final answer now. No more tool calls.",
                    })

                # Progress: turn_start (1-indexed for human display)
                await self._progress.turn_start(
                    turn=planning_turns + 1,
                    max_turns=int(getattr(self._cfg, "max_planning_turns", 10)),
                )

                # Budget pre-flight using actual input token count
                try:
                    input_tokens = self._ctx.count_tokens("\n".join(
                        m.get("content", "") for m in messages if isinstance(m.get("content"), str)
                    ))
                    await self._budget.check_and_deduct(
                        model,
                        input_tokens,
                        input_tokens // 3,
                        allow_over_budget=_budget_bypass_requested(message, self._cfg),
                    )
                    call_cost = self._budget._last_call_cost
                except BudgetExceeded as exc:
                    # Daily / monthly caps are the only enforced gates.
                    # Surface a clear, actionable message with both bypass and
                    # cap-raise options.
                    if exc.cap_type == "daily":
                        hint = (
                            f"Today's ${exc.cap_value:.2f} budget is used up. "
                            "Use '/budget bypass' (or reply 'continue anyway') "
                            "to override for this turn, or "
                            f"'/budget daily <amount>' to raise the daily cap."
                        )
                    else:
                        hint = (
                            f"Monthly ${exc.cap_value:.2f} cap reached. "
                            "Use '/budget bypass' to override for this turn, or "
                            f"'/budget monthly <amount>' to raise the monthly cap."
                        )
                    raise BudgetExceeded(
                        f"{exc}. {hint}",
                        cap_type=exc.cap_type,
                        cap_value=exc.cap_value,
                        current=exc.current,
                        call_cost=exc.call_cost,
                    ) from exc
                except Exception:
                    call_cost = 0.0
                total_cost += call_cost

                force = planning_turns >= self._cfg.max_planning_turns

                # Route every turn through the deterministic policy and call
                # Anthropic directly.  Falls back to _stream_collect only when
                # the direct path is unavailable or returns nothing usable.
                text = ""
                tool_calls: list[ToolCall] = []
                used_direct = False
                routed_model_name = model  # updated once the policy decides

                # Progress: llm_start (emitted around the actual LLM call,
                # whether routed direct-to-Anthropic or via _stream_collect
                # fallback).  llm_end fires in a finally so it always pairs.
                await self._progress.llm_start(model=model, token_budget=input_tokens if isinstance(input_tokens, int) else 0)
                try:
                    if use_direct and not force:
                        try:
                            # Sanitize tool names in message history so they match
                            # the sanitized tool definitions we send.  Without this
                            # the API rejects tool results referencing tool names
                            # that don't appear in the tool definitions.
                            api_messages = _sanitize_messages_for_api(messages)
                            _system = next(
                                (m.get("content", "") for m in api_messages
                                 if m.get("role") == "system"), "",
                            )
                            _convo = [m for m in api_messages if m.get("role") != "system"]
                            descriptor = TaskDescriptor(
                                task_type=TaskType.GENERAL_TOOL_USE,
                                input_tokens=int(input_tokens) if isinstance(input_tokens, int) else 0,
                                max_output_tokens=int(getattr(self._cfg, "max_output_tokens", 16384)),
                                requires_tools=bool(_tools_for_api),
                                # Cato's planning loop reasons between tool calls,
                                # which Haiku 4.5 cannot do.
                                requires_interleaved_thinking=bool(_tools_for_api),
                                cost_ceiling_usd=float(getattr(
                                    self._cfg, "per_call_cost_ceiling_usd", 2.50)),
                                task_key=f"{session_id}:chat",
                            )
                            routed_model, api_response, decision = await asyncio.wait_for(
                                self._router.complete_message(
                                    _convo,
                                    descriptor,
                                    system=_system or None,
                                    tools=_anthropic_tool_defs(_tools_for_api),
                                    idempotency_key=f"{session_id}:{planning_turns}",
                                ),
                                timeout=600,
                            )
                            routed_model_name = routed_model
                            logger.info("%s", decision.log_line())
                            text = api_response.get("content", "") or ""
                            tool_calls = _parse_tool_calls_openai(api_response)
                            tool_calls.extend(_parse_tool_calls_text(text))
                            text = _strip_tool_call_blocks(text)
                            # Reverse-map sanitized tool names back to dotted originals
                            for tc in tool_calls:
                                if tc.name in _api_name_map:
                                    tc.name = _api_name_map[tc.name]
                            logger.info(
                                "direct-anthropic parsed: model=%s text_len=%d tool_calls=%d names=%s",
                                routed_model, len(text), len(tool_calls),
                                [tc.name for tc in tool_calls] if tool_calls else "[]",
                            )
                            if text or tool_calls:
                                used_direct = True
                        except (CostGateExceeded, EscalationExhausted) as exc:
                            # Fail loud. A blocked cost gate or an exhausted
                            # escalation is a policy decision, not a transient
                            # error — do not silently retry on a weaker path.
                            logger.error("model policy stopped turn %d: %s", planning_turns, exc)
                            text = f"⚠️ Model policy stopped this request: {exc}"
                            tool_calls = []
                            used_direct = True
                        except AnthropicAPIError as exc:
                            if exc.classified.retry_class is RetryClass.NOT_RETRYABLE:
                                logger.error("Anthropic rejected turn %d: %s", planning_turns, exc)
                                text = f"⚠️ Anthropic API error ({exc.classified.error_type}). See daemon log."
                                tool_calls = []
                                used_direct = True
                            else:
                                logger.warning(
                                    "Anthropic turn %d exhausted retries: %s — falling back to _stream_collect",
                                    planning_turns, exc,
                                )
                        except Exception as exc:
                            logger.warning(
                                "Direct Anthropic turn %d failed: %s — falling back to _stream_collect",
                                planning_turns, exc,
                            )

                    if not used_direct:
                        logger.info("Using _stream_collect (turn=%d, direct=%s)", planning_turns, use_direct)
                        text, tool_calls = await self._stream_collect(messages, model, force)
                finally:
                    # Surface a single llm_token chunk with the assistant text
                    # so the frontend can render the model's "thinking" even
                    # when the direct path returns a non-streamed body.  Capped to
                    # avoid flooding the WS channel.
                    try:
                        if text:
                            preview = text if len(text) <= 800 else text[:800] + "…"
                            await self._progress.llm_token(preview)
                    except Exception:
                        pass
                    try:
                        await self._progress.llm_end(tokens_used=int(len(text) // _CHARS_PER_TOKEN) if text else 0)
                    except Exception:
                        pass

                _ensure_tool_call_ids(tool_calls, planning_turns)
                await _aappend(tpath, {
                    "ts": _now(), "role": "assistant", "content": text,
                    "tool_calls": [_tool_call_to_openai(tc) for tc in tool_calls],
                    "cost_usd": call_cost, "model": model, "session_id": session_id,
                })
                messages.append(_assistant_message_with_tool_calls(text, tool_calls))

                if not tool_calls or force:
                    # Detect "phantom action" — model described doing something but
                    # never emitted a tool_call.  Re-prompt once so it actually
                    # executes instead of just narrating.
                    _ACTION_HINTS = (
                        "i'll ", "i will ", "let me ", "i'm going to ",
                        "i am going to ", "let's ", "i can ",
                        "i'll now ", "let me now ",
                    )
                    _text_lower = (text or "").lower()
                    if (
                        not force
                        and planning_turns == 0
                        and any(h in _text_lower for h in _ACTION_HINTS)
                        and not getattr(self, "_continuation_retried", False)
                    ):
                        logger.warning(
                            "Phantom action detected — model described actions without "
                            "tool_calls. Re-prompting with continuation."
                        )
                        self._continuation_retried = True
                        messages.append({
                            "role": "user",
                            "content": (
                                "You described what you would do but did not actually "
                                "call any tools. Please use the available tools to "
                                "execute the actions now — do not just describe them."
                            ),
                        })
                        await self._progress.turn_end(turn=planning_turns + 1, has_final_answer=False)
                        planning_turns += 1
                        continue
                    final_text = text
                    await self._progress.turn_end(turn=planning_turns + 1, has_final_answer=True)
                    break

                planning_turns += 1
                for tc in tool_calls:
                    # Resolve hallucinated/short tool names before dispatch
                    tc.name = _resolve_tool_name(tc.name)
                    if tc.error or not tc.name or not isinstance(tc.args, dict) or tc.name not in _TOOL_REGISTRY:
                        # Malformed / unknown call — `_dispatch_tool` turns this
                        # into an error string for the model. Nothing executes,
                        # so there is no action to gate or record.
                        result = await self._dispatch_with_progress(tc)
                    else:
                        # Every gate the runtime has lives in _guarded_dispatch:
                        # safety -> authorization -> reversibility -> approval ->
                        # ledger INTENT -> dispatch -> ledger CONFIRMED/FAILED.
                        result = await self._guarded_dispatch(tc, session_id)

                        # Audit log: record every tool call
                        if self._audit_log:
                            try:
                                cost_cents = 0
                                # Try to determine cost from budget
                                try:
                                    cost_cents = int(round(self._budget._last_call_cost * 100))
                                except Exception:
                                    pass
                                self._audit_log.log(
                                    session_id, "tool_call", tc.name,
                                    tc.args,
                                    result,
                                    cost_cents=cost_cents,
                                )
                            except Exception as audit_exc:
                                logger.debug("Audit log failed: %s", audit_exc)

                    await _aappend(tpath, {
                        "ts": _now(), "role": "tool",
                        "tool_name": tc.name, "tool_call_id": tc.call_id,
                        "result": result, "session_id": session_id,
                    })
                    messages.append(_tool_result_message(tc, result))

                # All tools done; close the turn before looping again.
                await self._progress.turn_end(turn=planning_turns, has_final_answer=False)
        finally:
            # Always fire session_end so the frontend ghost message is torn
            # down even when the loop bails via exception or timeout.
            try:
                await self._progress.session_end(total_turns=planning_turns)
            except Exception:
                pass

        # BUG FIX BH-001: Never return empty final_text — gateway.send()
        # strips the budget footer, leaving nothing, which triggers the
        # "model returned no readable content" fallback.  Generate a real
        # fallback here so the user always gets *something* meaningful.
        if not (final_text or "").strip():
            final_text = (
                "I processed your request but wasn't able to generate a response. "
                "This can happen when the model returns only internal metadata. "
                "Please try rephrasing or simplifying your question."
            )
            logger.warning("BH-001: empty final_text — injected fallback")

        logger.info("Agent loop complete: text_len=%d model=%s turns=%d cost=%.4f",
                    len(final_text or ""), model, planning_turns, total_cost)
        _t = asyncio.create_task(
            self._memory.astore(f"Q: {message}\nA: {final_text}", source_file=session_id),
            name="memory-store",
        )
        self._bg_tasks.add(_t)
        _t.add_done_callback(self._bg_tasks.discard)

        # Fire-and-forget correction detection (Skill 1)
        _correction_task = asyncio.create_task(
            _check_for_correction(message, final_text, session_id, self._memory),
            name="correction-check",
        )
        self._bg_tasks.add(_correction_task)
        _correction_task.add_done_callback(self._bg_tasks.discard)

        return final_text, self._budget.format_footer(), model

    # ------------------------------------------------------------------
    # Compaction helpers
    # ------------------------------------------------------------------

    async def _maybe_compact(self, tpath: Path, session_id: str) -> None:
        """
        Compact the JSONL transcript when it exceeds token/turn thresholds.

        Reads all turns, checks if compaction is needed, distils the oldest
        turns (everything except the last HISTORY_WINDOW), stores the result
        in distilled_summaries, and rewrites the transcript to contain only
        the recent window.

        This is a no-op when the transcript does not exist or is within limits.
        """
        if not tpath.exists():
            return

        try:
            lines = tpath.read_text(encoding="utf-8").splitlines()
        except OSError:
            return

        # Parse all valid JSONL records
        records: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        total_turns = len(records)
        if total_turns <= HISTORY_WINDOW:
            return  # nothing to compact

        # Count tokens in the full history to decide whether compaction is needed
        history_text = "\n".join(r.get("content", "") for r in records if r.get("role") in ("user", "assistant"))
        history_tokens = self._ctx.count_tokens(history_text)

        needs_compact = (
            history_tokens > COMPACT_TOKEN_THRESHOLD
            or total_turns > COMPACT_TURN_THRESHOLD
        )
        if not needs_compact:
            return

        # Split: turns to distil vs turns to keep live
        keep_start = max(0, total_turns - HISTORY_WINDOW)
        old_records = records[:keep_start]
        recent_records = records[keep_start:]

        logger.info(
            "Compacting session=%s: %d total turns → distilling %d, keeping %d (history_tokens=%d)",
            session_id, total_turns, len(old_records), len(recent_records), history_tokens,
        )

        # Distil old turns using heuristic extractor (no LLM call)
        try:
            from .core.distiller import Distiller
            distiller = Distiller()
            distil_turns = [
                {"role": r.get("role", ""), "content": r.get("content", "")}
                for r in old_records
                if r.get("role") in ("user", "assistant")
            ]
            result = distiller.distill(
                session_id=session_id,
                turns=distil_turns,
                turn_start=0,
            )
            if result is not None:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._memory.store_distillation, result
                )
                logger.info(
                    "Distilled session=%s turns 0-%d: summary=%d chars, facts=%d, decisions=%d",
                    session_id, len(old_records) - 1,
                    len(result.summary), len(result.key_facts), len(result.decisions),
                )
        except Exception as exc:
            logger.warning("Distillation failed (non-fatal): %s", exc)

        # Rewrite transcript to only the recent window
        try:
            new_content = "\n".join(json.dumps(r, ensure_ascii=True) for r in recent_records) + "\n"
            await asyncio.get_running_loop().run_in_executor(
                None, tpath.write_text, new_content, "utf-8"
            )
        except OSError as exc:
            logger.warning("Transcript rewrite failed: %s", exc)

    def _load_distilled_summary(self, session_id: str) -> Optional[str]:
        """
        Load the most recent distilled summary for *session_id* and format it
        as a compact context block.  Returns None if no summaries exist.
        """
        try:
            rows = self._memory.load_recent_distillations(session_id=session_id, limit=3)
        except Exception:
            return None

        if not rows:
            return None

        parts: list[str] = ["## Conversation History Summary (compacted)"]
        for row in reversed(rows):  # oldest first
            summary = row.get("summary") or ""
            facts_raw = row.get("key_facts") or "[]"
            decisions_raw = row.get("decisions") or "[]"
            questions_raw = row.get("open_questions") or "[]"

            try:
                facts = json.loads(facts_raw) if isinstance(facts_raw, str) else facts_raw
            except (json.JSONDecodeError, TypeError):
                facts = []
            try:
                decisions = json.loads(decisions_raw) if isinstance(decisions_raw, str) else decisions_raw
            except (json.JSONDecodeError, TypeError):
                decisions = []
            try:
                questions = json.loads(questions_raw) if isinstance(questions_raw, str) else questions_raw
            except (json.JSONDecodeError, TypeError):
                questions = []

            if summary:
                parts.append(f"**Summary:** {summary}")
            if facts:
                parts.append("**Key facts:** " + "; ".join(str(f) for f in facts[:5]))
            if decisions:
                parts.append("**Decisions:** " + "; ".join(str(d) for d in decisions[:5]))
            if questions:
                parts.append("**Open questions:** " + "; ".join(str(q) for q in questions[:3]))

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Tool dispatch with progress callback (BH-011)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Ledger helpers
    # ------------------------------------------------------------------

    def _record_denial(
        self,
        *,
        tool_name: str,
        tool_input: Any,
        session_id: str,
        gate: str,
        reason: str,
        approval_ref: Optional[str] = None,
    ) -> None:
        """Write a DENIED entry for a gate refusal.

        Called before the refusal is handed back to the model. Best-effort by
        design: a denial that cannot be recorded must not turn into an allow,
        and the action is already not happening, so there is nothing to abort.
        The failure is logged at ERROR so it is visible.
        """
        if self._ledger is None:
            return
        try:
            self._ledger.record_denial(
                tool_name=tool_name or "unknown",
                tool_input=tool_input,
                agent_session_id=session_id or "unknown",
                gate=gate,
                reason=reason,
                approval_ref=approval_ref,
            )
        except BaseException as exc:  # LedgerError derives from BaseException
            logger.error(
                "Ledger DENIED entry failed (gate=%s tool=%s): %s", gate, tool_name, exc
            )

    def _ledger_idempotency_key(self, session_id: str, tc: ToolCall) -> str:
        """Key that makes a double-dispatch of the same call impossible.

        Scoped to (session, run, call) — `call_id` alone is not unique because
        the model restarts its counter at `call_cato_0_0` on every run.
        """
        run_id = getattr(self, "_run_id", "") or "norun"
        return f"{session_id}:{run_id}:{tc.call_id or id(tc)}"

    def _surface_unresolved_intents(self) -> list:
        """Report INTENTs with no terminal entry — i.e. a crash mid-action.

        A non-empty result after restart means the process died between "we are
        about to do this" and "we did / did not do it", so the real-world effect
        is unknown and needs a human to reconcile.
        """
        if self._ledger is None:
            return []
        try:
            orphans = self._ledger.unresolved_intents()
        except BaseException as exc:  # LedgerError derives from BaseException
            logger.error("Ledger recovery scan failed: %s", exc)
            return []
        if orphans:
            logger.critical(
                "LEDGER RECOVERY: %d unresolved INTENT(s) found at startup — a "
                "previous run died mid-action and the real-world effect is "
                "UNKNOWN. Reconcile with ledger.record_recovery(). Actions: %s",
                len(orphans),
                ", ".join(
                    f"{r.tool_name}@{r.timestamp}(action={r.action_id})"
                    for r in orphans[:10]
                ),
            )
        try:
            unknown = self._ledger.unreconciled_indeterminate()
        except BaseException as exc:  # LedgerError derives from BaseException
            logger.error("Ledger indeterminate scan failed: %s", exc)
            unknown = []
        if unknown:
            logger.critical(
                "LEDGER RECOVERY: %d action(s) with an UNKNOWN real-world "
                "outcome are awaiting reconciliation. Do NOT re-issue these "
                "requests until each is confirmed against the remote. Actions: %s",
                len(unknown),
                ", ".join(
                    f"{r.tool_name}@{r.timestamp}(action={r.action_id})"
                    for r in unknown[:10]
                ),
            )
        return orphans

    # ------------------------------------------------------------------
    # The guarded dispatch path — every gate the runtime has runs here
    # ------------------------------------------------------------------

    async def guarded_action(
        self,
        name: str,
        args: Optional[dict],
        session_id: str,
        *,
        call_id: str = "",
        dispatch: Optional[Callable[[], Any]] = None,
        human_approved: bool = False,
        approval_ref: Optional[str] = None,
    ) -> str:
        """THE shared pre-action gate. Every dispatch entry point must call this.

        This is the public seam that lets a non-model caller (the cron/YAML
        scheduler, an HTTP route, an adapter) run *exactly* the same gate
        sequence as a model tool call instead of growing a second, divergent
        copy of it. See :meth:`_guarded_dispatch` for the sequence.

        ``dispatch`` — an optional zero-argument coroutine factory that
        performs the work once every gate has passed, for callers whose unit
        of work is not a registered tool handler (e.g. the scheduler's
        ``site_services.pulse`` skill). It runs INSIDE the ledger INTENT, so it is
        recorded exactly like a tool dispatch. When omitted, the registered
        tool handler for ``name`` runs, unchanged.

        ``human_approved`` is the post-approval REPLAY path, identical in
        meaning to :meth:`execute_approved_tool`'s: an operator already
        confirmed these exact arguments out of band. A caller may only set it
        having just redeemed a single-use execution grant for this exact
        (canonical tool, argument digest) — i.e. proof that
        ``OutboundApprovalStore.consume()`` verified a signed ticket. Without
        that replay path an always-gated scheduled action could be approved but
        never executed, and a gate that can never be satisfied is a dead
        feature rather than a safety property.

        SECURITY: ``name``/``args`` are gate INPUTS, never gate OVERRIDES. No
        argument supplied here can lower the tier, skip approval, or authorize
        execution — that is the defect class this seam exists to stop
        repeating. ``human_approved`` is not an exception: it is a Python
        parameter set by dispatch code from a consumed ticket, never a value
        read out of a tool call, an HTTP body or a stored cron job.
        """
        tc = ToolCall(
            name=_resolve_tool_name(str(name or "")),
            args=dict(args) if isinstance(args, dict) else {},
            call_id=call_id or f"guarded-{uuid.uuid4().hex[:12]}",
        )
        return await self._guarded_dispatch(
            tc, session_id, dispatch=dispatch,
            human_approved=human_approved, approval_ref=approval_ref,
        )

    async def _guarded_dispatch(
        self,
        tc: ToolCall,
        session_id: str,
        *,
        approval_ref: Optional[str] = None,
        human_approved: bool = False,
        dispatch: Optional[Callable[[], Any]] = None,
    ) -> str:
        """Run every pre-action gate, then dispatch inside a ledger INTENT.

        Order (see also the module docstring of cato/safety.py):

          1. name resolution              — done by the caller
          2. risk classification / STOP   — SafetyGuard
          3. authorization                — TokenChecker (delegation token)
          4. reversibility                — ActionGuard
          5. approval                     — outbound approval policy + store
          6. ledger INTENT                — durably committed BEFORE dispatch
          7. dispatch
          8. ledger CONFIRMED / FAILED

        Every refusal in 2-5 writes a ledger DENIED entry before returning.

        ``human_approved`` marks the post-approval replay path: an operator has
        already confirmed these exact arguments out of band, which is precisely
        what gates 2, 4 and 5 exist to obtain, so they are skipped. The STOP
        file still binds — it is an emergency kill switch that postdates the
        approval — and the ledger still records everything.
        """
        tool_name = tc.name or ""
        args = tc.args if isinstance(tc.args, dict) else {}

        # --- STOP: always honoured, even for an approved action ------------
        if self._safety is not None and self._safety.is_stop_requested():
            reason = "STOP signal file present"
            logger.warning("STOP file detected — refusing %s", tool_name)
            self._record_denial(
                tool_name=tool_name, tool_input=args, session_id=session_id,
                gate="stop_file", reason=reason, approval_ref=approval_ref,
            )
            return json.dumps({"error": f"[SAFETY] {reason}.", "safety_denied": True})

        policy_gate = "human_approved" if human_approved else "auto"

        if not human_approved:
            # --- 2. risk classification -----------------------------------
            if self._safety and not self._safety.check_and_confirm(tool_name, args):
                error_msg = f"[SAFETY] Action '{tool_name}' denied by safety guard."
                logger.warning(error_msg)
                if self._audit_log:
                    try:
                        self._audit_log.log(
                            session_id, "error", tool_name, args, {}, error=error_msg,
                        )
                    except Exception:
                        pass
                self._record_denial(
                    tool_name=tool_name, tool_input=args, session_id=session_id,
                    gate="safety", reason=error_msg,
                )
                return json.dumps({"error": error_msg, "safety_denied": True})

            # --- 3. token authorization -----------------------------------
            if tool_name in {"integration.status", "integration.action", "integration.setup"}:
                auth = None
            else:
                auth = self._token_checker.check_authorization(tool_name, args, session_id)
            if auth is not None and not auth.authorized:
                if auth.requires_user_confirmation:
                    error_msg = (
                        f"[AUTH] Tool '{tool_name}' requires explicit user approval: {auth.reason}"
                    )
                else:
                    error_msg = f"[AUTH] Tool '{tool_name}' denied: {auth.reason}"
                logger.warning(error_msg)
                self._record_denial(
                    tool_name=tool_name, tool_input=args, session_id=session_id,
                    gate="authorization", reason=error_msg,
                )
                return json.dumps({"error": error_msg, "auth_denied": True})

            # --- 4. reversibility (ActionGuard) ---------------------------
            guard_error = self._check_action_guard(tool_name, args, session_id)
            if guard_error is not None:
                return guard_error

            # --- 5. approval ----------------------------------------------
            gate_result = await self._maybe_gate_outbound_tool(tc, session_id)
            if gate_result is not None:
                return gate_result

        # --- 6/7/8. ledger INTENT -> dispatch -> terminal entry ------------
        return await self._dispatch_recorded(
            tc, session_id, policy_gate=policy_gate, approval_ref=approval_ref,
            dispatch=dispatch,
        )

    def _check_action_guard(
        self, tool_name: str, args: dict, session_id: str,
    ) -> Optional[str]:
        """Run ActionGuard. Returns a refusal payload, or None to proceed.

        This is the gate that used to exist only as a dashboard panel. Its
        verdict binds here: `proceed=False` stops the dispatch.
        """
        if self._action_guard is None:
            return None
        registry_name = _reversibility_name(tool_name, args)
        try:
            decision = self._action_guard.check_before_execute(
                registry_name,
                args,
                current_autonomy_level=self._autonomy_level,
            )
        except Exception as exc:  # pragma: no cover — defensive
            # A guard that cannot render a verdict is not a licence to proceed.
            logger.error("ActionGuard raised on %s: %s — refusing", tool_name, exc)
            self._record_denial(
                tool_name=tool_name, tool_input=args, session_id=session_id,
                gate="action_guard", reason=f"guard_error: {exc}",
            )
            return json.dumps({
                "error": f"[GUARD] Action '{tool_name}' refused: pre-action guard failed.",
                "guard_denied": True,
            })

        if decision.proceed:
            return None

        error_msg = f"[GUARD] Action '{tool_name}' blocked: {decision.reason}"
        logger.warning("%s (checks=%s)", error_msg, decision.applied_checks)
        self._record_denial(
            tool_name=tool_name, tool_input=args, session_id=session_id,
            gate="action_guard", reason=decision.reason,
        )
        return json.dumps({
            "error": error_msg,
            "guard_denied": True,
            "requires_confirmation": decision.requires_confirmation,
        })

    async def _dispatch_recorded(
        self,
        tc: ToolCall,
        session_id: str,
        *,
        policy_gate: str,
        approval_ref: Optional[str] = None,
        dispatch: Optional[Callable[[], Any]] = None,
    ) -> str:
        """Commit a ledger INTENT, then dispatch inside it.

        `recorded_action` writes and reads back the INTENT before yielding, so
        by the time the tool runs the intent is durable. If it cannot be
        written, the body never executes and the action is aborted — a tool
        whose invocation cannot be proven must not run.
        """
        args = tc.args if isinstance(tc.args, dict) else {}

        if self._ledger is None:
            if self._ledger_required:
                reason = (
                    "action ledger is enabled but unavailable; refusing to run an "
                    "unrecorded action"
                )
                logger.critical("Ledger unavailable — aborting %s", tc.name)
                return json.dumps({"error": f"[LEDGER] {reason}", "ledger_denied": True})
            # Auditing explicitly disabled by the operator.
            if dispatch is not None:
                return await dispatch()
            return await self._dispatch_with_progress(tc)

        from .audit.ledger import DuplicateActionError, LedgerWriteError

        try:
            with self._ledger.recorded_action(
                tool_name=tc.name or "",
                tool_input=args,
                agent_session_id=session_id,
                policy_decision="allow",
                policy_gate=policy_gate,
                approval_ref=approval_ref,
                idempotency_key=self._ledger_idempotency_key(session_id, tc),
                actor=session_id,
                reversibility=_reversibility_score(tc.name or "", args),
            ) as action:
                return await action.arun(self._dispatch_for_ledger(tc, dispatch))
        except _ToolDispatchIndeterminate as exc:
            # arun() wrote INDETERMINATE (not FAILED): the request reached the
            # remote and the answer was lost, so we cannot claim it did not
            # happen. It stays on the reconciliation queue until a human or a
            # remote status query resolves it.
            logger.critical(
                "INDETERMINATE action %s: the request reached the remote and no "
                "answer came back — the real-world effect is UNKNOWN. Reconcile "
                "before retrying (ledger.unreconciled_indeterminate()). Detail: %s",
                tc.name, exc.detail,
            )
            return exc.result_text
        except _ToolDispatchFailure as exc:
            # arun() already wrote FAILED and recorded_action re-raised. The
            # ledger now reflects the truth; hand the model its error string.
            return exc.result_text
        except DuplicateActionError as exc:
            # Already recorded, so it may already have happened. Running it
            # again is the one thing we must not do.
            logger.error("Duplicate action refused (not re-run): %s", exc)
            return json.dumps({
                "error": "[LEDGER] This exact call was already recorded; refusing to "
                         "re-run it because the side effect may already have occurred.",
                "duplicate_action": True,
            })
        except LedgerWriteError as exc:
            logger.critical("Ledger write failed — action aborted: %s", exc)
            return json.dumps({
                "error": f"[LEDGER] Action aborted: the audit ledger could not record "
                         f"it ({exc}).",
                "ledger_denied": True,
            })

    async def _maybe_gate_outbound_tool(
        self, tc: ToolCall, session_id: str,
    ) -> Optional[str]:
        """Hold outbound tools until Telegram/API approval when required.

        SECURITY — there is deliberately NO early return on a model-supplied
        argument. ``_approval_granted``, ``dry_run`` and ``draft_only`` all
        arrive inside the JSON the model itself wrote; honouring any of them
        lets the model grant itself approval. The single legitimate downgrade
        is an :class:`ApprovalContext`, a Python object constructed by dispatch
        code, and this path never constructs an authorized one.
        """
        from .core.approval_policy import build_preview
        from .core.outbound_approval import approval_decision, get_approval_store

        args = tc.args if isinstance(tc.args, dict) else {}

        decision = approval_decision(tc.name or "", args)
        if decision.bypass_attempted:
            logger.warning(
                "Model attempted to self-authorize %s via args %s — ignored",
                decision.canonical, list(decision.bypass_attempted),
            )
        if not decision.requires_approval:
            return None

        # Redacted recursively by build_preview. This string is what reaches
        # Telegram, so it must never carry a credential — the old
        # json.dumps(args)[:500] did.
        preview = build_preview(tc.name or "", args, limit=500)
        store = get_approval_store()
        approval = store.create(
            session_id=session_id,
            tool_name=tc.name or "",
            args=args,
            preview=preview,
        )
        notify = getattr(self, "_outbound_notify", None)
        if notify is not None:
            try:
                res = notify(approval)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.debug("outbound notify failed: %s", exc)

        if self._audit_log:
            try:
                self._audit_log.log(
                    session_id,
                    "approval_pending",
                    tc.name or "",
                    args,
                    {"approval_id": approval.id},
                )
            except Exception:
                pass

        # A refusal is an event. Record it in the chain BEFORE the model is
        # told, so the ledger shows what Cato declined to do, not only what it
        # managed to do.
        self._record_denial(
            tool_name=tc.name or "",
            tool_input=args,
            session_id=session_id,
            gate="approval",
            reason=f"approval_required:{decision.reason} (approval_id={approval.id})",
            approval_ref=approval.id,
        )

        return json.dumps({
            "ok": False,
            "error": "approval_required",
            "approval_id": approval.id,
            "tool": tc.name,
            "message": (
                f"Outbound action held for approval. "
                f"Telegram: tap Approve for {approval.id} or POST /api/outbound/{approval.id}/approve"
            ),
        })

    async def execute_approved_tool(self, approval_id: str) -> str:
        """Redeem an approval exactly once, then run what the operator approved.

        Replaces the old "read the row, check status == approved, dispatch"
        shape, which was replayable: the row stayed `approved` forever, so every
        call re-executed the side effect. ``store.consume`` verifies the signed
        ticket, the expiry, the tool scope and the argument digest, then marks
        the ticket consumed atomically — a second call raises.

        The arguments executed are the ones ``consume`` returns (what the
        operator actually saw and approved), never a locally reconstructed copy,
        and no ``_approval_granted`` flag is re-injected.
        """
        from .core.approval_policy import TicketError
        from .core.outbound_approval import get_approval_store

        store = get_approval_store()
        try:
            ticket, approved_args = store.consume(approval_id)
        except TicketError as exc:
            reason = str(exc)
            logger.warning("Approval %s refused at consume: %s", approval_id, reason)
            row = store.get(approval_id)
            self._record_denial(
                tool_name=(row.tool_name if row else "unknown"),
                tool_input={"approval_id": approval_id},
                session_id=(row.session_id if row else "unknown"),
                gate="approval_consume",
                reason=reason,
                approval_ref=approval_id,
            )
            return json.dumps({
                "ok": False,
                "error": "approval_not_consumable",
                "reason": reason,
                "approval_id": approval_id,
            })

        row = store.get(approval_id)
        tool_name = row.tool_name if row else ticket.tool
        session_id = ticket.session_id or (row.session_id if row else "approval")
        tc = ToolCall(
            name=_resolve_tool_name(tool_name),
            args=dict(approved_args) if isinstance(approved_args, dict) else {},
            call_id=f"appr-{approval_id}",
        )
        return await self._guarded_dispatch(
            tc, session_id, approval_ref=approval_id, human_approved=True,
        )

    async def _dispatch_for_ledger(
        self,
        tc: ToolCall,
        dispatch: Optional[Callable[[], Any]] = None,
    ) -> str:
        """Dispatch, raising ``_ToolDispatchFailure`` when the call did not succeed.

        ``ActionHandle.arun()`` writes CONFIRMED unless the awaited coroutine
        raises, so this is what makes a failed tool call land in the ledger as
        FAILED. The caller unwraps the exception and returns ``result_text``,
        so the model's view of a tool error is unchanged.

        ``dispatch`` (from :meth:`guarded_action`) substitutes the unit of work
        for callers whose action is not a registered tool handler. The failure
        / indeterminate classification below is identical either way, so a
        scheduled action lands in the ledger with the same terminal entries.
        """
        if dispatch is not None:
            result_text = await dispatch()
        else:
            result_text = await self._dispatch_with_progress(tc)
        # Checked BEFORE the failure test: a timed-out remote call is
        # error-shaped too, and recording it FAILED would assert it did not
        # happen. Unknown outranks failed.
        unknown = _tool_result_indeterminate(result_text)
        if unknown is not None:
            raise _ToolDispatchIndeterminate(result_text, unknown)
        detail = _tool_result_failure(result_text)
        if detail is not None:
            raise _ToolDispatchFailure(result_text, detail)
        return result_text

    async def _dispatch_with_progress(self, tc: ToolCall) -> str:
        """Dispatch a tool call with start/end progress callbacks.

        BH-011 — Wraps the bare `_dispatch_tool` so the gateway can surface
        the currently-running tool in the desktop activity pill.  Callback
        failures are swallowed; tool dispatch itself is the source of truth.

        Also emits the richer Claude-Code-style tool_start / tool_end
        progress events when a ProgressEmitter is attached.
        """
        cb = self._on_tool_progress
        summary = _summarize_tool_call(tc)
        if cb is not None:
            try:
                _res = cb(tc.name, summary, "start")
                if asyncio.iscoroutine(_res):
                    await _res
            except Exception as exc:
                logger.debug("BH-011 progress callback (start) failed: %s", exc)
        # Streaming feed: emit structured tool_start
        try:
            emitter = getattr(self, "_progress", None)
            if emitter is not None:
                await emitter.tool_start(
                    tool=tc.name or "",
                    args_preview=summary,
                    call_id=tc.call_id or "",
                )
        except Exception:
            pass

        _ok = True
        _result_text = ""
        try:
            _result_text = await _dispatch_tool(tc)
            # Same failure test the ledger uses, so the progress feed's success
            # bit and the audit trail can never disagree.
            _ok = _tool_result_failure(_result_text) is None
            return _result_text
        except Exception:
            _ok = False
            raise
        finally:
            if cb is not None:
                try:
                    _res = cb(tc.name, summary, "end")
                    if asyncio.iscoroutine(_res):
                        await _res
                except Exception as exc:
                    logger.debug("BH-011 progress callback (end) failed: %s", exc)
            # Streaming feed: emit structured tool_end (success bit + summary)
            try:
                emitter = getattr(self, "_progress", None)
                if emitter is not None:
                    _result_summary = (_result_text or "").replace("\n", " ")[:160]
                    await emitter.tool_end(
                        tool=tc.name or "",
                        call_id=tc.call_id or "",
                        success=_ok,
                        summary=_result_summary,
                    )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def _stream_collect(
        self, messages: list[dict], model: str, force_text: bool = False
    ) -> tuple[str, list[ToolCall]]:
        """Stream from router; return (text, tool_calls) with retry on error."""
        # Build tool definitions from the registry so the model can do
        # structured tool calling (OpenAI function-calling format).
        # Sanitize dotted names (web.search → web_search) for OpenAI compat.
        if not force_text:
            tools, _local_name_map = _sanitize_tool_defs(get_tool_definitions())
        else:
            tools, _local_name_map = [], {}
        delay = _RETRY_BASE_DELAY
        for attempt in range(_MAX_RETRIES):
            try:
                chunks: list[str] = []
                structured_tool_calls: list[dict[str, Any]] = []
                async for chunk in self._router.complete(messages, model, tools=tools, stream=True):
                    if isinstance(chunk, str):
                        chunks.append(chunk)
                    elif isinstance(chunk, dict):
                        structured_tool_calls.extend(chunk.get("tool_calls") or [])
                full = "".join(chunks)
                calls: list[ToolCall] = []
                if not force_text:
                    if structured_tool_calls:
                        calls.extend(_parse_tool_calls_openai({"tool_calls": structured_tool_calls}))
                    calls.extend(_parse_tool_calls_text(full))
                    # Reverse-map sanitized names back to dotted originals
                    for tc in calls:
                        if tc.name in _local_name_map:
                            tc.name = _local_name_map[tc.name]
                visible = _strip_tool_call_blocks(full)
                # BH-006: If model returned no text AND no tool calls, treat as
                # transient failure and retry instead of immediately returning an
                # error message.  Only give up after exhausting all retry attempts.
                if not visible and not calls:
                    if attempt < _MAX_RETRIES - 1:
                        logger.warning(
                            "BH-006: empty model response (attempt %d) — "
                            "raw=%r, stripped=%r — retrying in %.1fs",
                            attempt + 1, full[:200], visible, delay,
                        )
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue  # retry
                    else:
                        logger.error("BH-006: empty model response after %d attempts", _MAX_RETRIES)
                        visible = (
                            "The model returned no readable content after multiple attempts. "
                            "Try rephrasing your message or check that the model is responding correctly."
                        )
                return visible, calls
            except Exception as exc:
                if attempt < _MAX_RETRIES - 1:
                    logger.warning("LLM attempt %d failed: %s — retry in %.1fs", attempt + 1, exc, delay)
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logger.error("LLM failed after %d attempts: %s", _MAX_RETRIES, exc)
                    return f"[error: {exc}]", []
        return "", []

    # ------------------------------------------------------------------
    # Transcript helpers
    # ------------------------------------------------------------------

    def _history_len(self, tpath: Path) -> int:
        if not tpath.exists():
            return 0
        try:
            return sum(1 for _ in tpath.open("r", encoding="utf-8"))
        except OSError:
            return 0

    def _recent_turns(self, tpath: Path, limit: int = 20) -> list[dict]:
        """Return up to ``limit`` recent transcript turns as API-ready messages.

        BH-007: A naive ``lines[-limit:]`` slice can sever an
        ``assistant(tool_calls=[X])`` → ``tool(tool_call_id=X)`` pair, leaving
        an orphan ``tool`` row that providers reject with HTTP 400.  After
        slicing, we run :func:`_repair_tool_call_pairing` to drop orphans and
        unfulfilled tool_calls before the messages reach the model.
        """
        if not tpath.exists():
            return []
        try:
            lines = tpath.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        msgs: list[dict] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = rec.get("role")
            if role == "user":
                msgs.append({"role": "user", "content": rec.get("content", "")})
            elif role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": rec.get("content", "")}
                # Preserve tool_calls so the model sees its own prior invocations
                if rec.get("tool_calls"):
                    msg["tool_calls"] = rec["tool_calls"]
                msgs.append(msg)
            elif role == "tool":
                # Include tool results so the model has full execution context
                msgs.append({
                    "role": "tool",
                    "tool_call_id": rec.get("tool_call_id", "unknown"),
                    "content": rec.get("result", rec.get("content", "")),
                })
        return _repair_tool_call_pairing(msgs)
