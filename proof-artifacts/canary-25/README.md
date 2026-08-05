# Canary-25 operator kit

Supervised batch for **G1 Loop Proof Card — Row 4** (25 hand-approved sends, 7-day tracking).

Cato **does not send email** from this kit. It only builds proof files and tracks metrics while you send through the outreach engine manually.

## Quick start

1. Point at your validated list (e.g. ConduitScore `outreach_valid_303.csv`) or a Clay export.
2. Validate the pool:

   ```text
   cato canary import --source C:\path\to\outreach_valid_303.csv
   ```

3. Select 25 and write artifacts:

   ```text
   cato canary select --source C:\path\to\outreach_valid_303.csv --seed 42
   ```

   Creates:
   - `manifest.json` — batch + per-contact flags
   - `selection-criteria.md` — audit trail for how the 25 were chosen
   - `tracking-sheet.csv` — spreadsheet-friendly log

4. For each contact: review copy → `cato canary approve --contact example.com` → send manually → `cato canary mark-sent --contact example.com`

5. Record engagement:

   ```text
   cato canary record --contact example.com --reply
   cato canary record --contact other.com --audit-view
   ```

   Each flag needs `--contact <domain>` (batch-only record is not supported).

   Or edit `tracking-sheet.csv` and run `cato canary sync-tracking`.

6. Check Row 4 status:

   ```text
   cato canary status
   ```

## Pass criteria (Row 4)

- **25/25** sends logged
- **≥1** reply **or** audit view
- **Complaint rate** &lt; 0.1%
- Track bounces in the sheet (document rate on loop proof card)

Do **not** set `gates.g1_manual_loop_proven: true` until rows 4–6 are complete on `docs/loop-proof-card.md`.

## Safety

- `live_outreach_allowed` stays false until G1 is signed.
- Never use `outreach.run` with `dry_run: false` at scale until the full loop is proven.

See `docs/conduitscore-asset-map.md` and `docs/loop-proof-card.md`.
