/**
 * ApprovalsView — one of the master spec's §10 9-item nav slots.
 *
 * Per §10: "Non-finance approvals (drafts, Monday updates); finance
 * approvals deep-link to Airtable/FinanceOS — never duplicated." This
 * chunk's real, working approval surface is the existing Gmail draft-reply
 * queue (`/api/inbox`'s `email_drafts`, already backed by real
 * approve/dismiss endpoints) — genuinely local, non-finance approvals.
 * Monday-update approvals don't exist yet (Monday API integration is a
 * separate, out-of-scope workstream) so that half is an honest "not yet
 * available" note, not fabricated data.
 *
 * Finance approvals are never rendered or actioned here — Cato has no write
 * path to FinanceOS by construction (guardrails.md: "FinanceOS is
 * read-only from Cato, always"), so this view only explains where finance
 * approvals happen instead of inventing a deep-link URL Cato doesn't have.
 */
import React, { useCallback, useEffect, useState } from "react";

interface ApprovalsViewProps {
  httpPort: number;
}

interface EmailDraft {
  id: number;
  subject?: string | null;
  from_email?: string | null;
  snippet?: string | null;
  draft_reply?: string | null;
  status: string;
  created_at?: string | null;
}

type EmailAction = "approve" | "dismiss";

function preview(text?: string | null, max = 220): string {
  const value = (text ?? "").trim();
  if (!value) return "—";
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

export const ApprovalsView: React.FC<ApprovalsViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/inbox`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setDrafts(Array.isArray(body?.email_drafts) ? body.email_drafts : []);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => { refresh(); }, [refresh]);

  const act = async (id: number, action: EmailAction) => {
    setBusyId(id);
    try {
      const r = await fetch(`${base}/api/inbox/email/${id}/${action}`, { method: "POST" });
      if (!r.ok && r.status !== 409) throw new Error(`HTTP ${r.status}`);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  return (
    <div className="page-view approvals-view">
      <div className="page-header">
        <h1 className="page-title">Approvals</h1>
        <div className="page-controls">
          <button className="btn-secondary" onClick={refresh}>Refresh</button>
        </div>
      </div>

      {error && <div className="page-error">{error}</div>}

      <div className="section-block">
        <div className="section-title">Draft replies awaiting your approval</div>
        {drafts.length === 0 ? (
          <div className="empty-state">Nothing waiting for approval</div>
        ) : (
          <div className="inbox-email-list">
            {drafts.map((d) => (
              <article className="inbox-email-card" key={d.id}>
                <div className="inbox-email-header">
                  <div className="inbox-email-title">
                    <span>{d.subject || "(no subject)"}</span>
                    <span className="action-badge">{d.status}</span>
                  </div>
                  <div className="inbox-email-meta"><span>{d.from_email || "Unknown sender"}</span></div>
                </div>
                <div className="inbox-email-snippet">{preview(d.snippet, 200)}</div>
                <div className="inbox-draft-reply">{preview(d.draft_reply, 600)}</div>
                <div className="inbox-email-actions">
                  <button className="btn-primary btn-sm" onClick={() => act(d.id, "approve")} disabled={busyId === d.id}>
                    {busyId === d.id ? "Working..." : "Approve"}
                  </button>
                  <button className="btn-danger-sm" onClick={() => act(d.id, "dismiss")} disabled={busyId === d.id}>
                    Dismiss
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <div className="section-block">
        <div className="section-title">Company / Monday updates awaiting approval</div>
        <div className="empty-state">
          Not yet available — the Monday-updates approval queue depends on the Monday API
          integration, which doesn't exist in this repo yet.
        </div>
      </div>

      <div className="coming-soon-panel">
        <strong>Finance approvals are never handled here</strong>
        <p>
          Cato never approves or writes to FinanceOS — that boundary is enforced at the client
          level, not just in this view. Finance approvals happen in FinanceOS/Airtable directly.
        </p>
      </div>
    </div>
  );
};

export default ApprovalsView;
