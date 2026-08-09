import React from "react";
import logoSrc from "../../../New Logos/CATO-E4Life-Structure-Transparent.png";

// The 9-item nav (master architecture §10). Legacy ids are kept in the type
// so App.tsx can still hold them as transient state and redirect them into
// the nav item that absorbed them (CHUNK_6_WORK_INBOX) — they are no longer
// reachable from the sidebar itself.
export type View =
  | "work-inbox" | "waiting-followups" | "approvals" | "calendar" | "company-tasks"
  | "finance" | "ask-e4l" | "activity-automations" | "settings-diagnostics"
  // Legacy ids — absorbed, redirected in App.tsx, not rendered in PRIMARY_NAV.
  | "dashboard" | "chat" | "inbox" | "coding-agent" | "interactive-cli"
  | "skills" | "cron" | "sessions" | "usage" | "logs" | "audit"
  | "memory" | "settings" | "config" | "budget" | "alerts"
  | "auth-keys" | "identity" | "flows" | "nodes" | "system" | "diagnostics";

interface SidebarProps {
  activeView: View;
  onNavigate: (view: View) => void;
  daemonStatus: "starting" | "ready" | "stopped" | "error";
}

// Exactly the master spec's §10 9-item nav, in table order.
const PRIMARY_NAV: Array<{ id: View; label: string; hint: string; icon: React.ReactNode }> = [
  { id: "work-inbox", label: "Work Inbox", hint: "What needs your attention", icon: <path d="M4 5h16v14H4V5Zm0 9h5l2 2h2l2-2h5" /> },
  { id: "waiting-followups", label: "Waiting / Follow-ups", hint: "Timers, owners, overdue first", icon: <path d="M12 8v4l3 3m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /> },
  { id: "approvals", label: "Approvals", hint: "Drafts & Monday updates", icon: <path d="m5 13 4 4L19 7" /> },
  { id: "calendar", label: "Calendar", hint: "Today & next meetings", icon: <path d="M7 3v4M17 3v4M4 9h16M5 6h14a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1Z" /> },
  { id: "company-tasks", label: "Company Tasks", hint: "Monday board (read-only)", icon: <path d="M9 5h11M9 12h11M9 19h11M4 5h.01M4 12h.01M4 19h.01" /> },
  { id: "finance", label: "Finance", hint: "FinanceOS control room (read-only)", icon: <path d="M4 19h16M6 19V9m4 10V5m4 14v-7m4 7V3" /> },
  { id: "ask-e4l", label: "Ask E4L", hint: "Vault-grounded chat + memory", icon: <path d="M5 5h14v10H9l-4 4V5Zm3 4h8M8 12h5" /> },
  { id: "activity-automations", label: "Activity / Automations", hint: "Audit, cron, sessions, budget", icon: <path d="M12 3 5 6v5c0 4.6 2.9 8 7 10 4.1-2 7-5.4 7-10V6l-7-3Zm-3 9 2 2 4-5" /> },
  { id: "settings-diagnostics", label: "Settings / Diagnostics", hint: "Operator/debug tier", icon: <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm0-12v2m0 13v2m8.5-8.5h-2m-13 0h-2m14.5-6-1.4 1.4M7.4 16.6 6 18m12 0-1.4-1.4M7.4 7.4 6 6" /> },
];

function NavIcon({ children }: { children: React.ReactNode }) {
  return <svg className="sidebar-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeView, onNavigate, daemonStatus }) => {
  const statusLabel = daemonStatus === "ready" ? "Systems online" : daemonStatus === "starting" ? "Connecting" : daemonStatus === "error" ? "Needs attention" : "Offline";

  return (
    <aside className="sidebar">
      <button className="sidebar-brand" onClick={() => onNavigate("work-inbox")} aria-label="Cato Work Inbox">
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
        <div className="sidebar-status"><span className={`status-dot status-${daemonStatus}`} /><span><strong>{statusLabel}</strong><small>Local, supervised agent</small></span></div>
      </div>
    </aside>
  );
};

export default Sidebar;
