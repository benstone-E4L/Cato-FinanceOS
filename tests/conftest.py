"""
tests/conftest.py — Pytest configuration for the Cato test suite.

Pre-imports the real cato package before any test collection begins so that
bootstrap-style tests (test_extraction_actions, test_browser_actions, etc.)
see the real modules in sys.modules and do NOT overwrite them with stubs.

Those test files call _make_pkg_stub() only when the key is absent:
    if name in sys.modules: return sys.modules[name]
So pre-loading the real package prevents all stub pollution.
"""
import sys
import pytest


def pytest_configure(config):
    """
    Pre-import the real cato package before test collection starts.

    This ensures the real `cato`, `cato.tools`, and `cato.platform` modules
    are in sys.modules before any bootstrap-style test file is imported.
    Those files guard with `if name in sys.modules: return sys.modules[name]`
    so they won't overwrite the real package with stubs.
    """
    try:
        import cato          # noqa: F401
        import cato.tools    # noqa: F401
        import cato.platform # noqa: F401
    except Exception:
        pass  # If cato isn't installed yet, don't block collection


@pytest.fixture(autouse=True, scope="function")
def restore_cato_modules():
    """
    Save real cato module references before each test and restore them after.

    Belt-and-suspenders: even if a test somehow replaces sys.modules entries,
    we restore them to the real modules after each test function completes.
    """
    _keys = ["cato", "cato.tools", "cato.platform"]
    saved = {k: sys.modules.get(k) for k in _keys}
    yield
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
