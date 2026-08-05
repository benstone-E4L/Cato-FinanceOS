/**
 * AuditLogView — SHA-256 hash-chained audit log with verification.
 */
import React, { useState, useEffect, useCallback } from "react";

interface AuditLogViewProps {
  httpPort: number;
}

interface AuditEntry {
  id: number;
  session_id: string;
  action_type: string;
  tool_name: string;
  cost_cents: number;
  error: string;
  timestamp: number;
  prev_hash: string;
  row_hash: string;
}

export const AuditLogView: React.FC<AuditLogViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sessionFilter, setSessionFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [verifyResult, setVerifyResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [verifying, setVerifying] = useState(false);

  const fetchEntries = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (sessionFilter) params.set("session_id", sessionFilter);
      if (actionFilter) params.set("action_type", actionFilter);
      const r = await fetch(`${base}/api/audit/entries?${params}`);
      setEntries(await r.json());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base, sessionFilter, actionFilter]);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  const verifyChain = async () => {
    setVerifying(true);
    try {
      const r = await fetch(`${base}/api/audit/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sessionFilter ? { session_id: sessionFilter } : {}),
      });
      const data = await r.json();
      setVerifyResult({
        ok: data.ok,
        message: data.ok ? "Chain integrity verified" : `Chain broken: ${data.error ?? "hash mismatch"}`,
      });
    } catch (e) {
      setVerifyResult({ ok: false, message: String(e) });
    } finally {
      setVerifying(false);
    }
  };

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Audit Log</h1>
        <div className="page-controls">
          <input
            className="filter-input"
            placeholder="Session ID filter"
            value={sessionFilter}
            onChange={(e) => setSessionFilter(e.target.value)}
          />
          <select
            className="settings-select"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
          >
            <option value="">All Actions</option>
            <option value="tool_call">tool_call</option>
            <option value="llm_response">llm_response</option>
            <option value="skill_load">skill_load</option>
            <option value="error">error</option>
          </select>
          <button className="btn-secondary" onClick={fetchEntries}>Filter</button>
          <button className="btn-primary" onClick={verifyChain} disabled={verifying}>
            {verifying ? "Verifying…" : "Verify Chain"}
          </button>
        </div>
      </div>

      {error && <div className="page-error">{error}</div>}

      {verifyResult && (
        <div className={`verify-banner ${verifyResult.ok ? "verify-ok" : "verify-fail"}`}>
          {verifyResult.ok ? "✓" : "✗"} {verifyResult.message}
        </div>
      )}

      {entries.length === 0 ? (
        <div className="empty-state">No audit entries</div>
      ) : (
        <div className="table-container">
          <table className="data-table audit-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Time</th>
                <th>Session</th>
                <th>Action</th>
                <th>Tool</th>
                <th>Cost</th>
                <th>Error</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className={e.error ? "row-error" : ""}>
                  <td>{e.id}</td>
                  <td className="ts-cell">{new Date(e.timestamp * 1000).toLocaleTimeString()}</td>
                  <td><code className="hash-cell">{e.session_id?.slice(0, 12)}…</code></td>
                  <td><span className="action-badge">{e.action_type}</span></td>
                  <td>{e.tool_name || "—"}</td>
                  <td>{e.cost_cents ? `¢${e.cost_cents}` : "—"}</td>
                  <td className="error-cell">{e.error || "—"}</td>
                  <td title={e.row_hash}><code className="hash-cell">{e.row_hash?.slice(0, 8)}…</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default AuditLogView;
