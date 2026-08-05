# Packaged-native parity proof

## Scope

- Findings: `TBL-18`, `TBL-21`
- Branch: `e4l-runtime-hardening`
- Source SHA at local verification: `32d75c81c1cb5a2464d1b6c09304581169cda8da`
- Safety: loopback/test clients only; no finance writes; no secrets printed

## Native boundary results

| Contract | Result | Evidence |
|---|---|---|
| Tauri status command reads the daemon credential from the current Cato data directory | PASS | `tests/test_packaged_native_contract.py`; `desktop/src-tauri/src/lib.rs`; `desktop/src-tauri/src/sidecar.rs` |
| Credential read fails closed for missing/empty content and is not logged | PASS | native contract tests plus source inspection |
| Valid authenticated dashboard and WebSocket access succeeds | PASS | `tests/test_dashboard_token_and_host.py`; `tests/test_gateway_ws_delivery.py` |
| Invalid credential and query-only credential fail | PASS | same focused auth suites |
| Shutdown/unmount cancels reconnect, including a late scheduler callback | PASS | `desktop/src/hooks/chatStreamPolicy.test.mjs` |
| Workflow injects full GitHub SHA and names the artifact with its short SHA | PASS (contract) | `.github/workflows/windows-desktop-artifact.yml`; `desktop/scripts/validate_artifact_custody.py` |
| Downloaded installer hash and workflow SHA agree | PENDING EXTERNAL ARTIFACT | Workflow has not yet been pushed/started on GitHub at the time of this report. |

## Test output

```text
python -m pytest tests/test_packaged_native_contract.py tests/test_dashboard_token_and_host.py tests/test_gateway_ws_delivery.py -q
60 passed

node --test desktop/src/hooks/chatStreamPolicy.test.mjs
5 passed, 0 failed

python desktop/scripts/validate_artifact_custody.py
[artifact-custody] PASS: Windows artifact workflow, version 0.2.0, and runtime SHA surface validated
```

## Verdict

**PARTIAL.** The automated native credential, authentication, rejection, lifecycle, and build-identity boundaries pass. The sole missing proof is an installer downloaded from a successful GitHub Actions run for the final pushed SHA, with its recorded SHA-256 checked against `SHA256SUMS.txt`. No installer was executed or installed.
