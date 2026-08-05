# PROMPT_build.md - Chunk 1: Workspace Template Files

**Chunk**: 1 / 6
**Iteration**: See `.ralph/.iteration`
**Max Retries**: 5
**Promise**: Write `<promise>CHUNK_1_COMPLETE</promise>` when ALL subtasks done and tests pass

---

## MISSION

Implement foundational workspace memory templates for Cato OpenClaw integration.

Users will configure their agent's personality, memory, and behavior through these templates — just like OpenClaw.

---

## REQUIREMENTS

### Subtask 1.1: Create AGENTS.md Template

**Path**: `~/.cato/workspace/AGENTS.md`

**Content** (template, user edits later):
```markdown
# Agent Operating Manual

## Thinking Framework
- Pause before responding
- Break complex tasks into steps
- Verify assumptions
- Ask clarifying questions if needed

## Tool Usage
- Use coding-agent for programming tasks
- Use web-browser for research
- Use memory to store important facts

## Safety Rules
- Never execute unverified commands
- Ask for permission before deleting files
- Validate API responses before using

## Response Style
- Be concise and direct
- Include reasoning for decisions
- Offer alternatives when appropriate
```

**Acceptance**: File exists, valid markdown, < 1000 tokens

---

### Subtask 1.2: Create MEMORY.md Template

**Path**: `~/.cato/workspace/MEMORY.md`

**Content** (template):
```markdown
# Long-Term Memory

## Projects
- Project 1: Description here

## Technical Notes
- Note 1: Technical decision made
- Note 2: Configuration detail

## Decisions
- Decision 1: Why we chose X over Y

## User Preferences
- Preference 1: How user likes things done
```

**Acceptance**: File exists, valid markdown, supports semantic search format

---

### Subtask 1.3: Create USER.md Template

**Path**: `~/.cato/workspace/USER.md`

**Content** (template):
```markdown
# User Profile

## Name & Background
[User's name and role]

## Preferences
- Communication style: [brief/detailed/technical]
- Time zone: [UTC/EST/etc]
- Response format: [bullet points/paragraphs/code blocks]

## Availability
- Active hours: [e.g., 9am-6pm EST]
- Response time preference: [immediate/within an hour]
```

**Acceptance**: File exists, valid markdown

---

### Subtask 1.4: Create HEARTBEAT.md Template

**Path**: `~/.cato/workspace/HEARTBEAT.md`

**Content** (template):
```markdown
# Periodic Health Checks

## Daily Checks (run every morning)
- [ ] Check daemon process running
- [ ] Verify API connectivity
- [ ] Review error logs

## Weekly Checks (run every Monday)
- [ ] Backup workspace files
- [ ] Review long-term memory
- [ ] Check token usage

## Monthly Checks (run 1st of month)
- [ ] Update MEMORY.md with new facts
- [ ] Archive old logs
- [ ] Review agent performance
```

**Acceptance**: File exists, valid markdown, checkbox format

---

### Subtask 1.5: Create TOOLS.md Template

**Path**: `~/.cato/workspace/TOOLS.md`

**Content** (template):
```markdown
# Local Tools & Scripts

## Available Commands
- `pytest` → Run tests
- `pytest tests/test_X.py` → Run specific test
- `git log --oneline` → View commit history
- `cato` → Start daemon

## Scripts
- `scripts/build.sh` → Build desktop app
- `scripts/test.sh` → Run full test suite
- `scripts/backup.sh` → Backup workspace

## Tips
- Python scripts in: `scripts/`
- Tests in: `tests/`
- Config in: `~/.cato/config.yaml`
```

**Acceptance**: File exists, valid markdown

---

### Subtask 1.6: Create Workspace Initialization Endpoint

**Modify**: `cato/api/workspace_routes.py` (new file)

**Implement**:
```python
# GET /api/workspace/templates — return list of templates
# POST /api/workspace/init — create all 5 template files
# GET /api/workspace/{filename} — read file contents
# PUT /api/workspace/{filename} — save file contents
```

**Endpoints**:
- `GET /api/workspace/templates` → `{"templates": ["AGENTS.md", "MEMORY.md", ...]}`
- `POST /api/workspace/init` → Creates all 5 files, returns `{"success": true}`
- `GET /api/workspace/AGENTS.md` → Returns file contents
- `PUT /api/workspace/AGENTS.md` → Saves updated contents

**Error Handling**:
- 404 if workspace dir not found
- 400 if invalid filename
- 500 if write fails

**Acceptance**: All 4 endpoints working, no 500 errors

---

### Subtask 1.7: Update ContextBuilder to Load Templates

**Modify**: `cato/core/context_builder.py`

**Add**:
```python
def load_workspace_files(workspace_dir: Path) -> Dict[str, str]:
    """Load all 5 workspace templates"""
    files = {}
    for name in ["AGENTS.md", "MEMORY.md", "USER.md", "HEARTBEAT.md", "TOOLS.md"]:
        path = workspace_dir / name
        if path.exists():
            files[name] = path.read_text()
    return files

def build_system_prompt(workspace_dir=None, ...) -> str:
    """Include workspace files in system prompt"""
    # ... existing code ...
    workspace_files = load_workspace_files(workspace_dir)
    # Inject into prompt before priority stack
    # Respect token budget
```

**Acceptance**: Workspace files loaded and injected, token budget respected

---

### Subtask 1.8: Add Unit Tests

**Create**: `tests/test_workspace_templates.py`

**Tests**:
- Test all 5 template files exist
- Test files are valid markdown
- Test ContextBuilder loads files
- Test token count < 2200
- Test API endpoints return correct structure
- Test file creation from template
- Test graceful handling of missing files

**Acceptance**: All tests pass (0 failures)

---

## GUARDRAILS (From .ralph/guardrails.md)

- ✅ **100% Test Pass Rate**: All pytest tests must pass before promise
- ✅ **Token Budget**: All templates combined < 2200 tokens
- ✅ **Workspace Directory**: Read from config.yaml, fall back to ~/.cato/workspace
- ✅ **Git Commits**: Create commit after successful completion
- ✅ **Cross-Platform**: No hardcoded paths, use Path.home()

---

## COMPLETION CHECKLIST

When ALL subtasks are done:
1. [ ] All 5 template files created in ~/.cato/workspace/
2. [ ] API endpoints working (GET/POST /api/workspace/*)
3. [ ] ContextBuilder loads and injects templates
4. [ ] Token budget calculation correct (< 2200 tokens)
5. [ ] All unit tests passing (pytest tests/test_workspace_templates.py)
6. [ ] No console errors in Tauri / browser
7. [ ] Git committed with message: "chunk: 1 - create workspace template files"
8. [ ] `.ralph/progress.md` updated with iteration count

---

## PROMISE PATTERN

When all above is complete, write:

```
<promise>CHUNK_1_COMPLETE</promise>
```

This tells Ralph Loop:
✅ Chunk 1 finished successfully
✅ Ready for migration/handoff to Chunk 2
✅ Do NOT reinject this prompt

---

## EXPECTED FILES MODIFIED

**New Files**:
- `cato/api/workspace_routes.py`
- `tests/test_workspace_templates.py`

**Modified Files**:
- `cato/core/context_builder.py` (add workspace loading)
- `.ralph/progress.md` (update status)

**Template Files Created** (in ~/.cato/workspace/):
- `AGENTS.md`
- `MEMORY.md`
- `USER.md`
- `HEARTBEAT.md`
- `TOOLS.md`

---

## ITERATION TRACKING

Check `.ralph/.iteration` before and after:
- Increment on each failed attempt
- Max 5 iterations before escalation

---

## SUCCESS INDICATORS

✅ **Files**: All 5 templates exist with correct format
✅ **API**: GET/POST endpoints working
✅ **Integration**: ContextBuilder loads templates without errors
✅ **Tests**: 100% pass rate (no failures, no skips)
✅ **Tokens**: Budget respected (< 2200 tokens total)
✅ **Performance**: Template loading < 100ms

---

**Remember**: "Me fail English? That's unpossible!" - Ralph Wiggum

Keep iterating until success. You've got this.
