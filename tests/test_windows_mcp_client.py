"""
Tests for cato.mcp.windows_client.WindowsMCPClient

All tests run fully offline — no Windows MCP server process is started.
The MCP session is mocked via unittest.mock so the client logic is exercised
in isolation from the actual ``uvx windows-mcp`` subprocess.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.mcp.windows_client import WindowsMCPClient, WindowsMCPError


# ---------------------------------------------------------------------------
# Shared mock factory
# ---------------------------------------------------------------------------

def _make_mock_session(*, tool_names: list[str] | None = None, error: bool = False) -> AsyncMock:
    """Return a mock ClientSession suitable for patching into the client."""
    session = AsyncMock()

    # initialize() returns a minimal InitializeResult
    session.initialize = AsyncMock(return_value=SimpleNamespace(serverInfo=SimpleNamespace(name="Windows-MCP")))

    # list_tools() returns an object with a .tools list
    names = tool_names or [
        "Snapshot", "Click", "Type", "Scroll", "Move", "Shortcut", "Wait",
        "PowerShell", "FileSystem", "App", "Scrape", "Clipboard",
        "Process", "Notification", "Registry", "MultiSelect", "MultiEdit",
    ]
    session.list_tools = AsyncMock(
        return_value=SimpleNamespace(tools=[SimpleNamespace(name=n) for n in names])
    )

    # call_tool() returns a mock result
    content_item = SimpleNamespace(text='{"elements": [], "status": "ok"}')
    result = SimpleNamespace(
        isError=error,
        content=[content_item],
    )
    session.call_tool = AsyncMock(return_value=result)

    return session


def _make_error_session() -> AsyncMock:
    """Return a mock session whose call_tool always returns isError=True."""
    return _make_mock_session(error=True)


# ---------------------------------------------------------------------------
# Patch helper — bypasses the real stdio transport
# ---------------------------------------------------------------------------

class _MockTransportCM:
    """Mimics the async context manager returned by stdio_client()."""

    def __init__(self, session: AsyncMock) -> None:
        self._session = session

    async def __aenter__(self):
        return (MagicMock(), MagicMock())   # (read_stream, write_stream)

    async def __aexit__(self, *_):
        pass


class _MockSessionCM:
    """Mimics the async context manager for ClientSession()."""

    def __init__(self, session: AsyncMock) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncMock:
        return self._session

    async def __aexit__(self, *_):
        pass


# ---------------------------------------------------------------------------
# Test 1: start / stop lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_starts_and_stops():
    """start() + stop() should not raise and should leave session cleared."""
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        client = WindowsMCPClient()
        await client.start()
        assert client._session is not None
        await client.stop()
        assert client._session is None


@pytest.mark.asyncio
async def test_start_idempotent():
    """Calling start() twice should not raise or duplicate state."""
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        client = WindowsMCPClient()
        await client.start()
        await client.start()   # second call should be a no-op
        assert client._session is not None
        await client.stop()


@pytest.mark.asyncio
async def test_context_manager():
    """``async with WindowsMCPClient()`` should start and stop cleanly."""
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            assert client._session is not None
        assert client._session is None


# ---------------------------------------------------------------------------
# Test 2: tool call routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_calls_correct_tool():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.snapshot(use_vision=True)

    mock_session.call_tool.assert_called_once()
    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "Snapshot"
    assert params["use_vision"] is True


@pytest.mark.asyncio
async def test_powershell_call():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.powershell("Get-Process", timeout=10)

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "PowerShell"
    assert params["command"] == "Get-Process"
    assert params["timeout"] == 10


@pytest.mark.asyncio
async def test_click_with_loc():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.click(loc=[100, 200], button="right", clicks=2)

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "Click"
    assert params["loc"] == [100, 200]
    assert params["button"] == "right"
    assert params["clicks"] == 2


@pytest.mark.asyncio
async def test_type_text_with_label():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.type_text("hello world", label=42, press_enter=True)

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "Type"
    assert params["label"] == 42
    assert params["text"] == "hello world"
    assert params["press_enter"] is True


@pytest.mark.asyncio
async def test_shortcut():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.shortcut("ctrl+c")

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "Shortcut"
    assert params["shortcut"] == "ctrl+c"


@pytest.mark.asyncio
async def test_clipboard_get():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.clipboard("get")

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "Clipboard"
    assert params["mode"] == "get"


@pytest.mark.asyncio
async def test_clipboard_set():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.clipboard("set", text="copied text")

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "Clipboard"
    assert params["text"] == "copied text"


@pytest.mark.asyncio
async def test_app_launch():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.app(mode="launch", name="claude")

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "App"
    assert params["mode"] == "launch"
    assert params["name"] == "claude"


@pytest.mark.asyncio
async def test_notification():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.notification("Cato", "Pipeline complete")

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "Notification"
    assert params["title"] == "Cato"
    assert params["message"] == "Pipeline complete"


@pytest.mark.asyncio
async def test_registry_get():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.registry("get", r"HKCU:\Software\Test", name="Value")

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "Registry"
    assert params["mode"] == "get"
    assert params["name"] == "Value"


@pytest.mark.asyncio
async def test_process_list():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.process("list", sort_by="cpu", limit=5)

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "Process"
    assert params["mode"] == "list"
    assert params["sort_by"] == "cpu"
    assert params["limit"] == 5


@pytest.mark.asyncio
async def test_filesystem_read():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.filesystem("read", r"C:\tmp\test.txt", limit=100)

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "FileSystem"
    assert params["mode"] == "read"
    assert params["path"] == r"C:\tmp\test.txt"
    assert params["limit"] == 100


@pytest.mark.asyncio
async def test_multiselect():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.multiselect(locs=[[10, 20], [30, 40]])

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "MultiSelect"
    assert params["locs"] == [[10, 20], [30, 40]]


@pytest.mark.asyncio
async def test_multiedit():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.multiedit(labels=[[1, "foo"], [2, "bar"]])

    tool_name, params = mock_session.call_tool.call_args.args
    assert tool_name == "MultiEdit"
    assert params["labels"] == [[1, "foo"], [2, "bar"]]


# ---------------------------------------------------------------------------
# Test 3: None params are stripped before call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_none_params_stripped():
    """None values must not be forwarded to call_tool (server uses defaults)."""
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.click(loc=[50, 60])   # label=None should be stripped

    _, params = mock_session.call_tool.call_args.args
    assert "label" not in params, "None-valued 'label' should be stripped from params"
    assert params["loc"] == [50, 60]


@pytest.mark.asyncio
async def test_snapshot_none_display_stripped():
    """display=None (the default) must not appear in the call_tool params."""
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            await client.snapshot()   # display defaults to None

    _, params = mock_session.call_tool.call_args.args
    assert "display" not in params


# ---------------------------------------------------------------------------
# Test 4: WindowsMCPError raised on server error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_error_raises_windows_mcp_error():
    """isError=True in the tool result must raise WindowsMCPError."""
    mock_session = _make_error_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            with pytest.raises(WindowsMCPError, match="returned error"):
                await client.snapshot()


@pytest.mark.asyncio
async def test_call_raises_when_not_started():
    """Calling a tool before start() must raise WindowsMCPError, not AttributeError."""
    client = WindowsMCPClient()
    with pytest.raises(WindowsMCPError, match="not started"):
        await client.snapshot()


# ---------------------------------------------------------------------------
# Test 5: input validation guards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_requires_loc_or_label():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            with pytest.raises(ValueError, match="loc.*label"):
                await client.click()


@pytest.mark.asyncio
async def test_type_text_requires_loc_or_label():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            with pytest.raises(ValueError, match="loc.*label"):
                await client.type_text("hello")


@pytest.mark.asyncio
async def test_move_requires_loc_or_label():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            with pytest.raises(ValueError, match="loc.*label"):
                await client.move()


@pytest.mark.asyncio
async def test_clipboard_set_requires_text():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            with pytest.raises(ValueError, match="text"):
                await client.clipboard("set")


@pytest.mark.asyncio
async def test_multiselect_requires_locs_or_labels():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            with pytest.raises(ValueError, match="locs.*labels"):
                await client.multiselect()


@pytest.mark.asyncio
async def test_multiedit_requires_locs_or_labels():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            with pytest.raises(ValueError, match="locs.*labels"):
                await client.multiedit()


# ---------------------------------------------------------------------------
# Test 6: list_tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tools_returns_expected_names():
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)):
        async with WindowsMCPClient() as client:
            names = await client.list_tools()

    assert "Snapshot" in names
    assert "PowerShell" in names
    assert "Click" in names
    assert len(names) == 17


@pytest.mark.asyncio
async def test_list_tools_raises_when_not_started():
    client = WindowsMCPClient()
    with pytest.raises(WindowsMCPError, match="Not started"):
        await client.list_tools()


# ---------------------------------------------------------------------------
# Test 7: custom command / env passthrough
# ---------------------------------------------------------------------------

def test_custom_command_stored_in_server_params():
    """Constructor args should be stored in StdioServerParameters."""
    client = WindowsMCPClient(
        command="npx",
        args=["windows-mcp@latest"],
        env={"MODE": "remote", "SANDBOX_ID": "abc", "API_KEY": "xyz"},
    )
    assert client._server_params.command == "npx"
    assert client._server_params.args == ["windows-mcp@latest"]
    assert client._server_params.env["MODE"] == "remote"


def test_default_command():
    """Default construction uses uvx + windows-mcp."""
    client = WindowsMCPClient()
    assert client._server_params.command == "uvx"
    assert client._server_params.args == ["windows-mcp"]


# ---------------------------------------------------------------------------
# Test 8: open_app_and_type does not raise ValueError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_app_and_type_does_not_raise():
    """open_app_and_type() must not raise ValueError (H-1 regression guard)."""
    mock_session = _make_mock_session()

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(mock_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(mock_session)), \
         patch("cato.mcp.windows_client.asyncio.sleep", new_callable=AsyncMock):
        async with WindowsMCPClient() as client:
            # Must not raise — previously raised ValueError because type_text
            # was called without loc or label.
            await client.open_app_and_type("claude", "hello pipeline")

    # Should have called: App(launch), Snapshot, App(switch), Type
    calls = [call.args[0] for call in mock_session.call_tool.call_args_list]
    assert "App" in calls
    assert "Snapshot" in calls
    assert "Type" in calls


# ---------------------------------------------------------------------------
# Test 9: start() failure cleans up _cm_stack (M-2 regression guard)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_failure_cleans_cm_stack():
    """If session.initialize() raises, stop() must drain _cm_stack."""
    failing_session = _make_mock_session()
    failing_session.initialize = AsyncMock(side_effect=RuntimeError("init failed"))

    with patch("cato.mcp.windows_client.stdio_client", return_value=_MockTransportCM(failing_session)), \
         patch("cato.mcp.windows_client.ClientSession", return_value=_MockSessionCM(failing_session)):
        client = WindowsMCPClient()
        with pytest.raises(RuntimeError, match="init failed"):
            await client.start()

    # After the failure, _cm_stack must be empty and _session must be None
    assert client._session is None
    assert client._cm_stack == []
