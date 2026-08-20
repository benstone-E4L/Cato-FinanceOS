#!/usr/bin/env python
"""Dependency-free static gate for the desktop artifact custody contract."""

from __future__ import annotations

import json
import colorsys
import re
import tomllib
from pathlib import Path

from PIL import Image


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[artifact-custody] ERROR: {message}")


def prohibited_pixel_count(path: Path) -> int:
    image = Image.open(path).convert("RGBA")
    count = 0
    for red, green, blue, alpha in image.getdata():
        if alpha == 0:
            continue
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        if 60 <= hue * 360 < 200 and saturation >= 0.01 and value >= 0.01:
            count += 1
    return count


def main() -> int:
    desktop_dir = Path(__file__).resolve().parents[1]
    repo_root = desktop_dir.parent
    workflow_path = repo_root / ".github" / "workflows" / "windows-desktop-artifact.yml"
    identity_path = desktop_dir / "src" / "lib" / "buildIdentity.ts"
    diagnostics_path = desktop_dir / "src" / "views" / "DiagnosticsView.tsx"
    native_path = desktop_dir / "src-tauri" / "src" / "lib.rs"
    sidecar_path = desktop_dir / "src-tauri" / "src" / "sidecar.rs"
    release_script_path = desktop_dir / "build_release.ps1"
    launcher_path = repo_root / "Launch-CatoDesktop.ps1"
    version_script_path = repo_root / "scripts" / "sync_version.py"
    live_harness_path = repo_root / "live-tests" / "cato" / "run_live_e2e.py"

    package = json.loads((desktop_dir / "package.json").read_text(encoding="utf-8"))
    tauri = json.loads((desktop_dir / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    cargo = (desktop_dir / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    require(package["version"] == tauri["version"], "package.json and tauri.conf.json versions differ")
    bundle_dependencies = set(project["project"]["optional-dependencies"]["bundle"])
    require("pyinstaller==6.15.0" in bundle_dependencies, "bundle extra must pin PyInstaller")
    require("pillow==11.3.0" in bundle_dependencies, "bundle extra must pin Pillow for raster validation")
    cargo_version = re.search(r'^version\s*=\s*"([^"]+)"', cargo, re.MULTILINE)
    require(bool(cargo_version), "Cargo.toml package version is missing")
    require(cargo_version.group(1) == package["version"], "Cargo.toml version differs from desktop version")
    icon_paths = [tauri["app"]["trayIcon"]["iconPath"], *tauri["bundle"]["icon"]]
    for relative_icon in icon_paths:
        icon = desktop_dir / "src-tauri" / relative_icon
        require(icon.is_file(), f"configured icon is missing: {relative_icon}")
        require(prohibited_pixel_count(icon) == 0, f"configured icon contains prohibited green/teal pixels: {relative_icon}")
    logo = repo_root / "New Logos" / "CATO-E4Life-Structure-Transparent.png"
    require(prohibited_pixel_count(logo) == 0, "shipped Cato logo contains prohibited green/teal pixels")

    workflow = workflow_path.read_text(encoding="utf-8")
    for marker in (
        "e4l-runtime-hardening",
        'python -m pip install ".[dev,bundle]"',
        "VITE_CATO_BUILD_SHA: ${{ github.sha }}",
        "CATO_BUILD_SHA: ${{ github.sha }}",
        "VITE_CATO_BUILD_VERSION=$version",
        "npx tauri build --bundles nsis",
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
    require("get_build_identity" in diagnostics, "Diagnostics does not read native build identity")
    require("Frontend/native build identity mismatch" in diagnostics, "identity mismatch is not fail-visible")

    native = native_path.read_text(encoding="utf-8")
    sidecar = sidecar_path.read_text(encoding="utf-8")
    release_script = release_script_path.read_text(encoding="utf-8")
    live_harness = live_harness_path.read_text(encoding="utf-8")
    require('option_env!("CATO_BUILD_SHA")' in native, "native binary does not embed source SHA")
    require("get_build_identity" in native, "native identity command is missing")
    require('.env("CATO_BUILD_SHA", super::NATIVE_BUILD_SHA)' in sidecar, "sidecar does not inherit native source SHA")
    require("write_build_manifest.py" in release_script, "local release omits custody manifest")
    require(version_script_path.is_file(), "release version check script is missing")
    require("sync_version.py --check" in release_script, "release build mutates or skips version custody")
    require(launcher_path.is_file(), "secure desktop launcher is missing")
    launcher = launcher_path.read_text(encoding="utf-8")
    require('Read-Host "Cato vault master password" -AsSecureString' in launcher, "launcher has no secure manual fallback")
    require('Join-Path $dataDir "vault-password.dpapi"' in launcher, "launcher does not use Windows-encrypted password custody")
    require("ConvertTo-SecureString $protectedPassword" in launcher, "launcher does not decrypt DPAPI custody securely")
    require("CATO_VAULT_PASSWORD" in launcher, "launcher does not perform the one-child vault handoff")
    require(".env" not in launcher, "launcher must never read dotenv credentials")
    require("validate_build_manifest" in live_harness, "live acceptance omits manifest binding")
    require('health.get("source_sha") != expected_head' in live_harness, "live daemon is not bound to HEAD")

    print(f"[artifact-custody] PASS: Windows artifact workflow, version {package['version']}, and runtime SHA surface validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
