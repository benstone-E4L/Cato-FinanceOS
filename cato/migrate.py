"""
cato/migrate.py — OpenClaw-to-Cato workspace migration.

Invoked by `cato migrate --from-openclaw` (stubbed in cli.py).

What gets copied:
  ~/.openclaw/agents/{agent_name}/ → ~/.cato/agents/{agent_name}/
    AGENTS.md, SOUL.md, USER.md, IDENTITY.md, MEMORY.md, TOOLS.md,
    HEARTBEAT.md, CRONS.json, sessions/*.jsonl, skills/*.md

What gets skipped (incompatible):
  config.json       — Cato uses YAML config; re-run `cato init`
  node_modules/     — not applicable to Cato
  *.env / .env.*    — re-enter API keys via `cato init` + `cato vault set`

Validation:
  SKILL.md          — must have a # Title and ## Instructions or ## Usage
  *.jsonl sessions  — every line must be valid JSON

After migration prints a summary table and next-step hints.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table


# ---------------------------------------------------------------------------
# OpenClaw auto-detection helpers (P1-7 additions)
# ---------------------------------------------------------------------------

def detect_openclaw_install() -> Optional[Path]:
    """
    Check for an OpenClaw installation by looking for ~/.openclaw/config.json.

    Returns the OpenClaw root Path if found, else None.
    """
    openclaw_dir = Path.home() / ".openclaw"
    config_file = openclaw_dir / "config.json"
    if config_file.exists():
        return openclaw_dir
    return None


def estimate_openclaw_last_month_cost(openclaw_dir: Path) -> Optional[float]:
    """
    Estimate last month's OpenClaw spend by scanning session JSONL files.

    Looks for cost_usd fields in session transcript lines inside
    ~/.openclaw/agents/*/sessions/*.jsonl.

    Returns estimated USD amount, or None if no session data found.
    """
    agents_dir = openclaw_dir / "agents"
    if not agents_dir.exists():
        return None

    total_usd = 0.0
    found_any = False

    for agent_dir in agents_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        sessions_dir = agent_dir / "sessions"
        if not sessions_dir.exists():
            continue
        for jsonl_file in sessions_dir.glob("*.jsonl"):
            try:
                for line in jsonl_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        cost = record.get("cost_usd", 0) or record.get("cost", 0)
                        if cost:
                            total_usd += float(cost)
                            found_any = True
                    except (json.JSONDecodeError, ValueError):
                        pass
            except OSError:
                pass

    return round(total_usd, 4) if found_any else None


def generate_migration_report(
    migrated_agents: int,
    migrated_skills: int,
    openclaw_cost: Optional[float],
) -> str:
    """
    Generate a post-migration report string with optional cost comparison.

    If openclaw_cost is provided, estimates the equivalent Cato cost using
    SwarmSync routing (assumed 40% cheaper than raw API pricing).
    """
    lines = [
        f"Migration complete! {migrated_agents} agents, {migrated_skills} skills imported.",
    ]
    if openclaw_cost is not None and openclaw_cost > 0:
        # Conservative SwarmSync savings estimate: ~30-50% cheaper, assume 35%
        cato_estimate = round(openclaw_cost * 0.65, 2)
        savings_pct = int((1.0 - cato_estimate / openclaw_cost) * 100)
        lines.append(
            f"Estimated last month in OpenClaw: ~${openclaw_cost:.2f} "
            f"-> Estimated in Cato with SwarmSync routing: ~${cato_estimate:.2f} "
            f"({savings_pct}% savings)"
        )
    return "\n".join(lines)

console = Console()

# Files copied verbatim when present
_WORKSPACE_FILES = [
    "AGENTS.md",
    "SOUL.md",
    "USER.md",
    "IDENTITY.md",
    "MEMORY.md",
    "TOOLS.md",
    "HEARTBEAT.md",
    "CRONS.json",
]

# Patterns for files that must never be copied
_SKIP_PATTERNS = re.compile(
    r"(config\.json|node_modules|\.env(\..+)?|\.env$)",
    re.IGNORECASE,
)

# Minimum SKILL.md: a level-1 heading and either ## Instructions or ## Usage
_SKILL_TITLE_RE = re.compile(r"^#\s+\S", re.MULTILINE)
_SKILL_SECTION_RE = re.compile(r"^##\s+(Instructions|Usage)\b", re.MULTILINE | re.IGNORECASE)


class OpenClawMigrator:
    """
    Migrates an OpenClaw workspace directory into a Cato workspace directory.

    Parameters
    ----------
    source_dir:
        Path to the OpenClaw root (default: ``~/.openclaw``).
    dest_dir:
        Path to the Cato root (default: ``~/.cato``).
    dry_run:
        When True, no files are written; only the report is printed.
    """

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        dest_dir: Optional[Path] = None,
        dry_run: bool = False,
    ) -> None:
        self.source = source_dir or Path.home() / ".openclaw"
        self.dest = dest_dir or Path.home() / ".cato"
        self.dry_run = dry_run
        self.stats: dict = {
            "agents": 0,
            "skills": 0,
            "sessions": 0,
            "skipped": 0,
            "errors": [],
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict:
        """
        Run the full migration and return the stats dict.

        Keys: agents, skills, sessions, skipped, errors.
        """
        agents_src = self.source / "agents"
        if not agents_src.exists():
            console.print(f"[red]Source directory not found: {agents_src}[/red]")
            return self.stats

        agent_dirs = sorted(d for d in agents_src.iterdir() if d.is_dir())
        if not agent_dirs:
            console.print("[yellow]No agent directories found in OpenClaw workspace.[/yellow]")
            return self.stats

        prefix = "[dim]DRY RUN[/dim]" if self.dry_run else ""
        if self.dry_run:
            console.print(f"\n[bold cyan]Cato Migration — Dry Run[/bold cyan]  {prefix}")
        else:
            console.print("\n[bold cyan]Cato Migration[/bold cyan]")
        console.print("=" * 54)

        for agent_dir in agent_dirs:
            self._migrate_agent(agent_dir)

        self._print_summary()
        return self.stats

    # ------------------------------------------------------------------
    # Per-agent migration
    # ------------------------------------------------------------------

    def _migrate_agent(self, agent_dir: Path) -> None:
        """Migrate one agent's workspace directory."""
        agent_name = agent_dir.name
        dest_agent = self.dest / "agents" / agent_name

        if dest_agent.exists() and not self.dry_run:
            console.print(
                f"  [yellow]SKIP[/yellow]  {agent_name}  — destination already exists"
            )
            self.stats["skipped"] += 1
            return

        if not self.dry_run:
            dest_agent.mkdir(parents=True, exist_ok=True)

        # 1. Workspace markdown / JSON files
        for filename in _WORKSPACE_FILES:
            src_file = agent_dir / filename
            if src_file.exists():
                if _SKIP_PATTERNS.search(filename):
                    self.stats["skipped"] += 1
                    continue
                if not self.dry_run:
                    shutil.copy2(src_file, dest_agent / filename)

        # 2. Skills directory
        skills_src = agent_dir / "skills"
        if skills_src.exists():
            skills_dest = dest_agent / "skills"
            if not self.dry_run:
                skills_dest.mkdir(exist_ok=True)
            for skill_file in sorted(skills_src.glob("*.md")):
                if self._validate_skill(skill_file):
                    if not self.dry_run:
                        shutil.copy2(skill_file, skills_dest / skill_file.name)
                    self.stats["skills"] += 1
                else:
                    msg = f"{agent_name}/skills/{skill_file.name}: missing # Title or ## Instructions"
                    self.stats["errors"].append(msg)
                    console.print(f"    [yellow]WARN[/yellow]  {msg}")
                    self.stats["skipped"] += 1

        # 3. Sessions directory (JSONL files)
        sessions_src = agent_dir / "sessions"
        if sessions_src.exists():
            sessions_dest = dest_agent / "sessions"
            if not self.dry_run:
                sessions_dest.mkdir(exist_ok=True)
            for jsonl_file in sorted(sessions_src.glob("*.jsonl")):
                if self._validate_jsonl(jsonl_file):
                    if not self.dry_run:
                        shutil.copy2(jsonl_file, sessions_dest / jsonl_file.name)
                    self.stats["sessions"] += 1
                else:
                    msg = f"{agent_name}/sessions/{jsonl_file.name}: invalid JSONL"
                    self.stats["errors"].append(msg)
                    console.print(f"    [yellow]WARN[/yellow]  {msg}")
                    self.stats["skipped"] += 1

        label = "[dim]would migrate[/dim]" if self.dry_run else "[green]migrated[/green]"
        console.print(f"  {label}  {agent_name}")
        self.stats["agents"] += 1

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_skill(self, skill_path: Path) -> bool:
        """Return True if SKILL.md has a # Title and ## Instructions/Usage."""
        try:
            text = skill_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return bool(_SKILL_TITLE_RE.search(text)) and bool(_SKILL_SECTION_RE.search(text))

    def _validate_jsonl(self, jsonl_path: Path) -> bool:
        """Return True if every non-empty line in the file is valid JSON."""
        try:
            for line in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if stripped:
                    json.loads(stripped)
        except (OSError, json.JSONDecodeError):
            return False
        return True

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _print_summary(self) -> None:
        """Print a rich summary table and next-step hints."""
        table = Table(title="Migration Summary", show_lines=True)
        table.add_column("Item", style="cyan")
        table.add_column("Count", justify="right", style="bold")

        table.add_row("Agents migrated", str(self.stats["agents"]))
        table.add_row("Skills migrated", str(self.stats["skills"]))
        table.add_row("Sessions migrated", str(self.stats["sessions"]))
        table.add_row("Files skipped / errors", str(self.stats["skipped"]))

        console.print()
        console.print(table)

        if self.stats["errors"]:
            console.print("\n[yellow]Validation warnings:[/yellow]")
            for err in self.stats["errors"]:
                console.print(f"  - {err}")

        if self.dry_run:
            console.print(
                "\n[dim]Dry run complete — no files were written. "
                "Re-run without --dry-run to apply.[/dim]"
            )
        else:
            console.print(
                "\nRun [bold]cato doctor[/bold] to check your workspace token budget."
            )
            console.print(
                "Run [bold]cato init[/bold] to configure API keys for the new vault."
            )
