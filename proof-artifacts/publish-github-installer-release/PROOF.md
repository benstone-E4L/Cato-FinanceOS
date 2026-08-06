# PROOF — publish-github-installer-release

**Status:** DONE  
**When:** 2026-08-06T17:22:01Z  
**SECRETS_PRINTED:** NO

## Mission
Create GitHub Release on private repo `benstone-E4L/Cato-FinanceOS` attaching installer from Actions run `31060544131` (artifact `Cato-v0.2.0-50a4832d`, SHA `50a4832d`).

## Verification gate (pre-publish)
| Check | Result |
|---|---|
| Artifact download | OK — `gh run download 31060544131 -n Cato-v0.2.0-50a4832d` |
| Run headSha | `50a4832d27c766a2b891f30ae30618c6b98520c1` matches short SHA `50a4832d` |
| Installer filename | `Cato-v0.2.0-50a4832d-setup.exe` (281876243 bytes) |
| Installer SHA256 | `e0b6fb8c35da9eb62fc08799741364587cd4fc1523cb7691bc1967ec6b2b95ce` |

## Release created
| Field | Value |
|---|---|
| Tag | `v0.2.0-50a4832d` |
| Title | `Cato v0.2.0 (50a4832d)` |
| Target commit | `50a4832d27c766a2b891f30ae30618c6b98520c1` |
| Release URL | https://github.com/benstone-E4L/Cato-FinanceOS/releases/tag/v0.2.0-50a4832d |
| Installer download | https://github.com/benstone-E4L/Cato-FinanceOS/releases/download/v0.2.0-50a4832d/Cato-v0.2.0-50a4832d-setup.exe |
| Checksums download | https://github.com/benstone-E4L/Cato-FinanceOS/releases/download/v0.2.0-50a4832d/SHA256SUMS.txt |

## DONE criteria
`gh release list` shows:

```
Cato v0.2.0 (50a4832d)	Latest	v0.2.0-50a4832d	2026-08-06T17:22:01Z
```

Assets on release:
- `Cato-v0.2.0-50a4832d-setup.exe` (281876243) — uploaded
- `SHA256SUMS.txt` (98) — uploaded

Machine-readable dump: `release-view.json`
