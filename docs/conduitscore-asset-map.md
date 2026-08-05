# ConduitScore Asset Map

**Build spec:** `CONDUITSCORE-NIGHT-SHIFT-001`  
**Last verified:** ____________ (re-run when moving machines or cloning repos)

> Fill every **Path / URL** cell. Mark **Exists?** after you verify on disk or in browser.  
> War-room references paths that may live outside this PC — if missing, note **LOCATE** and where you searched.

---

## 1. Strategy & inventory docs

| Asset | Path / URL | Exists? | Notes |
|-------|------------|---------|-------|
| War room master deliverable | `C:\Users\Administrator\Desktop\Decision Oracle\Assets Marketing Output\WAR-ROOM-MASTER-DELIVERABLE.md` | ☐ | |
| Inventory ConduitScore (companion) | `C:\Users\Administrator\Desktop\Decision Oracle\Assets Marketing Output\INVENTORY-05-conduitscore.md` | ☐ | |
| Night-shift build spec | `C:\Users\Administrator\Desktop\Cato\CONDUITSCORE_NIGHT_SHIFT_BUILD_SPEC.md` | ☐ | |
| Loop Proof Card | `C:\Users\Administrator\Desktop\Cato\docs\loop-proof-card.md` | ☐ | |
| Night-shift policy | `C:\Users\Administrator\Desktop\Cato\docs\night-shift-policy.yaml` | ☐ | |

---

## 2. ConduitScore product

| Asset | Path / URL | Exists? | Notes |
|-------|------------|---------|-------|
| ConduitScore repo (local) | ________________________________ | ☐ LOCATE | e.g. `Desktop\ConduitScore`, `Github\...` |
| Production site URL | https://________________________ | ☐ | |
| Staging URL (if any) | https://________________________ | ☐ | |
| Stripe Dashboard (product) | https://dashboard.stripe.com/... | ☐ | |
| **Stranger-test payable URL** | https://________________________ | ☐ | Checkout or Payment Link for P1-006 |
| Neon / DB console | ________________________________ | ☐ | |
| Public scoring API endpoint | https://________________________ | ☐ | No-auth API per war-room |

---

## 3. Contact lists (876 unsent — war-room)

| Asset | Path / URL | Exists? | Notes |
|-------|------------|---------|-------|
| 303 validated contacts | ________________________________ | ☐ LOCATE | Format: CSV / JSON / SQLite |
| 573 harvested contacts | ________________________________ | ☐ LOCATE | |
| Canary-25 subset manifest | `C:\Users\Administrator\Desktop\Cato\proof-artifacts\canary-25\manifest.json` | ☐ | `cato canary select --source <csv>` |
| Selection criteria doc | `proof-artifacts/canary-25/selection-criteria.md` | ☐ | Auto-written by `cato canary select` |
| Canary tracking sheet | `proof-artifacts/canary-25/tracking-sheet.csv` | ☐ | Sync: `cato canary sync-tracking` |
| Operator README | `proof-artifacts/canary-25/README.md` | ☐ | Row 4 supervised sends |

**Search hints if LOCATE:** Desktop, `Github`, ConduitScore repo `data/`, outreach engine `contacts/`, war-room `INVENTORY-05`.

---

## 4. Cold outreach engines

| Asset | Path / URL | Exists? | Notes |
|-------|------------|---------|-------|
| `conduit_outreach_pipeline/` root | ________________________________ | ☐ LOCATE | ~58 files per war-room |
| Entry script / CLI | ________________________________ | ☐ | |
| `reverse_funnel_outreach/` root | ________________________________ | ☐ LOCATE | |
| Entry script / CLI | ________________________________ | ☐ | |
| Gmail / SMTP credentials location | Vault key name: __________ | ☐ | Never paste secrets here |
| Warmup config | ________________________________ | ☐ | |
| Unsubscribe template path | ________________________________ | ☐ | |

---

## 5. Conduit (crypto-audit browser)

| Asset | Path / URL | Exists? | Notes |
|-------|------------|---------|-------|
| Conduit / conduit-browser repo | ________________________________ | ☐ LOCATE | |
| MCP server config in Cato | `%APPDATA%\cato\config.yaml` → conduit section | ☐ | |
| Cato conduit bridge | `C:\Users\Administrator\Desktop\Cato\cato\tools\conduit_bridge.py` | ☐ | |
| verify_deliverable / verify_rubric docs | ________________________________ | ☐ | |

---

## 6. AIVS / Representation Fidelity

| Asset | Path / URL | Exists? | Notes |
|-------|------------|---------|-------|
| AIVS spec (IETF/doc) | ________________________________ | ☐ LOCATE | |
| Fidelity MVP code path | ________________________________ | ☐ | P1-002 deliverable |
| Signing key / attestor | ________________________________ | ☐ | How artifacts are signed |
| Public verify page URL | https://________________________ | ☐ | |

---

## 7. Genesis fleet & SwarmSync

| Asset | Path / URL | Exists? | Notes |
|-------|------------|---------|-------|
| Genesis skill_bundles (source of truth) | ________________________________ | ☐ LOCATE | e.g. `Github/Genesis-Agents/skill_bundles/` |
| SwarmSync agents API | `https://swarmsync-agents.onrender.com` | ☐ | Default in `cato/tools/genesis.py` |
| Cato genesis tool | `C:\Users\Administrator\Desktop\Cato\cato\tools\genesis.py` | ☐ | |
| `GATEWAY_API_KEY` location | Vault / `.env` key name: __________ | ☐ | No secret values in this file |
| Agents used for loop | analyst, content, email, marketing: ☐ configured in allowlist | | |

---

## 8. Cato control plane (this repo)

| Asset | Path / URL | Exists? | Notes |
|-------|------------|---------|-------|
| Cato repo | `C:\Users\Administrator\Desktop\Cato` | ☐ | |
| Daemon runner | `C:\Users\Administrator\Desktop\Cato\cato_svc_runner.py` | ☐ | |
| Config | `%APPDATA%\cato\config.yaml` | ☐ | |
| Vault | `%APPDATA%\cato\vault.enc` | ☐ | |
| Budget state | `%APPDATA%\cato\budget.json` | ☐ | |
| Audit DB | `%APPDATA%\cato\cato.db` | ☐ | |
| YAML schedules dir | `%APPDATA%\cato\schedules\` | ☐ | |
| Clawflows dir | `%APPDATA%\cato\flows\` | ☐ | |
| Agent CRONS | `%APPDATA%\cato\agents\<agent>\CRONS.json` | ☐ | |
| Desktop app | `desktop\src-tauri\target\release\cato-desktop.exe` | ☐ | |
| Telegram bot | Config + vault `TELEGRAM_BOT_TOKEN` | ☐ | |

---

## 9. Proof artifacts directory (create as you go)

| Folder | Purpose |
|--------|---------|
| `C:\Users\Administrator\Desktop\Cato\proof-artifacts\fp1\` | Deliverability screenshots |
| `proof-artifacts\fidelity\` | Contract + samples |
| `proof-artifacts\canary-25\` | Manifest + tracking |
| `proof-artifacts\stripe\` | Redacted receipts |
| `proof-artifacts\audits\` | war-audit / truth-audit reports |

---

## Verification checklist

- [ ] Every **LOCATE** row resolved or ticket opened
- [ ] Stranger-test payable URL opens in incognito without login
- [ ] At least one cold engine entry script runs `--help` or dry-run
- [ ] Genesis `/health` returns OK (or warmup documented)
- [ ] Asset map reviewed by operator — date: __________
