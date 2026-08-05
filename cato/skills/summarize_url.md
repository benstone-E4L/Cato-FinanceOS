# Summarize URL
**Version:** 1.0.0
**Capabilities:** browser.navigate, browser.snapshot

## Instructions
Fetch a URL and return a concise summary of its content.

When given a URL:
1. Use `browser` tool with action `navigate` and the URL
2. Use `browser` tool with action `snapshot` to get the page text
3. Extract the main content (ignore nav, ads, footers)
4. Return a 3-5 sentence summary with key points as bullet list
5. Include: title, publication date (if found), author (if found)

<!-- COLD -->
