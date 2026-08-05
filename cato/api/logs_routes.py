"""
cato/api/logs_routes.py — Daily log API endpoints.

Endpoints for creating, reading, and listing daily log files.
"""

from __future__ import annotations

import logging
from datetime import datetime

from aiohttp import web

logger = logging.getLogger(__name__)


async def get_todays_log(request: web.Request) -> web.Response:
    """GET /api/logs/today — Get or create today's daily log."""
    try:
        from cato.core.daily_log_manager import create_daily_log, get_daily_log_content

        # Create if doesn't exist
        log_path = create_daily_log()
        content = get_daily_log_content()

        return web.json_response({
            "success": True,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "content": content,
            "path": str(log_path)
        })
    except Exception as e:
        logger.exception(f"Error getting today's log: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def get_log_by_date(request: web.Request) -> web.Response:
    """GET /api/logs/{date} — Get a specific daily log (YYYY-MM-DD format)."""
    try:
        date = request.match_info.get("date", "")

        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return web.json_response({
                "success": False,
                "error": f"Invalid date format: {date} (expected YYYY-MM-DD)"
            }, status=400)

        from cato.core.daily_log_manager import get_daily_log_content

        content = get_daily_log_content(date)

        if content is None:
            return web.json_response({
                "success": False,
                "error": f"Log not found for date: {date}"
            }, status=404)

        return web.json_response({
            "success": True,
            "date": date,
            "content": content
        })
    except Exception as e:
        logger.exception(f"Error getting log for date: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def list_recent_logs(request: web.Request) -> web.Response:
    """GET /api/logs/recent — List recent daily logs."""
    try:
        from cato.core.daily_log_manager import list_recent_logs

        # Get recent logs (default 7 days)
        days = request.query.get("days", "7")
        try:
            days = int(days)
        except ValueError:
            days = 7

        logs = list_recent_logs(days=days)

        return web.json_response({
            "success": True,
            "logs": logs,
            "count": len(logs),
            "days": days
        })
    except Exception as e:
        logger.exception(f"Error listing recent logs: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def archive_logs(request: web.Request) -> web.Response:
    """POST /api/logs/archive — Archive old logs (30+ days)."""
    try:
        from cato.core.daily_log_manager import archive_old_logs

        body = await request.json()
        threshold = body.get("days_threshold", 30)

        archived_count = archive_old_logs(days_threshold=threshold)

        return web.json_response({
            "success": True,
            "archived": archived_count,
            "days_threshold": threshold
        })
    except Exception as e:
        logger.exception(f"Error archiving logs: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


def register_routes(app: web.Application) -> None:
    """Register log routes with the aiohttp Application."""
    app.router.add_get("/api/logs/today", get_todays_log)
    app.router.add_get("/api/logs/{date}", get_log_by_date)
    app.router.add_get("/api/logs/recent", list_recent_logs)
    app.router.add_post("/api/logs/archive", archive_logs)
    logger.info("Daily logs routes registered")
