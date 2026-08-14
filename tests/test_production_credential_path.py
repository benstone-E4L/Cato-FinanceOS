from __future__ import annotations

import ast
import os
from pathlib import Path
from uuid import uuid4

from cato.vault import Vault
from cato.vault_bootstrap import (
    OPERATOR_VAULT_KEYS,
    bootstrap_launch_credentials,
    safe_subprocess_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ENTRYPOINTS = (
    REPO_ROOT / "cato_svc_runner.py",
    REPO_ROOT / "cato_service.py",
    REPO_ROOT / "cato" / "cli.py",
)
CHILD_PROCESS_LAUNCHERS = (
    REPO_ROOT / "cato" / "pipeline" / "workers.py",
    REPO_ROOT / "cato" / "orchestrator" / "cli_process_pool.py",
    REPO_ROOT / "cato" / "orchestrator" / "cli_invoker.py",
    REPO_ROOT / "cato" / "api" / "pty_routes.py",
    REPO_ROOT / "cato" / "tools" / "github_tool.py",
    REPO_ROOT / "cato" / "gateway.py",
    REPO_ROOT / "cato_telegram_bridge.py",
)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _attribute_name(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def test_all_production_entrypoints_disable_dotenv_launch_loading():
    for path in PRODUCTION_ENTRYPOINTS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _call_name(node) == "bootstrap_launch_credentials"
        ]
        assert calls, path.name
        for call in calls:
            keyword = next(item for item in call.keywords if item.arg == "load_dotenv")
            assert isinstance(keyword.value, ast.Constant)
            assert keyword.value.value is False


def test_production_source_has_no_operator_credential_environment_access():
    operator_keys = set(OPERATOR_VAULT_KEYS)
    violations: list[tuple[str, int, str]] = []
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in {"tests", "proof-artifacts", "test-outputs", "venv", ".venv"} for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _attribute_name(node.func) in {
                "os.environ.get",
                "os.getenv",
                "_os.environ.get",
                "_os.getenv",
            }:
                key = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
                if key in operator_keys:
                    violations.append((str(path.relative_to(REPO_ROOT)), node.lineno, "read"))
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Subscript):
                        continue
                    if _attribute_name(target.value) not in {"os.environ", "_os.environ"}:
                        continue
                    key = target.slice.value if isinstance(target.slice, ast.Constant) else None
                    if key in operator_keys:
                        violations.append((str(path.relative_to(REPO_ROOT)), node.lineno, "write"))
    assert violations == []


def test_cli_launchers_use_minimal_subprocess_environment():
    for path in CHILD_PROCESS_LAUNCHERS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        call_names = {
            _call_name(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        assert "safe_subprocess_environment" in call_names, path.name
        assert "items" not in {
            _call_name(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _attribute_name(node.func).endswith("environ.items")
        }, path.name


def test_minimal_subprocess_environment_excludes_operator_credentials():
    secret_value = uuid4().hex
    source = {
        "PATH": os.defpath,
        "TEMP": str(Path.cwd()),
        "ANTHROPIC_API_KEY": secret_value,
        "GH_TOKEN": secret_value,
        "CATO_VAULT_PASSWORD": secret_value,
        "CLAUDECODE": "1",
        "UNRELATED_PARENT_SETTING": "not-inherited",
    }

    child_env = safe_subprocess_environment(source)

    assert child_env["PATH"] == os.defpath
    assert child_env["TEMP"] == str(Path.cwd())
    assert secret_value not in child_env.values()
    assert set(child_env).isdisjoint(
        {"ANTHROPIC_API_KEY", "GH_TOKEN", "CATO_VAULT_PASSWORD", "CLAUDECODE"}
    )


def test_launch_consumes_unlock_passphrase_and_never_exports_vault_value(
    tmp_path, monkeypatch
):
    import cato.vault as vault_mod

    password = uuid4().hex
    stored_value = uuid4().hex
    monkeypatch.setattr(vault_mod, "_CACHED_VAULT_PASSWORD", None)
    monkeypatch.setenv("CATO_VAULT_PASSWORD", password)
    vault_path = tmp_path / "vault.enc"
    vault = Vault(vault_path=vault_path)
    vault.unlock(password, allow_create=True)
    vault.set("ANTHROPIC_API_KEY", stored_value)

    unlocked, _report = bootstrap_launch_credentials(
        vault_path=vault_path,
        require_password=True,
        load_dotenv=False,
    )

    assert unlocked is not None
    assert unlocked.get("ANTHROPIC_API_KEY") == stored_value
    assert "CATO_VAULT_PASSWORD" not in os.environ
    assert "ANTHROPIC_API_KEY" not in os.environ
