# Site Services Ops
**Version:** 1.0.0
**Capabilities:** site_services.inbox, site_services.stuck

## Instructions (HOT)
Triage permit-arbitrage opportunities from site-services inbox. **Never auto-send email or SMS** — always draft outreach and wait for explicit human approval before send. Use `site_services.inbox` to list new permit signals (address, SKU, price, quote URL). Use `site_services.stuck` when jobs stall in dispatch or payment. For each new item: (1) Telegram pulse sends inline buttons (Draft Email / Open Quote / Propose Match / Skip), (2) Draft queues `site_services.send_outreach` in outbound_approval — Approve Send calls POST send-outreach, (3) Propose Match calls match/preview then queues match_apply approval. Morning digest: `site_services.digest` schedule. Escalate disputes, refunds, and permit compliance to human review. Do not bypass OUTBOUND_SMS_ENABLED or payment gates.

<!-- COLD -->
