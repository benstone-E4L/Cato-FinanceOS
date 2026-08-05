"""Native packaging/auth boundary contracts for the Cato desktop shell.

These tests intentionally avoid requiring a local Rust toolchain.  The Windows
artifact workflow performs the real Rust/Tauri compile; this suite locks the
security-critical handoff and artifact identity wiring before that workflow runs.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_tauri_status_reads_daemon_credential_from_current_data_directory():
    lib = _source("desktop/src-tauri/src/lib.rs")
    sidecar = _source("desktop/src-tauri/src/sidecar.rs")

    assert "daemon_token: sidecar::SidecarManager::daemon_token()" in lib
    assert 'join("daemon.token")' in sidecar
    assert "std::fs::read_to_string(token_path)" in sidecar
    assert ".filter(|token| !token.is_empty())" in sidecar


def test_tauri_status_does_not_log_or_serialize_credential_outside_command_result():
    sidecar = _source("desktop/src-tauri/src/sidecar.rs")
    token_fn = re.search(
        r"pub fn daemon_token\(\) -> Option<String> \{(?P<body>.*?)\n    \}",
        sidecar,
        re.DOTALL,
    )
    assert token_fn, "daemon_token implementation is missing"
    assert "log::" not in token_fn.group("body")
    assert "println!" not in token_fn.group("body")


def test_packaging_workflow_embeds_and_names_exact_github_sha():
    workflow = _source(".github/workflows/windows-desktop-artifact.yml")
    identity = _source("desktop/src/lib/buildIdentity.ts")

    assert "VITE_CATO_BUILD_SHA: ${{ github.sha }}" in workflow
    assert 'shortSha = "${{ github.sha }}".Substring(0, 8)' in workflow
    assert "${{ steps.identity.outputs.short_sha }}" in workflow
    assert "FULL_SHA_PATTERN = /^[0-9a-f]{40}$/i" in identity
    assert "VITE_CATO_BUILD_SHA" in identity


def test_packaging_fails_closed_when_no_installer_is_produced():
    workflow = _source(".github/workflows/windows-desktop-artifact.yml")
    assert 'if ($installers.Count -eq 0) { throw "Tauri produced no NSIS installer" }' in workflow
    assert "if-no-files-found: error" in workflow
