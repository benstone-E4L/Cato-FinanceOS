---
name: self-improvement
description: "Captures learnings, errors, and corrections to enable continuous improvement. Use when: (1) A command or operation fails unexpectedly, (2) User corrects me ('No, that's wrong...', 'Actually...'), (3) User requests a capability that doesn't exist, (4) An external API or tool fails, (5) I realize my knowledge is outdated or incorrect, (6) A better approach is discovered for a recurring task. Also review learnings before major tasks."
---

# Self-Improvement Skill

Log learnings and errors to markdown files for continuous improvement. Important learnings get promoted to MEMORY.md.

<!-- COLD -->

## Quick Reference

| Situation | Action |
|-----------|--------|
| Command fails | Log as Error entry |
| User corrects me | Log as Learning entry |
| Missing capability | Log as Feature Request |
| Knowledge outdated | Log as Learning entry |
| Better approach found | Log as Learning entry |
| Before major task | Review recent learnings |

## Log File

All entries go to: `~/.openclaw/workspace/learnings/LEARNINGS.md`
(append-only — never overwrite, never summarize, just append)

## Logging Format

### Learning Entry
```
### LEARN-YYYYMMDD-XXX
**Date:** YYYY-MM-DD
**Area:** [frontend|backend|infra|tests|docs|config|openclaw|pipeline]
**Priority:** [critical|high|normal|low]
**Trigger:** What prompted this learning
**Learning:** What was learned
**Action:** What to do differently next time
**Status:** open
```

### Error Entry
```
### ERR-YYYYMMDD-XXX
**Date:** YYYY-MM-DD
**Area:** [area]
**Priority:** [priority]
**Error:** What went wrong
**Root Cause:** Why it happened
**Fix:** How it was resolved
**Prevention:** How to avoid in future
**Status:** open
```

### Feature Request Entry
```
### FEAT-YYYYMMDD-XXX
**Date:** YYYY-MM-DD
**Area:** [area]
**Priority:** [priority]
**Request:** What capability is needed
**Use Case:** When this would be useful
**Status:** open
```

## Promotion to MEMORY.md

When a learning is broadly applicable:
1. Add to MEMORY.md under "Lessons Learned" section
2. Mark original entry status as "promoted"
3. Reference the promoted location

## Detection Triggers

- Corrections: "No, that's wrong", "Actually...", "I meant..."
- Feature requests: "Can you...", "I wish you could..."
- Knowledge gaps: "I'm not sure about...", "Let me check..."
- Errors: Non-zero exit codes, exception traces, API failures

## Rules

1. Log immediately when trigger detected
2. Use specific, searchable area tags
3. Include actionable prevention steps
4. Review learnings before similar tasks
5. Promote broadly applicable learnings to MEMORY.md
6. Keep entries concise but complete
7. Never announce memory operations to user — just do it
8. Periodically review and resolve old entries during heartbeats
