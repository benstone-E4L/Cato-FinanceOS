"""GAP 2 — a tool call that failed must land in the ledger as FAILED.

`_dispatch_tool` deliberately never propagates a handler exception: the model
has to see a readable error string and keep going. That swallowing also hid the
failure from `ActionHandle.arun()`, which only writes FAILED when the awaited
call *raises* — so a call that failed was recorded CONFIRMED with
outcome='success'. The audit ledger, the system of record, was reporting real
failures as successes.

These tests cover both shapes the fix must distinguish and then treat alike in
the ledger: the handler *errored*, and the handler *returned* an error-shaped
result. In both cases the model must still receive its readable error string.
"""

from __future__ import annotations

import json

import pytest

from cato.agent_loop import AgentLoop, ToolCall
from cato.audit.action_guard import ActionGuard
from cato.audit.ledger import LedgerMiddleware, LedgerQuery
from cato.safety import SafetyGuard


class _Loop(AgentLoop):
    """AgentLoop with the heavy constructor skipped — same harness shape as
    tests/test_dispatch_gates.py. `_dispatch_with_progress` is the seam, so the
    real `_dispatch_for_ledger` / `arun` / ledger plumbing is exercised."""

    def __init__(self, **attrs):  # noqa: D107 — deliberately not calling super()
        self.dispatched: list[ToolCall] = []
        self._dispatch_result = json.dumps({"ok": True})
        self._dispatch_raises: BaseException | None = None
        for key, value in attrs.items():
            setattr(self, key, value)

    async def _dispatch_with_progress(self, tc: ToolCall) -> str:  # type: ignore[override]
        self.dispatched.append(tc)
        if self._dispatch_raises is not None:
            raise self._dispatch_raises
        return self._dispatch_result


class _AllowAuth:
    def check_authorization(self, *_a, **_k):
        return None


@pytest.fixture()
def ledger(tmp_path):
    mw = LedgerMiddleware(db_path=tmp_path / "ledger.db")
    yield mw
    mw.close()


@pytest.fixture()
def loop(tmp_path, monkeypatch, ledger):
    monkeypatch.setattr(SafetyGuard, "_stop_file_path", staticmethod(lambda: tmp_path / "STOP"))
    monkeypatch.setattr("cato.safety._is_interactive", lambda: False)
    return _Loop(
        _safety=SafetyGuard(config={"safety_mode": "strict"}),
        _audit_log=None,
        _token_checker=_AllowAuth(),
        _action_guard=ActionGuard(),
        _autonomy_level=0.5,
        _ledger=ledger,
        _ledger_required=True,
        _outbound_notify=None,
        _run_id="testrun",
    )


def _kinds(tmp_path) -> list[str]:
    q = LedgerQuery(db_path=tmp_path / "ledger.db")
    try:
        return [r.entry_kind for r in q.last_n(50)]
    finally:
        q.close()


def _outcomes(tmp_path, kind: str) -> list[str]:
    q = LedgerQuery(db_path=tmp_path / "ledger.db")
    try:
        return [r.outcome for r in q.by_entry_kind(kind)]
    finally:
        q.close()


class TestFailedDispatchIsRecordedAsFailed:
    @pytest.mark.asyncio
    async def test_error_shaped_result_is_recorded_failed_not_confirmed(self, loop, tmp_path):
        loop._dispatch_result = json.dumps({"error": "repo not found", "recoverable": True})

        result = await loop._guarded_dispatch(ToolCall(name="web.search", args={"q": "x"}, call_id="c1"), "s1")

        kinds = _kinds(tmp_path)
        assert "FAILED" in kinds, kinds
        assert "CONFIRMED" not in kinds, kinds
        # The model's view is untouched — same JSON the tool produced.
        assert json.loads(result)["error"] == "repo not found"

    @pytest.mark.asyncio
    async def test_a_raising_handler_is_still_recorded_failed(self, loop, tmp_path):
        loop._dispatch_raises = RuntimeError("handler exploded")

        with pytest.raises(RuntimeError):
            await loop._guarded_dispatch(ToolCall(name="web.search", args={"q": "x"}, call_id="c1"), "s1")

        assert "FAILED" in _kinds(tmp_path)
        assert "CONFIRMED" not in _kinds(tmp_path)

    @pytest.mark.asyncio
    async def test_the_failure_detail_reaches_the_ledger_outcome(self, loop, tmp_path):
        loop._dispatch_result = json.dumps({"error": "stripe returned 402"})

        await loop._guarded_dispatch(ToolCall(name="web.search", args={"q": "x"}, call_id="c1"), "s1")

        assert any("stripe returned 402" in o for o in _outcomes(tmp_path, "FAILED"))

    @pytest.mark.asyncio
    async def test_the_attempt_is_still_recorded_before_the_failure(self, loop, tmp_path):
        """The fix must not cost the ATTEMPTED row — an action that was tried and
        failed is a different fact from one that was never tried."""
        loop._dispatch_result = json.dumps({"error": "nope"})

        await loop._guarded_dispatch(ToolCall(name="web.search", args={"q": "x"}, call_id="c1"), "s1")

        kinds = _kinds(tmp_path)
        assert kinds.index("INTENT") < kinds.index("ATTEMPTED") < kinds.index("FAILED")

    @pytest.mark.asyncio
    async def test_a_real_success_is_still_confirmed(self, loop, tmp_path):
        """Control: the failure test above is detecting failure, not breaking success."""
        loop._dispatch_result = json.dumps({"ok": True, "results": []})

        result = await loop._guarded_dispatch(ToolCall(name="web.search", args={"q": "x"}, call_id="c1"), "s1")

        assert "CONFIRMED" in _kinds(tmp_path)
        assert "FAILED" not in _kinds(tmp_path)
        assert json.loads(result)["ok"] is True

    @pytest.mark.asyncio
    async def test_an_empty_error_field_is_not_a_failure(self, loop, tmp_path):
        """`{"error": null}` is a tool saying 'no error', not a failure."""
        loop._dispatch_result = json.dumps({"ok": True, "error": None})

        await loop._guarded_dispatch(ToolCall(name="web.search", args={"q": "x"}, call_id="c1"), "s1")

        assert "CONFIRMED" in _kinds(tmp_path)
        assert "FAILED" not in _kinds(tmp_path)

    @pytest.mark.asyncio
    async def test_non_json_output_is_not_read_as_a_failure(self, loop, tmp_path):
        """Plain-text tool output that merely contains the word error is a result,
        not an error envelope."""
        loop._dispatch_result = "no error occurred while reading the file"

        await loop._guarded_dispatch(ToolCall(name="web.search", args={"q": "x"}, call_id="c1"), "s1")

        assert "CONFIRMED" in _kinds(tmp_path)
        assert "FAILED" not in _kinds(tmp_path)
