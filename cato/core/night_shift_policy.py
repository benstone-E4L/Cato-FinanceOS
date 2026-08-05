"""
cato/core/night_shift_policy.py — Load night-shift-policy.yaml and enforce gates.

Default: live outreach OFF until operator sets gates.g1_manual_loop_proven in policy
or config live_outreach_enabled=True (both should be required for production sends).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from ..platform import get_data_dir

logger = logging.getLogger(__name__)

_DEFAULT_POLICY_REL = Path("docs/night-shift-policy.yaml")
_REPO_POLICY = Path(__file__).resolve().parents[2] / "docs" / "night-shift-policy.yaml"

_OUTBOUND_SKILLS = frozenset({
    "send_email",
    "outreach.run",
    "outreach_bridge",
    "genesis-email",
})

_FORBIDDEN_FLOW_NAMES = frozenset({
    "conduitscore-revenue-loop",
})


@dataclass
class NightShiftPolicy:
    version: str = "1.0"
    gates: dict[str, bool] = field(default_factory=lambda: {
        "g1_manual_loop_proven": False,
        "g2_engine_audit_go": False,
    })
    budget: dict[str, Any] = field(default_factory=dict)
    outreach: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    approval_required_tools: list[str] = field(default_factory=list)
    forbidden_until_g1: list[str] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def live_outreach_allowed(self) -> bool:
        try:
            from ..config import CatoConfig
            cfg = CatoConfig.load()
            if not getattr(cfg, "live_outreach_enabled", False):
                return False
        except Exception:
            pass
        phase = str(self.outreach.get("phase", "manual")).lower()
        if phase == "autonomous" and not self.gates.get("g3_cato_supervised_5_of_5", False):
            return False
        if not self.gates.get("g1_manual_loop_proven", False):
            return False
        return phase in ("supervised", "autonomous")

    def blocks_skill(self, skill: str, args: Optional[dict] = None) -> tuple[bool, str]:
        skill = (skill or "").strip()
        args = args or {}
        if skill.startswith("flow:"):
            flow_name = skill.split(":", 1)[1].strip()
            if flow_name in _FORBIDDEN_FLOW_NAMES and not self.live_outreach_allowed:
                return True, (
                    f"Flow '{flow_name}' blocked: G1 not proven "
                    "(loop-proof-card). Use dry_run locally only."
                )
        if skill in _FORBIDDEN_FLOW_NAMES and not self.live_outreach_allowed:
            return True, f"Flow '{skill}' blocked until G1."

        forbidden = self.forbidden_until_g1 or []
        token = f"flow.run:{args.get('flow', args.get('name', ''))}"
        if not self.live_outreach_allowed:
            for item in forbidden:
                if item == skill or item == token:
                    return True, f"'{skill}' forbidden until G1 (night-shift policy)."

        if not self.live_outreach_allowed:
            if skill in _OUTBOUND_SKILLS:
                if not args.get("draft_only") and not args.get("dry_run"):
                    return True, (
                        f"Outbound skill '{skill}' blocked: live outreach disabled. "
                        "Use draft_only/dry_run or complete G1 on loop-proof-card."
                    )
        return False, ""

    def blocks_flow_def(self, flow_def: dict) -> tuple[bool, str]:
        name = str(flow_def.get("name", ""))
        if flow_def.get("dry_run"):
            return False, ""
        if name in _FORBIDDEN_FLOW_NAMES and not self.live_outreach_allowed:
            return True, f"Flow '{name}' requires G1 or dry_run: true in YAML."
        return False, ""


_cached: Optional[NightShiftPolicy] = None


def load_night_shift_policy(path: Optional[Path] = None, *, reload: bool = False) -> NightShiftPolicy:
    """Load policy from path, repo default, or appdata copy."""
    global _cached
    if _cached is not None and not reload:
        return _cached

    candidates = [
        path,
        get_data_dir() / "night-shift-policy.yaml",
        _REPO_POLICY,
        Path.cwd() / _DEFAULT_POLICY_REL,
    ]
    raw: dict[str, Any] = {}
    for cand in candidates:
        if cand is None:
            continue
        p = Path(cand).expanduser()
        if p.is_file():
            try:
                raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                break
            except Exception as exc:
                logger.warning("Could not read night-shift policy %s: %s", p, exc)

    gates = raw.get("gates") or {}
    policy = NightShiftPolicy(
        version=str(raw.get("version", "1.0")),
        gates={k: bool(v) for k, v in gates.items()},
        budget=dict(raw.get("budget") or {}),
        outreach=dict(raw.get("outreach") or {}),
        safety=dict(raw.get("safety") or {}),
        approval_required_tools=list(raw.get("approval_required_tools") or []),
        forbidden_until_g1=list(raw.get("forbidden_until_g1") or []),
        paths={k: str(v) for k, v in (raw.get("paths") or {}).items()},
        raw=raw,
    )
    _cached = policy
    return policy


def assert_skill_allowed(skill: str, args: Optional[dict] = None) -> None:
    """Raise PermissionError if policy blocks this skill invocation."""
    policy = load_night_shift_policy()
    blocked, reason = policy.blocks_skill(skill, args)
    if blocked:
        raise PermissionError(reason)
