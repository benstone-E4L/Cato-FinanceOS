# Daily Digest
**Version:** 1.0.0
**Capabilities:** browser.search, memory.search, file.read

## Instructions
Generate a personalized daily digest for the user.

When asked for a daily digest (or triggered via cron):
1. Search memory for user's tracked topics: `memory search "topics interests follow"`
2. For each topic (max 5): `browser search "{topic} news today"`
3. Summarize the top story per topic in 2-3 sentences
4. Read today's daily log file if exists: `file read "YYYY-MM-DD.md"`
5. Include any open tasks or action items from the daily log
6. Format the digest as:

---
**Daily Digest — {date}**

**{Topic 1}:** {summary}
**{Topic 2}:** {summary}
...

**Open Tasks:** {from daily log, or "None"}

*Budget used today: {budget_footer}*

---

Send via the active channel (Telegram or WhatsApp).

<!-- COLD -->
