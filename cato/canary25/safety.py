"""G1 safety reminders — canary kit never enables live Cato outreach."""

from __future__ import annotations

from typing import Any


def policy_snapshot() -> dict[str, Any]:
    from ..core.night_shift_policy import load_night_shift_policy
    from ..config import CatoConfig

    policy = load_night_shift_policy()
    cfg = CatoConfig.load()
    return {
        "g1_manual_loop_proven": bool(policy.gates.get("g1_manual_loop_proven", False)),
        "g2_engine_audit_go": bool(policy.gates.get("g2_engine_audit_go", False)),
        "live_outreach_enabled": bool(getattr(cfg, "live_outreach_enabled", False)),
        "live_outreach_allowed": policy.live_outreach_allowed,
        "outreach_phase": str(policy.outreach.get("phase", "manual")),
    }


def assert_canary_operator_safe() -> list[str]:
    """
    Return warning strings (never raises). Canary commands must not flip outreach on.
    """
    snap = policy_snapshot()
    warnings: list[str] = []
    if snap["live_outreach_allowed"]:
        warnings.append(
            "WARNING: live_outreach_allowed is true — canary kit still only writes proof files; "
            "do not bulk-send via Cato until Row 4–6 evidence is complete."
        )
    else:
        warnings.append(
            "G1 safety OK: live outreach blocked by policy (expected during canary)."
        )
    if not snap["g2_engine_audit_go"]:
        warnings.append("Note: g2_engine_audit_go is false — Row 3 audits should be GO first.")
    if snap["g1_manual_loop_proven"]:
        warnings.append(
            "Note: g1_manual_loop_proven is true — ensure loop-proof-card rows 4–6 are "
            "actually complete before scaling beyond 25 sends."
        )
    return warnings
