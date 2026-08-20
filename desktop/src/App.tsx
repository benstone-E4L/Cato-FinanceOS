/**
 * App.tsx — Root component for Cato Desktop.
 *
 * Sidebar layout: left nav + main content area.
 * Polls the daemon health endpoint until ready.
 *
 * CHUNK_6_WORK_INBOX: Work Inbox is the default landing page and the
 * sidebar exposes exactly the master spec's §10 9-item nav. The legacy
 * 23-view surface still exists (nothing was deleted) but is only reachable
 * as a tab inside the nav item that absorbed it — see LEGACY_VIEW_REDIRECT
 * below, which maps every old `View` id to {newView, subTab} so any code
 * path (e.g. `cato-navigate` events fired by an older component) that still
 * asks for a legacy id lands on the correct new surface instead of 404ing.
 */

import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Sidebar, type View } from "./components/Sidebar";
import { CommandTopbar } from "./components/CommandTopbar";
import { InboxView } from "./views/InboxView";
import type { ChatConnectionStatus } from "./hooks/useChatStream";
import { WorkInboxView } from "./views/WorkInboxView";
import { ApprovalsView } from "./views/ApprovalsView";
import { WaitingFollowupsView } from "./views/WaitingFollowupsView";
import { CalendarView } from "./views/CalendarView";
import { CompanyTasksView } from "./views/CompanyTasksView";
import { FinanceView } from "./views/FinanceView";
import { AskE4LView } from "./views/AskE4LView";
import { ActivityAutomationsView } from "./views/ActivityAutomationsView";
import { SettingsDiagnosticsView } from "./views/SettingsDiagnosticsView";
import { AlertsView } from "./views/AlertsView";
import { DEFAULT_VIEW, resolveView } from "./workInboxContract";
import "./styles/app.css";
import "./styles/finance-shell.css";

type DaemonStatus = "starting" | "ready" | "stopped" | "error";

interface DaemonInfo {
  httpPort: number;
  wsPort: number;
  status: DaemonStatus;
  daemonToken?: string;
}

const DAEMON_DEFAULT_PORT = 8080;

function useDaemonInfo(): DaemonInfo {
  const [info, setInfo] = useState<DaemonInfo>({
    httpPort: DAEMON_DEFAULT_PORT,
    wsPort: DAEMON_DEFAULT_PORT,
    status: "starting",
  });

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;
    const maxAttempts = 120;

    const poll = async () => {
      while (!cancelled && attempts < maxAttempts) {
        try {
          const status = await invoke<{
            running: boolean;
            http_port: number;
            ws_port: number;
            daemon_token?: string | null;
          }>("get_daemon_status");
          if (status.running) {
            installCatoFetchAuth(status.daemon_token ?? undefined);
            setInfo({
              httpPort: status.http_port,
              wsPort: status.ws_port,
              status: "ready",
              daemonToken: status.daemon_token ?? undefined,
            });
            return;
          }
        } catch {
          // Daemon not yet ready
        }
        attempts++;
        await new Promise((r) => setTimeout(r, 1000));
      }
      if (!cancelled) {
        setInfo((prev) => ({ ...prev, status: "error" }));
      }
    };
    poll();
    return () => { cancelled = true; };
  }, []);

  return info;
}

function installCatoFetchAuth(token?: string): void {
  if (!token) return;
  const w = window as Window & {
    __CATO_DAEMON_TOKEN__?: string;
    __CATO_FETCH_PATCHED__?: boolean;
    __CATO_ORIGINAL_FETCH__?: typeof window.fetch;
  };
  w.__CATO_DAEMON_TOKEN__ = token;
  if (w.__CATO_FETCH_PATCHED__) return;

  const originalFetch = window.fetch.bind(window);
  w.__CATO_ORIGINAL_FETCH__ = originalFetch;
  w.__CATO_FETCH_PATCHED__ = true;

  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const rawUrl = input instanceof Request ? input.url : String(input);
    const isCatoLocal =
      rawUrl.startsWith("http://127.0.0.1:") ||
      rawUrl.startsWith("http://localhost:");

    if (!isCatoLocal || !w.__CATO_DAEMON_TOKEN__) {
      return originalFetch(input, init);
    }

    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    );
    if (!headers.has("X-Cato-Token")) {
      headers.set("X-Cato-Token", w.__CATO_DAEMON_TOKEN__);
    }

    if (input instanceof Request) {
      return originalFetch(new Request(input, { ...init, headers }));
    }
    return originalFetch(input, { ...init, headers });
  };
}

function renderView(
  resolvedView: View,
  subTab: string | null,
  daemon: DaemonInfo,
  onNavigate: (v: View) => void,
  onChatConnectionStatusChange: (status: ChatConnectionStatus) => void,
): React.ReactNode {
  const { httpPort, wsPort } = daemon;
  switch (resolvedView) {
    case "work-inbox":
      return <WorkInboxView httpPort={httpPort} onNavigate={onNavigate} />;
    case "waiting-followups":
      return <WaitingFollowupsView />;
    case "approvals":
      return <ApprovalsView httpPort={httpPort} />;
    case "calendar":
      return <CalendarView />;
    case "company-tasks":
      return <CompanyTasksView />;
    case "finance":
      return <FinanceView httpPort={httpPort} />;
    case "ask-e4l":
      return (
        <AskE4LView
          wsBase={`127.0.0.1:${wsPort}`}
          httpPort={httpPort}
          daemonToken={daemon.daemonToken}
          onConnectionStatusChange={onChatConnectionStatusChange}
          initialTab={subTab === "memory" ? "memory" : "chat"}
        />
      );
    case "activity-automations":
      return <ActivityAutomationsView httpPort={httpPort} initialTabId={subTab ?? undefined} />;
    case "settings-diagnostics":
      return (
        <SettingsDiagnosticsView
          httpPort={httpPort}
          wsPort={wsPort}
          daemonToken={daemon.daemonToken}
          initialTabId={subTab ?? undefined}
        />
      );
    // Legacy ids that resolveView() didn't remap (defensive fallback —
    // should not normally be reached since LEGACY_VIEW_REDIRECT covers all
    // of them, but never 404/dead-end silently if one is missed).
    case "inbox":
      return <InboxView httpPort={httpPort} />;
    case "alerts":
      return <AlertsView httpPort={httpPort} />;
    default:
      return <WorkInboxView httpPort={httpPort} onNavigate={onNavigate} />;
  }
}

function App() {
  const [view, setView] = useState<View>(DEFAULT_VIEW);
  const daemon = useDaemonInfo();
  const [chatStatus, setChatStatus] = useState<ChatConnectionStatus | "idle">("idle");

  // Allow child views to trigger navigation (e.g. quick-launch buttons).
  // Legacy event payloads (old view ids) are resolved the same way direct
  // sidebar navigation is, so nothing that used to work silently breaks.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<string>).detail as View;
      if (detail) setView(detail);
    };
    window.addEventListener("cato-navigate", handler);
    return () => window.removeEventListener("cato-navigate", handler);
  }, []);

  // Derive a sidebar daemon status that also reflects chat WebSocket health
  // when the daemon is otherwise reported as ready.
  let sidebarStatus: DaemonStatus = daemon.status;
  if (daemon.status === "ready") {
    if (chatStatus === "connecting" || chatStatus === "reconnecting") {
      sidebarStatus = "starting";
    } else if (chatStatus === "disconnected") {
      sidebarStatus = "error";
    }
  }

  const { view: resolvedView, subTab } = resolveView(view);

  return (
    <div className="app-root app-root-sidebar">
      <Sidebar
        activeView={resolvedView}
        onNavigate={setView}
        daemonStatus={sidebarStatus}
      />

      <div className="app-content">
        {daemon.status === "starting" && (
          <div className="app-loading">
            <div className="app-loading-spinner" />
            <p>Starting Cato daemon...</p>
          </div>
        )}

        {daemon.status === "ready" && (
          <>
            <CommandTopbar
              activeView={resolvedView}
              httpPort={daemon.httpPort}
              onNavigate={setView}
            />
            <main className="app-main">
              <ErrorBoundary>
                {renderView(resolvedView, subTab, daemon, setView, setChatStatus)}
              </ErrorBoundary>
            </main>
          </>
        )}

        {daemon.status === "error" && (
          <div className="app-error">
            <p>Failed to connect to Cato daemon.</p>
            <button className="retry-btn" onClick={() => window.location.reload()}>
              Retry
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
