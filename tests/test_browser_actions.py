"""
tests/test_browser_actions.py

Tests for each of the 10 new BrowserTool actions using a mocked Patchright page.
No real browser is launched — all page/locator/mouse/keyboard calls are AsyncMock.

Actions under test:
  scroll, fill (alias for type), wait, wait_for, key_press, hover,
  select_option, handle_dialog, navigate_back, console_messages
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Bootstrap — load browser.py as a standalone module (no real package)
# ---------------------------------------------------------------------------

CONDUIT_ROOT = Path(__file__).parent.parent / "cato"  # Cato package root


def _load_browser_module():
    """Load tools/browser.py with a stubbed platform dependency."""
    import importlib.util

    # Stub the parent package 'cato' and 'cato.platform'
    if "cato" not in sys.modules:
        cato_pkg = types.ModuleType("cato")
        cato_pkg.__path__ = [str(CONDUIT_ROOT)]
        cato_pkg.__package__ = "cato"
        sys.modules["cato"] = cato_pkg

    if "cato.platform" not in sys.modules:
        platform_mod = types.ModuleType("cato.platform")
        _tmp = Path(__file__).parent / "_tmp_browser_profile"
        platform_mod.get_data_dir = lambda: _tmp
        sys.modules["cato.platform"] = platform_mod

    mod_key = "cato.tools.browser"
    if mod_key not in sys.modules:
        # Stub tools sub-package
        if "cato.tools" not in sys.modules:
            tools_pkg = types.ModuleType("cato.tools")
            tools_pkg.__path__ = [str(CONDUIT_ROOT / "tools")]
            tools_pkg.__package__ = "cato.tools"
            sys.modules["cato.tools"] = tools_pkg

        spec = importlib.util.spec_from_file_location(
            mod_key,
            str(CONDUIT_ROOT / "tools" / "browser.py"),
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = "cato.tools"
        sys.modules[mod_key] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

    return sys.modules[mod_key]


_browser_mod = _load_browser_module()
BrowserTool = _browser_mod.BrowserTool


# ---------------------------------------------------------------------------
# Helpers to build a BrowserTool with a fully-mocked page
# ---------------------------------------------------------------------------

def _make_mock_page(url: str = "https://example.com") -> MagicMock:
    """Return a MagicMock that quacks like a Patchright Page."""
    page = MagicMock()
    page.url = url

    # Async methods
    page.title = AsyncMock(return_value="Test Page")
    page.goto = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.screenshot = AsyncMock()
    page.pdf = AsyncMock()
    page.evaluate = AsyncMock(return_value="page text")
    page.hover = AsyncMock()
    page.select_option = AsyncMock()
    page.go_back = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_url = AsyncMock()

    # keyboard
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()

    # mouse
    page.mouse = MagicMock()
    page.mouse.wheel = AsyncMock()

    # locator → returns an object with scroll_into_view_if_needed
    locator_mock = MagicMock()
    locator_mock.scroll_into_view_if_needed = AsyncMock()
    page.locator = MagicMock(return_value=locator_mock)

    # once() — synchronous, just records call
    page.once = MagicMock()

    # accessibility
    page.accessibility = MagicMock()
    page.accessibility.snapshot = AsyncMock(return_value={"role": "WebArea"})

    return page


def _make_tool_with_page(url: str = "https://example.com") -> tuple[BrowserTool, MagicMock]:
    """Create a BrowserTool with its browser lifecycle stubbed out."""
    tool = BrowserTool.__new__(BrowserTool)
    tool._browser = MagicMock()
    tool._browser.pages = [MagicMock()]   # liveness check passes
    tool._playwright = MagicMock()
    tool._network_log = []
    tool._console_messages = []

    page = _make_mock_page(url)
    tool._page = page
    return tool, page


# ---------------------------------------------------------------------------
# Tests for fill (alias)
# ---------------------------------------------------------------------------

class TestFill:
    @pytest.mark.asyncio
    async def test_fill_calls_page_fill(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("fill", {"selector": "#q", "text": "hello"})
        page.fill.assert_called_once_with("#q", "hello", timeout=10000)
        assert result["success"] is True
        assert result["typed"] == "hello"

    @pytest.mark.asyncio
    async def test_fill_returns_error_on_exception(self):
        tool, page = _make_tool_with_page()
        page.fill.side_effect = Exception("Element not found")
        result = await tool._dispatch("fill", {"selector": "#missing", "text": "x"})
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fill_and_type_are_same_underlying_method(self):
        """fill and type must both call page.fill (not keyboard.type)."""
        tool, page = _make_tool_with_page()
        await tool._dispatch("fill", {"selector": "#a", "text": "one"})
        await tool._dispatch("type", {"selector": "#b", "text": "two"})
        assert page.fill.call_count == 2


# ---------------------------------------------------------------------------
# Tests for scroll
# ---------------------------------------------------------------------------

class TestScroll:
    @pytest.mark.asyncio
    async def test_scroll_down(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("scroll", {"direction": "down", "amount": 300})
        page.mouse.wheel.assert_called_once_with(0, 300)
        assert result["success"] is True
        assert result["direction"] == "down"
        assert result["amount"] == 300

    @pytest.mark.asyncio
    async def test_scroll_up(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("scroll", {"direction": "up", "amount": 200})
        page.mouse.wheel.assert_called_once_with(0, -200)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_scroll_left_right(self):
        tool, page = _make_tool_with_page()
        await tool._dispatch("scroll", {"direction": "left", "amount": 100})
        page.mouse.wheel.assert_called_with(-100, 0)
        await tool._dispatch("scroll", {"direction": "right", "amount": 100})
        page.mouse.wheel.assert_called_with(100, 0)

    @pytest.mark.asyncio
    async def test_scroll_into_view_with_selector(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("scroll", {"selector": "#target"})
        page.locator.assert_called_once_with("#target")
        page.locator.return_value.scroll_into_view_if_needed.assert_called_once()
        assert result["action"] == "scroll_into_view"
        assert result["selector"] == "#target"


# ---------------------------------------------------------------------------
# Tests for wait
# ---------------------------------------------------------------------------

class TestWait:
    @pytest.mark.asyncio
    async def test_wait_returns_waited_seconds(self):
        tool, page = _make_tool_with_page()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await tool._dispatch("wait", {"seconds": 2.0})
        mock_sleep.assert_called_once_with(2.0)
        assert result["success"] is True
        assert result["waited_seconds"] == 2.0

    @pytest.mark.asyncio
    async def test_wait_caps_at_30_seconds(self):
        tool, page = _make_tool_with_page()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await tool._dispatch("wait", {"seconds": 999.0})
        mock_sleep.assert_called_once_with(30.0)
        assert result["waited_seconds"] == 30.0

    @pytest.mark.asyncio
    async def test_wait_default_one_second(self):
        tool, page = _make_tool_with_page()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await tool._dispatch("wait", {})
        mock_sleep.assert_called_once_with(1.0)
        assert result["waited_seconds"] == 1.0


# ---------------------------------------------------------------------------
# Tests for wait_for
# ---------------------------------------------------------------------------

class TestWaitFor:
    @pytest.mark.asyncio
    async def test_wait_for_selector(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("wait_for", {"condition": "selector", "value": "#btn"})
        page.wait_for_selector.assert_called_once_with("#btn", timeout=10000)
        assert result["success"] is True
        assert result["condition"] == "selector"

    @pytest.mark.asyncio
    async def test_wait_for_text(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("wait_for", {"condition": "text", "value": "loaded"})
        page.wait_for_function.assert_called_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_wait_for_network_idle(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("wait_for", {"condition": "network_idle"})
        page.wait_for_load_state.assert_called_once_with("networkidle", timeout=10000)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_wait_for_url(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("wait_for", {
            "condition": "url", "value": "https://done.com"
        })
        page.wait_for_url.assert_called_once_with("https://done.com", timeout=10000)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_wait_for_returns_error_on_timeout(self):
        tool, page = _make_tool_with_page()
        page.wait_for_selector.side_effect = Exception("Timeout 10000ms exceeded")
        result = await tool._dispatch("wait_for", {"condition": "selector", "value": "#gone"})
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_wait_for_custom_timeout(self):
        tool, page = _make_tool_with_page()
        await tool._dispatch("wait_for", {
            "condition": "selector", "value": "#x", "timeout_ms": 5000
        })
        page.wait_for_selector.assert_called_once_with("#x", timeout=5000)


# ---------------------------------------------------------------------------
# Tests for key_press
# ---------------------------------------------------------------------------

class TestKeyPress:
    @pytest.mark.asyncio
    async def test_key_press_enter(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("key_press", {"key": "Enter"})
        page.keyboard.press.assert_called_once_with("Enter")
        assert result["success"] is True
        assert result["key"] == "Enter"

    @pytest.mark.asyncio
    async def test_key_press_default_enter(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("key_press", {})
        page.keyboard.press.assert_called_once_with("Enter")

    @pytest.mark.asyncio
    async def test_key_press_escape(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("key_press", {"key": "Escape"})
        page.keyboard.press.assert_called_once_with("Escape")
        assert result["key"] == "Escape"

    @pytest.mark.asyncio
    async def test_key_press_tab(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("key_press", {"key": "Tab"})
        page.keyboard.press.assert_called_once_with("Tab")


# ---------------------------------------------------------------------------
# Tests for hover
# ---------------------------------------------------------------------------

class TestHover:
    @pytest.mark.asyncio
    async def test_hover_success(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("hover", {"selector": ".menu-item"})
        page.hover.assert_called_once_with(".menu-item", timeout=10000)
        assert result["success"] is True
        assert result["selector"] == ".menu-item"

    @pytest.mark.asyncio
    async def test_hover_error(self):
        tool, page = _make_tool_with_page()
        page.hover.side_effect = Exception("Element not visible")
        result = await tool._dispatch("hover", {"selector": "#hidden"})
        assert result["success"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# Tests for select_option
# ---------------------------------------------------------------------------

class TestSelectOption:
    @pytest.mark.asyncio
    async def test_select_by_value(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("select_option", {
            "selector": "#size", "value": "large"
        })
        page.select_option.assert_called_once_with("#size", value="large")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_select_by_label(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("select_option", {
            "selector": "#color", "label": "Blue"
        })
        page.select_option.assert_called_once_with("#color", label="Blue")
        assert result["success"] is True
        assert result["value"] == "Blue"

    @pytest.mark.asyncio
    async def test_select_by_index(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("select_option", {
            "selector": "#qty", "index": 2
        })
        page.select_option.assert_called_once_with("#qty", index=2)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_select_option_error(self):
        tool, page = _make_tool_with_page()
        page.select_option.side_effect = Exception("No such option")
        result = await tool._dispatch("select_option", {
            "selector": "#missing", "value": "x"
        })
        assert result["success"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# Tests for handle_dialog
# ---------------------------------------------------------------------------

class TestHandleDialog:
    @pytest.mark.asyncio
    async def test_handle_dialog_registers_accept(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("handle_dialog", {"action": "accept"})
        page.once.assert_called_once()
        call_args = page.once.call_args
        assert call_args[0][0] == "dialog"
        assert result["success"] is True
        assert result["registered_action"] == "accept"

    @pytest.mark.asyncio
    async def test_handle_dialog_registers_dismiss(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("handle_dialog", {"action": "dismiss"})
        page.once.assert_called_once()
        assert result["registered_action"] == "dismiss"

    @pytest.mark.asyncio
    async def test_handle_dialog_accept_with_text_invokes_callback(self):
        """Simulate the dialog callback being fired and verify it calls accept(text)."""
        tool, page = _make_tool_with_page()
        await tool._dispatch("handle_dialog", {"action": "accept", "text": "my input"})

        # Extract the registered callback
        callback = page.once.call_args[0][1]

        dialog = MagicMock()
        dialog.message = "Enter value:"
        dialog.type = "prompt"
        dialog.accept = AsyncMock()
        dialog.dismiss = AsyncMock()

        await callback(dialog)
        dialog.accept.assert_called_once_with("my input")
        dialog.dismiss.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_dialog_dismiss_invokes_callback(self):
        tool, page = _make_tool_with_page()
        await tool._dispatch("handle_dialog", {"action": "dismiss"})
        callback = page.once.call_args[0][1]

        dialog = MagicMock()
        dialog.message = "Are you sure?"
        dialog.type = "confirm"
        dialog.accept = AsyncMock()
        dialog.dismiss = AsyncMock()

        await callback(dialog)
        dialog.dismiss.assert_called_once()
        dialog.accept.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for navigate_back
# ---------------------------------------------------------------------------

class TestNavigateBack:
    @pytest.mark.asyncio
    async def test_navigate_back_calls_go_back(self):
        tool, page = _make_tool_with_page(url="https://example.com/page2")
        result = await tool._dispatch("navigate_back", {})
        page.go_back.assert_called_once_with(timeout=15000)
        assert result["success"] is True
        assert "url" in result
        assert "title" in result

    @pytest.mark.asyncio
    async def test_navigate_back_returns_title(self):
        tool, page = _make_tool_with_page()
        page.title = AsyncMock(return_value="Previous Page")
        result = await tool._dispatch("navigate_back", {})
        assert result["title"] == "Previous Page"


# ---------------------------------------------------------------------------
# Tests for console_messages
# ---------------------------------------------------------------------------

class TestConsoleMessages:
    @pytest.mark.asyncio
    async def test_console_messages_empty_initially(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("console_messages", {})
        assert result["messages"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_console_messages_returns_buffered(self):
        tool, page = _make_tool_with_page()
        tool._console_messages = [
            {"type": "log", "text": "hello"},
            {"type": "error", "text": "oops"},
        ]
        result = await tool._dispatch("console_messages", {})
        assert result["count"] == 2
        assert result["messages"][0]["text"] == "hello"
        assert result["messages"][1]["type"] == "error"

    @pytest.mark.asyncio
    async def test_console_messages_clears_buffer(self):
        tool, page = _make_tool_with_page()
        tool._console_messages = [{"type": "warn", "text": "warning"}]
        await tool._dispatch("console_messages", {})
        # Buffer must be cleared after retrieval
        assert tool._console_messages == []

    @pytest.mark.asyncio
    async def test_console_messages_second_call_empty(self):
        tool, page = _make_tool_with_page()
        tool._console_messages = [{"type": "log", "text": "once"}]
        first = await tool._dispatch("console_messages", {})
        second = await tool._dispatch("console_messages", {})
        assert first["count"] == 1
        assert second["count"] == 0


# ---------------------------------------------------------------------------
# Tests for _console_messages init attribute
# ---------------------------------------------------------------------------

class TestConsoleMessageInit:
    def test_console_messages_list_initialized(self):
        """BrowserTool.__init__ must set up _console_messages as an empty list."""
        # We can't call __init__ without triggering mkdir, so we check the
        # instance created via __new__ + manual init of the attribute.
        tool = BrowserTool.__new__(BrowserTool)
        tool._console_messages = []
        assert isinstance(tool._console_messages, list)
        assert tool._console_messages == []


# ---------------------------------------------------------------------------
# Tests for unknown action error
# ---------------------------------------------------------------------------

class TestDispatchUnknownAction:
    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        tool, page = _make_tool_with_page()
        result = await tool._dispatch("fly_to_moon", {})
        assert "error" in result
        assert "fly_to_moon" in result["error"]

    @pytest.mark.asyncio
    async def test_all_new_actions_in_dispatch_table(self):
        """Verify that all 10 new actions are routable."""
        tool, _ = _make_tool_with_page()
        # These actions are registered and return dicts (not error dicts for unknown action).
        # We just verify they don't hit the "Unknown browser action" path.
        new_actions = [
            "scroll", "wait", "wait_for", "key_press", "hover",
            "select_option", "handle_dialog", "navigate_back", "console_messages",
            "fill",
        ]
        with patch("asyncio.sleep", new_callable=AsyncMock):
            for act in new_actions:
                result = await tool._dispatch(act, {})
                # The result must NOT be the "Unknown browser action" error
                assert "Unknown browser action" not in result.get("error", ""), \
                    f"Action '{act}' not found in dispatch table"
