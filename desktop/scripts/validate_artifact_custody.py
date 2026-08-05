#!/usr/bin/env python
"""Dependency-free static gate for the desktop artifact custody contract."""

from __future__ import annotations

import json
import re
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[artifact-custody] ERROR: {message}")


def main() -> int:
    desktop_dir = Path(__file__).resolve().parents[1]
    repo_root = desktop_dir.parent
    workflow_path = repo_root / ".github" / "workflows" / "windows-desktop-artifact.yml"
    identity_path = desktop_dir / "src" / "lib" / "buildIdentity.ts"
    diagnostics_path = desktop_dir / "src" / "views" / "DiagnosticsView.tsx"

    package = json.loads((desktop_dir / "package.json").read_text(encoding="utf-8"))
    tauri = json.loads((desktop_dir / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    cargo = (desktop_dir / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    require(package["version"] == tauri["version"], "package.json and tauri.conf.json versions differ")
    cargo_version = re.search(r'^version\s*=\s*"([^"]+)"', cargo, re.MULTILINE)
    require(bool(cargo_version), "Cargo.toml package version is missing")
    require(cargo_version.group(1) == package["version"], "Cargo.toml version differs from desktop version")

    workflow = workflow_path.read_text(encoding="utf-8")
    for marker in (
        "e4l-runtime-hardening",
        "VITE_CATO_BUILD_SHA: ${{ github.sha }}",
        "VITE_CATO_BUILD_VERSION=$version",
        "npm run tauri build -- --bundles nsis",
        "Get-FileHash -Algorithm SHA256",
        "actions/upload-artifact@v4",
        "if-no-files-found: error",
    ):
        require(marker in workflow, f"workflow is missing required marker: {marker}")
    require("secrets." not in workflow, "artifact build must not require repository secrets")

    identity = identity_path.read_text(encoding="utf-8")
    require("/^[0-9a-f]{40}$/i" in identity, "build SHA must require a complete 40-character commit")
    require("VITE_CATO_BUILD_VERSION" in identity, "runtime version is not embedded")
    require("VITE_CATO_BUILD_SHA" in identity, "runtime SHA is not embedded")
    diagnostics = diagnostics_path.read_text(encoding="utf-8")
    require("BUILD_IDENTITY_LABEL" in diagnostics, "Diagnostics does not expose build identity")

    print(f"[artifact-custody] PASS: Windows artifact workflow, version {package['version']}, and runtime SHA surface validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
