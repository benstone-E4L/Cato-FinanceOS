# Cato Skills — HOT/COLD Convention

## Overview

Each skill file may be split into a **HOT** section and a **COLD** section using the
`<!-- COLD -->` delimiter. The context builder loads only the HOT section on every turn,
keeping skill overhead low. The COLD section is never auto-injected; it is only loaded
when explicitly requested (e.g., via `retrieve_cold_section(skill_path)`).

## Delimiter

```
<!-- COLD -->
```

Everything **above** this line is the HOT section.
Everything **below** this line is the COLD section.

## HOT Section Guidelines (≤ 300 tokens)

The HOT section should contain only what the agent needs on every turn:

1. Skill name and version
2. Trigger phrases (keywords that activate this skill)
3. Parameter schema / quick reference table
4. 2-3 minimal usage examples
5. Critical rules (the must-never-do items)

## COLD Section Guidelines

The COLD section contains everything else:

- Full API documentation
- Extended usage examples with edge cases
- Troubleshooting tables
- Background/rationale prose
- Appendices

## When No Delimiter Is Needed

If the entire skill file is under 300 tokens, omit the delimiter — the whole file is
treated as HOT and loaded in full each turn.

## Example Structure

```markdown
# My Skill
**Version:** 1.0.0
**Capabilities:** some.capability

## Trigger Phrases
"do thing", "run thing"

## Quick Reference
| Action | Params |
|--------|--------|
| do_x   | param1 |

## Usage
\`\`\`
tool: do_x  param1: value
\`\`\`

<!-- COLD -->

## Full Documentation

[Extended content here — never auto-injected]
```

## Loading API

```python
from cato.core.context_builder import load_hot_section, retrieve_cold_section
from pathlib import Path

skill = Path("~/.cato/workspace/agent/SKILL.md").expanduser()

# Automatic in build_system_prompt() — HOT only
hot = load_hot_section(skill)

# Explicit on-demand — COLD only
cold = retrieve_cold_section(skill)
```
