"""Security regression tests for shell tool and safety scanner.

C-2 / Phase A: adversarial quoting, escaping, and concatenation must not
bypass ``_classify_shell`` or gateway-mode allowlist enforcement. Gateway
stays fail-closed without an execution grant.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cato.auth.token_checker import _DEFAULT_ALLOWED_TOOLS
from cato.config import CatoConfig
from cato.safety import RiskTier, _classify_shell, _normalize_shell_for_scan
from cato.tools.shell import ShellTool


# ---------------------------------------------------------------------------
# Policy / config baselines (pre-existing)
# ---------------------------------------------------------------------------

def test_shell_variants_policy():
    """Only 'shell' is in the default-allowed whitelist (the tool has its own
    gateway allowlist as its security boundary).  The higher-privilege variants
    (shell_execute, shell.exec, python.execute) still require explicit delegation."""
    assert "shell" in _DEFAULT_ALLOWED_TOOLS, "shell must be in default-allowed list"

    restricted = {"shell_execute", "shell.exec", "python.execute"}
    overlap = restricted & set(_DEFAULT_ALLOWED_TOOLS)
    assert not overlap, f"High-privilege shell variants found in whitelist: {overlap}"


@pytest.mark.parametrize("verb", [
    "remove-item", "clear-content", "format-volume",
    "stop-process", "invoke-expression", "iex",
])
def test_powershell_destructive_verbs_blocked(verb):
    """Each PS destructive verb must classify as IRREVERSIBLE."""
    tier = _classify_shell({"command": f"{verb} C:\\temp\\foo"})
    assert tier == RiskTier.IRREVERSIBLE, f"{verb!r} classified as {tier}, expected IRREVERSIBLE"


def test_powershell_full_mode_default_false():
    """CatoConfig default must have powershell_full_mode == False."""
    cfg = CatoConfig()
    assert cfg.powershell_full_mode is False


def test_shell_hosts_not_in_default_allowlist():
    """cmd/powershell/pwsh/rm must not be default-gateway — Windows shell hosts
    would otherwise execute the full attacker string after first-token match."""
    default = set(ShellTool.DEFAULT_ALLOWLIST)
    banned = {
        "rm", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    }
    assert not (default & banned), f"shell hosts still default-allowlisted: {default & banned}"
    extended = set(ShellTool.EXTENDED_ALLOWLIST)
    assert banned <= extended, "shell hosts must remain opt-in via EXTENDED_ALLOWLIST"


# ---------------------------------------------------------------------------
# C-2 adversarial classification fuzz
# ---------------------------------------------------------------------------

# Patterns that previously classified as REVERSIBLE_WRITE under plain split().
_ADVERSARIAL_IRREVERSIBLE = [
    '"remove-item" C:\\temp\\foo',
    "'remove-item' C:\\temp\\foo",
    'powershell -Command "Remove-Item C:\\temp\\foo"',
    'powershell -c "& {Remove-Item x}"',
    "rem`ove-item C:\\x",
    'remove""-item C:\\x',
    'powershell -Command "Invoke-Expression (\'rm x\')"',
    '"rm" -rf /tmp/x',
    "r''m -rf /tmp/x",
    'powershell -Command ("re"+"move-item") file',
    'powershell -Command "re"+"move-item" file',
    "cmd /c rem^ove-item x",
    "I`e`x 'rm x'",
    "Remove.Item C:\\x",
    "echo hi & del C:\\temp\\foo",
    "echo hi && rm -rf /tmp/x",
]


@pytest.mark.parametrize("command", _ADVERSARIAL_IRREVERSIBLE)
def test_classify_shell_adversarial_irreversible(command):
    """Quote / escape / concat dodges must still escalate to IRREVERSIBLE."""
    tier = _classify_shell({"command": command})
    assert tier >= RiskTier.IRREVERSIBLE, (
        f"dodge classified as {tier.name}: {command!r} "
        f"(normalized={_normalize_shell_for_scan(command)!r})"
    )


@pytest.mark.parametrize("command", [
    'powershell -EncodedCommand RQBYAA==',
    "pwsh -enc RQBYAA==",
    "git push origin main",
    "commit --amend -m x",
])
def test_classify_shell_adversarial_high_stakes(command):
    tier = _classify_shell({"command": command})
    assert tier == RiskTier.HIGH_STAKES, f"{command!r} -> {tier.name}"


def test_classify_shell_benign_echo_stays_reversible():
    assert _classify_shell({"command": "echo hello"}) == RiskTier.REVERSIBLE_WRITE


# ---------------------------------------------------------------------------
# Gateway execute E2E — fail closed, no runner invocation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("command", _ADVERSARIAL_IRREVERSIBLE)
async def test_gateway_execute_adversarial_fail_closed(command, monkeypatch, tmp_path):
    """ShellTool.execute (gateway / mode omitted) must refuse dodge payloads
    without calling the subprocess runner and without an execution grant."""
    from cato.core.approval_policy import clear_execution_grants

    clear_execution_grants()
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "cato.tools.shell.ShellTool._run_sandbox",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not execute")),
    )
    monkeypatch.setattr(
        "cato.tools.shell.ShellTool._run_full",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not execute")),
    )

    tool = ShellTool()
    # Force default allowlist (ignore operator exec-approvals.json)
    monkeypatch.setattr(tool, "_load_allowlist", lambda: set(ShellTool.DEFAULT_ALLOWLIST) | {
        # Even if an operator opted hosts back in, risk scan must still refuse.
        "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
        "rm", "echo",
    })

    out = json.loads(await tool.execute({"command": command}))
    assert out.get("blocked") is True, out
    assert out.get("approval_required") is True, out
    assert "error" in out
    assert "IRREVERSIBLE" in out["error"] or "HIGH_STAKES" in out["error"] or "allowlist" in out["error"]


@pytest.mark.asyncio
async def test_gateway_execute_mode_omitted_same_as_gateway(monkeypatch, tmp_path):
    from cato.core.approval_policy import clear_execution_grants

    clear_execution_grants()
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "cato.tools.shell.ShellTool._run_sandbox",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not execute")),
    )

    tool = ShellTool()
    monkeypatch.setattr(
        tool,
        "_load_allowlist",
        lambda: set(ShellTool.DEFAULT_ALLOWLIST) | {"powershell", "powershell.exe"},
    )
    out = json.loads(await tool.execute({
        "command": 'powershell -Command "Remove-Item C:\\temp\\foo"',
    }))
    assert out["blocked"] is True
    assert out["requested_mode"] == "gateway"


@pytest.mark.asyncio
async def test_gateway_benign_echo_still_runs(monkeypatch, tmp_path):
    """Hardening must not brick ordinary allowlisted gateway commands."""
    from cato.core.approval_policy import clear_execution_grants

    clear_execution_grants()
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))

    async def _fake_run(self, **kw):
        assert kw["mode"] == "gateway"
        return {"stdout": "hi\n", "stderr": "", "returncode": 0, "truncated": False}

    monkeypatch.setattr("cato.tools.shell.ShellTool._run", _fake_run)
    out = json.loads(await ShellTool().execute({"command": "echo hi"}))
    assert out["returncode"] == 0
    assert out["stdout"].startswith("hi")


@pytest.mark.asyncio
async def test_full_mode_still_requires_grant(monkeypatch, tmp_path):
    """Unrestricted full mode remains fail-closed without an execution grant."""
    from cato.core.approval_policy import clear_execution_grants

    clear_execution_grants()
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "cato.tools.shell.ShellTool._run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("full must not run")),
    )
    out = json.loads(await ShellTool().execute({
        "command": "rm -rf /tmp/x",
        "mode": "full",
    }))
    assert out["approval_required"] is True
    assert "execution ticket" in out["error"].lower() or "mode" in out["error"].lower()


@pytest.mark.asyncio
async def test_gateway_unbalanced_quotes_fail_closed(monkeypatch, tmp_path):
    from cato.core.approval_policy import clear_execution_grants

    clear_execution_grants()
    monkeypatch.setenv("CATO_WORKSPACE_DIR", str(tmp_path))
    out = json.loads(await ShellTool().execute({"command": 'echo "unterminated'}))
    assert out["blocked"] is True
