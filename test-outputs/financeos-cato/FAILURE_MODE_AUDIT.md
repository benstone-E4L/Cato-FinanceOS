# Failure Mode Audit: Cato desktop → authenticated daemon WebSocket → browser E2E harness
**Scope:** Desktop chat connection, daemon-token custody, `/ws` authentication, message delivery, and the browser-only proof harness | **Target version:** `0b7b99d` plus local authenticated-harness changes, 2026-08-05 | **Mode:** interactive | **Auditor confidence:** HIGH — the complete connection path was read from source and driven through a real Chromium/WebSocket run

## 0. Executive Summary
- **Verdict: FLAWED.** Authentication fails closed and the current happy path is proven, but message delivery has no application-level acknowledgement/idempotency, the legacy injected-token dashboard retains a broad DOM-XSS blast radius, and the harness mocks enough HTTP behavior to hide cross-surface contract drift.
- **Top 5 risks:** F01 unacknowledged chat delivery, RPN 36; F02 legacy dashboard DOM-XSS can expose the daemon token, RPN 36; F03 harness HTTP mocks can certify an incompatible daemon, RPN 27; F04 reconnect timers can outlive a Chat mount, RPN 27; F05 long-lived token in the WebSocket query string can enter diagnostics, RPN 24.
- **Counts:** CRITICAL 0 | HIGH 4 | MEDIUM 8 | LOW 4 (of 16 total)
- **Next action:** Add a `client_message_id` + server acknowledgement/deduplication contract before treating WebSocket delivery as reliable for finance-agent commands.

## 1. Process Overview
Cato starts a loopback daemon, the native shell reads its token, React builds an authenticated WebSocket URL, the daemon checks the token, and the gateway accepts and answers messages. The E2E harness preserves the real server and WebSocket boundary while replacing downstream model execution with a deterministic response.

```text
1. Daemon loads/creates 64-char token → ~/.cato/daemon.token
   [cato/ui/server.py:141-156]
2. Tauri reads daemon.token → get_daemon_status returns ports + token
   [desktop/src-tauri/src/sidecar.rs:43-48; desktop/src-tauri/src/lib.rs:33-39]
3. React receives daemon status → Chat builds ws://127.0.0.1:<port>/ws?token=<encoded>
   [desktop/src/App.tsx:68-76; desktop/src/hooks/useChatStream.ts:137-146]
4. Daemon validates loopback Host → compares query/header token → upgrades socket
   [cato/ui/server.py:526-540; cato/ui/server.py:859-870]
   ├─ invalid token → HTTP 401 [PROVEN by invalid-token probe]
   └─ valid token → gateway.register_websocket [cato/ui/server.py:872]
5. User submits prompt → client sends message envelope
   [desktop/src/views/ChatView.tsx:230-252; desktop/src/hooks/useChatStream.ts:240+]
6. Gateway parses/queues command → emits response → React persists/render response
   [cato/gateway.py:1035-1053; desktop/src/hooks/useChatStream.ts:155-199]
7. Harness branch: deterministic gateway uses the same create_ui_app and `/ws`
   [test-outputs/financeos-cato/authenticated_ws_harness.py:13-47]
8. Playwright drives dashboard → workflow → Send → authenticated response
   [test-outputs/financeos-cato/e2e_financeos_cato.py:95-104]
```

Full nine-category coverage: steps 1–6, because they cross security, network, and finance-command handoffs. Abbreviated coverage: steps 7–8, emphasizing technical, data, and process-design failures.

## 2. Risk Table
| ID | Step | Failure mode | Category | L | I | D | RPN | Tier |
|---|---:|---|---|---:|---:|---:|---:|---|
| F01 | 5–6 | No `client_message_id`, acknowledgement, or gateway dedupe means a disconnect around Send can silently lose a finance command or cause a manual duplicate | Timing/process | 3 | 4 | 3 | 36 | HIGH |
| F02 | 1–4 | Legacy dashboard injects `_DAEMON_TOKEN` into JavaScript while many dynamic surfaces use `innerHTML`; one unescaped daemon value can expose every privileged local API | Security | 3 | 4 | 3 | 36 | HIGH |
| F03 | 7–8 | Playwright routes every HTTP request on port 8080 to fixtures, so `/api/inbox`, `/api/sessions`, FinanceOS, and CORS/auth contract drift can pass while only `/ws` is real | Process/data | 3 | 3 | 3 | 27 | HIGH |
| F04 | 3 | `setTimeout(connect, backoff)` is not retained or cancelled; a timer scheduled before unmount can create a socket after Chat is gone | Timing/technical | 3 | 3 | 3 | 27 | HIGH |
| F05 | 3–4 | Long-lived daemon token is placed in the WebSocket query string, which can appear in browser/network diagnostics or access logs | Security | 2 | 4 | 3 | 24 | MEDIUM |
| F06 | 6 | Up to 500 finance chat messages persist indefinitely in localStorage without TTL or operator-controlled retention | Data/compliance | 3 | 3 | 2 | 18 | MEDIUM |
| F07 | 7 | The harness token is fixed and committed; if the harness is left listening, any local process that knows the repository can authenticate | Security/process | 2 | 3 | 3 | 18 | MEDIUM |
| F08 | 1–2 | `chmod(0o600)` is not a Windows ACL guarantee; token confidentiality depends on profile-directory ACL inheritance | Security | 2 | 3 | 3 | 18 | MEDIUM |
| F09 | 3 | Reconnect has no jitter; many windows recovering together can synchronize at the 30-second cap | Scalability/timing | 2 | 3 | 3 | 18 | MEDIUM |
| F10 | 8 | Invalid-token refusal is a one-off probe, not a persistent E2E scenario, so a future fail-open regression will not fail CI | Process/security | 2 | 4 | 2 | 16 | MEDIUM |
| F11 | 7 | Harness `json.loads(raw)` has no malformed-frame guard and can terminate the deterministic response path on unexpected browser data | Edge/technical | 2 | 2 | 3 | 12 | MEDIUM |
| F12 | 4 | CORS accepts any localhost origin and port; a compromised local web app can call Cato if it obtains the token | Security | 2 | 3 | 2 | 12 | MEDIUM |
| F13 | 1 | Token persists across daemon restarts, expanding the exposure window compared with a per-process credential | Security/process | 2 | 3 | 2 | 12 | MEDIUM |
| F14 | 7 | Fixed ports 8080/5173 make the harness fail when another local service owns either port | External/edge | 2 | 2 | 1 | 4 | LOW |
| F15 | 8 | Green-color assertion scans only the current dashboard DOM, not Inbox, Settings, or deferred states | Process/edge | 2 | 2 | 1 | 4 | LOW |
| F16 | 3 | Non-JSON WebSocket payloads are displayed as assistant text, potentially masking a protocol/version mismatch as a valid answer | Data/edge | 1 | 2 | 2 | 4 | LOW |

## 3. High-Risk Step Detail

### Steps 1–2 — token creation and native custody
- Human: local operator can copy or weaken profile permissions; no UI asks them to handle the token. 
- Technical: file read/write or data-directory resolution failure prevents native authentication.
- Process: token rotation/revocation is absent; the token is reused when it remains 64 characters.
- External: N/A — token creation makes no vendor/network call.
- Data: truncated or replaced token yields native/server mismatch and endless reconnect.
- Security: Windows protection relies on directory ACL inheritance because `chmod(0o600)` is not a complete Windows ACL operation.
- Timing: native shell can read the token before the daemon finishes replacing an invalid file.
- Scale: N/A — one token/file per local profile.
- Edge: read-only/full-disk/profile-redirection failures can block persistence.

### Steps 3–4 — browser connection and daemon authentication
- Human: operator can expose the query URL through diagnostics or screenshots.
- Technical: Strict Mode lifecycle previously left the UI permanently Connecting; setup now resets `mountedRef` and teardown detaches callbacks.
- Process: reconnect timers are not owned/cancelled, so lifecycle correctness remains incomplete.
- External: loopback browser and native runtime versions can differ in WebSocket behavior.
- Data: stale port/token pairs cause authenticated connection failure.
- Security: host validation and constant-time comparison defend the boundary; query-token visibility and broad localhost CORS remain.
- Timing: scheduled reconnect can fire after unmount; synchronized clients have no jitter.
- Scale: repeated mounted Chat views can accumulate unnecessary connection attempts.
- Edge: IPv6 is allowed server-side but the React host allowlist forces `127.0.0.1:<port>`.

### Steps 5–6 — send, queue, and receive
- Human: a user will retry when no reply appears, creating duplicate finance work.
- Technical: a socket can close after the browser sends but before it receives a response.
- Process: there is no client acknowledgement, durable outbox, or replay/dedupe key.
- External: downstream model or CLI latency can exceed the user's willingness to wait.
- Data: duplicate/lost prompts can produce inconsistent proposed actions; localStorage retains sensitive contents.
- Security: authenticated access is proven, but token compromise grants the same message surface.
- Timing: disconnect ambiguity is silent; TCP completion does not prove gateway acceptance.
- Scale: unbounded user retries can multiply model work and queue load.
- Edge: empty input is blocked; malformed gateway frames can be rendered as ordinary assistant text.

## 4. Correctness Audit
1. **Logically sound:** The native token and port feed the React hook, the same token is compared by `/ws`, and the authenticated response reaches Chat. This exact path passed in Chromium. Delivery confirmation is logically incomplete because UI send completion is not gateway acceptance.
2. **Complete:** Authentication and reconnect exist, but acknowledgement, idempotency, retry ownership, token rotation, and retention policy are missing.
3. **Robust:** Host validation, constant-time comparison, fail-closed 401 behavior, bounded exponential backoff, and defensive API shapes are concrete defenses. Lack of jitter, timer cancellation, and application-level delivery state weakens failure recovery.
4. **Efficient:** One WebSocket carries bidirectional chat efficiently. Polling chat history every five seconds alongside WebSocket delivery duplicates transport work and adds dedupe complexity.
5. **Resilient:** The client reconnects and the daemon rejects invalid tokens. It cannot distinguish “message never arrived” from “message accepted but response lost,” so partial network failure is not safely recoverable.
6. **Brittle points:** The long-lived token is a single capability credential, the legacy dashboard's DOM construction magnifies any injection, and the E2E HTTP interception can hide daemon/API incompatibility.

Summary: authentication is materially sound and now proven, but command-delivery semantics and test parity are not strong enough for unattended finance-agent operation.

## 5. Mitigations

**Finding:** Unacknowledged/duplicate finance commands (RPN: 36, HIGH)  
**Mitigation:** Add `client_message_id` to `buildChatMessagePayload`; have `Gateway._handle_ws_message` persist/recognize the ID and immediately emit `{type:"accepted", client_message_id}` before work begins. Keep pending IDs in Chat and retry only IDs without acknowledgement.  
**Type:** Prevention + Recovery  
**Effort:** 1–2 days  
**Owner:** fix-now (Claude, next implementation session)

**Finding:** Legacy dashboard token exposure through DOM-XSS surface (RPN: 36, HIGH)  
**Mitigation:** Replace data-bearing `innerHTML` writes in `cato/ui/dashboard.html` with DOM/textContent construction or a single escaping helper, add a restrictive CSP, and stop injecting the long-lived token into a broadly mutable page.  
**Type:** Prevention  
**Effort:** 2–4 days  
**Owner:** next-session (Claude, queued)

**Finding:** E2E HTTP mocks hide daemon contract drift (RPN: 27, HIGH)  
**Mitigation:** Run a second parity scenario without `page.route` interception for `/health`, `/api/sessions`, `/api/inbox`, and `/api/finance-os/health`; seed only the deterministic gateway/model boundary. Require those routes and auth headers to pass.  
**Type:** Detection  
**Effort:** 1 day  
**Owner:** fix-now (Claude, next implementation session)

**Finding:** Reconnect timer survives unmount (RPN: 27, HIGH)  
**Mitigation:** Store the timeout ID in `reconnectTimerRef`, clear it in effect cleanup, and make `connect()` return immediately when `mountedRef.current` is false. Add a Strict Mode test that advances fake timers after unmount and asserts no new `WebSocket`.  
**Type:** Prevention  
**Effort:** 2–4 hours  
**Owner:** fix-now (Claude, next implementation session)

Medium mitigations: move browser WS auth to a first-message envelope to keep tokens out of URLs; establish Windows ACLs explicitly; generate a random harness token per run; add jitter; add invalid-token CI coverage; give chat history a retention/clear policy; catch malformed harness frames; narrow allowed localhost origins where practical.

Low findings: allocate ephemeral harness ports, scan all navigable surfaces for forbidden colors, and treat non-JSON frames as protocol errors instead of assistant messages.

## 6. Handoff
Run `truth-fix-loop` to implement and verify F01–F04 iteratively, or `output-to-orchestrator` if assigning the mitigation cards across agents. This audit predicts risk; it does not prove the complete product works. Before shipping, rerun `/truth-before-launch` after the delivery and parity mitigations land.

**Changed:** Produced this grounded FMEA and an authenticated deterministic WebSocket harness; fixed the Strict Mode connection lifecycle defects found while establishing proof.  
**Verified:** Valid token connects, invalid token is refused, Chromium sends a guarded E4Life prompt and receives an authenticated response, all five browser scenarios pass, and every audit step cites source lines.  
**Still Broken:** No message acknowledgement/idempotency, uncancelled reconnect timers, HTTP-mocked parity gaps, and the legacy token-bearing dashboard DOM-XSS surface remain unresolved predictions.
