/**
 * TabHub — generic tabbed container used to absorb the legacy operator/debug
 * views into the master architecture's 9-item nav (CHUNK_6_WORK_INBOX).
 *
 * Each absorbed nav item (Ask E4L, Activity/Automations, Settings/
 * Diagnostics) renders one of these instead of being rebuilt from scratch —
 * the underlying view components are unchanged, only their entry point
 * changes from a dedicated sidebar slot to a tab inside the hub that
 * absorbed them.
 */
import React, { useState } from "react";

export interface TabHubTab {
  id: string;
  label: string;
  render: () => React.ReactNode;
}

interface TabHubProps {
  tabs: TabHubTab[];
  initialTabId?: string;
  title: string;
  subtitle?: string;
}

export const TabHub: React.FC<TabHubProps> = ({ tabs, initialTabId, title, subtitle }) => {
  const [activeId, setActiveId] = useState<string>(
    initialTabId && tabs.some((t) => t.id === initialTabId) ? initialTabId : (tabs[0]?.id ?? ""),
  );

  // Legacy-route redirects (App.tsx passes a fresh initialTabId when the
  // user's View state points at an absorbed legacy id) must win even when
  // this hub instance is already mounted.
  React.useEffect(() => {
    if (initialTabId && tabs.some((t) => t.id === initialTabId)) {
      setActiveId(initialTabId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTabId]);

  const active = tabs.find((t) => t.id === activeId) ?? tabs[0];

  return (
    <div className="page-view tab-hub">
      <div className="page-header">
        <div>
          <h1 className="page-title">{title}</h1>
          {subtitle && <p className="tab-hub-subtitle">{subtitle}</p>}
        </div>
      </div>
      <div className="tab-hub-strip" role="tablist" aria-label={title}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={tab.id === active?.id}
            className={`tab-hub-tab${tab.id === active?.id ? " active" : ""}`}
            onClick={() => setActiveId(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="tab-hub-panel" role="tabpanel" data-active-tab={active?.id ?? ""}>
        {active?.render()}
      </div>
    </div>
  );
};

export default TabHub;
