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
 * approvals happen and links to the separate loopback FinanceOS authority.
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
  const [financeApprovalsUrl, setFinanceApprovalsUrl] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [inboxResult, financeResult] = await Promise.allSettled([
        fetch(`${base}/api/inbox`),
        fetch(`${base}/api/finance-os/control-room`, { signal: AbortSignal.timeout(6000) }),
      ]);
      try {
        if (inboxResult.status === "rejected") throw inboxResult.reason;
        const inboxResponse = inboxResult.value;
        if (!inboxResponse.ok) throw new Error(`Inbox HTTP ${inboxResponse.status}`);
        const body = await inboxResponse.json();
        setDrafts(Array.isArray(body?.email_drafts) ? body.email_drafts : []);
        setError(null);
      } catch (e) {
        setError(String(e));
      }
      try {
        if (financeResult.status === "rejected") throw financeResult.reason;
        if (!financeResult.value.ok) {
          throw new Error(`Finance HTTP ${financeResult.value.status}`);
        }
        const financeBody = await financeResult.value.json() as { approval_url?: unknown };
        setFinanceApprovalsUrl(
          typeof financeBody.approval_url === "string" ? financeBody.approval_url : null,
        );
      } catch {
        setFinanceApprovalsUrl(null);
      }
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
        <strong>Finance approvals are not handled by this surface</strong>
        <p>
          This installed Approvals view issues GET-only control-room requests and has no finance
          mutation wired into it. Finance approvals happen in FinanceOS/Airtable directly.
        </p>
        {financeApprovalsUrl ? (
          <a
            className="btn-secondary-sm external-approval-link"
            href={financeApprovalsUrl}
            target="_blank"
            rel="noreferrer"
            aria-label="Open FinanceOS approvals in a separate application"
          >
            Open FinanceOS approvals ↗
          </a>
        ) : (
          <span className="empty-state">FinanceOS approval authority is unavailable.</span>
        )}
      </div>
    </div>
  );
};

export default ApprovalsView;
