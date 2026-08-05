# Super-GitHub
**Version:** 1.0.0
**Capabilities:** github.pr.review, github.pr.merge, github.issue.create, github.issue.list, github.release.create

## Overview
GitHub operations with optional 3-model AI PR review pipeline.
Uses the `gh` CLI and injects `GH_TOKEN` from the Cato vault.

## Setup
```bash
# Store your GitHub token in the vault
cato vault set github_token ghp_xxxxxxxxxxxx
```

## 3-Model PR Review Pipeline
1. Fetch diff via `gh pr diff <number>`
2. Dispatch Claude / Codex / Gemini in parallel (cli_process_pool)
3. Score confidence via confidence_extractor
4. Abort if models diverge via early_terminator (threshold 0.85)
5. Synthesize via synthesis.simple_synthesis
6. Post comment via `gh pr comment`

## CLI Usage
```bash
# Review a PR
cato github pr review 123
cato github pr review https://github.com/org/repo/pull/123

# Merge a PR
cato github pr merge 42 --method squash

# Issues
cato github issue list
cato github issue create --title "Bug: crash on startup" --body "..."

# Release
cato github release --tag v1.2.0 --notes "Bug fixes and improvements"
```

<!-- COLD -->
## Security
- GitHub token stored encrypted in vault (`github_token`)
- Token injected as `GH_TOKEN` env var — never written to disk or logs
- All `gh` subprocess outputs are sanitized before display
- Token redacted from AuditLog inputs automatically

## Windows Compatibility
- `gh` resolved via `shutil.which()`, wrapped in `cmd.exe /c` for .CMD wrappers
- Identical pattern to codex/gemini in `cli_invoker.py`
