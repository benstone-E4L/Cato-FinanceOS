/**
 * UsageView — Live token/call usage statistics with model breakdown.
 */
import React, { useState, useEffect, useCallback } from "react";

interface UsageViewProps {
  httpPort: number;
}

interface UsageData {
  total_calls?: number;
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  model_breakdown?: Record<string, number>;
  daily?: Record<string, number>;
  [key: string]: unknown;
}

export const UsageView: React.FC<UsageViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchUsage = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/usage/summary`);
      setUsage(await r.json());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchUsage();
  }, [fetchUsage]);

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Usage</h1>
        <button className="btn-secondary" onClick={fetchUsage}>Refresh</button>
      </div>
      {error && <div className="page-error">{error}</div>}

      <div className="dash-grid">
        <div className="dash-card">
          <div className="dash-card-label">Total Calls</div>
          <div className="dash-card-value">{usage?.total_calls ?? 0}</div>
        </div>
        <div className="dash-card">
          <div className="dash-card-label">Total Tokens</div>
          <div className="dash-card-value">{(usage?.total_tokens ?? 0).toLocaleString()}</div>
          <div className="dash-card-sub">
            {usage?.input_tokens != null && `${usage.input_tokens.toLocaleString()} in`}
            {usage?.output_tokens != null && ` · ${usage.output_tokens.toLocaleString()} out`}
          </div>
        </div>
      </div>

      {usage?.model_breakdown && Object.keys(usage.model_breakdown).length > 0 && (
        <div className="section-block">
          <div className="section-title">Model Breakdown</div>
          <div className="table-container">
            <table className="data-table">
              <thead><tr><th>Model</th><th>Calls</th></tr></thead>
              <tbody>
                {Object.entries(usage.model_breakdown)
                  .sort(([, a], [, b]) => b - a)
                  .map(([model, calls]) => (
                    <tr key={model}>
                      <td><code className="code-cell">{model}</code></td>
                      <td>{calls}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Raw data for anything not parsed above */}
      {usage && Object.keys(usage).length > 0 && (
        <div className="section-block">
          <div className="section-title">Raw Response</div>
          <pre className="raw-json">{JSON.stringify(usage, null, 2)}</pre>
        </div>
      )}
    </div>
  );
};

export default UsageView;
