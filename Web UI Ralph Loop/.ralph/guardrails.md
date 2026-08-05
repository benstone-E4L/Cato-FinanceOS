# Guardrails - Lessons Learned

### Sign: Onboarding overlay is the root cause of ALL navigation failures
- **Trigger**: Fixing navigation in dashboard.html
- **Instruction**: The `<div id="onboarding-overlay">` intercepts pointer events and blocks ALL nav clicks. Fix the overlay first — it resolves 17 bugs at once.
- **Source**: Web UI audit — every nav click failed with the same error

### Sign: dashboard.html is a monolithic 1700+ line file
- **Trigger**: Editing dashboard.html
- **Instruction**: Be careful with line numbers — they shift. Use unique string matches for edits, not line numbers.
- **Source**: Codebase analysis

### Sign: Bot name "AI" appears in 3 specific locations
- **Trigger**: Renaming bot from "AI" to "Cato"
- **Instruction**: Lines 1432 (renderMessages), 1439 (typing-indicator), 1549 (startStreaming). Search for all instances.
- **Source**: Web UI audit

### Sign: Backend fixes from Desktop App loop carry over
- **Trigger**: Starting Web UI work
- **Instruction**: CORS PUT fix, config security filter, CLI status improvements, heartbeat metrics, config reload — these are already done from the Desktop App loop. Don't redo them.
- **Source**: Desktop App Ralph Loop Chunks 1 & 6
