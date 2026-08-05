"""
tests/test_flow_routes_gates.py — t20: the HTTP flow surface.

``POST /api/flows`` sanitised the flow NAME and never looked at the step
SKILLS, so arbitrary skill names went straight into stored YAML.
``POST /api/flows/{name}/run`` then built a FlowEngine and ran it with no gate
at all. Both are on the same ``X-Cato-Token`` surface as the cron API.

Write-time skill validation is defence in depth ONLY. The real control is the
run-time gate in ``FlowEngine._dispatch_step`` (tests/test_flow_engine_gates.py),
because flows can already exist on disk from before this fix.

No network, no daemon, no real flow execution.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

import cato.agent_loop as agent_loop_mod
from cato.ui.server import create_ui_app


async def _noop(_args: dict) -> str:  # pragma: no cover — never dispatched here
    return "noop"


def _auth(app) -> dict:
    """The daemon token this app minted. Never logged, never asserted on."""
    return {"X-Cato-Token": app["daemon_token"]}


class TestCreateFlowRejectsUnknownSkills(AioHTTPTestCase):
    async def get_application(self):
        return await create_ui_app(gateway=None)

    def setUp(self) -> None:
        super().setUp()
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self._flows = __import__("pathlib").Path(self._dir.name)
        # A non-empty registry, so known_skills() can actually answer.
        self._reg = patch.dict(
            agent_loop_mod._TOOL_REGISTRY, {"memory.search": _noop}, clear=False,
        )
        self._reg.start()
        self._flows_patch = patch(
            "cato.orchestrator.clawflows.FLOWS_DIR", self._flows,
        )
        self._flows_patch.start()

    def tearDown(self) -> None:
        self._flows_patch.stop()
        self._reg.stop()
        self._dir.cleanup()
        super().tearDown()

    async def test_unknown_step_skill_is_rejected(self):
        resp = await self.client.post("/api/flows", headers=_auth(self.app), json={
            "name": "pwn",
            "content": (
                "name: pwn\nsteps:\n  - skill: shell.pwn\n    args: {command: x}\n"
            ),
        })

        assert resp.status == 400
        body = await resp.json()
        assert any("unknown skill" in p for p in body.get("problems", []))
        assert not (self._flows / "pwn.yaml").exists(), (
            "a flow naming an unknown skill must not be written to disk"
        )

    async def test_known_step_skill_is_accepted(self):
        resp = await self.client.post("/api/flows", headers=_auth(self.app), json={
            "name": "ok-flow",
            "content": (
                "name: ok-flow\nsteps:\n  - skill: memory.search\n"
                "    args: {query: hi}\n"
            ),
        })

        assert resp.status == 200
        assert (self._flows / "ok-flow.yaml").exists()

    async def test_malformed_yaml_is_rejected(self):
        resp = await self.client.post("/api/flows", headers=_auth(self.app), json={
            "name": "broken",
            "content": "steps: [ this: is: not: yaml",
        })

        assert resp.status == 400
        assert not (self._flows / "broken.yaml").exists()


class TestRunFlowRouteFailsClosedWithoutAGateChain(AioHTTPTestCase):
    """A gateway that cannot produce an AgentLoop must not run a flow anyway."""

    async def get_application(self):
        gateway = SimpleNamespace(_budget=None)  # no _agent_loop, no _ensure_agent_loop
        return await create_ui_app(gateway=gateway)

    async def test_run_without_gate_chain_is_refused(self):
        resp = await self.client.post(
            "/api/flows/anything/run", headers=_auth(self.app), json={},
        )

        assert resp.status == 503
        body = await resp.json()
        assert "gate chain is unavailable" in body["error"]
