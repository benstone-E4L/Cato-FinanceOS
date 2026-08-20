# Cato live end-to-end acceptance package

This package proves the installed Cato desktop/runtime boundary on the operator workstation without
printing credentials or making finance writes. The full profile combines:

1. the deterministic production-bundle Work Inbox browser acceptance (including a forced
   FinanceOS live-to-stale transition);
2. exact clean Git revision and native executable custody;
3. the real operator daemon's health, lifecycle markers, protected HTTP routes, valid/invalid
   WebSocket authentication, encrypted-vault/config hygiene, and read-only FinanceOS contract;
4. an optional single low-token direct-Anthropic response through Cato's real gateway.

The live model check creates one Cato web session and incurs a small API charge. It never records
the prompt, response, daemon token, vault password, or credential values. FinanceOS is read-only;
an unavailable upstream passes only when Cato returns the explicit stale fallback contract.

## Full exact-HEAD run

From the repository root, after building `desktop/src-tauri/target/release/cato-desktop.exe`:

```powershell
python live-tests/cato/run_live_e2e.py --exercise-model
```

Results and screenshots are written beneath `output/live-cato/` (gitignored). A rerun without an
API call omits `--exercise-model`. Use `--skip-work-inbox` only when separately supplied current
Work Inbox evidence is being composed into the same proof bundle.

## Pass boundary

`PASS` means every selected check passed on the recorded branch/SHA and workstation. It does not
claim that FinanceOS is externally connected: `connected=false, stale=true` is the expected safe
fallback when the local FinanceOS authority is unavailable. It also does not perform or certify a
real payment, ledger mutation, external approval, installer signing, or GitHub deployment.
