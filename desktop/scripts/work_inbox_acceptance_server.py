"""Local browser acceptance server for CHUNK_6_WORK_INBOX.

Serves the production desktop bundle, proxies requests through Cato's real
``create_ui_app`` routes, and provides a deterministic loopback FinanceOS
upstream that can be stopped to exercise Cato's live-to-stale cache path.
No credential value is returned to or embedded in the browser.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from aiohttp import ClientSession, web

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


async def _start_site(app: web.Application, host: str, port: int) -> tuple[web.AppRunner, int]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    sockets = site._server.sockets  # noqa: SLF001 - aiohttp exposes no bound-port accessor
    return runner, int(sockets[0].getsockname()[1])


def _finance_fixture() -> web.Application:
    app = web.Application()

    async def control_room(_: web.Request) -> web.Response:
        return web.json_response(
            {"close_status": "acceptance-ready", "holds": 0, "write_gate_enabled": False}
        )

    async def integration_health(_: web.Request) -> web.Response:
        return web.json_response({"financeos_fixture": "healthy"})

    app.router.add_get("/api/v1/control-room", control_room)
    app.router.add_get("/api/v1/control-room/integrations-health", integration_health)
    return app


async def run(dist: Path, outer_port: int) -> None:
    finance_runner, finance_port = await _start_site(_finance_fixture(), "127.0.0.1", 0)
    os.environ["FINANCEOS_CONTROL_ROOM_URL"] = f"http://127.0.0.1:{finance_port}"

    # Import only after APPDATA and the loopback FinanceOS route are isolated.
    from cato.ui import server as cato_server  # noqa: PLC0415

    cato_app = await cato_server.create_ui_app(None)
    cato_runner, cato_port = await _start_site(cato_app, "127.0.0.1", 0)
    session = ClientSession()
    state = {"finance_runner": finance_runner, "finance_running": True}

    async def index(_: web.Request) -> web.Response:
        html = (dist / "index.html").read_text(encoding="utf-8")
        shim = f"""<script>
window.__TAURI_INTERNALS__ = {{
  invoke: async (command) => {{
    if (command === 'get_daemon_status') return {{
      running: true, http_port: {outer_port}, ws_port: {outer_port}, daemon_token: null
    }};
    throw new Error('Unsupported acceptance command: ' + command);
  }}
}};
</script>"""
        return web.Response(text=html.replace("<head>", f"<head>{shim}"), content_type="text/html")

    async def favicon(_: web.Request) -> web.Response:
        return web.Response(status=204)

    async def asset(request: web.Request) -> web.StreamResponse:
        relative = request.match_info["path"]
        target = (dist / "assets" / relative).resolve()
        assets_root = (dist / "assets").resolve()
        if assets_root not in target.parents or not target.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(target)

    async def proxy(request: web.Request) -> web.Response:
        upstream_path = f"/api/{request.match_info['path']}"
        if request.query_string:
            upstream_path = f"{upstream_path}?{request.query_string}"
        target = f"http://127.0.0.1:{cato_port}{upstream_path}"
        headers = {"X-Cato-Token": cato_server._DAEMON_TOKEN}
        async with session.request(request.method, target, headers=headers, data=await request.read()) as response:
            body = await response.read()
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            return web.Response(body=body, status=response.status, headers={"Content-Type": content_type})

    async def stop_finance(_: web.Request) -> web.Response:
        if state["finance_running"]:
            await state["finance_runner"].cleanup()
            state["finance_running"] = False
        return web.json_response({"finance_running": False})

    async def status(_: web.Request) -> web.Response:
        async with session.get(
            f"http://127.0.0.1:{cato_port}/api/finance-os/control-room",
            headers={"X-Cato-Token": cato_server._DAEMON_TOKEN},
        ) as response:
            finance_route_status = response.status
        return web.json_response(
            {
                "ready": True,
                "finance_running": state["finance_running"],
                "cato_route": "real",
                "cato_port": cato_port,
                "finance_route_status": finance_route_status,
                "browser_finance_path": "registered_production_route",
            }
        )

    outer = web.Application()
    outer.router.add_get("/", index)
    outer.router.add_get("/favicon.ico", favicon)
    outer.router.add_get("/assets/{path:.*}", asset)
    outer.router.add_route("*", "/api/{path:.*}", proxy)
    outer.router.add_post("/acceptance/stop-finance", stop_finance)
    outer.router.add_get("/acceptance/status", status)
    outer_runner, _ = await _start_site(outer, "127.0.0.1", outer_port)

    print(f"READY outer_port={outer_port} cato_route=real finance_fixture=loopback", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await outer_runner.cleanup()
        await session.close()
        await cato_runner.cleanup()
        if state["finance_running"]:
            await state["finance_runner"].cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--appdata", type=Path, required=True)
    args = parser.parse_args()
    args.appdata.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(args.appdata.resolve())
    asyncio.run(run(args.dist.resolve(), args.port))


if __name__ == "__main__":
    main()
