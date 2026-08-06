import asyncio, json, os, sys, time
from pathlib import Path

import aiohttp

OUT = Path(r"""C:\Users\Work\Desktop\vault\projects\My Github\Cato\proof-artifacts\fix-daemon-anthropic-dns""")
TOKEN_PATH = Path(os.environ.get("APPDATA", "")) / "cato" / "daemon.token"
token = TOKEN_PATH.read_text(encoding="utf-8").strip()
assert token, "missing daemon token"

async def main():
    health = await _get("http://127.0.0.1:8080/health")
    (OUT / "health_post_restart.txt").write_text(health, encoding="utf-8")
    session_id = f"fix-daemon-anthropic-dns-{int(time.time())}"
    url = "ws://127.0.0.1:8080/ws"
    headers = {"X-Cato-Token": token}
    evidence = {
        "session_id": session_id,
        "path": "daemon WebSocket /ws -> gateway -> agent_loop -> AnthropicDirectClient",
        "SECRETS_PRINTED": "NO",
    }
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(url, headers=headers, heartbeat=30) as ws:
            # send chat message in whatever shape the gateway expects
            msg = {
                "type": "message",
                "text": "Reply with exactly one word: PONG",
                "channel": "web",
                "session_id": session_id,
            }
            await ws.send_json(msg)
            replies = []
            deadline = time.time() + 120
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.receive(), timeout=max(1, deadline - time.time()))
                except asyncio.TimeoutError:
                    break
                if raw.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    evidence["ws_end"] = str(raw.type)
                    break
                if raw.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(raw.data)
                replies.append(data)
                t = data.get("type")
                if t in ("response", "message", "error", "assistant"):
                    text = data.get("text") or data.get("content") or ""
                    if data.get("role") == "user":
                        continue
                    if t == "message" and data.get("role") != "assistant":
                        # may be echo of user
                        if data.get("channel") == "web" and data.get("role") == "user":
                            continue
                    if text or t == "error":
                        evidence["reply_type"] = t
                        evidence["reply_preview"] = str(text)[:300]
                        evidence["raw_keys"] = sorted(list(data.keys()))
                        break
            evidence["n_frames"] = len(replies)
            (OUT / "ws_frames.json").write_text(json.dumps(replies, indent=2)[:50000], encoding="utf-8")
    ok = False
    preview = (evidence.get("reply_preview") or "").strip()
    if preview and not preview.lower().startswith("[error") and "DNS" not in preview and "400" not in preview:
        ok = True
        evidence["RESULT"] = "PASS"
    else:
        evidence["RESULT"] = "BLOCKED_OR_FAIL"
        evidence["reply_preview"] = preview
    lines = [f"{k}={v}" for k, v in evidence.items()]
    (OUT / "model_call_evidence.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("RESULT", evidence.get("RESULT"))
    print("preview", (preview[:120] if preview else ""))

async def _get(url):
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            return f"status={r.status}\n{await r.text()}"

asyncio.run(main())
