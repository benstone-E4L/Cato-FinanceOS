# AGENTS — Cato's Coding Backends

Cato dispatches coding tasks to CLI agents running as subprocesses on this machine.

## Codex — PRIMARY
- **Invoke**: `codex mcp-server` (MCP JSON-RPC over stdio)
- **Mode**: Warm pool — process started at daemon startup, stays resident
- **Auth**: None required — runs locally
- **Bypass flag**: `--dangerously-bypass-approvals-and-sandbox`
- **Status**: Working
- **Use for**: Code generation, file edits, shell commands, general tasks

## Cursor Agent — SECONDARY
- **Invoke**: `node.exe index.js --print --trust --yolo --model auto`
- **Path**: `%LOCALAPPDATA%\cursor-agent\versions\2026.02.27-e7d2ef6\`
- **Auth**: Cursor IDE session (must be logged into Cursor IDE)
- **Status**: Working — confirmed responding
- **Use for**: Complex multi-file tasks, Cursor's built-in model routing

## Gemini — TERTIARY (degraded)
- **Invoke**: `gemini -p <prompt>`
- **Auth**: Authenticated (`AIzaSyAc5lGnaAGDLlYsG1EOfceobFVK9Ge_FeA`)
- **Status**: Degraded — hangs non-interactively on this VPS (needs TTY)
- **Use for**: Only if Codex and Cursor are unavailable

## Claude CLI — BLOCKED
- **Reason**: Cato runs inside Claude Code — nested invocation blocked
- **Alternative**: Chat uses OpenRouter directly (not Claude CLI)

## Active Configuration
```yaml
subagent_enabled: true
primary_coding_backend: codex
fallback_backend: cursor
enabled_models: [codex, cursor, gemini]
```

## Notes
- All CLIs are `.cmd` files on Windows — resolved via `shutil.which()` + `cmd.exe /c`
- Codex warm pool: if process dies, Cato respawns it automatically
- Cursor Agent does NOT need a running Cursor IDE — just the stored session
