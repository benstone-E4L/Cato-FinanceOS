# Remote MCP Setup

Cato can now expose a remote MCP endpoint for Claude custom connectors.

## Connector Values

- Name: `Cato`
- Remote MCP server URL: `https://mcp.your-domain.com/mcp`
- OAuth Client ID: leave blank
- OAuth Client Secret: leave blank

## Local Runtime

When `mcp_enabled: true`, Cato starts an internal MCP server and proxies it through the main aiohttp server:

- MCP route: `/mcp`
- MCP health route: `/mcp/health`

Default local settings:

- `mcp_host: 127.0.0.1`
- `mcp_port: 8765`

## Public Reverse Proxy Example

Point a public HTTPS hostname such as `mcp.directorybolt.com` at the VPS, then proxy:

- `https://mcp.directorybolt.com/mcp` -> `http://127.0.0.1:8080/mcp`
- `https://mcp.directorybolt.com/mcp/health` -> `http://127.0.0.1:8080/mcp/health`

Claude.ai expects the HTTPS URL, not the local port.
