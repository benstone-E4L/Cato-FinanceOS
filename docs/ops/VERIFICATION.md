# Verification — exact-HEAD operator acceptance

This is the reproducible verification route for Cato's supported local Windows
desktop. Results are valid only for the Git revision and artifact hashes named
by the generated custody manifest; a source change requires a rebuild and a new
run. Never treat an old PASS as evidence for a new HEAD.

## Current evidence boundary

The latest promoted proof before the current change set is commit
`4199d19badb250f47ad2a42ce5e19c6756f5af0a`. Its retained evidence is in:

- `output/cato-live-e2e-4199d19/result.json`
- `output/cato-live-e2e-4199d19/full-suite.xml`
- `C:\Users\Work\Desktop\vault-next\projects\cato\proof-artifacts\operator-live-work-inbox-4199d19`

That run proved a manifest-bound native desktop and adjacent daemon, matching
live process images/hashes and `source_sha`, authenticated HTTP and WebSocket
boundaries, ten rendered Work Inbox checks, encrypted credential custody, a
safe FinanceOS control-room fallback, and one real direct-Anthropic response.
The full offline suite reported 3,071 passed, 5 skipped, 4 deselected, and zero
failures/errors. These are historical exact-HEAD facts, not a claim about a
later dirty tree or unbuilt commit.

No public installer publication, code-signing chain, live Telegram exchange,
or FinanceOS/Xero mutation is claimed.

## Reproduce for the current HEAD

From the repository root in PowerShell:

```powershell
git status --short
git rev-parse HEAD
python -m pytest -q
npm --prefix desktop test
npm --prefix desktop run lint
powershell -ExecutionPolicy Bypass -File desktop\build_release.ps1
python live-tests\cato\run_live_e2e.py
```

The live runner is bounded and must fail closed unless it can bind all of the
following to the same clean HEAD:

1. custody-manifest source revision;
2. native desktop executable path and SHA-256;
3. runtime-resolved adjacent daemon path and SHA-256;
4. running daemon PID image, `/health.source_sha`, and canonical ports;
5. rendered production bundle build identity;
6. Work Inbox browser assertions and FinanceOS fallback behavior;
7. encrypted vault/launch handoff custody without exposing secret values;
8. authenticated HTTP/WebSocket checks and the direct-Anthropic live receipt.

If any item disagrees, the result is not exact-HEAD acceptance. Rebuild, restart,
and rerun; do not edit evidence to make it agree.

## Credential handling

Repository `.env` is never a launch credential source. On this workstation it
is a user-controlled EFS-encrypted backup and must not be read, printed, edited,
or deleted by automation. Provider credentials live in `%APPDATA%\cato\vault.enc`.
The launch password handoff is the Work-account DPAPI blob
`%APPDATA%\cato\vault-password.dpapi`; the bootstrap consumes the decrypted
value into memory and removes it from the process environment.

Validation must inspect only custody metadata (existence, encryption state,
ACLs, hashes, and redacted key names), never credential values.

## Vault promotion

After an exact clean-HEAD run, copy the immutable result package into
`vault-next/projects/cato/proof-artifacts`, register its hashes in
`EVIDENCE.yaml`, update `STATE.yaml` and `CANONICAL.yaml` to the same revision,
then run:

```powershell
python C:\Users\Work\Desktop\vault-next\tools\vaultctl\vaultctl.py validate --strict
python C:\Users\Work\Desktop\vault-next\tools\vaultctl\vaultctl.py context cato --json
```

Portfolio-wide Vault diagnostics may belong to other projects. Report them
separately; Cato is current only when its own declared revision and evidence
validate together.
