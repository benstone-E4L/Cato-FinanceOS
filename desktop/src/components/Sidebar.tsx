import React from "react";
import logoSrc from "../../../New Logos/CATO-E4Life-Structure-Transparent.png";

export type View =
  | "dashboard" | "chat" | "inbox" | "coding-agent" | "interactive-cli"
  | "skills" | "cron" | "sessions" | "usage" | "logs" | "audit"
  | "memory" | "settings" | "config" | "budget" | "alerts"
  | "auth-keys" | "identity" | "flows" | "nodes" | "system" | "diagnostics";

interface SidebarProps {
  activeView: View;
  onNavigate: (view: View) => void;
  daemonStatus: "starting" | "ready" | "stopped" | "error";
}

const PRIMARY_NAV: Array<{ id: View; label: string; hint: string; icon: React.ReactNode }> = [
  { id: "dashboard", label: "Control room", hint: "FinanceOS overview", icon: <path d="M4 13h6V4H4v9Zm10 7h6V11h-6v9ZM4 20h6v-3H4v3Zm10-13h6V4h-6v3Z" /> },
  { id: "chat", label: "Ask Cato", hint: "Direct the agent", icon: <path d="M5 5h14v10H9l-4 4V5Zm3 4h8M8 12h5" /> },
  { id: "inbox", label: "Inbox", hint: "Drafts & approvals", icon: <path d="M4 5h16v14H4V5Zm0 9h5l2 2h2l2-2h5" /> },
  { id: "flows", label: "Automations", hint: "Recurring workflows", icon: <path d="M7 7h10M7 17h10M5 7a2 2 0 1 0 0 .01M19 17a2 2 0 1 0 0 .01M12 7v5a5 5 0 0 0 5 5" /> },
  { id: "audit", label: "Activity", hint: "Proof & history", icon: <path d="M12 3 5 6v5c0 4.6 2.9 8 7 10 4.1-2 7-5.4 7-10V6l-7-3Zm-3 9 2 2 4-5" /> },
];

function NavIcon({ children }: { children: React.ReactNode }) {
  return <svg className="sidebar-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeView, onNavigate, daemonStatus }) => {
  const statusLabel = daemonStatus === "ready" ? "Systems online" : daemonStatus === "starting" ? "Connecting" : daemonStatus === "error" ? "Needs attention" : "Offline";

  return (
    <aside className="sidebar">
      <button className="sidebar-brand" onClick={() => onNavigate("dashboard")} aria-label="Cato control room">
        <img src={logoSrc} alt="" className="sidebar-logo" />
        <span className="sidebar-brand-copy"><strong>Cato</strong><small>E4Life FinanceOS</small></span>
      </button>

      <nav className="sidebar-nav" aria-label="Primary navigation">
        <span className="sidebar-eyebrow">Workspace</span>
        <ul className="sidebar-group-list">
          {PRIMARY_NAV.map((item) => (
            <li key={item.id}>
              <button className={`sidebar-nav-item${activeView === item.id ? " active" : ""}`} onClick={() => onNavigate(item.id)} aria-current={activeView === item.id ? "page" : undefined}>
                <NavIcon>{item.icon}</NavIcon>
                <span className="sidebar-nav-copy"><span>{item.label}</span><small>{item.hint}</small></span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="sidebar-footer">
        <button className={`sidebar-settings${activeView === "settings" ? " active" : ""}`} onClick={() => onNavigate("settings")}>
          <NavIcon><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm0-12v2m0 13v2m8.5-8.5h-2m-13 0h-2m14.5-6-1.4 1.4M7.4 16.6 6 18m12 0-1.4-1.4M7.4 7.4 6 6" /></NavIcon>
          <span>Settings</span>
        </button>
        <div className="sidebar-status"><span className={`status-dot status-${daemonStatus}`} /><span><strong>{statusLabel}</strong><small>Local, supervised agent</small></span></div>
      </div>
    </aside>
  );
};

export default Sidebar;
