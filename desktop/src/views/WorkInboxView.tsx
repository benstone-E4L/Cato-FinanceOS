/**
 * WorkInboxView — Cato's default landing page (CHUNK_6_WORK_INBOX, master
 * spec §10: "the Work Inbox IS the product").
 *
 * It renders the six fixed card-state groups in order from real local data:
 * pending Gmail draft approvals and the read-only FinanceOS control-room
 * contract. Groups without an authoritative source remain explicitly empty.
 */
import React, { useCallback, useEffect, useState } from "react";
import type { View } from "../components/Sidebar";
import { isFinanceStale, WORK_INBOX_GROUPS, type WorkInboxGroupId } from "../workInboxContract";

interface WorkInboxViewProps {
  httpPort: number;
  onNavigate: (view: View) => void;
}

interface EmailDraft {
  id: number;
  subject?: string | null;
  from_email?: string | null;
  snippet?: string | null;
  created_at?: string | null;
}

interface ControlRoomPayload {
  connected: boolean;
  stale: boolean;
  data: { control_room?: Record<string, unknown>; integrations_health?: Record<string, unknown> } | null;
  cached_at: string | null;
  approval_url: string | null;
}

function preview(text?: string | null, max = 140): string {
  const value = (text ?? "").trim();
  if (!value) return "—";
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

const GROUP_EMPTY_HINT: Record<WorkInboxGroupId, string> = {
  needs_me: "No sourced items need direct action.",
  waiting: "No tracked follow-ups.",
  approvals: "Nothing waiting for your approval.",
  due_soon: "Nothing due soon.",
  fyi: "Nothing to summarize.",
  resolved: "Nothing resolved yet.",
};

export const WorkInboxView: React.FC<WorkInboxViewProps> = ({ httpPort, onNavigate }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [finance, setFinance] = useState<ControlRoomPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [financeError, setFinanceError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [inboxResult, financeResult] = await Promise.allSettled([
      fetch(`${base}/api/inbox`).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      }),
      fetch(`${base}/api/finance-os/control-room`, { signal: AbortSignal.timeout(6000) }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      }),
    ]);
    if (inboxResult.status === "fulfilled") {
      setDrafts(Array.isArray(inboxResult.value?.email_drafts) ? inboxResult.value.email_drafts : []);
      setError(null);
    } else {
      setError(String(inboxResult.reason));
    }
    if (financeResult.status === "fulfilled") {
      setFinance(financeResult.value as ControlRoomPayload);
      setFinanceError(null);
    } else {
      // Preserve the last known card. A Cato-route failure is materially
      // different from FinanceOS's explicit stale payload and must be visible.
      setFinanceError(String(financeResult.reason));
    }
    setLoading(false);
  }, [base]);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(refresh, 20000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refresh]);

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  const groups: Record<WorkInboxGroupId, React.ReactNode[]> = {
    needs_me: [],
    waiting: [],
    approvals: drafts.map((d) => (
      <div className="work-inbox-card" key={`draft-${d.id}`}>
        <span className="work-inbox-card-edge edge-gold" aria-hidden="true" />
        <div className="work-inbox-card-body">
        <div className="work-inbox-card-header">
          <span className="work-inbox-card-title">{d.subject || "(no subject)"}</span>
          <span className="action-badge">Draft reply</span>
        </div>
        <div className="work-inbox-card-meta">{d.from_email || "Unknown sender"}</div>
        <div>{preview(d.snippet)}</div>
        </div>
        <button className="btn-secondary-sm" onClick={() => onNavigate("approvals" as View)}>Review in Approvals →</button>
      </div>
    )),
    due_soon: [],
    fyi: finance
      ? [
          <div className="work-inbox-card" key="finance-card">
            <span className={`work-inbox-card-edge ${isFinanceStale(finance) ? "edge-ember" : "edge-gold"}`} aria-hidden="true" />
            <div className="work-inbox-card-body">
            <div className="work-inbox-card-header">
              <span className="work-inbox-card-title">FinanceOS status</span>
              {!isFinanceStale(finance) ? <span className="action-badge">Live</span> : <span className="work-inbox-card-stale">Stale</span>}
            </div>
            {finance.data?.control_room ? (
              <div className="work-inbox-card-meta">
                Close status: {String(finance.data.control_room["close_status"] ?? "—")}
                {finance.stale && finance.cached_at ? ` · as of ${finance.cached_at}` : ""}
              </div>
            ) : (
              <div className="work-inbox-card-meta">FinanceOS is not connected yet.</div>
            )}
            </div>
            <button className="btn-secondary-sm" onClick={() => onNavigate("finance" as View)}>Open Finance →</button>
          </div>,
        ]
      : [],
    resolved: [],
  };

  return (
    <div className="page-view work-inbox-view">
      <div className="page-header">
        <div className="page-heading-copy">
          <span className="page-kicker">Operator attention queue</span>
          <h1 className="page-title">Work Inbox</h1>
          <p>Verified items from Cato's available local sources, grouped by decision state.</p>
        </div>
        <div className="page-controls">
          <button className="btn-secondary" onClick={refresh}>Refresh</button>
        </div>
      </div>

      {error && <div className="page-error">{error}</div>}
      {financeError && (
        <div className="page-error" role="status">
          Cato Finance route unavailable; preserving the last-known FinanceOS card: {financeError}
        </div>
      )}

      {WORK_INBOX_GROUPS.map((group) => (
        <section className="work-inbox-group" key={group.id} data-work-inbox-group={group.id}>
          <div className="work-inbox-group-header">
            <span className="work-inbox-group-title">{group.label}</span>
            <span className="work-inbox-group-count">{groups[group.id].length}</span>
          </div>
          {groups[group.id].length === 0 ? (
            <div className="work-inbox-empty-group">{GROUP_EMPTY_HINT[group.id]}</div>
          ) : (
            groups[group.id]
          )}
        </section>
      ))}
    </div>
  );
};

export default WorkInboxView;
