/** Executable CHUNK_6_WORK_INBOX navigation and presentation contract. */

export const PRIMARY_NAV_ITEMS = [
  { id: "work-inbox", label: "Work Inbox", hint: "What needs your attention" },
  { id: "waiting-followups", label: "Waiting/Follow-ups", hint: "Reserved — not yet available" },
  { id: "approvals", label: "Approvals", hint: "Local drafts; Monday reserved" },
  { id: "calendar", label: "Calendar", hint: "Reserved — not yet available" },
  { id: "company-tasks", label: "Company Tasks", hint: "Monday view not yet available" },
  { id: "finance", label: "Finance", hint: "FinanceOS control room (read-only)" },
  { id: "ask-e4l", label: "Ask E4L", hint: "Vault-grounded chat + memory" },
  { id: "activity-automations", label: "Activity/Automations", hint: "Audit, cron, sessions, budget" },
  { id: "settings-diagnostics", label: "Settings/Diagnostics", hint: "Operator/debug tier" },
] as const;

export type PrimaryView = (typeof PRIMARY_NAV_ITEMS)[number]["id"];

export type LegacyView =
  | "dashboard" | "chat" | "inbox" | "coding-agent" | "interactive-cli"
  | "skills" | "cron" | "sessions" | "replay" | "usage" | "logs" | "audit"
  | "memory" | "settings" | "config" | "budget" | "alerts"
  | "auth-keys" | "identity" | "flows" | "nodes" | "system" | "diagnostics";

export type View = PrimaryView | LegacyView;
export const DEFAULT_VIEW: PrimaryView = "work-inbox";

export interface ResolvedView {
  view: PrimaryView;
  subTab: string | null;
}

export const LEGACY_VIEW_REDIRECT: Record<LegacyView, ResolvedView> = {
  dashboard: { view: "work-inbox", subTab: null },
  inbox: { view: "work-inbox", subTab: null },
  alerts: { view: "work-inbox", subTab: null },
  chat: { view: "ask-e4l", subTab: "chat" },
  memory: { view: "ask-e4l", subTab: "memory" },
  audit: { view: "activity-automations", subTab: "audit" },
  cron: { view: "activity-automations", subTab: "cron" },
  sessions: { view: "activity-automations", subTab: "sessions" },
  replay: { view: "activity-automations", subTab: "sessions" },
  usage: { view: "activity-automations", subTab: "usage" },
  logs: { view: "activity-automations", subTab: "logs" },
  budget: { view: "activity-automations", subTab: "budget" },
  settings: { view: "settings-diagnostics", subTab: "settings" },
  config: { view: "settings-diagnostics", subTab: "config" },
  identity: { view: "settings-diagnostics", subTab: "identity" },
  "auth-keys": { view: "settings-diagnostics", subTab: "auth-keys" },
  skills: { view: "settings-diagnostics", subTab: "skills" },
  system: { view: "settings-diagnostics", subTab: "system" },
  diagnostics: { view: "settings-diagnostics", subTab: "diagnostics" },
  nodes: { view: "settings-diagnostics", subTab: "nodes" },
  flows: { view: "settings-diagnostics", subTab: "flows" },
  "coding-agent": { view: "settings-diagnostics", subTab: "coding-agent" },
  "interactive-cli": { view: "settings-diagnostics", subTab: "interactive-cli" },
};

const PRIMARY_IDS = new Set<string>(PRIMARY_NAV_ITEMS.map((item) => item.id));

export function resolveView(view: View): ResolvedView {
  if (PRIMARY_IDS.has(view)) return { view: view as PrimaryView, subTab: null };
  return LEGACY_VIEW_REDIRECT[view as LegacyView] ?? { view: DEFAULT_VIEW, subTab: null };
}

export const WORK_INBOX_GROUPS = [
  { id: "needs_me", label: "Needs Me" },
  { id: "waiting", label: "Waiting" },
  { id: "approvals", label: "Approvals" },
  { id: "due_soon", label: "Due Soon" },
  { id: "fyi", label: "FYI/Summarized" },
  { id: "resolved", label: "Resolved" },
] as const;

export type WorkInboxGroupId = (typeof WORK_INBOX_GROUPS)[number]["id"];

export function isFinanceStale(payload: { connected: boolean; stale: boolean }): boolean {
  return payload.stale || !payload.connected;
}
