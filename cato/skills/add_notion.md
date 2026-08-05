# Add to Notion
**Version:** 1.0.0
**Capabilities:** shell

## Instructions
Add a page or block to Notion using the Notion API.

Requirements: NOTION_API_KEY must be set in vault, DATABASE_ID must be provided or stored in MEMORY.md.

When asked to add something to Notion:
1. Check vault for NOTION_API_KEY
2. Check MEMORY.md for the target database ID, or ask user if not found
3. Use the `shell` tool to POST to the Notion API:
   ```
   curl -X POST https://api.notion.com/v1/pages \
     -H "Authorization: Bearer {NOTION_API_KEY}" \
     -H "Notion-Version: 2022-06-28" \
     -H "Content-Type: application/json" \
     -d '{"parent": {"database_id": "{DATABASE_ID}"}, "properties": {...}}'
   ```
4. Report the created page URL from the response

<!-- COLD -->
