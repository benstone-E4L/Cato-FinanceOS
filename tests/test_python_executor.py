"""
tests/test_python_executor.py — Tests for Skill 7: Python Execution Sandbox.

Min 20 tests covering:
- SandboxViolationError for blocked patterns
- Safe code executes successfully
- Timeout enforcement
- plt.show() replacement with savefig
- Return code captured correctly
- ExecutionResult structure
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.tools.python_executor import (
    BLOCKED_PATTERNS,
    ExecutionResult,
    PythonExecutor,
    SandboxViolationError,
    _check_blocked_patterns,
    _patch_matplotlib,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def executor(tmp_path):
    """PythonExecutor backed by tmp_path sandbox."""
    return PythonExecutor(sandbox_dir=tmp_path / "sandbox")


# ---------------------------------------------------------------------------
# SandboxViolationError — blocked patterns
# ---------------------------------------------------------------------------

class TestBlockedPatterns:
    def test_os_remove_blocked(self):
        """os.remove in code raises SandboxViolationError."""
        with pytest.raises(SandboxViolationError, match="os.remove"):
            _check_blocked_patterns("import os; os.remove('/tmp/file')")

    def test_shutil_rmtree_blocked(self):
        """shutil.rmtree raises SandboxViolationError."""
        with pytest.raises(SandboxViolationError, match="shutil.rmtree"):
            _check_blocked_patterns("import shutil; shutil.rmtree('/danger')")

    def test_subprocess_run_blocked(self):
        """subprocess.run raises SandboxViolationError."""
        with pytest.raises(SandboxViolationError, match="subprocess.run"):
            _check_blocked_patterns("import subprocess; subprocess.run(['ls'])")

    def test_subprocess_call_blocked(self):
        """subprocess.call raises SandboxViolationError."""
        with pytest.raises(SandboxViolationError, match="subprocess.call"):
            _check_blocked_patterns("import subprocess; subprocess.call(['ls'])")

    def test_socket_connect_blocked(self):
        """socket.connect raises SandboxViolationError."""
        with pytest.raises(SandboxViolationError, match="socket.connect"):
            _check_blocked_patterns("s = socket.socket(); s.socket.connect(('host', 80))")

    def test_all_blocked_patterns_listed(self):
        """All 5 blocked patterns are present in BLOCKED_PATTERNS constant."""
        assert "os.remove" in BLOCKED_PATTERNS
        assert "shutil.rmtree" in BLOCKED_PATTERNS
        assert "subprocess.run" in BLOCKED_PATTERNS
        assert "subprocess.call" in BLOCKED_PATTERNS
        assert "socket.connect" in BLOCKED_PATTERNS

    def test_safe_code_passes_check(self):
        """Code without blocked patterns passes the check."""
        _check_blocked_patterns("print('hello')\nx = 1 + 2")  # No exception

    def test_sandbox_violation_error_is_exception(self):
        """SandboxViolationError is an Exception subclass."""
        assert issubclass(SandboxViolationError, Exception)

    @pytest.mark.asyncio
    async def test_execute_raises_sandbox_violation(self, executor):
        """executor.execute() raises SandboxViolationError for blocked patterns."""
        with pytest.raises(SandboxViolationError):
            await executor.execute("import os; os.remove('/tmp/x')")


# ---------------------------------------------------------------------------
# Safe code execution
# ---------------------------------------------------------------------------

class TestSafeExecution:
    @pytest.mark.asyncio
    async def test_simple_print(self, executor):
        """Simple print statement produces stdout output."""
        result = await executor.execute("print('hello sandbox')")
        assert result.success is True
        assert "hello sandbox" in result.stdout

    @pytest.mark.asyncio
    async def test_arithmetic(self, executor):
        """Arithmetic code executes and returns correct result."""
        result = await executor.execute("print(3 * 7)")
        assert "21" in result.stdout
        assert result.returncode == 0

    @pytest.mark.asyncio
    async def test_multiline_code(self, executor):
        """Multiline code executes correctly."""
        code = "x = 10\ny = 20\nprint(x + y)"
        result = await executor.execute(code)
        assert "30" in result.stdout

    @pytest.mark.asyncio
    async def test_execution_result_structure(self, executor):
        """ExecutionResult has all required fields."""
        result = await executor.execute("print('ok')")
        assert hasattr(result, "code")
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "returncode")
        assert hasattr(result, "rounds_used")
        assert hasattr(result, "success")
        assert hasattr(result, "artifacts")

    @pytest.mark.asyncio
    async def test_returncode_zero_on_success(self, executor):
        """Successful code has returncode 0."""
        result = await executor.execute("x = 1")
        assert result.returncode == 0

    @pytest.mark.asyncio
    async def test_returncode_nonzero_on_error(self, executor):
        """Code with syntax error has non-zero returncode."""
        result = await executor.execute("this is not valid python @@@")
        assert result.returncode != 0

    @pytest.mark.asyncio
    async def test_stderr_captured(self, executor):
        """stderr output is captured in result."""
        result = await executor.execute("import sys; sys.stderr.write('error msg')")
        assert "error" in result.stderr.lower() or result.stderr != ""

    @pytest.mark.asyncio
    async def test_success_false_on_error(self, executor):
        """success=False when code fails."""
        result = await executor.execute("raise ValueError('intentional')")
        assert result.success is False


# ---------------------------------------------------------------------------
# plt.show() → plt.savefig() replacement
# ---------------------------------------------------------------------------

class TestMatplotlibPatch:
    def test_plt_show_replaced(self):
        """plt.show() is replaced with plt.savefig() call."""
        code = "import matplotlib.pyplot as plt\nplt.plot([1,2,3])\nplt.show()"
        artifacts_dir = Path("/tmp/test_artifacts")
        patched = _patch_matplotlib(code, artifacts_dir)
        assert "plt.show()" not in patched
        assert "plt.savefig" in patched

    def test_plt_show_unchanged_when_absent(self):
        """Code without plt.show() is returned unchanged."""
        code = "print('no matplotlib here')"
        artifacts_dir = Path("/tmp/test_artifacts")
        patched = _patch_matplotlib(code, artifacts_dir)
        assert patched == code

    def test_plt_close_added_after_savefig(self):
        """plt.close() is added after plt.savefig() to free memory."""
        code = "plt.show()"
        artifacts_dir = Path("/tmp/test_artifacts")
        patched = _patch_matplotlib(code, artifacts_dir)
        assert "plt.close()" in patched

    def test_savefig_path_in_artifacts_dir(self):
        """The saved figure path is inside the artifacts directory."""
        code = "plt.show()"
        artifacts_dir = Path("/fake/artifacts")
        patched = _patch_matplotlib(code, artifacts_dir)
        # The path string should reference the artifacts_dir
        assert "fake" in patched or "artifacts" in patched


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------

class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self, executor):
        """Code that exceeds timeout returns failed ExecutionResult."""
        # Use a very short timeout and code that sleeps
        result = await executor.execute(
            "import time; time.sleep(60)",
            timeout_sec=0.1,
        )
        assert result.success is False
        assert result.returncode == -1 or "timed out" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_fast_code_completes_within_timeout(self, executor):
        """Fast code completes successfully within the timeout."""
        result = await executor.execute("print('fast')", timeout_sec=10.0)
        assert result.success is True
