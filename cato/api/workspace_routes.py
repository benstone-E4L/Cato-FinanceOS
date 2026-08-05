"""
cato/api/workspace_routes.py — Workspace template file management.

Endpoints for reading, writing, and listing workspace files (AGENTS.md, MEMORY.md, etc.)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from aiohttp import web

logger = logging.getLogger(__name__)

# Template file names (read-only list)
TEMPLATE_NAMES = ["AGENTS.md", "MEMORY.md", "USER.md", "HEARTBEAT.md", "TOOLS.md"]


def _workspace_dir() -> Path:
    """Get the workspace directory."""
    from cato.config import CatoConfig
    config = CatoConfig.load()
    if config.workspace_dir:
        return Path(config.workspace_dir).expanduser()
    return Path.home() / ".cato" / "workspace"


async def get_templates(request: web.Request) -> web.Response:
    """GET /api/workspace/templates — Return list of available templates."""
    try:
        workspace = _workspace_dir()
        workspace.mkdir(parents=True, exist_ok=True)

        # Check which templates exist
        existing = []
        for name in TEMPLATE_NAMES:
            if (workspace / name).exists():
                existing.append(name)

        return web.json_response({
            "success": True,
            "templates": existing,
            "available": TEMPLATE_NAMES
        })
    except Exception as e:
        logger.exception(f"Error fetching templates: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def init_templates(request: web.Request) -> web.Response:
    """POST /api/workspace/init — Create all 5 template files."""
    try:
        workspace = _workspace_dir()
        workspace.mkdir(parents=True, exist_ok=True)

        templates = {
            "AGENTS.md": """# Agent Operating Manual

## Thinking Framework
- Pause before responding to complex requests
- Break tasks into smaller, verifiable steps
- Verify assumptions with the user before proceeding
- Ask clarifying questions when requirements are ambiguous

## Tool Usage
- **coding-agent**: Programming tasks, code generation, debugging
- **web-browser**: Research, information gathering, documentation
- **memory**: Store important decisions, technical notes, user preferences

## Safety Rules
- Never execute unverified shell commands
- Always ask for permission before destructive operations
- Validate API responses before using them

## Response Style
- Be concise and direct
- Include reasoning for technical decisions
- Offer alternatives when applicable
""",
            "MEMORY.md": """# Long-Term Memory

## Projects
(Add your projects here)

## Technical Notes
(Add technical decisions and configurations)

## Decisions
(Add important decisions made)

## User Preferences
(Add user communication preferences)
""",
            "USER.md": """# User Profile

## Name & Background
(Your name and role)

## Preferences
- Communication style: (brief/detailed/technical)
- Time zone: (your timezone)
- Response format: (bullet points/paragraphs/code blocks)

## Availability
- Active hours: (your working hours)
- Response time preference: (immediate/within an hour/etc)
""",
            "HEARTBEAT.md": """# Periodic Health Checks

## Daily Checks
- [ ] Check daemon process running
- [ ] Verify API connectivity
- [ ] Review error logs

## Weekly Checks
- [ ] Backup workspace files
- [ ] Review long-term memory
- [ ] Check token usage

## Monthly Checks
- [ ] Update MEMORY.md with new facts
- [ ] Archive old logs
- [ ] Review agent performance
""",
            "TOOLS.md": """# Local Tools & Scripts

## Available Commands
- `pytest` → Run tests
- `git log --oneline` → View commit history

## Scripts
(Add your local scripts and tools)

## Tips
(Add any helpful tips specific to your setup)
"""
        }

        created = []
        for name, content in templates.items():
            path = workspace / name
            if not path.exists():
                path.write_text(content)
                created.append(name)
                logger.info(f"Created template: {name}")
            else:
                logger.info(f"Template already exists: {name}")

        return web.json_response({
            "success": True,
            "created": created,
            "workspace_dir": str(workspace)
        })
    except Exception as e:
        logger.exception(f"Error initializing templates: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def get_workspace_file(request: web.Request) -> web.Response:
    """GET /api/workspace/{filename} — Read workspace file contents."""
    try:
        filename = request.match_info.get("filename", "")

        # Validate filename
        if not filename or ".." in filename or filename not in TEMPLATE_NAMES:
            return web.json_response({
                "success": False,
                "error": f"Invalid filename: {filename}"
            }, status=400)

        workspace = _workspace_dir()
        file_path = workspace / filename

        if not file_path.exists():
            return web.json_response({
                "success": False,
                "error": f"File not found: {filename}"
            }, status=404)

        content = file_path.read_text(encoding="utf-8")
        return web.json_response({
            "success": True,
            "filename": filename,
            "content": content
        })
    except Exception as e:
        logger.exception(f"Error reading workspace file: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def put_workspace_file(request: web.Request) -> web.Response:
    """PUT /api/workspace/{filename} — Save workspace file contents."""
    try:
        filename = request.match_info.get("filename", "")

        # Validate filename
        if not filename or ".." in filename or filename not in TEMPLATE_NAMES:
            return web.json_response({
                "success": False,
                "error": f"Invalid filename: {filename}"
            }, status=400)

        body = await request.json()
        content = body.get("content", "")

        workspace = _workspace_dir()
        workspace.mkdir(parents=True, exist_ok=True)
        file_path = workspace / filename

        # LEDGERED: these files (SOUL.md / IDENTITY.md / AGENTS.md / TOOLS.md)
        # are loaded into the system prompt, so writing one changes what the
        # agent is instructed to do. Operator-only, but never unrecorded.
        from cato.core.operator_ledger import record_operator_action

        async def _write() -> None:
            file_path.write_text(content, encoding="utf-8")

        await record_operator_action(
            tool_name="workspace.file_write",
            tool_input={"filename": filename, "bytes": len(content)},
            session_id="ui-workspace",
            run=_write,
            reversibility=0.6,
        )
        logger.info(f"Updated workspace file: {filename}")

        return web.json_response({
            "success": True,
            "filename": filename,
            "message": f"Successfully saved {filename}"
        })
    except Exception as e:
        logger.exception(f"Error writing workspace file: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


def register_routes(app: web.Application) -> None:
    """Register workspace routes with the aiohttp Application."""
    app.router.add_get("/api/workspace/templates", get_templates)
    app.router.add_post("/api/workspace/init", init_templates)
    app.router.add_get("/api/workspace/{filename}", get_workspace_file)
    app.router.add_put("/api/workspace/{filename}", put_workspace_file)
    logger.info("Workspace routes registered")
