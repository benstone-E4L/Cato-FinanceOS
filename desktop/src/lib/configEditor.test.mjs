import assert from "node:assert/strict";
import test from "node:test";

import { configPatchBody, patchCatoConfig } from "./configEditor.ts";
import { readFile } from "node:fs/promises";

const configView = await readFile(new URL("../views/ConfigView.tsx", import.meta.url), "utf8");

test("ordinary config save submits no secret and preserves returned form state", async () => {
  let submitted;
  const fetchImpl = async (_url, init) => {
    submitted = JSON.parse(init.body);
    return {
      ok: true,
      status: 200,
      json: async () => ({ status: "ok", config: { ...submitted, log_level: "DEBUG" } }),
    };
  };
  const saved = await patchCatoConfig("http://127.0.0.1:8080", {
    agent_name: "Cato",
    telegram_enabled: true,
  }, fetchImpl);
  assert.deepEqual(submitted, { agent_name: "Cato", telegram_enabled: true });
  assert.deepEqual(saved, { agent_name: "Cato", telegram_enabled: true, log_level: "DEBUG" });
});

test("config editor refuses Telegram token before any request", async () => {
  let called = false;
  await assert.rejects(
    patchCatoConfig("http://127.0.0.1:8080", {
      telegram_bot_token: "not-a-real-token",
    }, async () => {
      called = true;
      throw new Error("must not be called");
    }),
    /Credentials must be stored in Auth Keys/,
  );
  assert.equal(called, false);
  assert.throws(() => configPatchBody({ API_KEY: "not-a-real-key" }), /Auth Keys/);
});

test("non-2xx config response is visible as a failed save", async () => {
  await assert.rejects(
    patchCatoConfig("http://127.0.0.1:8080", { agent_name: "Cato" }, async () => ({
      ok: false,
      status: 400,
      json: async () => ({ status: "error", message: "invalid config" }),
    })),
    /invalid config/,
  );
});

test("Config form labels the legacy model field as inert and read-only", () => {
  assert.match(configView, /Legacy display model \(does not control execution\)/);
  assert.match(configView, /default_model[\s\S]{0,120}readOnly/);
  assert.doesNotMatch(configView, /setField\("default_model"/);
});
