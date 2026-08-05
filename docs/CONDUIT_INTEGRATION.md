# Conduit integration (config-driven)

When Conduit is enabled (`conduit\_enabled: true` in config), Cato uses a config-driven Conduit bridge so that extraction limits, crawl delay, selector healing, and vault come from **CatoConfig**.

## Creating the bridge

**Use the config-driven constructor everywhere:**

```python
from cato.config import CatoConfig
from cato.platform import get\_data\_dir
from cato.tools.conduit\_bridge import ConduitBridge

cfg = CatoConfig.load()  # or your runtime config
session\_id = "my-session"

bridge = ConduitBridge(
    cfg.to\_conduit\_bridge\_config(
        session\_id,
        data\_dir=str(get\_data\_dir()),
        conduit\_budget\_per\_session=cfg.conduit\_budget\_per\_session,
    ),
    session\_id,
)
await bridge.start()
# ... use bridge ...
await bridge.stop()
```

**Do not** use the legacy form `ConduitBridge(session\_id, budget\_cents=..., data\_dir=...)` in new code; it leaves `\_config` empty so extraction/crawl/selector-healing from config are not applied.

## Config fields used by the bridge

|Field|Purpose|
|-|-|
|`conduit\_extract\_max\_chars`|Default max chars for `extract\_main`|
|`conduit\_crawl\_delay\_sec` / `conduit\_crawl\_max\_delay\_sec`|Crawl rate limiting|
|`selector\_healing\_enabled`|ARIA/text fallback for click, type, fill, hover|
|`vault`|API keys and credentials (search, login)|
|`searxng\_url` / `search\_rerank\_enabled`|Used by WebSearchTool when registered with config|

## Tool registration

* **Gateway** calls `register\_all\_tools(loop)` (from `cato.tools`) then `register\_all\_tools(loop.register\_tool, self.\_cfg)` (from `cato.agent\_loop`) so that:

  * Shell, file, memory, and browser (Conduit when enabled) are registered.
  * Web search tools (web.search, web.code, etc.) are registered with **config** so SearXNG, reranking, and vault are used.
* When `conduit\_enabled` is true, the browser tool is a `ConduitBrowserTool` that builds the bridge with `cfg.to\_conduit\_bridge\_config(...)` per session.

## Tests

* `tests/test\_conduit\_config.py` — regression tests for `to\_conduit\_bridge\_config()`, bridge dict config, and tool registration with config.
* `tests/test\_audit\_chain.py` — all ConduitBridge creation uses the config-dict pattern.

