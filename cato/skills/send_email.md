# Send Email via Gmail
**Version:** 1.0.0
**Capabilities:** browser.navigate, browser.click, browser.type

## Instructions
Draft and send an email via Gmail web interface.

When asked to send an email:
1. Navigate to https://mail.google.com
2. Click "Compose" button
3. Fill in To, Subject, Body using the `browser` type action
4. Ask user to confirm before sending: "Ready to send to {recipient}. Confirm? (yes/no)"
5. If confirmed: click Send
6. Report success or any errors encountered

IMPORTANT: Always ask for confirmation before clicking Send.

<!-- COLD -->
