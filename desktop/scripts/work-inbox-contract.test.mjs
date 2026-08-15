import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  DEFAULT_VIEW,
  FINANCEOS_APPROVALS_URL,
  LEGACY_VIEW_REDIRECT,
  PRIMARY_NAV_ITEMS,
  WORK_INBOX_GROUPS,
  isFinanceStale,
  resolveView,
} from "../src/workInboxContract.ts";

const app = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const sidebar = await readFile(new URL("../src/components/Sidebar.tsx", import.meta.url), "utf8");
const inbox = await readFile(new URL("../src/views/WorkInboxView.tsx", import.meta.url), "utf8");
const approvals = await readFile(new URL("../src/views/ApprovalsView.tsx", import.meta.url), "utf8");

const expectedNav = [
  "Work Inbox",
  "Waiting/Follow-ups",
  "Approvals",
  "Calendar",
  "Company Tasks",
  "Finance",
  "Ask E4L",
  "Activity/Automations",
  "Settings/Diagnostics",
];

const expectedGroups = [
  "needs_me",
  "waiting",
  "approvals",
  "due_soon",
  "fyi",
  "resolved",
];

test("Work Inbox is the default landing surface", () => {
  assert.equal(DEFAULT_VIEW, "work-inbox");
  assert.match(app, /useState<View>\(DEFAULT_VIEW\)/);
});

test("primary navigation contains exactly the nine specified labels in order", () => {
  assert.deepEqual(PRIMARY_NAV_ITEMS.map((item) => item.label), expectedNav);
  assert.match(sidebar, /PRIMARY_NAV_ITEMS\.map/);
});

test("all absorbed legacy route ids resolve, including Replay", () => {
  const legacyIds = [
    "dashboard", "inbox", "alerts", "chat", "memory", "audit", "cron", "sessions",
    "replay", "usage", "logs", "budget", "settings", "config", "identity", "auth-keys",
    "skills", "system", "diagnostics", "nodes", "flows", "coding-agent", "interactive-cli",
  ];
  assert.deepEqual(Object.keys(LEGACY_VIEW_REDIRECT).sort(), legacyIds.sort());
  for (const id of legacyIds) assert.notEqual(resolveView(id).view, undefined);
  assert.deepEqual(resolveView("replay"), { view: "activity-automations", subTab: "sessions" });
});

test("Work Inbox renders all six card groups in fixed order", () => {
  assert.deepEqual(WORK_INBOX_GROUPS.map((group) => group.id), expectedGroups);
  assert.deepEqual(WORK_INBOX_GROUPS.map((group) => group.label), [
    "Needs Me", "Waiting", "Approvals", "Due Soon", "FYI/Summarized", "Resolved",
  ]);
  assert.match(inbox, /WORK_INBOX_GROUPS\.map/);
});

test("FinanceOS stale payloads are visibly stale even if connected is true", () => {
  assert.match(inbox, /isFinanceStale\(finance\)/);
  assert.match(inbox, /work-inbox-card-stale[^>]*>Stale</);
  assert.equal(isFinanceStale({ connected: true, stale: true }), true);
  assert.equal(isFinanceStale({ connected: false, stale: false }), true);
  assert.equal(isFinanceStale({ connected: true, stale: false }), false);
});

test("approval destinations separate local and external authority", () => {
  assert.match(inbox, /onNavigate\("approvals"/);
  assert.equal(FINANCEOS_APPROVALS_URL, "http://127.0.0.1:3001");
  assert.match(approvals, /href=\{FINANCEOS_APPROVALS_URL\}/);
  assert.match(approvals, /target="_blank"/);
  assert.doesNotMatch(approvals, /finance[^\n]{0,80}(approve|dismiss)/i);
});
