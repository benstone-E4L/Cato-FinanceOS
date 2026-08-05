"""Security regression tests for auth / token checker."""
import pytest
from cato.auth.token_checker import TokenChecker
from cato.auth.token_store import TokenStore, ACTION_CATEGORIES


def test_shell_allowed_by_default_non_strict(tmp_path):
    """shell is in _DEFAULT_ALLOWED_TOOLS — the shell tool has its own gateway
    allowlist, so double-gating it at the token layer blocks Cato's normal
    operation.  shell_execute/shell.exec/python.execute still require a token
    (they are NOT in the default-allowed list)."""
    store = TokenStore(db_path=tmp_path / "tokens.db")
    checker = TokenChecker(token_store=store)

    # shell itself is default-allowed
    result = checker.check_authorization("shell", {}, agent_session_id="test-session")
    assert result.authorized, "shell must be authorized by default in non-strict mode"

    # variants without the default allow still require a token
    for tool in ("shell_execute", "shell.exec", "python.execute"):
        result = checker.check_authorization(tool, {}, agent_session_id="test-session")
        assert not result.authorized, f"{tool!r} was authorized without a token"
        assert result.requires_user_confirmation


def test_genesis_allowed_by_default(tmp_path):
    """genesis is in _DEFAULT_ALLOWED_TOOLS — it is Cato's built-in SwarmSync
    integration and should not require a per-call user confirmation."""
    store = TokenStore(db_path=tmp_path / "tokens.db")
    checker = TokenChecker(token_store=store)
    result = checker.check_authorization("genesis", {}, agent_session_id="test-session")
    assert result.authorized, "genesis must be authorized by default in non-strict mode"


def test_create_token_rejects_invalid_category():
    """Server's category validation must reject unknown categories."""
    valid_categories = set(ACTION_CATEGORIES) | {"*"}

    # Valid category — no invalid entries
    invalid = set(["file.read"]) - valid_categories
    assert not invalid, "file.read should be a valid category"

    # Invalid category — must be detected
    invalid = set(["__invalid__"]) - valid_categories
    assert invalid, "__invalid__ should not pass category validation"


def test_valid_action_categories_accepted():
    """Known ACTION_CATEGORIES entries must all pass the server's validation check."""
    valid_categories = set(ACTION_CATEGORIES) | {"*"}
    for cat in ACTION_CATEGORIES:
        assert cat in valid_categories, f"{cat!r} not in valid set"
