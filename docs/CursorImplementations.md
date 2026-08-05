Summary of what was done in Cato (C:\Users\Administrator\Desktop\Cato) against your checklist:
1) ConduitBridge instantiations
tests/test_audit_chain.py — All 6 uses now use the config-dict form:
ConduitBridge(cfg_dict, session_id) with cfg_dict = {"conduit_budget_per_session": ..., "data_dir": str(...)}.
No remaining legacy ConduitBridge(session_id, budget_cents=..., data_dir=...) in tests.
tests/test_e2e_cato.py — Already used the dict + session_id pattern; left as-is.
cato/tools/conduit_bridge.py — Docstring updated to recommend the config-driven pattern and to say legacy style does not set _config.
Live path — cato/tools/__init__.py uses ConduitBrowserTool(agent_loop._cfg, agent_loop._budget), which builds the bridge via to_conduit_bridge_config(...) (see below). No direct legacy ConduitBridge(...) in production code.
2) Config compatibility
CatoConfig (in cato/config.py) already has load() from YAML and now includes Conduit-related fields:
conduit_extract_max_chars, searxng_url, search_rerank_enabled, conduit_crawl_delay_sec, conduit_crawl_max_delay_sec, selector_healing_enabled, vault (and optional data_dir / conduit_budget_per_session in to_conduit_bridge_config).
to_conduit_bridge_config(session_id, data_dir=..., conduit_budget_per_session=...) is implemented and used where the bridge is created.
3) Bridge uses shared config
cato/tools/conduit_bridge.py
Dict constructor — When the first argument is a dict, self._config is set (and self._config = {} for the legacy string-first form).
Consumption of _config
extract_main — max_chars default from _config.conduit_extract_max_chars, and fmt supported.
map_site / crawl_site — ConduitCrawler is created with crawl_delay_sec and crawl_max_delay_sec from _config.
click, type_text, fill, hover — Use _try_selector_healing when _config.selector_healing_enabled is true; healing is logged to the audit log.
Safe defaults used when keys are missing (e.g. cfg.get(..., 1.0)).
cato/tools/conduit_crawl.py — ConduitCrawler now takes optional crawl_delay_sec and crawl_max_delay_sec and uses _wait_crawl_delay() before each request.
4) Tool registration
cato/gateway.py — Builds the loop then:
register_all_tools(loop) from cato.tools (shell, file, memory, browser).
register_conduit_web_tools(loop.register_tool, self._cfg) from cato.agent_loop so web search tools get config.
cato/agent_loop.py — Defines register_all_tools(register_tool_fn, config) and AgentLoop.register_tool; web search registration receives config.
cato/tools/_init_.py — Uses agent_loop._cfg (fixed from _config), and when conduit_enabled uses ConduitBrowserTool, which builds the bridge with cfg.to_conduit_bridge_config(...).
5) ConduitBrowserTool and exports
ConduitBrowserTool added in cato/tools/conduit_bridge.py: takes (config, budget), implements async execute(args) by building ConduitBridge(bridge_cfg, session_id) with config.to_conduit_bridge_config(...) and delegating to the bridge.
cato.tools continues to export register_all_tools (and other tools); gateway imports from .tools and .agent_loop without circular dependency.
6) AgentLoop
AgentLoop in cato/agent_loop.py is the full loop (run, budget, memory, etc.). It has register_tool(self, name, fn) delegating to the module-level registry, so register_all_tools(loop.register_tool, self._cfg) is valid and used by the gateway.
7) Regression tests
tests/test_conduit_config.py added with:
CatoConfig.to_conduit_bridge_config — Required keys, optional data_dir/conduit_budget_per_session, and extraction/crawl values.
ConduitBridge — Accepts dict config and sets _config; legacy positional form still works and leaves _config empty.
register_all_tools — Registers tools (via global registry) and accepts (register_tool_fn, config).
Bridge config consumption — _config is set and used for crawl delay and extract_main default.
8) Documentation and cleanup
docs/CONDUIT_INTEGRATION.md — Describes the config-driven bridge pattern, required config fields, tool registration, and tests.
ConduitBridge docstring in code — Preferred pattern with to_conduit_bridge_config and note on legacy form.
No temporary debug logging added; no duplicated config left in the changes.
9–10) Manual checks for you
Symlinked Cato ↔ Conduit — Not verified here; run your usual symlink setup and imports from the real entrypoint.
Functional integration — With conduit_enabled=true, start Cato, trigger a flow that uses the browser/search, and confirm in logs or behavior that:
crawl delay, extraction limit, selector healing, and (if set) SearXNG/rerank/vault match config.
Legacy constructor regression — The test test_legacy_positional_session_id_still_works ensures ConduitBridge(session_id, budget_cents=..., data_dir=...) still works and sets _config = {}.
All 23 tests in tests/test_conduit_config.py and tests/test_audit_chain.py pass. Run the full Cato test suite and your integration flow once more to confirm nothing else is broken.

Files:
test_audit_chain.py +14-26
conduit_crawl.py +24 -1
config.py +49
agent_loop.py +10
test_conduit_config.py +169
_init _. py +2 -2
conduit_bridge.py +141 -27
gateway.py +3 -1
CONDUIT_INTEGRATION.md +53
