# Combined Issue Register

This register merges the 16 failure-mode findings in `FAILURE_MODE_AUDIT.md` with the six non-duplicate findings from `TRUTH_BEFORE_LAUNCH.md`.

**Total:** 22 findings — 6 HIGH, 11 MEDIUM, 5 LOW.

| IDs | Tier | Scope |
|---|---|---|
| F01–F04 | HIGH | delivery acknowledgement/idempotency, legacy DOM-XSS/token exposure, real-HTTP E2E parity, reconnect teardown |
| F05–F13 | MEDIUM | token transport/retention/ACL/CORS, chat retention, harness security, reconnect jitter, negative auth CI, malformed frames |
| F14–F16 | LOW | ephemeral ports, all-surface no-green coverage, non-JSON protocol handling |
| TBL-17–TBL-18 | HIGH | distributable artifact, production parity and custody |
| TBL-19–TBL-21 | MEDIUM | claims evidence, second-surface/no-green drift, packaged native auth proof |
| TBL-22 | LOW | runtime build identity |

The original audit's executive count stated 4 HIGH / 8 MEDIUM / 4 LOW, but its risk table contains 4 HIGH / 9 MEDIUM / 3 LOW. This register preserves every original row and uses the row-level severities as the source of truth instead of silently dropping or reclassifying a finding.
