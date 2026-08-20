import React, { useMemo, useState } from "react";
import { ActivityIndicator } from "./ActivityIndicator";
import { PRIMARY_NAV_ITEMS, type PrimaryView } from "../workInboxContract";

interface CommandTopbarProps {
  activeView: PrimaryView;
  httpPort: number;
  onNavigate: (view: PrimaryView) => void;
}

export const CommandTopbar: React.FC<CommandTopbarProps> = ({
  activeView,
  httpPort,
  onNavigate,
}) => {
  const [query, setQuery] = useState("");
  const active = useMemo(
    () => PRIMARY_NAV_ITEMS.find((item) => item.id === activeView),
    [activeView],
  );

  const navigateFromQuery = () => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return;
    const destination = PRIMARY_NAV_ITEMS.find((item) =>
      `${item.label} ${item.hint}`.toLowerCase().includes(normalized),
    );
    if (destination) {
      onNavigate(destination.id);
      setQuery("");
    }
  };

  return (
    <header className="command-topbar">
      <div className="command-breadcrumb" aria-live="polite">
        <span>Cato</span>
        <span className="command-chevron" aria-hidden="true">›</span>
        <strong>{active?.label ?? "Work Inbox"}</strong>
        <span className="command-view-chip">{active?.hint ?? "Operator workspace"}</span>
      </div>

      <div className="command-actions">
        <label className="command-search">
          <span className="sr-only">Find a Cato surface</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") navigateFromQuery(); }}
            placeholder="Find a surface…"
          />
          <kbd>Enter</kbd>
        </label>
        <ActivityIndicator httpPort={httpPort} />
        <button className="command-new-task" onClick={() => onNavigate("ask-e4l")}>New task</button>
      </div>
    </header>
  );
};

export default CommandTopbar;
