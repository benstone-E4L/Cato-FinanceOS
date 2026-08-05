"""
cato/tools/__init__.py — Register all built-in tools with the agent loop.

Call register_all_tools(agent_loop) once at startup to wire every tool
handler into the loop's _TOOL_REGISTRY.
"""

from .browser import BrowserTool
from .file import FileTool
from .genesis import GENESIS_TOOL_SCHEMA, GenesisTool
from .memory import MemoryTool
from .shell import ShellTool

__all__ = ["ShellTool", "FileTool", "BrowserTool", "MemoryTool", "GenesisTool"]


def register_all_tools(agent_loop) -> None:
    """Register all tools with the module-level tool registry in agent_loop."""
    from ..agent_loop import register_tool
    register_tool("shell", ShellTool().execute)
    register_tool("file", FileTool().execute)
    register_tool("memory", MemoryTool().execute)
    register_tool(
        "genesis",
        GenesisTool(budget=getattr(agent_loop, "_budget", None)).execute,
        GENESIS_TOOL_SCHEMA,
    )

    # Use Conduit browser engine if enabled in config, otherwise plain browser
    try:
        conduit_enabled = getattr(agent_loop._cfg, "conduit_enabled", False)
    except Exception:
        conduit_enabled = False

    if conduit_enabled:
        from .conduit_bridge import ConduitBrowserTool
        register_tool("browser", ConduitBrowserTool(agent_loop._cfg, agent_loop._budget).execute)
    else:
        register_tool("browser", BrowserTool().execute)

    _register_flow_tools(agent_loop)
    _register_night_shift_tools(agent_loop)


def _register_night_shift_tools(agent_loop) -> None:
    from ..agent_loop import register_tool
    from .send_email_tool import SEND_EMAIL_SCHEMA, execute_send_email
    from .outreach_bridge import OUTREACH_SCHEMA, execute_outreach_run
    from .site_services_bridge import (
        INBOX_SCHEMA,
        STUCK_SCHEMA,
        execute_site_services_inbox,
        execute_site_services_stuck,
    )

    register_tool("send_email", execute_send_email, SEND_EMAIL_SCHEMA)
    register_tool("outreach.run", execute_outreach_run, OUTREACH_SCHEMA)
    register_tool("site_services.inbox", execute_site_services_inbox, INBOX_SCHEMA)
    register_tool("site_services.stuck", execute_site_services_stuck, STUCK_SCHEMA)


def _register_flow_tools(agent_loop) -> None:
    """Register flow.run with budget-aware FlowEngine."""
    try:
        from ..orchestrator.clawflows import FlowEngine
    except ImportError:
        return

    # agent_loop is threaded through so every flow STEP runs the same gate
    # chain the flow.run tool call itself ran. Gating the flow but not its
    # steps would let one approval authorize unbounded tool calls inside it.
    engine = FlowEngine(
        budget=getattr(agent_loop, "_budget", None), agent_loop=agent_loop,
    )

    async def _flow_run(args: dict) -> str:
        name = args.get("flow", args.get("name", ""))
        if not name:
            return "[flow: name required]"
        cap = args.get("budget_cap_cents")
        result = await engine.run_flow(
            name,
            trigger_context=args,
            budget_cap_cents=int(cap) if cap is not None else None,
        )
        return f"flow={name} status={result.status} steps={len(result.step_outputs)} error={result.error or ''}"

    from ..agent_loop import register_tool
    register_tool("flow.run", _flow_run)
