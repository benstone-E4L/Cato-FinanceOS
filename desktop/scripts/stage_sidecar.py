#!/usr/bin/env python
"""
Build and stage the frozen Cato daemon sidecar for Tauri bundling.

Release bundles use a frozen Python executable as the desktop sidecar.
Development runs can still rely on a PATH-installed `cato`, but `tauri build`
must produce a self-contained bundle and therefore requires a staged binary.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import json
from pathlib import Path


def fail(message: str) -> "NoReturn":
    print(f"[stage_sidecar] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize_arch(raw_arch: str) -> str:
    arch = raw_arch.lower().strip()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "arm64": "aarch64",
    }
    return aliases.get(arch, arch)


def target_triple() -> str:
    arch = normalize_arch(os.environ.get("TAURI_ENV_ARCH") or platform.machine())
    platform_name = (os.environ.get("TAURI_ENV_PLATFORM") or sys.platform).lower()

    if platform_name.startswith("win"):
        suffix = "pc-windows-msvc"
    elif platform_name.startswith("darwin") or platform_name == "macos":
        suffix = "apple-darwin"
    elif platform_name.startswith("linux"):
        suffix = "unknown-linux-gnu"
    else:
        fail(f"unsupported platform for sidecar staging: {platform_name}")

    if arch not in {"x86_64", "aarch64"}:
        fail(f"unsupported architecture for sidecar staging: {arch}")

    return f"{arch}-{suffix}"


def output_name(triple: str) -> str:
    suffix = ".exe" if triple.endswith("windows-msvc") else ""
    return f"cato-{triple}{suffix}"


#: Fixed name of the staged onedir bundle under ``src-tauri/binaries``.
#:
#: Deliberately NOT triple-suffixed. ``tauri.conf.json`` bundles this directory
#: as a *resource*, and that config is static JSON with no per-target
#: substitution — a triple in the path would only resolve on one platform.
#: ``externalBin`` used to handle the triple for us, but it takes a single file
#: and a onedir build is a directory, so the triple moves out of the path and
#: the folder name becomes constant instead.
BUNDLE_DIR_NAME = "cato-sidecar"


def inner_executable_name(triple: str) -> str:
    """Name of the real executable *inside* the staged onedir bundle.

    PyInstaller names the produced executable after ``--name``; we pass a
    constant so Rust can join a fixed path under the resource directory
    rather than reconstruct the target triple at runtime.
    """
    return "cato.exe" if triple.endswith("windows-msvc") else "cato"


def output_bundle_dir(binaries_dir: Path) -> Path:
    """Directory the onedir bundle is staged into."""
    return binaries_dir / BUNDLE_DIR_NAME


def main() -> int:
    desktop_dir = Path(__file__).resolve().parents[1]
    repo_root = desktop_dir.parent
    binaries_dir = desktop_dir / "src-tauri" / "binaries"
    binaries_dir.mkdir(parents=True, exist_ok=True)

    triple = target_triple()
    bundle_dir = output_bundle_dir(binaries_dir)
    inner_exe = bundle_dir / inner_executable_name(triple)
    source_override = os.environ.get("CATO_SIDECAR_SOURCE")

    if source_override:
        source = Path(source_override).expanduser().resolve()
        if not source.exists():
            fail(f"CATO_SIDECAR_SOURCE does not exist: {source}")
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        if source.is_dir():
            shutil.copytree(source, bundle_dir)
        else:
            # A single file override still has to land as the inner executable
            # of a onedir-shaped bundle, because that is the only layout the
            # Tauri resource path and the Rust spawn path know how to resolve.
            bundle_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, inner_exe)
        print(f"[stage_sidecar] copied sidecar from {source} -> {bundle_dir}")
        return 0

    try:
        import PyInstaller
    except ImportError as exc:
        fail(
            "PyInstaller is required for release bundling. "
            "Install it first, for example with `python -m pip install pyinstaller`."
        )
    if PyInstaller.__version__ != "6.15.0":
        fail(
            "release custody requires PyInstaller 6.15.0 exactly; "
            f"found {PyInstaller.__version__}. Install the pinned bundle dependencies."
        )

    cli_entry = repo_root / "cato" / "__main__.py"
    if not cli_entry.exists():
        fail(f"missing module entrypoint: {cli_entry}")

    with tempfile.TemporaryDirectory(prefix="cato-pyinstaller-") as tmpdir:
        tmp = Path(tmpdir)
        source_sha = os.environ.get("CATO_BUILD_SHA", "").strip().lower()
        if len(source_sha) != 40 or any(ch not in "0123456789abcdef" for ch in source_sha):
            fail("CATO_BUILD_SHA must be a full commit SHA for a release sidecar")
        identity_path = tmp / "cato_build_identity.json"
        identity_path.write_text(json.dumps({"source_sha": source_sha}), encoding="utf-8")
        data_separator = ";" if sys.platform.startswith("win") else ":"
        # --onedir, NOT --onefile. A onefile build re-extracts the entire
        # archive to a fresh temp directory on EVERY launch; measured on this
        # tree that cost 46.273s just to print `--version`, paid twice per app
        # start. The same code as a onedir bundle measured 2.895s warm. The
        # trade is disk layout (a directory instead of one file), which is why
        # the bundle ships as a Tauri *resource* rather than an externalBin.
        staged_name = Path(inner_executable_name(triple)).stem
        build_dist = tmp / "dist"
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            staged_name,
            "--add-data",
            f"{identity_path}{data_separator}.",
            "--distpath",
            str(build_dist),
            "--workpath",
            str(tmp / "build"),
            "--specpath",
            str(tmp / "spec"),
            str(cli_entry),
        ]

        print(f"[stage_sidecar] building {BUNDLE_DIR_NAME}/ ({staged_name})")
        subprocess.run(cmd, cwd=repo_root, check=True)

        produced = build_dist / staged_name
        produced_exe = produced / inner_executable_name(triple)
        if not produced_exe.is_file():
            fail(f"PyInstaller completed but no sidecar executable was produced at {produced_exe}")

        # Only now replace whatever was staged before. Building into a temp
        # distpath first means a failed build leaves the previously working
        # bundle intact instead of deleting it up front.
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        bundle_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(bundle_dir))

    if not inner_exe.is_file():
        fail(f"staged bundle is missing its executable: {inner_exe}")

    print(f"[stage_sidecar] staged {bundle_dir} (entrypoint: {inner_exe.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
