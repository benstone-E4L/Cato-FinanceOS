#!/usr/bin/env python3
"""
verify_python_build.py — Confirm the package builds a usable wheel.

Used by:
  - GitHub Actions Python Verify (after pytest)
  - hatch scripts: verify / verify-fast

Root cause this closes: python-verify.yml called this path, but the file was
never in the tree, so the job failed after a green pytest run.
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)


def _optional_pytest() -> None:
    _run([sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line"])


def _build_wheel() -> Path:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "build", "--wheel", "--outdir", str(DIST)])
    wheels = sorted(DIST.glob("*.whl"))
    if not wheels:
        raise SystemExit("No wheel produced under dist/")
    wheel = wheels[-1]
    print(f"Built wheel: {wheel.name} ({wheel.stat().st_size} bytes)", flush=True)
    return wheel


def _assert_wheel_contains_package(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    package_files = [n for n in names if n.startswith("cato/") and n.endswith(".py")]
    if "cato/__init__.py" not in names:
        raise SystemExit(f"Wheel missing cato/__init__.py: {wheel.name}")
    if len(package_files) < 5:
        raise SystemExit(
            f"Wheel looks too thin ({len(package_files)} cato/*.py files): {wheel.name}"
        )
    print(f"Wheel package files: {len(package_files)} under cato/", flush=True)


def _import_from_wheel(wheel: Path) -> None:
    """Install the wheel into a temp venv-less path and import cato."""
    with tempfile.TemporaryDirectory(prefix="cato-wheel-check-") as tmp:
        target = Path(tmp) / "site"
        target.mkdir()
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(target),
                str(wheel),
            ]
        )
        # Import without pulling the live editable install from PYTHONPATH.
        env_pythonpath = str(target)
        code = (
            "import sys; "
            f"sys.path.insert(0, {env_pythonpath!r}); "
            "import cato; "
            "print(f'import ok: cato {cato.__version__}')"
        )
        _run([sys.executable, "-c", code])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Skip the pytest suite (CI already ran it in a prior step).",
    )
    args = parser.parse_args(argv)

    # Sanity: source tree is importable before we burn a build.
    importlib.invalidate_caches()
    import cato  # noqa: F401

    print(f"Source import ok: cato {cato.__version__}", flush=True)

    if not args.skip_pytest:
        _optional_pytest()

    wheel = _build_wheel()
    _assert_wheel_contains_package(wheel)
    _import_from_wheel(wheel)
    print("verify_python_build: OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
