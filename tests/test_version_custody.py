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


def test_packaged_identity_cannot_be_overridden_by_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    packaged_sha = "b" * 40
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("CATO_BUILD_SHA", "a" * 40)
    (tmp_path / "cato_build_identity.json").write_text(
        json.dumps({"source_sha": packaged_sha}), encoding="utf-8"
    )
    module_path = root / "cato" / "runtime_identity.py"
    spec = importlib.util.spec_from_file_location("packaged_runtime_identity_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.runtime_source_sha() == packaged_sha


def test_live_manifest_recomputes_runtime_and_staged_sidecar_hashes(tmp_path: Path) -> None:
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
    sidecar = release / "cato.exe"
    staged_sidecar = binaries / "cato-x86_64-pc-windows-msvc.exe"
    bundle = dist / "index.html"
    native.write_bytes(b"native")
    sidecar.write_bytes(b"sidecar")
    staged_sidecar.write_bytes(b"sidecar")
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
                "staged_sidecar": {
                    "path": staged_sidecar.name,
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
    with pytest.raises(AssertionError, match="Runtime sidecar"):
        module.validate_build_manifest(manifest, native, head)


def test_live_manifest_rejects_staged_runtime_sidecar_mismatch(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "live-tests" / "cato" / "run_live_e2e.py"
    spec = importlib.util.spec_from_file_location("cato_live_e2e_mismatch", module_path)
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
    runtime = release / "cato.exe"
    staged = binaries / "cato-x86_64-pc-windows-msvc.exe"
    native.write_bytes(b"native")
    runtime.write_bytes(b"runtime")
    staged.write_bytes(b"staged!")
    (dist / "index.html").write_bytes(b"bundle")
    sha = lambda value: hashlib.sha256(value).hexdigest()
    head = "b" * 40
    manifest = release / "cato-build-manifest.json"
    manifest.write_text(json.dumps({
        "source_sha": head,
        "native": {"sha256": sha(b"native"), "bytes": 6},
        "sidecar": {"path": runtime.name, "sha256": sha(b"runtime"), "bytes": 7},
        "staged_sidecar": {"path": staged.name, "sha256": sha(b"staged!"), "bytes": 7},
        "dist": {"index.html": sha(b"bundle")},
    }), encoding="utf-8")

    with pytest.raises(AssertionError, match="Staged and runtime sidecars"):
        module.validate_build_manifest(manifest, native, head)
