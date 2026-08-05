"""
tests/test_gateway_skills.py — Unit tests for new Gateway methods added in the
skills/agents/workspace feature set.

Covers:
  1. _list_skills()          — empty dir, valid SKILL.md, missing SKILL.md
  2. _list_agents()          — no agents dir, agent with identity files, without
  3. _list_workspace_files() — empty workspace, .md files present, non-.md ignored
  4. _read_workspace_file()  — agent-specific found, fallback to global, missing
  5. _write_workspace_file() — correct write, creates dir if missing
  6. _delete_skill()         — deletes existing dir, graceful on missing
  7. WS handler routing      — each new message type dispatched and replied correctly
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.config import CatoConfig
from cato.gateway import Gateway


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gateway(tmp_path: Path) -> Gateway:
    """Construct a minimal Gateway with mocked config, budget, and vault."""
    cfg = CatoConfig()
    cfg.workspace_dir = str(tmp_path / "workspace")
    cfg.agent_name = "test-agent"

    budget = MagicMock()
    budget.format_footer.return_value = ""

    vault = MagicMock()

    gw = Gateway(config=cfg, budget=budget, vault=vault)
    return gw


def _make_ws() -> MagicMock:
    """Return a mock WebSocket simulating aiohttp WebSocketResponse (uses send_str)."""
    ws = MagicMock(spec=["send_str"])
    ws.send_str = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# 1. _list_skills()
# ---------------------------------------------------------------------------

class TestListSkills:
    """Unit tests for Gateway._list_skills()."""

    def test_empty_skills_dir_returns_empty_list(self, tmp_path):
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            result = gw._list_skills()

        assert result == []

    def test_skill_dir_with_skill_md_returned(self, tmp_path):
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "# My Awesome Skill\nversion: 1.2.3\n\nDoes cool things.\n",
            encoding="utf-8",
        )

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            result = gw._list_skills()

        assert len(result) == 1
        s = result[0]
        assert s["name"] == "My Awesome Skill"
        assert s["version"] == "1.2.3"
        assert s["dir"] == "my-skill"
        assert "Does cool things." in s["content"]

    def test_skill_dir_with_lowercase_skill_md_returned(self, tmp_path):
        """Fallback: skill.md (lowercase) is also recognised."""
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "lower-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "# Lower Skill\nversion: 0.1\n\nLowercase file.\n",
            encoding="utf-8",
        )

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            result = gw._list_skills()

        assert len(result) == 1
        assert result[0]["name"] == "Lower Skill"

    def test_skill_dir_without_skill_md_still_listed(self, tmp_path):
        """A skill subdirectory without any SKILL.md is still listed (name = dir name)."""
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "bare-skill"
        skill_dir.mkdir(parents=True)
        # No SKILL.md file at all

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            result = gw._list_skills()

        assert len(result) == 1
        assert result[0]["name"] == "bare-skill"
        assert result[0]["content"] == ""
        assert result[0]["description"] == ""

    def test_multiple_skills_all_listed(self, tmp_path):
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        for name in ("alpha", "beta", "gamma"):
            d = skills_root / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"# {name}\nversion: 1.0\n\n{name} skill.\n",
                                        encoding="utf-8")

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            result = gw._list_skills()

        names = {s["dir"] for s in result}
        assert names == {"alpha", "beta", "gamma"}

    def test_non_directory_entries_in_skills_root_ignored(self, tmp_path):
        """Plain files in the skills root are skipped."""
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)
        (skills_root / "README.txt").write_text("not a skill dir", encoding="utf-8")

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            result = gw._list_skills()

        assert result == []

    def test_skill_description_from_blockquote_line(self, tmp_path):
        """Lines starting with '> ' are used as description."""
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "quoted"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "# Quoted Skill\n> A brief description\nversion: 2.0\n",
            encoding="utf-8",
        )

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            result = gw._list_skills()

        assert result[0]["description"] == "A brief description"

    def test_skill_result_has_required_keys(self, tmp_path):
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        (skills_root / "sk").mkdir(parents=True)

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            result = gw._list_skills()

        for key in ("name", "description", "version", "dir", "content"):
            assert key in result[0], f"Missing key: {key}"


# ---------------------------------------------------------------------------
# 2. _list_agents()
# ---------------------------------------------------------------------------

class TestListAgents:
    """Unit tests for Gateway._list_agents()."""

    def test_no_agents_dir_returns_empty_list(self, tmp_path):
        gw = _make_gateway(tmp_path)
        # agents_dir does NOT exist
        agents_root = tmp_path / "nonexistent_agents"

        with patch.object(gw, "_agents_dir", return_value=agents_root):
            result = gw._list_agents()

        assert result == []

    def test_agent_with_identity_files_in_workspace_subdir(self, tmp_path):
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agent_ws = agents_root / "my-agent" / "workspace"
        agent_ws.mkdir(parents=True)
        (agent_ws / "SOUL.md").write_text("soul content", encoding="utf-8")
        (agent_ws / "MEMORY.md").write_text("memory content", encoding="utf-8")
        (agent_ws / "notes.txt").write_text("ignored", encoding="utf-8")

        with patch.object(gw, "_agents_dir", return_value=agents_root):
            result = gw._list_agents()

        assert len(result) == 1
        agent = result[0]
        assert agent["id"] == "my-agent"
        assert "SOUL.md" in agent["identity_files"]
        assert "MEMORY.md" in agent["identity_files"]
        assert "notes.txt" not in agent["identity_files"]

    def test_agent_without_workspace_subdir_uses_flat_layout(self, tmp_path):
        """When no workspace/ subdir exists, identity files are read from agent dir itself."""
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agent_dir = agents_root / "flat-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "IDENTITY.md").write_text("identity content", encoding="utf-8")

        with patch.object(gw, "_agents_dir", return_value=agents_root):
            result = gw._list_agents()

        assert len(result) == 1
        agent = result[0]
        assert agent["id"] == "flat-agent"
        assert "IDENTITY.md" in agent["identity_files"]

    def test_agent_without_identity_files_still_listed(self, tmp_path):
        """An agent dir with no recognised identity .md files is included with empty list."""
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agent_ws = agents_root / "empty-agent" / "workspace"
        agent_ws.mkdir(parents=True)
        (agent_ws / "random.md").write_text("not identity", encoding="utf-8")

        with patch.object(gw, "_agents_dir", return_value=agents_root):
            result = gw._list_agents()

        assert len(result) == 1
        assert result[0]["identity_files"] == []

    def test_multiple_agents_all_returned(self, tmp_path):
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        for name in ("alpha", "beta"):
            d = agents_root / name
            d.mkdir(parents=True)
            (d / "SOUL.md").write_text("soul", encoding="utf-8")

        with patch.object(gw, "_agents_dir", return_value=agents_root):
            result = gw._list_agents()

        ids = {a["id"] for a in result}
        assert ids == {"alpha", "beta"}

    def test_non_directory_entries_in_agents_dir_ignored(self, tmp_path):
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agents_root.mkdir(parents=True)
        (agents_root / "stray_file.txt").write_text("not an agent", encoding="utf-8")

        with patch.object(gw, "_agents_dir", return_value=agents_root):
            result = gw._list_agents()

        assert result == []

    def test_agent_result_has_required_keys(self, tmp_path):
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        (agents_root / "agent-x").mkdir(parents=True)

        with patch.object(gw, "_agents_dir", return_value=agents_root):
            result = gw._list_agents()

        for key in ("id", "workspace", "identity_files"):
            assert key in result[0], f"Missing key: {key}"


# ---------------------------------------------------------------------------
# 3. _list_workspace_files()
# ---------------------------------------------------------------------------

class TestListWorkspaceFiles:
    """Unit tests for Gateway._list_workspace_files()."""

    def test_nonexistent_workspace_returns_empty_dict(self, tmp_path):
        gw = _make_gateway(tmp_path)
        missing_ws = tmp_path / "does_not_exist"

        with patch.object(gw, "_workspace_dir", return_value=missing_ws):
            result = gw._list_workspace_files()

        assert result == {}

    def test_empty_workspace_returns_empty_dict(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = tmp_path / "workspace"
        ws.mkdir(parents=True)

        with patch.object(gw, "_workspace_dir", return_value=ws):
            result = gw._list_workspace_files()

        assert result == {}

    def test_md_files_returned_with_content(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = tmp_path / "workspace"
        ws.mkdir(parents=True)
        (ws / "MEMORY.md").write_text("agent memory here", encoding="utf-8")
        (ws / "NOTES.md").write_text("some notes", encoding="utf-8")

        with patch.object(gw, "_workspace_dir", return_value=ws):
            result = gw._list_workspace_files()

        assert "MEMORY.md" in result
        assert result["MEMORY.md"] == "agent memory here"
        assert "NOTES.md" in result
        assert result["NOTES.md"] == "some notes"

    def test_non_md_files_are_ignored(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = tmp_path / "workspace"
        ws.mkdir(parents=True)
        (ws / "notes.txt").write_text("text file", encoding="utf-8")
        (ws / "data.json").write_text("{}", encoding="utf-8")
        (ws / "legit.md").write_text("markdown", encoding="utf-8")

        with patch.object(gw, "_workspace_dir", return_value=ws):
            result = gw._list_workspace_files()

        assert list(result.keys()) == ["legit.md"]
        assert "notes.txt" not in result
        assert "data.json" not in result

    def test_returns_dict_not_list(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "file.md").write_text("content", encoding="utf-8")

        with patch.object(gw, "_workspace_dir", return_value=ws):
            result = gw._list_workspace_files()

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 4. _read_workspace_file()
# ---------------------------------------------------------------------------

class TestReadWorkspaceFile:
    """Unit tests for Gateway._read_workspace_file()."""

    def test_reads_file_from_agent_workspace_subdir(self, tmp_path):
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agent_ws = agents_root / "agent-1" / "workspace"
        agent_ws.mkdir(parents=True)
        (agent_ws / "SOUL.md").write_text("soul content", encoding="utf-8")

        with patch.object(gw, "_agents_dir", return_value=agents_root):
            result = gw._read_workspace_file("agent-1", "SOUL.md")

        assert result == "soul content"

    def test_reads_file_from_agent_flat_dir(self, tmp_path):
        """Falls back to agent_dir/filename when workspace/filename is absent."""
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agent_dir = agents_root / "flat-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "IDENTITY.md").write_text("identity content", encoding="utf-8")

        with patch.object(gw, "_agents_dir", return_value=agents_root):
            result = gw._read_workspace_file("flat-agent", "IDENTITY.md")

        assert result == "identity content"

    def test_falls_back_to_global_workspace(self, tmp_path):
        """When neither agent path exists, reads from global workspace dir."""
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agents_root.mkdir(parents=True)  # exists but no agent dir inside
        global_ws = tmp_path / "global_workspace"
        global_ws.mkdir(parents=True)
        (global_ws / "MEMORY.md").write_text("global memory", encoding="utf-8")

        with patch.object(gw, "_agents_dir", return_value=agents_root), \
             patch.object(gw, "_workspace_dir", return_value=global_ws):
            result = gw._read_workspace_file("no-such-agent", "MEMORY.md")

        assert result == "global memory"

    def test_returns_empty_string_when_file_not_found_anywhere(self, tmp_path):
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agents_root.mkdir(parents=True)
        global_ws = tmp_path / "global_workspace"
        global_ws.mkdir(parents=True)
        # File does NOT exist in either location

        with patch.object(gw, "_agents_dir", return_value=agents_root), \
             patch.object(gw, "_workspace_dir", return_value=global_ws):
            result = gw._read_workspace_file("ghost-agent", "NONEXISTENT.md")

        assert result == ""

    def test_agent_workspace_takes_priority_over_global(self, tmp_path):
        """Agent-specific workspace file shadows the global one."""
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agent_ws = agents_root / "priority-agent" / "workspace"
        agent_ws.mkdir(parents=True)
        (agent_ws / "MEMORY.md").write_text("agent memory", encoding="utf-8")
        global_ws = tmp_path / "global_workspace"
        global_ws.mkdir(parents=True)
        (global_ws / "MEMORY.md").write_text("global memory", encoding="utf-8")

        with patch.object(gw, "_agents_dir", return_value=agents_root), \
             patch.object(gw, "_workspace_dir", return_value=global_ws):
            result = gw._read_workspace_file("priority-agent", "MEMORY.md")

        assert result == "agent memory"


# ---------------------------------------------------------------------------
# 5. _write_workspace_file()
# ---------------------------------------------------------------------------

class TestWriteWorkspaceFile:
    """Unit tests for Gateway._write_workspace_file()."""

    def test_writes_content_to_workspace(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = tmp_path / "workspace"
        # Do NOT pre-create ws — write should create it

        with patch.object(gw, "_workspace_dir", return_value=ws):
            gw._write_workspace_file("NOTES.md", "my notes content")

        written = (ws / "NOTES.md").read_text(encoding="utf-8")
        assert written == "my notes content"

    def test_creates_workspace_dir_if_missing(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = tmp_path / "deep" / "workspace"
        assert not ws.exists()

        with patch.object(gw, "_workspace_dir", return_value=ws):
            gw._write_workspace_file("FILE.md", "content")

        assert ws.exists()
        assert (ws / "FILE.md").exists()

    def test_overwrites_existing_file(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = tmp_path / "workspace"
        ws.mkdir(parents=True)
        (ws / "MEMORY.md").write_text("old content", encoding="utf-8")

        with patch.object(gw, "_workspace_dir", return_value=ws):
            gw._write_workspace_file("MEMORY.md", "new content")

        assert (ws / "MEMORY.md").read_text(encoding="utf-8") == "new content"

    def test_write_empty_content(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = tmp_path / "workspace"

        with patch.object(gw, "_workspace_dir", return_value=ws):
            gw._write_workspace_file("EMPTY.md", "")

        assert (ws / "EMPTY.md").read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# 6. _delete_skill()
# ---------------------------------------------------------------------------

class TestDeleteSkill:
    """Unit tests for Gateway._delete_skill()."""

    def test_deletes_existing_skill_directory(self, tmp_path):
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "to-delete"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# To Delete\n", encoding="utf-8")

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            gw._delete_skill("to-delete")

        assert not skill_dir.exists()

    def test_delete_nonexistent_skill_does_not_raise(self, tmp_path):
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            # Must not raise any exception
            gw._delete_skill("ghost-skill")

    def test_delete_only_removes_target_skill(self, tmp_path):
        """Other skill directories are left untouched."""
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        for name in ("keeper", "to-delete"):
            (skills_root / name).mkdir(parents=True)

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            gw._delete_skill("to-delete")

        assert not (skills_root / "to-delete").exists()
        assert (skills_root / "keeper").exists()

    def test_delete_matches_by_directory_name(self, tmp_path):
        """_delete_skill matches on skill_dir.name, NOT on the # header in SKILL.md."""
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "dir-name"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Friendly Name\n", encoding="utf-8")

        with patch.object(gw, "_skills_dir", return_value=skills_root):
            # Must use the directory name, not the header name
            gw._delete_skill("dir-name")

        assert not skill_dir.exists()


# ---------------------------------------------------------------------------
# 7. WebSocket handler routing — new message types
# ---------------------------------------------------------------------------

class TestWsHandlerRouting:
    """
    Verify that _handle_ws_message() correctly routes each new message type
    and sends the expected response back through the WebSocket.

    All domain methods (_list_skills, _list_agents, etc.) are mocked so that
    these tests exercise ONLY the routing/dispatch layer.
    """

    @pytest.mark.asyncio
    async def test_skill_list_routing(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()
        fake_skills = [{"name": "S", "description": "", "version": "", "dir": "s", "content": ""}]

        with patch.object(gw, "_list_skills", return_value=fake_skills):
            await gw._handle_ws_message(ws, json.dumps({"type": "skill_list"}))

        ws.send_str.assert_called_once()
        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "skill_list_result"
        assert reply["skills"] == fake_skills

    @pytest.mark.asyncio
    async def test_skill_install_routing_success(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()
        fake_skill = {"name": "New", "description": "", "version": "", "dir": "new", "content": ""}

        with patch.object(gw, "_install_skill_from_url", new=AsyncMock(return_value=fake_skill)):
            await gw._handle_ws_message(ws, json.dumps({"type": "skill_install",
                                                         "url": "https://example.com/skill.git"}))

        ws.send_str.assert_called_once()
        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "skill_installed"
        assert reply["skill"] == fake_skill

    @pytest.mark.asyncio
    async def test_skill_install_routing_failure(self, tmp_path):
        """When _install_skill_from_url returns None, an error is sent."""
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        with patch.object(gw, "_install_skill_from_url", new=AsyncMock(return_value=None)):
            await gw._handle_ws_message(ws, json.dumps({"type": "skill_install",
                                                         "url": "https://bad.example.com/broken"}))

        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "error"
        assert "Failed to install" in reply["text"]

    @pytest.mark.asyncio
    async def test_skill_install_missing_url_returns_error(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        await gw._handle_ws_message(ws, json.dumps({"type": "skill_install"}))

        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "error"
        assert "url" in reply["text"].lower()

    @pytest.mark.asyncio
    async def test_skill_delete_routing(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        with patch.object(gw, "_delete_skill") as mock_delete:
            await gw._handle_ws_message(ws, json.dumps({"type": "skill_delete",
                                                         "name": "old-skill"}))

        mock_delete.assert_called_once_with("old-skill")
        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "skill_deleted"
        assert reply["name"] == "old-skill"

    @pytest.mark.asyncio
    async def test_skill_delete_missing_name_returns_error(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        await gw._handle_ws_message(ws, json.dumps({"type": "skill_delete"}))

        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "error"
        assert "name" in reply["text"].lower()

    @pytest.mark.asyncio
    async def test_agent_list_routing(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()
        fake_agents = [{"id": "agent-1", "workspace": "/tmp/ws", "identity_files": ["SOUL.md"]}]

        with patch.object(gw, "_list_agents", return_value=fake_agents):
            await gw._handle_ws_message(ws, json.dumps({"type": "agent_list"}))

        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "agent_list_result"
        assert reply["agents"] == fake_agents

    @pytest.mark.asyncio
    async def test_workspace_files_routing(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()
        fake_files = {"MEMORY.md": "content", "SOUL.md": "identity"}

        with patch.object(gw, "_list_workspace_files", return_value=fake_files):
            await gw._handle_ws_message(ws, json.dumps({"type": "workspace_files"}))

        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "workspace_files_result"
        assert reply["files"] == fake_files

    @pytest.mark.asyncio
    async def test_workspace_file_get_routing(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        with patch.object(gw, "_read_workspace_file", return_value="file content") as mock_read:
            await gw._handle_ws_message(ws, json.dumps({
                "type": "workspace_file_get",
                "agent_id": "my-agent",
                "filename": "MEMORY.md",
            }))

        mock_read.assert_called_once_with("my-agent", "MEMORY.md")
        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "workspace_file_result"
        assert reply["name"] == "MEMORY.md"
        assert reply["content"] == "file content"

    @pytest.mark.asyncio
    async def test_workspace_file_get_uses_default_agent_id(self, tmp_path):
        """When agent_id is omitted, config.agent_name is used."""
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        with patch.object(gw, "_read_workspace_file", return_value="") as mock_read:
            await gw._handle_ws_message(ws, json.dumps({
                "type": "workspace_file_get",
                "filename": "SOUL.md",
            }))

        # agent_id should default to gw._cfg.agent_name ("test-agent")
        mock_read.assert_called_once_with("test-agent", "SOUL.md")

    @pytest.mark.asyncio
    async def test_workspace_file_save_routing(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        with patch.object(gw, "_write_workspace_file") as mock_write:
            await gw._handle_ws_message(ws, json.dumps({
                "type": "workspace_file_save",
                "filename": "NOTES.md",
                "content": "new notes",
            }))

        mock_write.assert_called_once_with("NOTES.md", "new notes")
        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "workspace_file_saved"
        assert reply["filename"] == "NOTES.md"

    @pytest.mark.asyncio
    async def test_workspace_file_save_missing_filename_returns_error(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        await gw._handle_ws_message(ws, json.dumps({
            "type": "workspace_file_save",
            "content": "some content",
        }))

        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "error"
        assert "filename" in reply["text"].lower()

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        await gw._handle_ws_message(ws, "not valid json {{")

        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "error"
        assert "invalid" in reply["text"].lower()

    @pytest.mark.asyncio
    async def test_unknown_message_type_returns_error(self, tmp_path):
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        await gw._handle_ws_message(ws, json.dumps({"type": "completely_unknown_type"}))

        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "error"
        assert "unknown" in reply["text"].lower()

    @pytest.mark.asyncio
    async def test_workspace_file_save_empty_content_allowed(self, tmp_path):
        """Saving an empty string to a file is valid — content is optional."""
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        with patch.object(gw, "_write_workspace_file") as mock_write:
            await gw._handle_ws_message(ws, json.dumps({
                "type": "workspace_file_save",
                "filename": "EMPTY.md",
                "content": "",
            }))

        mock_write.assert_called_once_with("EMPTY.md", "")
        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "workspace_file_saved"


# ---------------------------------------------------------------------------
# 8. _skills_dir() and _workspace_dir() — path helpers
# ---------------------------------------------------------------------------

class TestPathHelpers:
    """Minimal tests for the directory-returning helpers."""

    def test_skills_dir_creates_and_returns_path(self, tmp_path, monkeypatch):
        """_skills_dir() returns ~/.cato/skills and creates it if absent."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        gw = _make_gateway(tmp_path)
        result = gw._skills_dir()
        assert result == tmp_path / ".cato" / "skills"
        assert result.exists()

    def test_workspace_dir_uses_config_workspace_dir(self, tmp_path):
        """_workspace_dir() returns config.workspace_dir when set."""
        gw = _make_gateway(tmp_path)
        custom_ws = tmp_path / "custom_ws"
        gw._cfg.workspace_dir = str(custom_ws)
        result = gw._workspace_dir()
        assert result == custom_ws

    def test_workspace_dir_falls_back_to_home_cato(self, tmp_path, monkeypatch):
        """When config.workspace_dir is empty, returns ~/.cato/workspace."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        gw = _make_gateway(tmp_path)
        gw._cfg.workspace_dir = ""
        result = gw._workspace_dir()
        assert result == tmp_path / ".cato" / "workspace"

    def test_agents_dir_returns_home_cato_agents(self, tmp_path, monkeypatch):
        """_agents_dir() always returns ~/.cato/agents."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        gw = _make_gateway(tmp_path)
        result = gw._agents_dir()
        assert result == tmp_path / ".cato" / "agents"


# ---------------------------------------------------------------------------
# 9. Bug fix tests — _ws_broadcast, _install_skill_from_url, _list_agents
# ---------------------------------------------------------------------------

class TestWsBroadcastClientTypeDetection:
    """
    Bug 1: _ws_broadcast must dispatch to send_str() for aiohttp-style clients
    and to send() for raw-websockets-style clients.  Dead clients must be
    evicted from _ws_clients on exception.
    """

    @pytest.mark.asyncio
    async def test_aiohttp_client_uses_send_str(self, tmp_path):
        """Client with send_str attribute → send_str(raw) is called, send() is not."""
        gw = _make_gateway(tmp_path)

        # aiohttp-style WebSocketResponse: has send_str, no send
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()

        gw._ws_clients.add(ws)
        await gw._ws_broadcast({"type": "ping"})

        ws.send_str.assert_called_once()
        raw_arg = ws.send_str.call_args.args[0]
        assert json.loads(raw_arg)["type"] == "ping"

    @pytest.mark.asyncio
    async def test_raw_websockets_client_uses_send(self, tmp_path):
        """Client without send_str (raw websockets) → send(raw) is called."""
        gw = _make_gateway(tmp_path)

        # raw-websockets-style: has send, no send_str
        ws = MagicMock(spec=["send"])
        ws.send = AsyncMock()

        gw._ws_clients.add(ws)
        await gw._ws_broadcast({"type": "pong"})

        ws.send.assert_called_once()
        raw_arg = ws.send.call_args.args[0]
        assert json.loads(raw_arg)["type"] == "pong"

    @pytest.mark.asyncio
    async def test_dead_aiohttp_client_removed_on_exception(self, tmp_path):
        """When send_str() raises, the dead client is evicted from _ws_clients."""
        gw = _make_gateway(tmp_path)

        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock(side_effect=RuntimeError("connection closed"))

        gw._ws_clients.add(ws)
        # Must not raise despite the client error
        await gw._ws_broadcast({"type": "response", "text": "hello"})

        assert ws not in gw._ws_clients


class TestInstallSkillFromUrlGitRmtree:
    """
    Bug 4: _install_skill_from_url must call shutil.rmtree on an existing dest
    dir before git-cloning, so that reinstalling a skill works cleanly.
    """

    @pytest.mark.asyncio
    async def test_existing_dest_dir_removed_before_git_clone(self, tmp_path):
        """
        When dest already exists and the URL is a git repo (not .md),
        shutil.rmtree must be called before the clone subprocess is launched.
        """
        gw = _make_gateway(tmp_path)
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)

        # Pre-create the destination directory to simulate a previous install
        dest = skills_root / "my-skill"
        dest.mkdir(parents=True)
        (dest / "stale.txt").write_text("old content", encoding="utf-8")

        rmtree_calls: list = []

        async def fake_subprocess(*args, **kwargs):
            proc = MagicMock()
            proc.returncode = 0
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch.object(gw, "_skills_dir", return_value=skills_root), \
             patch("shutil.rmtree", side_effect=lambda p, **kw: rmtree_calls.append(p)) as mock_rmtree, \
             patch("asyncio.create_subprocess_exec", new=fake_subprocess), \
             patch.object(gw, "_list_skills", return_value=[]):
            await gw._install_skill_from_url("https://example.com/my-skill")

        assert len(rmtree_calls) == 1, "shutil.rmtree should be called exactly once"
        assert rmtree_calls[0] == dest


class TestListAgentsWorkspaceOSError:
    """
    Bug 6: _list_agents must not propagate OSError from workspace.iterdir().
    Instead it logs a warning and sets identity_files to [] for that agent.
    """

    def test_oserror_in_iterdir_does_not_raise(self, tmp_path):
        """
        When workspace.iterdir() raises OSError, _list_agents must still
        return the agent entry (with empty identity_files) rather than raising.

        Strategy: create the agent dir with a workspace/ subdir on disk so the
        outer agents_dir.iterdir() works normally.  Then monkeypatch iterdir()
        only on the specific workspace Path object so only that call raises.
        """
        gw = _make_gateway(tmp_path)
        agents_root = tmp_path / "agents"
        agent_dir = agents_root / "broken-agent"
        workspace_dir = agent_dir / "workspace"
        workspace_dir.mkdir(parents=True)

        # Intercept Path.__truediv__ so that when _list_agents constructs
        # agent_dir / "workspace" it gets back a Path whose iterdir() raises.
        real_truediv = Path.__truediv__

        def patched_truediv(self, other):
            result = real_truediv(self, other)
            if str(result) == str(workspace_dir):
                # Return a mock that looks like workspace_dir but raises on iterdir
                m = MagicMock(spec=Path)
                m.__str__ = lambda s: str(workspace_dir)
                m.exists.return_value = True
                m.iterdir.side_effect = OSError("Permission denied")
                return m
            return result

        with patch.object(gw, "_agents_dir", return_value=agents_root), \
             patch.object(Path, "__truediv__", patched_truediv):
            # Must not raise
            result = gw._list_agents()

        assert len(result) == 1
        agent = result[0]
        assert agent["id"] == "broken-agent"
        assert agent["identity_files"] == []


# ---------------------------------------------------------------------------
# 10. Bug-fix tests for R1–R4
# ---------------------------------------------------------------------------

class TestWsSend:
    """
    R1: _ws_send() static helper must route to send_str() for aiohttp-style
    WebSocket objects and to send() for raw-websockets-style objects.
    """

    @pytest.mark.asyncio
    async def test_ws_send_uses_send_str_for_aiohttp(self, tmp_path):
        """When ws has send_str, _ws_send calls send_str with the JSON string."""
        gw = _make_gateway(tmp_path)
        # aiohttp-style: only has send_str
        ws = MagicMock(spec=["send_str"])
        ws.send_str = AsyncMock()

        payload = {"type": "ping", "data": 42}
        await gw._ws_send(ws, payload)

        ws.send_str.assert_called_once()
        sent_arg = ws.send_str.call_args.args[0]
        assert json.loads(sent_arg) == payload

    @pytest.mark.asyncio
    async def test_ws_send_uses_send_for_raw_websockets(self, tmp_path):
        """When ws has no send_str (raw websockets library), _ws_send calls send."""
        gw = _make_gateway(tmp_path)
        # raw-websockets-style: only has send
        ws = MagicMock(spec=["send"])
        ws.send = AsyncMock()

        payload = {"type": "pong", "value": "hello"}
        await gw._ws_send(ws, payload)

        ws.send.assert_called_once()
        sent_arg = ws.send.call_args.args[0]
        assert json.loads(sent_arg) == payload


class TestListAgentsOuterOSError:
    """
    R2: _list_agents outer loop — agents_dir.iterdir() wrapped in try/except OSError.
    When iterdir() raises on the agents directory itself, must return [] without raising.
    """

    def test_list_agents_outer_oserror_returns_empty(self, tmp_path):
        """
        Patch agents_dir.iterdir() to raise OSError; _list_agents must return []
        without propagating the exception.
        """
        gw = _make_gateway(tmp_path)
        # Create the agents dir so the exists() check passes
        agents_root = tmp_path / "agents"
        agents_root.mkdir(parents=True)

        # Use Path.__truediv__ to intercept the exact agents_root object and make
        # its iterdir() raise, while agents_root.exists() still returns True.
        real_truediv = Path.__truediv__

        def patched_truediv(self, other):
            result = real_truediv(self, other)
            # Match only the agents_root path
            if str(result) == str(agents_root):
                m = MagicMock(spec=Path)
                m.exists.return_value = True
                m.iterdir.side_effect = OSError("Permission denied on agents dir")
                return m
            return result

        # We patch _agents_dir to return agents_root normally, and separately
        # patch iterdir on the Path returned by _agents_dir.
        real_agents_dir = gw._agents_dir

        def mock_agents_dir():
            m = MagicMock(spec=Path)
            m.exists.return_value = True
            m.iterdir.side_effect = OSError("Permission denied on agents dir")
            return m

        with patch.object(gw, "_agents_dir", side_effect=mock_agents_dir):
            result = gw._list_agents()

        assert result == []


class TestWorkspaceFileSaveOSError:
    """
    R3: workspace_file_save WS handler wraps _write_workspace_file in try/except OSError.
    On failure, sends {"type": "error", "text": "Could not save file: ..."}.
    """

    @pytest.mark.asyncio
    async def test_workspace_file_save_oserror_sends_error_message(self, tmp_path):
        """
        When _write_workspace_file raises OSError, the handler must send an
        error reply whose text contains the original error message.
        """
        gw = _make_gateway(tmp_path)
        ws = _make_ws()

        with patch.object(
            gw, "_write_workspace_file", side_effect=OSError("disk full")
        ):
            await gw._handle_ws_message(ws, json.dumps({
                "type": "workspace_file_save",
                "filename": "NOTES.md",
                "content": "some content",
            }))

        ws.send_str.assert_called_once()
        reply = json.loads(ws.send_str.call_args.args[0])
        assert reply["type"] == "error"
        # The error text must reference the failure (either the message or "Could not save")
        assert "disk full" in reply["text"] or "Could not save" in reply["text"]


class TestListWorkspaceFilesOuterOSError:
    """
    R4: _list_workspace_files outer loop — ws.iterdir() wrapped in try/except OSError.
    When iterdir() raises on the workspace directory itself, must return {} without raising.
    """

    def test_list_workspace_files_outer_oserror_returns_empty(self, tmp_path):
        """
        Create a real workspace dir, then patch its iterdir() to raise OSError.
        _list_workspace_files must return {} without propagating the exception.
        """
        gw = _make_gateway(tmp_path)
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir(parents=True)

        # Build a mock that mimics the workspace Path but raises on iterdir()
        def mock_workspace_dir():
            m = MagicMock(spec=Path)
            m.exists.return_value = True
            m.iterdir.side_effect = OSError("I/O error reading workspace")
            return m

        with patch.object(gw, "_workspace_dir", side_effect=mock_workspace_dir):
            result = gw._list_workspace_files()

        assert result == {}
