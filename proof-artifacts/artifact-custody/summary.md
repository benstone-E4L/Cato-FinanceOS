# Artifact custody proof

- Generated workflow: `.github/workflows/windows-desktop-artifact.yml`
- Trigger: pushes and pull requests targeting `e4l-runtime-hardening`, plus manual dispatch
- Output: unsigned NSIS installer named `Cato-v<version>-<8-char SHA>-setup.exe`
- Custody: full GitHub SHA is compiled into the UI; SHA-256 checksums ship beside the installer
- Secrets: none required; workflow permission is read-only
- Runtime proof: Diagnostics displays the version and short SHA while retaining the full SHA in its title
- Local gates: artifact contract PASS, ESLint PASS, TypeScript/Vite production build PASS
- Embedded identity: the local production bundle contains `32d75c81c1cb5a2464d1b6c09304581169cda8da`
- Rust gate: unavailable locally because `cargo` is not installed/on PATH for this Windows profile. GitHub's Windows runner installs Rust before the Tauri build.
- Publication: intentionally not performed; the parent orchestrator owns review, push, and the first GitHub run.
