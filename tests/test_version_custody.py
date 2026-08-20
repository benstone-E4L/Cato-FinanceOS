from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_desktop_versions_match_canonical_package_version() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "sync_version.py"), "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "PASS" in completed.stdout


def test_live_manifest_recomputes_staged_sidecar_hash(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "live-tests" / "cato" / "run_live_e2e.py"
    spec = importlib.util.spec_from_file_location("cato_live_e2e_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.REPO = tmp_path
    release = tmp_path / "desktop" / "src-tauri" / "target" / "release"
    binaries = tmp_path / "desktop" / "src-tauri" / "binaries"
    dist = tmp_path / "desktop" / "dist"
    release.mkdir(parents=True)
    binaries.mkdir(parents=True)
    dist.mkdir(parents=True)
    native = release / "cato-desktop.exe"
    sidecar = binaries / "cato-x86_64-pc-windows-msvc.exe"
    bundle = dist / "index.html"
    native.write_bytes(b"native")
    sidecar.write_bytes(b"sidecar")
    bundle.write_bytes(b"bundle")
    sha = lambda value: hashlib.sha256(value).hexdigest()
    head = "a" * 40
    manifest = release / "cato-build-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_sha": head,
                "native": {"sha256": sha(b"native"), "bytes": 6},
                "sidecar": {
                    "path": sidecar.name,
                    "sha256": sha(b"sidecar"),
                    "bytes": 7,
                },
                "dist": {"index.html": sha(b"bundle")},
            }
        ),
        encoding="utf-8",
    )

    result = module.validate_build_manifest(manifest, native, head)
    assert result["sidecar_sha256"] == sha(b"sidecar")

    sidecar.write_bytes(b"tampered")
    with pytest.raises(AssertionError, match="Staged sidecar"):
        module.validate_build_manifest(manifest, native, head)
