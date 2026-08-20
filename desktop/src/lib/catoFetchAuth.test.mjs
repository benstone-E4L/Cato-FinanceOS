import assert from "node:assert/strict";
import test from "node:test";

import { isExactCatoDaemonUrl } from "./catoFetchAuth.ts";

test("auth target accepts only the exact daemon origin", () => {
  const daemon = "http://127.0.0.1:8080";
  const page = "tauri://localhost/";

  assert.equal(isExactCatoDaemonUrl("http://127.0.0.1:8080/api/inbox", daemon, page), true);
  assert.equal(isExactCatoDaemonUrl("http://127.0.0.1:3001/api/finance", daemon, page), false);
  assert.equal(isExactCatoDaemonUrl("http://localhost:8080/api/inbox", daemon, page), false);
  assert.equal(isExactCatoDaemonUrl("http://127.0.0.1:8081/ws", daemon, page), false);
  assert.equal(isExactCatoDaemonUrl("https://127.0.0.1:8080/api/inbox", daemon, page), false);
});
