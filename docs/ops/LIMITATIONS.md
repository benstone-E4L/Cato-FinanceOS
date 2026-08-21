# Known Limitations and Launch Boundary

This file describes the currently supported local operator build. Historical
failure counts and superseded architecture claims have been removed so they
cannot be mistaken for present state. Exact results live in
[VERIFICATION.md](VERIFICATION.md) and the evidence-bound Vault record.

## Distribution and custody

- The proven surface is a local Windows Tauri desktop plus its adjacent Cato
  daemon. There is no claim of a publicly published, signed installer or a
  third-party production deployment.
- Exact-HEAD proof expires whenever source or packaged artifacts change. A
  clean source tree alone does not prove that the running executables match it.
- Evidence directories are named by short Git revision. The revision in the
  live result, custody manifest, running health response, and Vault must match;
  never hardcode a formerly current SHA in operating instructions.

## Model execution

- Production chat, Ask E4L, forced-final turns, and session compaction must use
  `cato/model_policy.py` and the direct Anthropic client. Stored OpenAI,
  OpenRouter, Google, or SwarmSync credentials are not model-routing inputs.
- The `default_model` config field remains only as a legacy display/config
  value. The former caller-selected multi-provider router is disabled and its
  provider dispatch helpers have been removed.
- A live direct-Anthropic round trip proves that sampled path and credential;
  deterministic negative tests are still required to prove other credentials
  cannot redirect classification, escalation, Ask E4L, or compaction.

## Finance boundary

- The installed Finance and Approvals views issue GET-only control-room
  requests. No mutation is wired into those desktop surfaces.
- `FinanceOSClient` contains mutation primitives for possible future workflows.
  Therefore the narrower UI boundary must not be described as a universal
  inability for the client to write.
- FinanceOS outage fallback and stale-state preservation are covered by rendered
  acceptance. No live FinanceOS or Xero write is claimed.
- Finance approvals remain in FinanceOS/Airtable, outside Cato's Approvals view.

## Credentials

- Runtime provider credentials are stored in the AES-256-GCM encrypted vault.
  Repository `.env` is not loaded at launch; on the proven workstation it is an
  EFS-encrypted, user-controlled backup that automation must not modify.
- The vault master-password handoff is protected with Windows DPAPI and a
  Work-account-only ACL. Recovery still depends on preserving the operator's
  intended backup/recovery material; DPAPI is account/machine scoped.
- Logs, tests, and evidence must never include credential values.

## Integrations and unproven surfaces

- SwarmSync is optional and restricted to Genesis, the integration registry,
  and the site-services bridge. It is not in model execution.
- Telegram is configured locally, but there is no current exact-HEAD live
  bidirectional Telegram trace. Treat it as unverified until one is captured.
- Calendar, Waiting/Follow-ups, and Monday Company Tasks are reserved navigation
  surfaces and explicitly not yet available.
- Coding-agent and external-service behavior depends on locally installed CLIs,
  accounts, network availability, and third-party APIs; an offline unit test
  does not prove those external systems.

## Test and Vault interpretation

- The `1a6c535` exact-HEAD full suite reported 3,081 passed, 5 skipped,
  4 deselected, and zero failures/errors. This is a historical example;
  skipped/deselected tests provide no signal and must be reviewed by name in
  each new run.
- Global `vaultctl validate --strict` can report portfolio problems unrelated
  to Cato. At the last audit it reported 20 errors across other projects while
  `vaultctl context cato` was CURRENT/VERIFIED. Do not collapse those two facts
  or repeat an obsolete global count.

## Operational rule

A safe launch requires all of these to agree: clean Git HEAD, custody manifest,
native and daemon artifact hashes, running PID image paths, daemon `source_sha`,
rendered bundle identity, live acceptance result, and the Cato Vault record.
Any disagreement is a stop condition, not a warning to explain away.
