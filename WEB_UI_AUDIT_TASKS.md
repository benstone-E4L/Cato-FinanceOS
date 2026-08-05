# Cato Web UI Audit — Task List
**Date**: 2026-03-09 07:15:00
**Total findings**: 27 bugs, 1 security, 1 warnings, 15 passing

## SECURITY Issues
- [ ] **SECURITY**: SECURITY-CONFIG — /api/config leaks telegram_bot_token in plaintext: 8622193070:AAHwOvcvD...

## Bugs
- [ ] **BUG**: API-CLI-STATUS — codex CLI: installed=True but logged_in=False — version check failed (timeout or error). The 'logged_in' field is determined solely by whether '--version' succeeds, not actual auth status
- [ ] **BUG**: API-CLI-STATUS — gemini CLI: installed=True but logged_in=False — version check failed (timeout or error). The 'logged_in' field is determined solely by whether '--version' succeeds, not actual auth status
- [ ] **BUG**: API-CLI-STATUS — cursor CLI: installed=True but logged_in=False — version check failed (timeout or error). The 'logged_in' field is determined solely by whether '--version' succeeds, not actual auth status
- [ ] **BUG**: NAV — Error navigating to 'Chat': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"chat\"]")
    - locator resolved to <div data-page="chat" class="nav-item active" onclick="navigate('chat')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    54 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Agents': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"agents\"]")
    - locator resolved to <div class="nav-item" data-page="agents" onclick="navigate('agents')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Skills': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"skills\"]")
    - locator resolved to <div class="nav-item" data-page="skills" onclick="navigate('skills')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Cron': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"cron\"]")
    - locator resolved to <div class="nav-item" data-page="cron" onclick="navigate('cron')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    54 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Sessions': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"sessions\"]")
    - locator resolved to <div class="nav-item" data-page="sessions" onclick="navigate('sessions')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Flows': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"flows\"]")
    - locator resolved to <div class="nav-item" data-page="flows" onclick="navigate('flows')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Usage': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"usage\"]")
    - locator resolved to <div class="nav-item" data-page="usage" onclick="navigate('usage')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Audit Log': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"audit\"]")
    - locator resolved to <div class="nav-item" data-page="audit" onclick="navigate('audit')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Memory': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"memory\"]")
    - locator resolved to <div class="nav-item" data-page="memory" onclick="navigate('memory')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Logs': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"logs\"]")
    - locator resolved to <div class="nav-item" data-page="logs" onclick="navigate('logs')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Alerts': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"alerts\"]")
    - locator resolved to <div class="nav-item" data-page="alerts" onclick="navigate('alerts')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'System': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"system\"]")
    - locator resolved to <div class="nav-item" data-page="system" onclick="navigate('system')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Diagnostics': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"diagnostics\"]")
    - locator resolved to <div class="nav-item" data-page="diagnostics" onclick="navigate('diagnostics')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Nodes': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"nodes\"]")
    - locator resolved to <div class="nav-item" data-page="nodes" onclick="navigate('nodes')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Config': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"config\"]")
    - locator resolved to <div class="nav-item" data-page="config" onclick="navigate('config')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms
    - waiting for element to be visible, enabled and stable
    - element is visible, enabled and stable
    - scrolling into view if needed
    - done scrolling

- [ ] **BUG**: NAV — Error navigating to 'Budget': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"budget\"]")
    - locator resolved to <div class="nav-item" data-page="budget" onclick="navigate('budget')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Conduit': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"conduit\"]")
    - locator resolved to <div class="nav-item" data-page="conduit" onclick="navigate('conduit')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Vault & Auth': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"vault\"]")
    - locator resolved to <div class="nav-item" data-page="vault" onclick="navigate('vault')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: NAV — Error navigating to 'Identity': Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"identity\"]")
    - locator resolved to <div class="nav-item" data-page="identity" onclick="navigate('identity')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

- [ ] **BUG**: PLAYWRIGHT — Browser test failed: Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"chat\"]")
    - locator resolved to <div data-page="chat" class="nav-item active" onclick="navigate('chat')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms

Traceback (most recent call last):
  File "C:\Users\Administrator\Desktop\Cato\web_ui_playwright_test.py", line 668, in <module>
    await page.wait_for_timeout(500)
  File "C:\Program Files\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
  File "C:\Program Files\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Program Files\Python312\Lib\asyncio\base_events.py", line 691, in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
  File "C:\Users\Administrator\Desktop\Cato\web_ui_playwright_test.py", line 262, in run_browser_tests
    else:
  File "C:\Users\Administrator\AppData\Roaming\Python\Python312\site-packages\playwright\async_api\_generated.py", line 15603, in click
    await self._impl_obj.click(
  File "C:\Users\Administrator\AppData\Roaming\Python\Python312\site-packages\playwright\_impl\_locator.py", line 162, in click
    return await self._frame._click(self._selector, strict=True, **params)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Administrator\AppData\Roaming\Python\Python312\site-packages\playwright\_impl\_frame.py", line 566, in _click
    await self._channel.send("click", self._timeout, locals_to_params(locals()))
  File "C:\Users\Administrator\AppData\Roaming\Python\Python312\site-packages\playwright\_impl\_connection.py", line 69, in send
    return await self._connection.wrap_api_call(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Administrator\AppData\Roaming\Python\Python312\site-packages\playwright\_impl\_connection.py", line 559, in wrap_api_call
    raise rewrite_error(error, f"{parsed_st['apiName']}: {error}") from None
playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator("[data-page=\"chat\"]")
    - locator resolved to <div data-page="chat" class="nav-item active" onclick="navigate('chat')">…</div>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div id="onboarding-overlay">…</div> intercepts pointer events
    - retrying click action
      - waiting 100ms
    55 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div id="onboarding-overlay">…</div> intercepts pointer events
     - retrying click action
       - waiting 500ms


- [ ] **BUG**: SOURCE-BOT-NAME — Found 2 hardcoded "AI" in bot avatar elements. Lines: 1432 (renderMessages), 1439 (typing-indicator), 1549 (startStreaming). Should be "Cato" or configurable.
- [ ] **BUG**: SOURCE-HEARTBEAT — Dashboard heartbeat display does not show the 'last_heartbeat' timestamp from the API — user cannot see WHEN the last heartbeat was, only the status badge and uptime
- [ ] **BUG**: SOURCE-CLI-AUTH — CLI auth detection in server.py (line 396) equates 'version command succeeded' with 'logged_in=True'. This is incorrect — running 'codex --version' or 'gemini --version' timing out does NOT mean the user is not authenticated. The API should check actual auth state or at minimum not conflate version availability with login status.
- [ ] **BUG**: SOURCE-NO-RETRY — No retry/reconnect button exists for failed CLI auth checks on the Vault & Auth page. Users cannot re-check CLI status without reloading the entire page.

## Warnings / UX Issues
- [ ] **UX**: SOURCE-IDENTITY-DUP — Identity page has dedicated buttons for: ['SOUL.md', 'IDENTITY.md', 'USER.md', 'AGENTS.md', 'SOUL.md']. Agents page IDENTITY_FILES list includes: 'SOUL.md','IDENTITY.md','MEMORY.md','TOOLS.md','USER.md','AGENTS.md','HEARTBEAT.md'. These two pages overlap in functionality — the same files (SOUL.md, IDENTITY.md, USER.md, AGENTS.md) are editable from both places with different UI patterns.

## Passing Checks
- [x] **OK**: API-HEALTH — /health returns 200 OK — uptime=3971s
- [x] **OK**: API-HEARTBEAT — /api/heartbeat status=alive, uptime=3968s, last=2026-03-09T14:04:26.682884+00:00
- [x] **OK**: API-CONFIG — /api/config returns 200
- [x] **OK**: API-BUDGET — /api/budget/summary — session_spend=0.0, monthly_spend=0.0
- [x] **OK**: API-SKILLS — /api/skills returns 18 skills
- [x] **OK**: API-SESSIONS — /api/sessions returns 3 sessions
- [x] **OK**: API-VAULT — /api/vault/keys returns 5 keys: ['OPENROUTER_API_KEY', 'PLAYWRIGHT_TEST_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_PHONE', 'TEST_KEY']
- [x] **OK**: API-CLI-STATUS — claude CLI: installed, version='2.1.71 (Claude Code)'
- [x] **OK**: API-USAGE — /api/usage/summary returns data, total_calls=0
- [x] **OK**: API-LOGS — /api/logs returns 41 entries
- [x] **OK**: API-AUDIT — /api/audit/entries returns 0 entries
- [x] **OK**: API-ADAPTERS — /api/adapters returns adapters: ['telegram', 'whatsapp']
- [x] **OK**: API-CRON — /api/cron/jobs returns 3 jobs
- [x] **OK**: PAGE-CODING-AGENT — /coding-agent page loads correctly
- [x] **OK**: PAGE-DASHBOARD — Dashboard loads with title: Cato Dashboard
