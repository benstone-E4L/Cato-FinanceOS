/**
 * BudgetView — Live budget tracking with hard cap badge and model breakdown.
 */
import React, { useState, useEffect, useCallback } from "react";

interface BudgetViewProps {
  httpPort: number;
}

interface BudgetData {
  session_spend: number;
  session_cap: number;
  session_pct_remaining: number;
  monthly_spend: number;
  monthly_cap: number;
  monthly_pct_remaining: number;
  monthly_calls: number;
  total_spend_all_time: number;
  month_key: string;
}

function CapBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="cap-bar-track">
      <div className="cap-bar-fill" style={{ width: `${Math.min(100 - pct, 100)}%`, background: color }} />
    </div>
  );
}

export const BudgetView: React.FC<BudgetViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [budget, setBudget] = useState<BudgetData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchBudget = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/budget/summary`);
      setBudget(await r.json());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchBudget();
    const t = setInterval(fetchBudget, 10000);
    return () => clearInterval(t);
  }, [fetchBudget]);

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  const monthPct = budget?.monthly_pct_remaining ?? 100;
  const monthUsed = 100 - monthPct;
  const monthColor = monthPct > 40 ? "#2563eb" : monthPct > 15 ? "#eab308" : "#ef4444";

  const sessPct = budget?.session_pct_remaining ?? 100;
  const sessColor = sessPct > 40 ? "#2563eb" : sessPct > 15 ? "#eab308" : "#ef4444";

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Budget</h1>
        <button className="btn-secondary" onClick={fetchBudget}>Refresh</button>
      </div>
      {error && <div className="page-error">{error}</div>}

      {/* Hard cap badge — Cato differentiator */}
      <div className="hard-cap-badge">
        <span className="hard-cap-icon">🛡</span>
        <div>
          <div className="hard-cap-title">Hard Spending Caps Enforced</div>
          <div className="hard-cap-desc">
            ${budget?.session_cap ?? 1}/session · ${budget?.monthly_cap ?? 20}/month.
            OpenClaw has no caps — users report $300–750/mo runaway costs.
          </div>
        </div>
      </div>

      <div className="dash-grid">
        {/* Monthly spend */}
        <div className="dash-card" style={{ borderTop: `3px solid ${monthColor}` }}>
          <div className="dash-card-label">Monthly Spend ({budget?.month_key})</div>
          <div className="dash-card-value">${budget?.monthly_spend.toFixed(4) ?? "0.0000"}</div>
          <div className="dash-card-sub">${budget?.monthly_cap ?? 20} cap · {monthPct.toFixed(0)}% remaining</div>
          <CapBar pct={monthPct} color={monthColor} />
          <div className="cap-bar-pct">{monthUsed.toFixed(1)}% used</div>
        </div>

        {/* Session spend */}
        <div className="dash-card" style={{ borderTop: `3px solid ${sessColor}` }}>
          <div className="dash-card-label">Current Session Spend</div>
          <div className="dash-card-value">${budget?.session_spend.toFixed(6) ?? "0.000000"}</div>
          <div className="dash-card-sub">${budget?.session_cap ?? 1} cap · {sessPct.toFixed(0)}% remaining</div>
          <CapBar pct={sessPct} color={sessColor} />
        </div>

        {/* Monthly calls */}
        <div className="dash-card">
          <div className="dash-card-label">Monthly API Calls</div>
          <div className="dash-card-value">{budget?.monthly_calls ?? 0}</div>
        </div>

        {/* All-time spend */}
        <div className="dash-card">
          <div className="dash-card-label">All-Time Spend</div>
          <div className="dash-card-value">${budget?.total_spend_all_time.toFixed(2) ?? "0.00"}</div>
          <div className="dash-card-sub">since installation</div>
        </div>
      </div>
    </div>
  );
};

export default BudgetView;
