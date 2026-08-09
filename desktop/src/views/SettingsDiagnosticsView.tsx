/**
 * SettingsDiagnosticsView — the master spec's §10 "Settings / Diagnostics"
 * nav item (operator/debug tier). Per §10: "Config, identity, keys, skills,
 * system state. Absorbs Settings, Config, Identity, AuthKeys, Skills,
 * System, Diagnostics, Nodes, Flows, CodingAgent, InteractiveCLI." This is
 * the only place the legacy operator/debug surface survives post-chunk
 * (guardrails.md's do-not-build list) — every absorbed view is unchanged,
 * this is purely a tab container.
 */
import React from "react";
import { TabHub, type TabHubTab } from "../components/TabHub";
import { SettingsView } from "./SettingsView";
import { ConfigView } from "./ConfigView";
import { IdentityView } from "./IdentityView";
import { AuthKeysView } from "./AuthKeysView";
import { SkillsView } from "./SkillsView";
import { SystemView } from "./SystemView";
import { DiagnosticsView } from "./DiagnosticsView";
import { NodesView } from "./NodesView";
import { FlowsView } from "./FlowsView";
import { CodingAgentView } from "./CodingAgentView";
import { InteractiveCLIView } from "./InteractiveCLIView";

interface SettingsDiagnosticsViewProps {
  httpPort: number;
  wsPort: number;
  daemonToken?: string;
  initialTabId?: string;
}

export const SettingsDiagnosticsView: React.FC<SettingsDiagnosticsViewProps> = ({
  httpPort, wsPort, daemonToken, initialTabId,
}) => {
  const tabs: TabHubTab[] = [
    { id: "settings", label: "Settings", render: () => <SettingsView httpPort={httpPort} /> },
    { id: "config", label: "Config", render: () => <ConfigView httpPort={httpPort} /> },
    { id: "identity", label: "Identity", render: () => <IdentityView httpPort={httpPort} /> },
    { id: "auth-keys", label: "Auth keys", render: () => <AuthKeysView httpPort={httpPort} /> },
    { id: "skills", label: "Skills", render: () => <SkillsView httpPort={httpPort} /> },
    { id: "system", label: "System", render: () => <SystemView httpPort={httpPort} /> },
    { id: "diagnostics", label: "Diagnostics", render: () => <DiagnosticsView httpPort={httpPort} wsPort={wsPort} daemonToken={daemonToken} /> },
    { id: "nodes", label: "Nodes", render: () => <NodesView httpPort={httpPort} /> },
    { id: "flows", label: "Flows", render: () => <FlowsView httpPort={httpPort} /> },
    {
      id: "coding-agent",
      label: "Coding agent",
      render: () => (
        <CodingAgentView
          wsBase={`127.0.0.1:${httpPort}`}
          apiBase={`http://127.0.0.1:${httpPort}`}
          daemonToken={daemonToken}
        />
      ),
    },
    { id: "interactive-cli", label: "Interactive CLI", render: () => <InteractiveCLIView httpPort={httpPort} /> },
  ];
  return (
    <TabHub
      tabs={tabs}
      initialTabId={initialTabId}
      title="Settings / Diagnostics"
      subtitle="Operator/debug tier — config, identity, keys, skills, system state"
    />
  );
};

export default SettingsDiagnosticsView;
