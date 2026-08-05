"""
tests/test_heartbeat.py — Comprehensive unit tests for cato/heartbeat.py.

Coverage:
  - _parse_heartbeat_md: interval extraction, default interval, minimum clamp,
    checklist item parsing ([ ] and [x]), missing file, empty file, no items
  - _build_heartbeat_prompt: format, agent name embedding, checklist rendering
  - HeartbeatMonitor._tick: fires agents due for check, skips agents not due,
    skips agents with no items, skips missing agents dir, handles multiple agents
  - HeartbeatMonitor._fire: calls gateway.ingest with correct args, handles
    gateway exceptions gracefully
  - HeartbeatMonitor.fire_now: workspace/ layout, flat layout, no HEARTBEAT.md,
    empty items list, returns items list
  - HeartbeatMonitor.run_forever: CancelledError exits cleanly, non-fatal
    exceptions are swallowed and loop continues
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
from cato.heartbeat import (
    _DEFAULT_INTERVAL,
    HeartbeatMonitor,
    _build_heartbeat_prompt,
    _parse_heartbeat_md,
)


# ===========================================================================
# _parse_heartbeat_md
# ===========================================================================

class TestParseHeartbeatMd:
    """Unit tests for the HEARTBEAT.md parser."""

    def test_missing_file_returns_defaults(self, tmp_path):
        """A non-existent path returns (_DEFAULT_INTERVAL, [])."""
        path = tmp_path / "nonexistent" / "HEARTBEAT.md"
        interval, items = _parse_heartbeat_md(path)
        assert interval == _DEFAULT_INTERVAL
        assert items == []

    def test_empty_file_returns_defaults(self, tmp_path):
        """An empty file returns (_DEFAULT_INTERVAL, [])."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text("", encoding="utf-8")
        interval, items = _parse_heartbeat_md(path)
        assert interval == _DEFAULT_INTERVAL
        assert items == []

    def test_custom_interval_extracted(self, tmp_path):
        """<!-- interval: N --> sets the poll interval in seconds."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "# Heartbeat\n<!-- interval: 600 -->\n\n- [ ] Check disk space\n",
            encoding="utf-8",
        )
        interval, items = _parse_heartbeat_md(path)
        assert interval == 600
        assert items == ["Check disk space"]

    def test_interval_minimum_clamped_to_30(self, tmp_path):
        """Intervals below 30s are clamped to 30."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "<!-- interval: 5 -->\n- [ ] Health check\n",
            encoding="utf-8",
        )
        interval, items = _parse_heartbeat_md(path)
        assert interval == 30

    def test_interval_exactly_30_is_accepted(self, tmp_path):
        """Interval of exactly 30 is at the boundary and must be accepted."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "<!-- interval: 30 -->\n- [ ] Check endpoints\n",
            encoding="utf-8",
        )
        interval, _ = _parse_heartbeat_md(path)
        assert interval == 30

    def test_unchecked_items_parsed(self, tmp_path):
        """Lines starting with - [ ] are parsed as checklist items."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "- [ ] Check disk space\n- [ ] Verify API is up\n- [ ] Confirm logs clean\n",
            encoding="utf-8",
        )
        _, items = _parse_heartbeat_md(path)
        assert items == ["Check disk space", "Verify API is up", "Confirm logs clean"]

    def test_checked_items_also_parsed(self, tmp_path):
        """Lines with - [x] (already checked) are also parsed as items."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "- [x] Previously OK item\n- [ ] New item to check\n",
            encoding="utf-8",
        )
        _, items = _parse_heartbeat_md(path)
        assert "Previously OK item" in items
        assert "New item to check" in items
        assert len(items) == 2

    def test_non_checklist_lines_ignored(self, tmp_path):
        """Regular markdown lines and headers are not parsed as items."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "# Heartbeat Checklist\n\nSome description text.\n\n- [ ] Real item\n\n"
            "Another paragraph.\n",
            encoding="utf-8",
        )
        _, items = _parse_heartbeat_md(path)
        assert items == ["Real item"]

    def test_interval_tag_case_insensitive(self, tmp_path):
        """<!-- INTERVAL: 120 --> (uppercase) should be recognized."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "<!-- INTERVAL: 120 -->\n- [ ] Check service\n",
            encoding="utf-8",
        )
        interval, _ = _parse_heartbeat_md(path)
        assert interval == 120

    def test_interval_with_extra_spaces_in_tag(self, tmp_path):
        """<!-- interval:   45   --> with extra whitespace is valid."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "<!--  interval:   45   -->\n- [ ] Check memory\n",
            encoding="utf-8",
        )
        interval, _ = _parse_heartbeat_md(path)
        assert interval == 45

    def test_no_interval_tag_uses_default(self, tmp_path):
        """File without an interval tag uses _DEFAULT_INTERVAL."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "# Heartbeat\n\n- [ ] Check processes\n",
            encoding="utf-8",
        )
        interval, _ = _parse_heartbeat_md(path)
        assert interval == _DEFAULT_INTERVAL

    def test_whitespace_stripped_from_items(self, tmp_path):
        """Leading/trailing whitespace is stripped from item text."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "-  [ ]   Item with extra spaces   \n",
            encoding="utf-8",
        )
        _, items = _parse_heartbeat_md(path)
        assert items[0] == "Item with extra spaces"

    def test_multiple_items_parsed_correctly(self, tmp_path):
        """Three distinct items are all parsed."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text(
            "<!-- interval: 300 -->\n\n"
            "- [ ] Check disk space is above 10%\n"
            "- [ ] Verify monitoring script is running\n"
            "- [ ] Confirm API endpoints return 200\n",
            encoding="utf-8",
        )
        interval, items = _parse_heartbeat_md(path)
        assert interval == 300
        assert len(items) == 3
        assert "Check disk space is above 10%" in items
        assert "Verify monitoring script is running" in items
        assert "Confirm API endpoints return 200" in items

    def test_file_with_only_interval_no_items(self, tmp_path):
        """File with interval but no checklist returns empty items list."""
        path = tmp_path / "HEARTBEAT.md"
        path.write_text("<!-- interval: 60 -->\n\nNo checklist items here.\n", encoding="utf-8")
        interval, items = _parse_heartbeat_md(path)
        assert interval == 60
        assert items == []


# ===========================================================================
# _build_heartbeat_prompt
# ===========================================================================

class TestBuildHeartbeatPrompt:
    """Unit tests for the prompt builder."""

    def test_agent_name_appears_in_prompt(self):
        """The agent name is included in the prompt header."""
        prompt = _build_heartbeat_prompt("my-agent", ["Check disk"])
        assert "my-agent" in prompt

    def test_checklist_items_appear_in_prompt(self):
        """Each checklist item is rendered inside the prompt."""
        items = ["Check disk space", "Verify API", "Confirm logs"]
        prompt = _build_heartbeat_prompt("worker", items)
        for item in items:
            assert item in prompt

    def test_heartbeat_marker_present(self):
        """Prompt begins with [HEARTBEAT CHECK ...] marker."""
        prompt = _build_heartbeat_prompt("agent-1", ["Check something"])
        assert "[HEARTBEAT CHECK" in prompt

    def test_empty_items_list_produces_valid_prompt(self):
        """An empty items list does not crash; prompt still has the header."""
        prompt = _build_heartbeat_prompt("empty-agent", [])
        assert "empty-agent" in prompt
        assert "[HEARTBEAT CHECK" in prompt

    def test_items_formatted_as_unchecked(self):
        """Items are rendered as '- [ ] item' in the checklist block."""
        prompt = _build_heartbeat_prompt("tester", ["Check disk space"])
        assert "- [ ] Check disk space" in prompt

    def test_respond_instruction_present(self):
        """Prompt includes 'Respond with:' instruction for the agent."""
        prompt = _build_heartbeat_prompt("tester", ["Check thing"])
        assert "Respond with:" in prompt


# ===========================================================================
# HeartbeatMonitor._fire
# ===========================================================================

class TestHeartbeatMonitorFire:
    """Tests for _fire() — the gateway injection call."""

    @pytest.mark.asyncio
    async def test_fire_calls_gateway_ingest(self):
        """_fire() calls gateway.ingest with correct session_id and channel."""
        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, Path("/tmp/fake"))

        await monitor._fire("my-agent", ["Check something"])

        mock_gateway.ingest.assert_called_once()
        call_kwargs = mock_gateway.ingest.call_args.kwargs
        assert call_kwargs["session_id"] == "heartbeat-my-agent"
        assert call_kwargs["channel"] == "heartbeat"
        assert call_kwargs["agent_id"] == "my-agent"
        assert "my-agent" in call_kwargs["message"]

    @pytest.mark.asyncio
    async def test_fire_ingest_exception_is_swallowed(self):
        """If gateway.ingest raises, _fire() logs but does not propagate."""
        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock(side_effect=RuntimeError("gateway down"))
        monitor = HeartbeatMonitor(mock_gateway, Path("/tmp/fake"))

        # Must not raise
        await monitor._fire("agent-x", ["Check disk"])

    @pytest.mark.asyncio
    async def test_fire_prompt_includes_all_items(self):
        """Prompt passed to gateway.ingest includes every checklist item."""
        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, Path("/tmp/fake"))

        items = ["Check disk", "Verify API", "Confirm logs"]
        await monitor._fire("agent-y", items)

        message = mock_gateway.ingest.call_args.kwargs["message"]
        for item in items:
            assert item in message


# ===========================================================================
# HeartbeatMonitor._tick
# ===========================================================================

class TestHeartbeatMonitorTick:
    """Tests for _tick() — the periodic polling loop body."""

    @pytest.mark.asyncio
    async def test_tick_no_agents_dir(self, tmp_path):
        """_tick() exits silently when the agents directory does not exist."""
        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)
        # No agents/ subdirectory created
        await monitor._tick()
        mock_gateway.ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_fires_agent_with_elapsed_interval(self, tmp_path):
        """_tick() fires an agent whose interval has elapsed."""
        agents_dir = tmp_path / "agents" / "worker"
        agents_dir.mkdir(parents=True)
        hb = agents_dir / "HEARTBEAT.md"
        hb.write_text(
            "<!-- interval: 60 -->\n- [ ] Check disk\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)
        # last_fire is 0.0 (epoch), so interval definitely elapsed
        monitor._last_fire["worker"] = 0.0

        await monitor._tick()

        mock_gateway.ingest.assert_called_once()
        kwargs = mock_gateway.ingest.call_args.kwargs
        assert kwargs["agent_id"] == "worker"

    @pytest.mark.asyncio
    async def test_tick_skips_agent_not_yet_due(self, tmp_path):
        """_tick() does NOT fire an agent whose interval has not yet elapsed."""
        agents_dir = tmp_path / "agents" / "worker"
        agents_dir.mkdir(parents=True)
        hb = agents_dir / "HEARTBEAT.md"
        hb.write_text(
            "<!-- interval: 300 -->\n- [ ] Check disk\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)
        # Set last_fire to "just now" so interval has NOT elapsed
        monitor._last_fire["worker"] = time.time()

        await monitor._tick()

        mock_gateway.ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_skips_agent_with_no_heartbeat_md(self, tmp_path):
        """_tick() skips agents whose directory has no HEARTBEAT.md."""
        agents_dir = tmp_path / "agents" / "silent-agent"
        agents_dir.mkdir(parents=True)
        # No HEARTBEAT.md created

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        await monitor._tick()

        mock_gateway.ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_skips_agent_with_empty_items(self, tmp_path):
        """_tick() skips agents with HEARTBEAT.md that has no - [ ] items."""
        agents_dir = tmp_path / "agents" / "no-items"
        agents_dir.mkdir(parents=True)
        hb = agents_dir / "HEARTBEAT.md"
        hb.write_text("# Heartbeat\n<!-- interval: 60 -->\n\nNo items here.\n", encoding="utf-8")

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        await monitor._tick()

        mock_gateway.ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_finds_heartbeat_in_workspace_subdir(self, tmp_path):
        """_tick() finds HEARTBEAT.md at agent_dir/workspace/HEARTBEAT.md."""
        workspace_dir = tmp_path / "agents" / "ws-agent" / "workspace"
        workspace_dir.mkdir(parents=True)
        hb = workspace_dir / "HEARTBEAT.md"
        hb.write_text(
            "<!-- interval: 60 -->\n- [ ] Check service\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)
        monitor._last_fire["ws-agent"] = 0.0

        await monitor._tick()

        mock_gateway.ingest.assert_called_once()

    @pytest.mark.asyncio
    async def test_tick_finds_heartbeat_in_flat_layout(self, tmp_path):
        """_tick() falls back to agent_dir/HEARTBEAT.md when workspace/ not found."""
        agent_dir = tmp_path / "agents" / "flat-agent"
        agent_dir.mkdir(parents=True)
        hb = agent_dir / "HEARTBEAT.md"
        hb.write_text(
            "<!-- interval: 60 -->\n- [ ] Check flat\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)
        monitor._last_fire["flat-agent"] = 0.0

        await monitor._tick()

        mock_gateway.ingest.assert_called_once()

    @pytest.mark.asyncio
    async def test_tick_updates_last_fire_after_firing(self, tmp_path):
        """_tick() updates _last_fire[agent] after a successful fire."""
        agents_dir = tmp_path / "agents" / "tracker"
        agents_dir.mkdir(parents=True)
        hb = agents_dir / "HEARTBEAT.md"
        hb.write_text(
            "<!-- interval: 60 -->\n- [ ] Check tracker\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)
        monitor._last_fire["tracker"] = 0.0

        before = time.time()
        await monitor._tick()
        after = time.time()

        assert before <= monitor._last_fire["tracker"] <= after

    @pytest.mark.asyncio
    async def test_tick_multiple_agents_fires_only_due_ones(self, tmp_path):
        """_tick() fires only agents that are due, skips those that are not."""
        for agent, due in [("due-agent", True), ("not-due-agent", False)]:
            d = tmp_path / "agents" / agent
            d.mkdir(parents=True)
            (d / "HEARTBEAT.md").write_text(
                "<!-- interval: 60 -->\n- [ ] Check\n",
                encoding="utf-8",
            )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)
        monitor._last_fire["due-agent"] = 0.0       # very old → due
        monitor._last_fire["not-due-agent"] = time.time()  # just fired → not due

        await monitor._tick()

        assert mock_gateway.ingest.call_count == 1
        fired_agent = mock_gateway.ingest.call_args.kwargs["agent_id"]
        assert fired_agent == "due-agent"

    @pytest.mark.asyncio
    async def test_tick_skips_non_directory_entries(self, tmp_path):
        """_tick() skips files (not dirs) inside the agents directory."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir(parents=True)
        # Put a file (not a directory) in agents/
        (agents_dir / "some-file.txt").write_text("junk", encoding="utf-8")

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        # Must not crash
        await monitor._tick()
        mock_gateway.ingest.assert_not_called()


# ===========================================================================
# HeartbeatMonitor.fire_now
# ===========================================================================

class TestHeartbeatMonitorFireNow:
    """Tests for the manual fire_now() trigger."""

    @pytest.mark.asyncio
    async def test_fire_now_returns_items_on_success(self, tmp_path):
        """fire_now() returns the list of checklist items sent to the agent."""
        agent_dir = tmp_path / "agents" / "my-agent" / "workspace"
        agent_dir.mkdir(parents=True)
        (agent_dir / "HEARTBEAT.md").write_text(
            "- [ ] Check disk\n- [ ] Check memory\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        result = await monitor.fire_now("my-agent")
        assert result == ["Check disk", "Check memory"]
        mock_gateway.ingest.assert_called_once()

    @pytest.mark.asyncio
    async def test_fire_now_returns_none_when_no_heartbeat_md(self, tmp_path):
        """fire_now() returns None when HEARTBEAT.md does not exist."""
        agent_dir = tmp_path / "agents" / "ghost-agent"
        agent_dir.mkdir(parents=True)

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        result = await monitor.fire_now("ghost-agent")
        assert result is None
        mock_gateway.ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_fire_now_returns_empty_list_when_no_items(self, tmp_path):
        """fire_now() returns [] when HEARTBEAT.md has no checklist items."""
        agent_dir = tmp_path / "agents" / "empty-agent" / "workspace"
        agent_dir.mkdir(parents=True)
        (agent_dir / "HEARTBEAT.md").write_text(
            "# Heartbeat\nNo checklist items.\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        result = await monitor.fire_now("empty-agent")
        assert result == []
        mock_gateway.ingest.assert_not_called()

    @pytest.mark.asyncio
    async def test_fire_now_checks_workspace_subdir_first(self, tmp_path):
        """fire_now() checks workspace/HEARTBEAT.md before flat HEARTBEAT.md."""
        # Create both layouts
        ws_dir = tmp_path / "agents" / "dual-agent" / "workspace"
        ws_dir.mkdir(parents=True)
        (ws_dir / "HEARTBEAT.md").write_text(
            "- [ ] Workspace item\n",
            encoding="utf-8",
        )
        # Also flat layout
        flat_dir = tmp_path / "agents" / "dual-agent"
        (flat_dir / "HEARTBEAT.md").write_text(
            "- [ ] Flat item\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        result = await monitor.fire_now("dual-agent")
        # workspace/ is checked first
        assert result == ["Workspace item"]

    @pytest.mark.asyncio
    async def test_fire_now_falls_back_to_flat_layout(self, tmp_path):
        """fire_now() uses flat HEARTBEAT.md when workspace/ layout absent."""
        agent_dir = tmp_path / "agents" / "flat-only"
        agent_dir.mkdir(parents=True)
        (agent_dir / "HEARTBEAT.md").write_text(
            "- [ ] Flat item\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        result = await monitor.fire_now("flat-only")
        assert result == ["Flat item"]

    @pytest.mark.asyncio
    async def test_fire_now_calls_ingest_with_heartbeat_channel(self, tmp_path):
        """fire_now() uses channel='heartbeat' in the gateway.ingest call."""
        agent_dir = tmp_path / "agents" / "chan-agent" / "workspace"
        agent_dir.mkdir(parents=True)
        (agent_dir / "HEARTBEAT.md").write_text(
            "- [ ] Check endpoint\n",
            encoding="utf-8",
        )

        mock_gateway = MagicMock()
        mock_gateway.ingest = AsyncMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        await monitor.fire_now("chan-agent")
        kwargs = mock_gateway.ingest.call_args.kwargs
        assert kwargs["channel"] == "heartbeat"


# ===========================================================================
# HeartbeatMonitor.run_forever
# ===========================================================================

class TestHeartbeatMonitorRunForever:
    """Tests for the main background loop."""

    @pytest.mark.asyncio
    async def test_run_forever_exits_on_cancelled_error(self):
        """run_forever() exits cleanly when the task is cancelled."""
        mock_gateway = MagicMock()
        monitor = HeartbeatMonitor(mock_gateway, Path("/tmp/fake"))

        task = asyncio.create_task(monitor.run_forever())
        # Give it a tiny moment to start the first sleep
        await asyncio.sleep(0)
        task.cancel()
        # Should not raise CancelledError to the caller
        await asyncio.wait_for(asyncio.shield(task), timeout=2.0)

    @pytest.mark.asyncio
    async def test_run_forever_swallows_tick_exceptions(self, tmp_path):
        """Exceptions inside _tick() are caught so the loop continues."""
        mock_gateway = MagicMock()
        monitor = HeartbeatMonitor(mock_gateway, tmp_path)

        call_count = 0

        async def bad_tick():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("simulated tick failure")
            # Cancel after second call so the test terminates
            raise asyncio.CancelledError

        monitor._tick = bad_tick

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            try:
                await monitor.run_forever()
            except asyncio.CancelledError:
                pass

        # The loop must have been entered at least twice (error on 1st, cancel on 2nd)
        assert call_count >= 2
