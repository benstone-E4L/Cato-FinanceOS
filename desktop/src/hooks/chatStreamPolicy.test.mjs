import assert from "node:assert/strict";
import test from "node:test";

import {
  CHAT_HISTORY_TTL_MS,
  decodeChatHistory,
  decodeSocketFrame,
  encodeChatHistory,
  reconnectDelayMs,
  scheduleReconnect,
} from "./chatStreamPolicy.ts";

test("reconnect jitter is deterministic and bounded", () => {
  assert.equal(reconnectDelayMs(1, 0), 400);
  assert.equal(reconnectDelayMs(1, 0.5), 500);
  assert.equal(reconnectDelayMs(1, 1), 600);
  assert.equal(reconnectDelayMs(20, 1), 30_000);
});

test("expired chat history is rejected and current history survives", () => {
  const now = 2_000_000_000_000;
  const messages = [{ id: "one", role: "user", text: "hello", timestamp: now }];
  assert.deepEqual(decodeChatHistory(encodeChatHistory(messages, now), now), messages);
  assert.deepEqual(
    decodeChatHistory(encodeChatHistory(messages, now - CHAT_HISTORY_TTL_MS), now),
    [],
  );
});

test("legacy array history migrates without data loss", () => {
  const messages = [{ id: "legacy", role: "assistant", text: "hello", timestamp: 1 }];
  assert.deepEqual(decodeChatHistory(JSON.stringify(messages)), messages);
});

test("non-JSON and non-object frames are protocol errors", () => {
  assert.deepEqual(decodeSocketFrame("plain text"), {
    ok: false,
    error: "Protocol error: daemon sent a non-JSON WebSocket frame.",
  });
  assert.equal(decodeSocketFrame("[]").ok, false);
  assert.deepEqual(decodeSocketFrame('{"type":"health"}'), {
    ok: true,
    value: { type: "health" },
  });
});

test("a cancelled reconnect callback cannot open a socket after unmount", () => {
  let opens = 0;
  let scheduledCallback = () => {};
  let cancelled = false;
  const timer = scheduleReconnect(
    () => { opens += 1; },
    500,
    (callback) => {
      scheduledCallback = callback;
      return 42;
    },
    (id) => {
      assert.equal(id, 42);
      cancelled = true;
    },
  );
  timer.cancel();
  // Even a hostile/faulty scheduler delivering after cancellation is guarded.
  scheduledCallback();
  assert.equal(cancelled, true);
  assert.equal(opens, 0);
});
