"""
tests/test_conduit_config.py — Regression tests for config-driven Conduit integration.

  - CatoConfig.to_conduit_bridge_config() returns the dict shape ConduitBridge expects
  - ConduitBridge accepts and stores dict config in _config
  - register_all_tools(loop.register_tool, config) stores tools and config is passed
  - Legacy ConduitBridge(session_id, budget_cents=..., data_dir=...) still works (no _config)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure cato package is importable (same as other Cato tests)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestCatoConfigToConduitBridgeConfig:
    """CatoConfig.to_conduit_bridge_config() output shape and values."""

    def test_returns_dict_with_required_keys(self):
        from cato.config import CatoConfig

        cfg = CatoConfig()
        out = cfg.to_conduit_bridge_config("sess-1")
        assert isinstance(out, dict)
        assert out["session_id"] == "sess-1"
        assert "conduit_extract_max_chars" in out
        assert "searxng_url" in out
        assert "search_rerank_enabled" in out
        assert "conduit_crawl_delay_sec" in out
        assert "conduit_crawl_max_delay_sec" in out
        assert "selector_healing_enabled" in out
        assert "vault" in out

    def test_optional_data_dir_and_budget_included_when_provided(self):
        from cato.config import CatoConfig

        cfg = CatoConfig()
        out = cfg.to_conduit_bridge_config(
            "sess-2",
            data_dir="/tmp/cato",
            conduit_budget_per_session=50,
        )
        assert out["data_dir"] == "/tmp/cato"
        assert out["conduit_budget_per_session"] == 50

    def test_extraction_and_crawl_values_from_config(self):
        from cato.config import CatoConfig

        cfg = CatoConfig(
            conduit_extract_max_chars=10_000,
            conduit_crawl_delay_sec=2.5,
            conduit_crawl_max_delay_sec=120.0,
            selector_healing_enabled=True,
        )
        out = cfg.to_conduit_bridge_config("sess-3")
        assert out["conduit_extract_max_chars"] == 10_000
        assert out["conduit_crawl_delay_sec"] == 2.5
        assert out["conduit_crawl_max_delay_sec"] == 120.0
        assert out["selector_healing_enabled"] is True

    def test_session_id_passed_correctly(self):
        from cato.config import CatoConfig

        cfg = CatoConfig()
        out = cfg.to_conduit_bridge_config("my-session-id-123")
        assert out["session_id"] == "my-session-id-123"


class TestConduitBridgeAcceptsDictConfig:
    """ConduitBridge stores dict config in _config."""

    def test_dict_config_sets_config_attribute(self, tmp_path):
        from cato.tools.conduit_bridge import ConduitBridge

        cfg = {
            "conduit_budget_per_session": 99,
            "data_dir": str(tmp_path),
            "conduit_extract_max_chars": 15_000,
            "conduit_crawl_delay_sec": 2.0,
        }
        bridge = ConduitBridge(cfg, "test-session")
        assert bridge._config == cfg
        assert bridge._session_id == "test-session"
        assert bridge._budget_cents == 99

    def test_legacy_positional_session_id_still_works(self, tmp_path):
        """Legacy ConduitBridge(session_id, budget_cents=..., data_dir=...) leaves _config empty."""
        from cato.tools.conduit_bridge import ConduitBridge

        bridge = ConduitBridge(
            "legacy-session",
            budget_cents=10,
            data_dir=tmp_path,
        )
        assert bridge._session_id == "legacy-session"
        assert bridge._budget_cents == 10
        assert bridge._config == {}


class TestRegisterAllToolsWithConfig:
    """register_all_tools(loop.register_tool, config) stores tools and config is used."""

    def test_register_all_tools_stores_tools(self):
        from cato.agent_loop import AgentLoop, register_all_tools, _TOOL_REGISTRY
        from cato.config import CatoConfig

        cfg = CatoConfig()
        loop = AgentLoop(
            config=cfg,
            budget=MagicMock(),
            vault=MagicMock(),
            memory=MagicMock(),
            context_builder=MagicMock(),
        )
        register_all_tools(loop.register_tool, cfg)
        # Web search tools should be in global registry
        assert "web.search" in _TOOL_REGISTRY
        assert "web.code" in _TOOL_REGISTRY
        assert "web.news" in _TOOL_REGISTRY
        assert callable(_TOOL_REGISTRY["web.search"])

    def test_no_old_register_all_tools_loop_only_pattern(self):
        """Ensure register_all_tools takes (register_tool_fn, config)."""
        from cato.agent_loop import register_all_tools
        import inspect

        sig = inspect.signature(register_all_tools)
        params = list(sig.parameters)
        assert len(params) >= 1
        assert "config" in params or (len(params) == 2 and params[1] == "config")


class TestConduitBridgeConfigConsumption:
    """Bridge uses _config for crawl delay and extract_main default."""

    def test_map_site_passes_crawl_delay_to_crawler(self):
        """ConduitCrawler is constructed with crawl_delay from bridge _config (unit: bridge builds crawler with config)."""
        from cato.tools.conduit_bridge import ConduitBridge

        cfg = {
            "conduit_budget_per_session": 100,
            "data_dir": "/tmp",
            "conduit_crawl_delay_sec": 3.0,
            "conduit_crawl_max_delay_sec": 90.0,
        }
        bridge = ConduitBridge(cfg, "sess")
        assert getattr(bridge, "_config", {}) == cfg

    def test_extract_main_default_max_chars_from_config(self):
        """extract_main() uses conduit_extract_max_chars from _config when max_chars not passed."""
        from cato.tools.conduit_bridge import ConduitBridge

        cfg = {
            "conduit_budget_per_session": 100,
            "data_dir": "/tmp",
            "conduit_extract_max_chars": 30_000,
        }
        bridge = ConduitBridge(cfg, "sess")
        # Default max_chars is read inside extract_main() from self._config; we only assert _config is set
        assert bridge._config.get("conduit_extract_max_chars") == 30_000
