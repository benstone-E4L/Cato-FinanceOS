"""File tool security and functionality tests."""
import json
import pytest
import asyncio
from pathlib import Path
from cato.tools.file import FileTool


@pytest.mark.asyncio
async def test_path_traversal_blocked(tmp_path):
    tool = FileTool()
    # Attempt path traversal
    raw = await tool.execute({"action": "read", "path": "../../etc/passwd", "agent_id": "test"})
    result = json.loads(raw)
    assert result.get("success") is False or "error" in result


@pytest.mark.asyncio
async def test_valid_read_write(tmp_path, monkeypatch):
    # BH-010 — the file tool no longer exposes a `_WORKSPACE_ROOT` module
    # constant; it reads `CATO_WORKSPACE_DIR` at call time via the
    # `_workspace_root()` helper.  Monkeypatch the env var so the tool
    # writes into the pytest tmp_path instead of the operator's real
    # workspace.
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    tool = FileTool()
    # Write then read
    write_raw = await tool.execute({"action": "write", "path": "test.txt", "content": "hello", "agent_id": "test"})
    write_result = json.loads(write_raw)
    assert write_result.get("success") is True
    read_raw = await tool.execute({"action": "read", "path": "test.txt", "agent_id": "test"})
    read_result = json.loads(read_raw)
    assert "hello" in read_result.get("content", "")
    # Also verify the file actually landed under tmp_path/main/, proving the
    # env-var bridge worked (regression lock against the BH-010 fix being
    # undone in the future).
    written_file = tmp_path / "test" / "test.txt"
    assert written_file.exists(), f"expected file at {written_file}"
    assert written_file.read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_path_traversal_dotdot_blocked(tmp_path, monkeypatch):
    """../../etc/passwd style paths must be rejected by the file tool."""
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    tool = FileTool()
    raw = await tool.execute({"action": "read", "path": "../../etc/passwd", "agent_id": "test"})
    result = json.loads(raw)
    assert result.get("success") is False
    assert "traversal" in (result.get("error") or "").lower()


@pytest.mark.asyncio
async def test_path_traversal_windows_blocked(tmp_path, monkeypatch):
    """..\\..\\Windows\\System32 style paths must be rejected on all platforms."""
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    tool = FileTool()
    raw = await tool.execute({"action": "read", "path": "..\\..\\Windows\\System32", "agent_id": "test"})
    result = json.loads(raw)
    assert result.get("success") is False
    assert "traversal" in (result.get("error") or "").lower()


# ---------------------------------------------------------------------------
# patch action — workspace root
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_basic(tmp_path, monkeypatch):
    """patch replaces old_string with new_string in a workspace file."""
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    tool = FileTool()
    await tool.execute({"action": "write", "path": "script.py", "content": 'log(hello)\nprint("world")\n', "agent_id": "test"})
    raw = await tool.execute({
        "action": "patch", "path": "script.py", "agent_id": "test",
        "old_string": "log(hello)", "new_string": 'log("hello")',
    })
    result = json.loads(raw)
    assert result["success"] is True
    assert result["replacements"] == 1
    read = json.loads(await tool.execute({"action": "read", "path": "script.py", "agent_id": "test"}))
    assert 'log("hello")' in read["content"]


@pytest.mark.asyncio
async def test_patch_no_match_fails_loudly(tmp_path, monkeypatch):
    """patch must return success=False with a clear error when old_string is not found."""
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    tool = FileTool()
    await tool.execute({"action": "write", "path": "f.txt", "content": "hello world", "agent_id": "test"})
    raw = await tool.execute({
        "action": "patch", "path": "f.txt", "agent_id": "test",
        "old_string": "this text does not exist", "new_string": "x",
    })
    result = json.loads(raw)
    assert result["success"] is False
    assert "not found" in (result.get("error") or "").lower()


@pytest.mark.asyncio
async def test_patch_ambiguous_fails_loudly(tmp_path, monkeypatch):
    """patch must refuse when old_string appears more than once (without replace_all)."""
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    tool = FileTool()
    await tool.execute({"action": "write", "path": "f.txt", "content": "foo\nfoo\n", "agent_id": "test"})
    raw = await tool.execute({
        "action": "patch", "path": "f.txt", "agent_id": "test",
        "old_string": "foo", "new_string": "bar",
    })
    result = json.loads(raw)
    assert result["success"] is False
    assert "2" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_patch_replace_all(tmp_path, monkeypatch):
    """patch with replace_all=True replaces every occurrence."""
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    tool = FileTool()
    await tool.execute({"action": "write", "path": "f.txt", "content": "foo\nfoo\nfoo\n", "agent_id": "test"})
    raw = await tool.execute({
        "action": "patch", "path": "f.txt", "agent_id": "test",
        "old_string": "foo", "new_string": "bar", "replace_all": True,
    })
    result = json.loads(raw)
    assert result["success"] is True
    assert result["replacements"] == 3
    read = json.loads(await tool.execute({"action": "read", "path": "f.txt", "agent_id": "test"}))
    assert "foo" not in read["content"]
    assert read["content"].count("bar") == 3


@pytest.mark.asyncio
async def test_patch_missing_old_string_arg(tmp_path, monkeypatch):
    """patch without old_string must return a clear error."""
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    tool = FileTool()
    await tool.execute({"action": "write", "path": "f.txt", "content": "hello", "agent_id": "test"})
    raw = await tool.execute({"action": "patch", "path": "f.txt", "agent_id": "test"})
    result = json.loads(raw)
    assert result["success"] is False
    assert "old_string" in (result.get("error") or "")


# ---------------------------------------------------------------------------
# root='absolute' mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_absolute_read(tmp_path):
    """root='absolute' can read any file by absolute path."""
    target = tmp_path / "target.txt"
    target.write_text("absolute content", encoding="utf-8")
    tool = FileTool()
    raw = await tool.execute({"action": "read", "path": str(target), "root": "absolute"})
    result = json.loads(raw)
    assert result["success"] is True
    assert "absolute content" in result["content"]


@pytest.mark.asyncio
async def test_absolute_write(tmp_path):
    """root='absolute' can write to any path."""
    target = tmp_path / "out.txt"
    tool = FileTool()
    raw = await tool.execute({"action": "write", "path": str(target), "root": "absolute", "content": "written"})
    result = json.loads(raw)
    assert result["success"] is True
    assert target.read_text(encoding="utf-8") == "written"


@pytest.mark.asyncio
async def test_absolute_patch(tmp_path):
    """root='absolute' patch edits a file outside the workspace without PowerShell."""
    target = tmp_path / "script.py"
    target.write_text('log(bad line)\nprint("ok")\n', encoding="utf-8")
    tool = FileTool()
    raw = await tool.execute({
        "action": "patch", "path": str(target), "root": "absolute",
        "old_string": "log(bad line)", "new_string": 'log("bad line")',
    })
    result = json.loads(raw)
    assert result["success"] is True
    assert result["replacements"] == 1
    assert 'log("bad line")' in target.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_absolute_missing_path_errors():
    """root='absolute' with empty path must return a clear error."""
    tool = FileTool()
    raw = await tool.execute({"action": "read", "path": "", "root": "absolute"})
    result = json.loads(raw)
    assert result["success"] is False
    assert "path is required" in (result.get("error") or "").lower()


@pytest.mark.asyncio
async def test_absolute_nonexistent_file(tmp_path):
    """root='absolute' read of a non-existent file returns a clear error."""
    tool = FileTool()
    raw = await tool.execute({"action": "read", "path": str(tmp_path / "nope.txt"), "root": "absolute"})
    result = json.loads(raw)
    assert result["success"] is False
    assert "not found" in (result.get("error") or "").lower()
