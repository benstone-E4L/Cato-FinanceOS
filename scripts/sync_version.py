#!/usr/bin/env python
"""Check or synchronize desktop manifests to Cato's package version."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_SOURCE = ROOT / "cato" / "__init__.py"
PACKAGE_JSON = ROOT / "desktop" / "package.json"
TAURI_JSON = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
CARGO_TOML = ROOT / "desktop" / "src-tauri" / "Cargo.toml"


def canonical_version() -> str:
    match = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)["\']',
        VERSION_SOURCE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        raise SystemExit("sync_version: cato/__init__.py has no __version__")
    return match.group(1)


def json_version(path: Path) -> str:
    return str(json.loads(path.read_text(encoding="utf-8"))["version"])


def cargo_version() -> str:
    match = re.search(
        r'^version\s*=\s*"([^"]+)"', CARGO_TOML.read_text(encoding="utf-8"), re.MULTILINE
    )
    if not match:
        raise SystemExit("sync_version: Cargo.toml package version is missing")
    return match.group(1)


def write_json_version(path: Path, version: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = version
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()

    version = canonical_version()
    current = {
        PACKAGE_JSON: json_version(PACKAGE_JSON),
        TAURI_JSON: json_version(TAURI_JSON),
        CARGO_TOML: cargo_version(),
    }
    mismatches = {path: value for path, value in current.items() if value != version}
    if args.check:
        if mismatches:
            details = ", ".join(f"{path.relative_to(ROOT)}={value}" for path, value in mismatches.items())
            raise SystemExit(f"sync_version: expected {version}; mismatches: {details}")
        print(f"sync_version: PASS {version}")
        return 0

    write_json_version(PACKAGE_JSON, version)
    write_json_version(TAURI_JSON, version)
    cargo_text = CARGO_TOML.read_text(encoding="utf-8")
    cargo_text = re.sub(
        r'^(version\s*=\s*)"[^"]+"', rf'\g<1>"{version}"', cargo_text, count=1, flags=re.MULTILINE
    )
    CARGO_TOML.write_text(cargo_text, encoding="utf-8")
    print(f"sync_version: wrote {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
