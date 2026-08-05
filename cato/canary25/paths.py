"""Default paths for canary-25 proof artifacts."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_CANARY = Path(__file__).resolve().parents[2] / "proof-artifacts" / "canary-25"

#: Overrides both the policy value and the repo default. Set this on any host
#: where the repo directory is not writable, or in CI.
ENV_OVERRIDE = "CATO_PROOF_ARTIFACTS_DIR"


def default_canary_dir() -> Path:
    """Resolve the canary-25 directory.

    Order: ``$CATO_PROOF_ARTIFACTS_DIR`` -> night-shift policy ``paths`` ->
    repo-relative default. An absolute machine-specific path in the policy is
    no longer required; leaving it empty is the portable choice.
    """
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return Path(override).expanduser() / "canary-25"
    try:
        from ..core.night_shift_policy import load_night_shift_policy

        policy = load_night_shift_policy()
        raw = (policy.paths or {}).get("proof_artifacts_dir") or ""
        if raw:
            base = Path(raw).expanduser()
            return base / "canary-25"
    except Exception:
        pass
    return _REPO_CANARY
