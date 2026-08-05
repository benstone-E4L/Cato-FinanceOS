"""
tests/test_github_tool.py — Tests for SKILL 3: Super-GitHub 3-Model PR Review.

Covers:
- _resolve_gh() path resolution (normal + Windows .CMD)
- _extract_pr_number() URL and integer parsing
- GitHubTool._gh_env() token injection from vault
- GitHubTool.pr_merge() — delegates to gh CLI
- GitHubTool.issue_create() / issue_list()
- GitHubTool.release_create()
- GitHubTool.pr_review() — 3-model pipeline (mocked)
- _invoke_single_model() — model not found fallback
- Confidence scoring integration
- Synthesis integration (simple_synthesis called with 3 results)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _resolve_gh
# ---------------------------------------------------------------------------

class TestResolveGh:
    def test_gh_found_posix(self):
        from cato.tools.github_tool import _resolve_gh
        with patch("shutil.which", return_value="/usr/bin/gh"), \
             patch("sys.platform", "linux"):
            args = _resolve_gh()
        assert args == ["/usr/bin/gh"]

    def test_gh_not_found_raises(self):
        from cato.tools.github_tool import _resolve_gh
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="gh"):
                _resolve_gh()

    def test_gh_cmd_wrapper_windows(self):
        from cato.tools.github_tool import _resolve_gh
        with patch("shutil.which", return_value=r"C:\Program Files\GitHub CLI\gh.cmd"), \
             patch("sys.platform", "win32"):
            args = _resolve_gh()
        assert args[0] == "cmd.exe"
        assert args[1] == "/c"
        assert args[2].endswith(".cmd")

    def test_gh_bat_wrapper_windows(self):
        from cato.tools.github_tool import _resolve_gh
        with patch("shutil.which", return_value=r"C:\tools\gh.bat"), \
             patch("sys.platform", "win32"):
            args = _resolve_gh()
        assert "cmd.exe" in args

    def test_gh_no_cmd_wrap_on_linux(self):
        """Linux gh.sh scripts should NOT be wrapped in cmd.exe."""
        from cato.tools.github_tool import _resolve_gh
        with patch("shutil.which", return_value="/usr/local/bin/gh"), \
             patch("sys.platform", "linux"):
            args = _resolve_gh()
        assert "cmd.exe" not in args


# ---------------------------------------------------------------------------
# _extract_pr_number
# ---------------------------------------------------------------------------

class TestExtractPrNumber:
    def test_bare_integer(self):
        from cato.tools.github_tool import _extract_pr_number
        assert _extract_pr_number("123") == 123

    def test_url_with_number(self):
        from cato.tools.github_tool import _extract_pr_number
        assert _extract_pr_number("https://github.com/org/repo/pull/456") == 456

    def test_url_with_trailing_slash(self):
        from cato.tools.github_tool import _extract_pr_number
        assert _extract_pr_number("https://github.com/org/repo/pull/789/") == 789

    def test_invalid_raises(self):
        from cato.tools.github_tool import _extract_pr_number
        with pytest.raises(ValueError):
            _extract_pr_number("not-a-number")

    def test_url_without_pull_raises(self):
        from cato.tools.github_tool import _extract_pr_number
        with pytest.raises(ValueError):
            _extract_pr_number("https://github.com/org/repo/issues/5")


# ---------------------------------------------------------------------------
# GitHubTool._gh_env
# ---------------------------------------------------------------------------

class TestGhEnv:
    def test_no_vault_returns_os_env(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool(vault=None)
        env = tool._gh_env()
        assert isinstance(env, dict)

    def test_vault_injects_gh_token(self):
        from cato.tools.github_tool import GitHubTool
        vault = MagicMock()
        vault.get.return_value = "ghp_test_token_123"
        tool = GitHubTool(vault=vault)
        env = tool._gh_env()
        assert env.get("GH_TOKEN") == "ghp_test_token_123"

    def test_vault_exception_does_not_crash(self):
        from cato.tools.github_tool import GitHubTool
        vault = MagicMock()
        vault.get.side_effect = Exception("vault locked")
        tool = GitHubTool(vault=vault)
        env = tool._gh_env()
        # Should still return a dict, just without GH_TOKEN
        assert isinstance(env, dict)
        assert "GH_TOKEN" not in env

    def test_vault_no_token_does_not_inject(self):
        from cato.tools.github_tool import GitHubTool
        vault = MagicMock()
        vault.get.return_value = None
        tool = GitHubTool(vault=vault)
        env = tool._gh_env()
        assert "GH_TOKEN" not in env


# ---------------------------------------------------------------------------
# _run_gh — subprocess helper
# ---------------------------------------------------------------------------

class TestRunGh:
    @pytest.mark.asyncio
    async def test_run_gh_success(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"output text", b""))
        mock_proc.returncode = 0

        with patch("cato.tools.github_tool._resolve_gh", return_value=["gh"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await tool._run_gh(["pr", "list"])
        assert result == "output text"

    @pytest.mark.asyncio
    async def test_run_gh_nonzero_raises(self):
        from cato.tools.github_tool import GitHubTool
        from cato.orchestrator.cli_invoker import SubprocessError
        tool = GitHubTool()
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error message"))
        mock_proc.returncode = 1

        with patch("cato.tools.github_tool._resolve_gh", return_value=["gh"]), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(SubprocessError):
                await tool._run_gh(["pr", "diff", "1"])

    @pytest.mark.asyncio
    async def test_run_gh_gh_not_found_returns_error_in_callers(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch("cato.tools.github_tool._resolve_gh", side_effect=FileNotFoundError("gh not found")):
            # pr_merge wraps the error
            result = await tool.pr_merge(1)
        assert "Error" in result or "error" in result.lower() or "not found" in result.lower()


# ---------------------------------------------------------------------------
# pr_merge
# ---------------------------------------------------------------------------

class TestPrMerge:
    @pytest.mark.asyncio
    async def test_pr_merge_squash(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch.object(tool, "_run_gh", new=AsyncMock(return_value="Merged!")):
            result = await tool.pr_merge(42, method="squash")
        assert "42" in result or "Merged" in result

    @pytest.mark.asyncio
    async def test_pr_merge_invalid_method(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        result = await tool.pr_merge(1, method="badmethod")
        assert "Invalid" in result or "invalid" in result.lower()

    @pytest.mark.asyncio
    async def test_pr_merge_rebase(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch.object(tool, "_run_gh", new=AsyncMock(return_value="")):
            result = await tool.pr_merge(10, method="rebase")
        assert "rebase" in result or "10" in result


# ---------------------------------------------------------------------------
# issue_create / issue_list
# ---------------------------------------------------------------------------

class TestIssueOperations:
    @pytest.mark.asyncio
    async def test_issue_create_returns_url(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch.object(tool, "_run_gh", new=AsyncMock(return_value="https://github.com/org/repo/issues/5")):
            result = await tool.issue_create(title="Test Bug", body="Bug body")
        assert "github.com" in result

    @pytest.mark.asyncio
    async def test_issue_list_parses_json(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        mock_data = json.dumps([
            {"number": 1, "title": "Bug #1", "state": "open", "url": "https://github.com/org/repo/issues/1"},
            {"number": 2, "title": "Feature request", "state": "open", "url": "https://github.com/org/repo/issues/2"},
        ])
        with patch.object(tool, "_run_gh", new=AsyncMock(return_value=mock_data)):
            result = await tool.issue_list()
        assert "Bug #1" in result
        assert "Feature request" in result
        assert "#1" in result

    @pytest.mark.asyncio
    async def test_issue_list_empty(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch.object(tool, "_run_gh", new=AsyncMock(return_value="[]")):
            result = await tool.issue_list()
        assert "No open issues" in result

    @pytest.mark.asyncio
    async def test_issue_list_error(self):
        from cato.tools.github_tool import GitHubTool
        from cato.orchestrator.cli_invoker import SubprocessError
        tool = GitHubTool()
        with patch.object(tool, "_run_gh", new=AsyncMock(side_effect=SubprocessError("gh", 1, "auth error"))):
            result = await tool.issue_list()
        assert "Error" in result


# ---------------------------------------------------------------------------
# release_create
# ---------------------------------------------------------------------------

class TestReleaseCreate:
    @pytest.mark.asyncio
    async def test_release_create_success(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch.object(tool, "_run_gh", new=AsyncMock(return_value="https://github.com/org/repo/releases/tag/v1.0.0")):
            result = await tool.release_create(tag="v1.0.0", notes="Initial release")
        assert "v1.0.0" in result or "github.com" in result

    @pytest.mark.asyncio
    async def test_release_create_empty_notes(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch.object(tool, "_run_gh", new=AsyncMock(return_value="")):
            result = await tool.release_create(tag="v2.0.0")
        # Should return a default message
        assert "v2.0.0" in result

    @pytest.mark.asyncio
    async def test_release_create_error(self):
        from cato.tools.github_tool import GitHubTool
        from cato.orchestrator.cli_invoker import SubprocessError
        tool = GitHubTool()
        with patch.object(tool, "_run_gh", new=AsyncMock(side_effect=SubprocessError("gh", 1, "not found"))):
            result = await tool.release_create(tag="v3.0.0")
        assert "Error" in result


# ---------------------------------------------------------------------------
# pr_review — 3-model pipeline
# ---------------------------------------------------------------------------

class TestPrReview:
    @pytest.mark.asyncio
    async def test_pr_review_invalid_target(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()
        result = await tool.pr_review("not-a-pr")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_pr_review_diff_fetch_error(self):
        from cato.tools.github_tool import GitHubTool
        from cato.orchestrator.cli_invoker import SubprocessError
        tool = GitHubTool()
        with patch.object(tool, "_run_gh", new=AsyncMock(side_effect=SubprocessError("gh", 1, "not found"))):
            result = await tool.pr_review("123")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_pr_review_runs_synthesis(self):
        from cato.tools.github_tool import GitHubTool
        tool = GitHubTool()

        diff_text = "diff --git a/file.py b/file.py\n+def new_func(): pass\n"
        mock_model_result = {
            "model": "claude",
            "response": "Looks good! confidence: 0.90",
            "confidence": 0.90,
            "latency_ms": 100,
        }

        async def mock_invoke_model(model, prompt, env):
            return mock_model_result

        with patch.object(tool, "_run_gh", new=AsyncMock(side_effect=[diff_text, "ok"])), \
             patch("cato.tools.github_tool._invoke_single_model", new=mock_invoke_model):
            result = await tool.pr_review("https://github.com/org/repo/pull/99")

        assert "99" in result

    @pytest.mark.asyncio
    async def test_pr_review_truncates_large_diff(self):
        from cato.tools.github_tool import GitHubTool, _MAX_DIFF_CHARS
        tool = GitHubTool()

        large_diff = "+" + "x" * (_MAX_DIFF_CHARS + 5000)
        prompts_captured = []

        async def mock_invoke_model(model, prompt, env):
            prompts_captured.append(prompt)
            return {"model": model, "response": "OK confidence: 0.8", "confidence": 0.8, "latency_ms": 50}

        with patch.object(tool, "_run_gh", new=AsyncMock(side_effect=[large_diff, "ok"])), \
             patch("cato.tools.github_tool._invoke_single_model", new=mock_invoke_model):
            await tool.pr_review("1")

        # All prompts sent to models should have truncated diff
        for p in prompts_captured:
            # The prompt includes the diff, verify it's not the full massive diff
            assert len(p) < _MAX_DIFF_CHARS + 2000  # some overhead for prompt template


# ---------------------------------------------------------------------------
# _invoke_single_model
# ---------------------------------------------------------------------------

class TestInvokeSingleModel:
    @pytest.mark.asyncio
    async def test_model_not_installed_returns_gracefully(self):
        from cato.tools.github_tool import _invoke_single_model
        with patch("cato.tools.github_tool._resolve_cli", side_effect=FileNotFoundError("not found")):
            result = await _invoke_single_model("codex", "test prompt", {})
        assert result["model"] == "codex"
        assert result["confidence"] == 0.0
        assert "not installed" in result["response"]

    @pytest.mark.asyncio
    async def test_model_subprocess_error_returns_gracefully(self):
        from cato.tools.github_tool import _invoke_single_model
        with patch("cato.tools.github_tool._resolve_cli", return_value=["codex"]), \
             patch("cato.tools.github_tool._run_subprocess_async", new=AsyncMock(side_effect=RuntimeError("crash"))):
            result = await _invoke_single_model("codex", "prompt", {})
        assert result["model"] == "codex"
        assert result["confidence"] < 1.0
        assert "error" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_model_confidence_extracted(self):
        from cato.tools.github_tool import _invoke_single_model
        response = "The code looks good. confidence: 0.92"
        with patch("cato.tools.github_tool._resolve_cli", return_value=["claude"]), \
             patch("cato.tools.github_tool._run_subprocess_async", new=AsyncMock(return_value=response)):
            result = await _invoke_single_model("claude", "prompt", {})
        assert result["confidence"] == pytest.approx(0.92)
        assert result["model"] == "claude"
        assert result["latency_ms"] >= 0
