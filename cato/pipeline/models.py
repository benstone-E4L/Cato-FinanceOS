from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


PHASE_NAMES: dict[int, str] = {
    1: "market-research",
    2: "seo-marketing",
    3: "design",
    4: "technical-spec",
    5: "construction",
    6: "testing",
    7: "deployment",
    8: "post-deploy",
    9: "health",
}


@dataclass
class EmpireRun:
    run_id: str
    business_slug: str
    idea: str
    business_dir: Path
    status: str = "CREATED"
    current_phase: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerAssignment:
    task_id: str
    run_id: str
    business_slug: str
    phase: int
    prompt: str
    worker: str
    cwd: Optional[Path] = None
    timeout_sec: float = 300.0
    prompt_file: Optional[Path] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerResult:
    worker: str
    success: bool
    response: str
    source: str = "subprocess"
    latency_ms: float = 0.0
    degraded: bool = False
    error: str = ""
    artifacts: list[str] = field(default_factory=list)


@dataclass
class PhaseRequirement:
    type: str
    script: Optional[Path] = None
    args: list[str] = field(default_factory=list)
    exit_code_0_required: bool = True
    note: str = ""


@dataclass
class PhaseSpec:
    phase: int
    name: str
    worker: str
    model_tier: str
    output_dir: str
    prompt_sources: list[Path] = field(default_factory=list)
    support_workers: list[str] = field(default_factory=list)
    required_outputs: list[str] = field(default_factory=list)
    requirements: list[PhaseRequirement] = field(default_factory=list)
    summary: str = ""


@dataclass
class PhasePromptBundle:
    spec: PhaseSpec
    prompt: str
    source_files: list[Path] = field(default_factory=list)
    requirements: list[PhaseRequirement] = field(default_factory=list)
