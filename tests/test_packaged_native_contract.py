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


def test_packaged_sidecar_launches_bundled_binary_without_system_python():
    """The installer must not depend on the user having Python on PATH.

    The daemon is declared as a Tauri externalBin and resolved through the
    shell plugin's sidecar API, so the launched program is the artifact the
    installer shipped — never an interpreter discovered at runtime.
    """
    sidecar = _source("desktop/src-tauri/src/sidecar.rs")
    config = _source("desktop/src-tauri/tauri.conf.json")
    lib = _source("desktop/src-tauri/src/lib.rs")
    cargo = _source("desktop/src-tauri/Cargo.toml")

    assert '"binaries/cato"' in config
    assert "tauri-plugin-shell" in cargo
    # The plugin must actually be registered, or shell().sidecar() fails at runtime.
    assert "tauri_plugin_shell::init()" in lib

    assert 'app.shell().sidecar("cato")' in sidecar
    assert '.args(["start", "--channel", "webchat"])' in sidecar

    # No interpreter discovery of any kind on the release start path.
    # Comments may explain the removal; no executable line may reference one.
    code = "\n".join(
        line for line in sidecar.splitlines() if not line.lstrip().startswith("//")
    )
    assert "python" not in code.lower()
    assert "CATO_PYTHON" not in code
    assert 'env::var("PATH")' not in code


def test_packaged_sidecar_never_assembles_a_command_string():
    """An install path containing spaces must not be re-parsed as arguments.

    Tauri's sidecar API takes the configured binary name and passes argv
    directly, so there is no shell string to quote. Reintroducing
    std::process::Command would put path quoting back in our hands — the exact
    failure mode that breaks `C:\\Program Files\\Cato Desktop`.
    """
    sidecar = _source("desktop/src-tauri/src/sidecar.rs")

    assert "std::process::Command" not in sidecar
    assert "create_subprocess_shell" not in sidecar
    assert "sh -c" not in sidecar
    assert "cmd /c" not in sidecar.lower()
    # Arguments are passed as a list, never interpolated into one string.
    assert 'format!("{} start' not in sidecar
    assert "tauri_plugin_shell::{" in sidecar


def test_missing_bundled_sidecar_is_fail_visible():
    """A missing sidecar must surface, not silently fall back to anything."""
    sidecar = _source("desktop/src-tauri/src/sidecar.rs")

    assert "Bundled Cato executable is unavailable" in sidecar
    assert "Reinstall the desktop app" in sidecar
    assert 'log::error!("{}", message)' in sidecar
    # start() propagates the resolution error rather than swallowing it.
    assert "Self::sidecar_command(app)?" in sidecar
