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


def main() -> int:
    desktop_dir = Path(__file__).resolve().parents[1]
    repo_root = desktop_dir.parent
    binaries_dir = desktop_dir / "src-tauri" / "binaries"
    binaries_dir.mkdir(parents=True, exist_ok=True)

    triple = target_triple()
    output_path = binaries_dir / output_name(triple)
    source_override = os.environ.get("CATO_SIDECAR_SOURCE")

    if output_path.exists():
        output_path.unlink()

    if source_override:
        source = Path(source_override).expanduser().resolve()
        if not source.exists():
            fail(f"CATO_SIDECAR_SOURCE does not exist: {source}")
        shutil.copy2(source, output_path)
        print(f"[stage_sidecar] copied sidecar from {source} -> {output_path}")
        return 0

    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        fail(
            "PyInstaller is required for release bundling. "
            "Install it first, for example with `python -m pip install pyinstaller`."
        )

    cli_entry = repo_root / "cato" / "__main__.py"
    if not cli_entry.exists():
        fail(f"missing module entrypoint: {cli_entry}")

    with tempfile.TemporaryDirectory(prefix="cato-pyinstaller-") as tmpdir:
        tmp = Path(tmpdir)
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            output_path.stem,
            "--distpath",
            str(binaries_dir),
            "--workpath",
            str(tmp / "build"),
            "--specpath",
            str(tmp / "spec"),
            str(cli_entry),
        ]

        print(f"[stage_sidecar] building {output_path.name}")
        subprocess.run(cmd, cwd=repo_root, check=True)

    if not output_path.exists():
        fail(f"PyInstaller completed but no sidecar was produced at {output_path}")

    print(f"[stage_sidecar] staged {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
