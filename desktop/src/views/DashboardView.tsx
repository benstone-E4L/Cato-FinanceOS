import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator } from "../components/ActivityIndicator";
import type { View } from "../components/Sidebar";

interface DashboardViewProps { httpPort: number; onNavigate: (view: View) => void; }
interface CatoHealth { status: string; version: string; uptime: number; }
interface BudgetData { monthly_spend: number; monthly_cap: number; monthly_pct_remaining: number; monthly_calls: number; }
interface SessionEntry { session_id: string; queue_depth: number; running: boolean; }
interface FinanceHealth {
  connected: boolean; status: "ok" | "degraded" | "unavailable"; db?: boolean; module_layer_wired?: boolean; queue_depth?: number;
  oldest_hold_age_hours: number | null; last_xero_sync_at: string | null;
  production_write_enabled?: boolean; version?: string;
}

function formatUptime(seconds = 0) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function StatusMark({ tone = "neutral" }: { tone?: "good" | "warn" | "danger" | "neutral" }) {
  return <span className={`finance-status-mark finance-status-${tone}`} aria-hidden="true" />;
}

export const DashboardView: React.FC<DashboardViewProps> = ({ httpPort, onNavigate }) => {
  const catoBase = `http://127.0.0.1:${httpPort}`;
  const [health, setHealth] = useState<CatoHealth | null>(null);
  const [finance, setFinance] = useState<FinanceHealth | null>(null);
  const [budget, setBudget] = useState<BudgetData | null>(null);
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const [catoResult, financeResult, budgetResult, sessionsResult] = await Promise.allSettled([
      fetch(`${catoBase}/health`).then((r) => r.json()),
      fetch(`${catoBase}/api/finance-os/health`, { signal: AbortSignal.timeout(5000) }).then((r) => {
        if (!r.ok) throw new Error(`FinanceOS bridge returned ${r.status}`);
        return r.json();
      }),
      fetch(`${catoBase}/api/budget/summary`).then((r) => r.json()),
      fetch(`${catoBase}/api/sessions`).then((r) => r.json()),
    ]);
    const catoPayload = catoResult.status === "fulfilled" && catoResult.value && typeof catoResult.value === "object"
      ? catoResult.value as CatoHealth : null;
    setHealth(catoPayload);
    const financePayload = financeResult.status === "fulfilled" ? financeResult.value as FinanceHealth : null;
    setFinance(financePayload?.connected ? financePayload : null);
    const budgetPayload = budgetResult.status === "fulfilled" && budgetResult.value && typeof budgetResult.value === "object"
      ? budgetResult.value as BudgetData : null;
    setBudget(budgetPayload);
    setSessions(sessionsResult.status === "fulfilled" && Array.isArray(sessionsResult.value)
      ? sessionsResult.value as SessionEntry[] : []);
    setLoading(false);
  }, [catoBase]);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(refresh, 15000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refresh]);

  const running = sessions.filter((session) => session.running).length;
  const queueDepth = finance?.queue_depth;
  const financeTone = !finance ? "neutral" : finance.status === "ok" ? "good" : "warn";
  const spendPct = budget?.monthly_cap ? Math.min(100, (budget.monthly_spend / budget.monthly_cap) * 100) : 0;
  const startPrompt = (prompt: string) => {
    window.sessionStorage.setItem("cato.pendingPrompt", prompt);
    onNavigate("chat");
  };

  return (
    <div className="dash-view finance-command-center">
      <header className="finance-hero">
        <div>
          <p className="finance-kicker">{new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" }).format(new Date())} · Finance command center</p>
          <h1>Good morning, Ben.</h1>
          <p>One place to direct Cato, review exceptions, and keep the books supervised.</p>
        </div>
        <div className="finance-hero-actions">
          <ActivityIndicator httpPort={httpPort} />
          <button className="finance-icon-button" onClick={refresh} aria-label="Refresh control room" title="Refresh">↻</button>
        </div>
      </header>

      <section className="finance-command-card">
        <div className="finance-command-orb">C</div>
        <div className="finance-command-copy"><span>What needs attention?</span><small>Ask about cash, close, approvals, entities, or a specific transaction.</small></div>
        <button onClick={() => onNavigate("chat")}>Ask Cato <span>→</span></button>
      </section>

      <section className="finance-signal-grid" aria-label="System overview">
        <article className="finance-signal-card">
          <div className="finance-card-top"><span>FinanceOS</span><StatusMark tone={financeTone} /></div>
          <strong>{loading ? "Checking…" : finance ? (finance.status === "ok" ? "Operational" : "Degraded") : "Not connected"}</strong>
          <small>{finance ? `v${finance.version ?? "unknown"} · database ${finance.db ? "online" : "offline"}` : "FinanceOS health bridge unavailable"}</small>
        </article>
        <article className="finance-signal-card">
          <div className="finance-card-top"><span>Review queue</span><StatusMark tone={queueDepth === undefined ? "neutral" : queueDepth > 0 ? "warn" : "good"} /></div>
          <strong>{queueDepth ?? "—"}</strong>
          <small>{queueDepth === undefined ? "FinanceOS connection required" : queueDepth === 1 ? "item needs review" : "items need review"}</small>
        </article>
        <article className="finance-signal-card">
          <div className="finance-card-top"><span>Agent activity</span><StatusMark tone={health?.status === "ok" ? "good" : "danger"} /></div>
          <strong>{running ? `${running} working` : "Ready"}</strong>
          <small>{health ? `Cato v${health.version} · up ${formatUptime(health.uptime)}` : "Daemon unavailable"}</small>
        </article>
        <article className="finance-signal-card">
          <div className="finance-card-top"><span>Xero write gate</span><StatusMark tone={!finance ? "neutral" : finance.production_write_enabled ? "warn" : "good"} /></div>
          <strong>{!finance ? "Unknown" : finance.production_write_enabled ? "Enabled" : "Protected"}</strong>
          <small>{!finance ? "Connect FinanceOS to verify the gate" : finance.production_write_enabled ? "Production writes require supervision" : "Production writes are disabled"}</small>
        </article>
      </section>

      <section className="finance-main-grid">
        <article className="finance-panel finance-attention-panel">
          <div className="finance-panel-heading"><div><p>Priority</p><h2>Needs attention</h2></div><button onClick={() => onNavigate("inbox")}>Open inbox</button></div>
          {!finance ? (
            <div className="finance-empty-state"><span>◇</span><strong>FinanceOS is not connected</strong><p>Cato is ready. Start the FinanceOS API to surface live holds and exceptions here.</p></div>
          ) : queueDepth === 0 ? (
            <div className="finance-empty-state"><span>✓</span><strong>Nothing is blocked</strong><p>No open FinanceOS work items are waiting for review.</p></div>
          ) : (
            <div className="finance-attention-row"><div className="finance-attention-icon">!</div><div><strong>{queueDepth ?? 0} open FinanceOS work {queueDepth === 1 ? "item" : "items"}</strong><p>{finance.oldest_hold_age_hours === null ? "Investigate the queue before the next posting cycle." : `Oldest hold is ${finance.oldest_hold_age_hours} hours old.`}</p></div><button onClick={() => startPrompt("Inspect the current E4Life FinanceOS work queue. Summarize each open item, identify the oldest hold, and propose the safest next action. Do not execute any ledger or Xero write.")}>Ask Cato</button></div>
          )}
        </article>

        <article className="finance-panel finance-guardrail-panel">
          <div className="finance-panel-heading"><div><p>Guardrail</p><h2>Agent budget</h2></div><button onClick={() => onNavigate("budget")}>Details</button></div>
          <div className="finance-spend"><strong>${budget?.monthly_spend.toFixed(2) ?? "0.00"}</strong><span>of ${budget?.monthly_cap.toFixed(0) ?? "20"} this month</span></div>
          <div className="finance-progress"><span style={{ width: `${spendPct}%` }} /></div>
          <div className="finance-budget-meta"><span>{budget?.monthly_calls ?? 0} model calls</span><span>{Math.max(0, 100 - spendPct).toFixed(0)}% remaining</span></div>
        </article>
      </section>

      <section className="finance-panel finance-workflows">
        <div className="finance-panel-heading"><div><p>Runbook</p><h2>Start a focused workflow</h2></div><button onClick={() => onNavigate("flows")}>All automations</button></div>
        <div className="finance-workflow-grid">
          <button onClick={() => startPrompt("Prepare my E4Life morning finance brief: cash position, open holds, exceptions, deadlines, and anything that needs my approval. Separate verified facts from unavailable data.")}><span>01</span><strong>Morning finance brief</strong><small>Cash, holds, exceptions, and deadlines</small></button>
          <button onClick={() => onNavigate("inbox")}><span>02</span><strong>Review proposed actions</strong><small>Approve, reject, or request evidence</small></button>
          <button onClick={() => startPrompt("Help me investigate a FinanceOS variance. First ask for the account, entity, period, and expected value. Then trace evidence before proposing any correction; do not write to a ledger.")}><span>03</span><strong>Investigate a variance</strong><small>Trace the source before proposing a fix</small></button>
        </div>
      </section>
    </div>
  );
};

export default DashboardView;
