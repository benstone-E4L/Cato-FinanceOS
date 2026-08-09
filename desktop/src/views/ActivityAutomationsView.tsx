/**
 * ActivityAutomationsView — the master spec's §10 "Activity / Automations"
 * nav item. Per §10: "Audit chain, cron + Trigger.dev run health, session
 * replay. Absorbs AuditLog, Cron, Sessions, Replay, Logs, Usage, Budget."
 *
 * Each absorbed view is unchanged — this is a tab container, not a rebuild.
 * Session replay (ReplayView) is reachable transitively: SessionsView
 * already opens it in-place when a session's "replay" action is clicked
 * (see SessionsView.tsx), so it needs no separate tab here.
 */
import React from "react";
import { TabHub, type TabHubTab } from "../components/TabHub";
import { AuditLogView } from "./AuditLogView";
import { CronView } from "./CronView";
import { SessionsView } from "./SessionsView";
import { UsageView } from "./UsageView";
import { LogsView } from "./LogsView";
import { BudgetView } from "./BudgetView";

interface ActivityAutomationsViewProps {
  httpPort: number;
  initialTabId?: string;
}

export const ActivityAutomationsView: React.FC<ActivityAutomationsViewProps> = ({ httpPort, initialTabId }) => {
  const tabs: TabHubTab[] = [
    { id: "audit", label: "Audit chain", render: () => <AuditLogView httpPort={httpPort} /> },
    { id: "cron", label: "Cron", render: () => <CronView httpPort={httpPort} /> },
    { id: "sessions", label: "Sessions & replay", render: () => <SessionsView httpPort={httpPort} /> },
    { id: "usage", label: "Usage", render: () => <UsageView httpPort={httpPort} /> },
    { id: "logs", label: "Logs", render: () => <LogsView httpPort={httpPort} /> },
    { id: "budget", label: "Budget", render: () => <BudgetView httpPort={httpPort} /> },
  ];
  return (
    <TabHub
      tabs={tabs}
      initialTabId={initialTabId}
      title="Activity / Automations"
      subtitle="Audit chain, cron + run health, session replay, logs, usage, budget"
    />
  );
};

export default ActivityAutomationsView;
