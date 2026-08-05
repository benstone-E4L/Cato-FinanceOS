/**
 * ReplayView — Dry-run replay visualization for a session.
 * POST /api/sessions/{sessionId}/replay → ReplayReport
 */
import React, { useState, useEffect, useCallback } from "react";

export interface ReplayViewProps {
  httpPort: number;
  sessionId: string | null;
  onBack: () => void;
}

interface ReplayStep {
  index: number;
  tool_name: string;
  matched: boolean;
  elapsed_ms: number;
}

interface ReplayReport {
  session_id: string;
  mode: string;
  total_steps: number;
  matched: number;
  mismatched: number;
  skipped: number;
  elapsed_seconds: number;
  steps: ReplayStep[];
}

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  accent?: string;
}

const MetricCard: React.FC<MetricCardProps> = ({ label, value, accent }) => (
  <div className="dash-card" style={accent ? { borderTop: `3px solid ${accent}` } : {}}>
    <div className="dash-card-label">{label}</div>
    <div className="dash-card-value">{value}</div>
  </div>
);

export const ReplayView: React.FC<ReplayViewProps> = ({ httpPort, sessionId, onBack }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [report, setReport] = useState<ReplayReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runReplay = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const r = await fetch(
        `${base}/api/sessions/${encodeURIComponent(sessionId)}/replay`,
        { method: "POST" }
      );
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`Server returned ${r.status}: ${text}`);
      }
      const data: ReplayReport = await r.json();
      setReport(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base, sessionId]);

  useEffect(() => {
    if (sessionId) {
      runReplay();
    }
  }, [sessionId, runReplay]);

  if (!sessionId) {
    return (
      <div className="page-view">
        <div className="empty-state">No session selected for replay.</div>
      </div>
    );
  }

  const matchRate =
    report && report.total_steps > 0
      ? Math.round((report.matched / report.total_steps) * 100)
      : 0;

  return (
    <div className="page-view" style={{ marginBottom: "2rem" }}>
      {/* Header */}
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <button className="btn-secondary" onClick={onBack}>
            ← Back
          </button>
          <h1 className="page-title" style={{ margin: 0 }}>
            Replay
          </h1>
          <code style={{ fontSize: "0.8rem", opacity: 0.6 }}>{sessionId}</code>
        </div>
        {!loading && (
          <button className="btn-secondary" onClick={runReplay}>
            Re-run
          </button>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div className="view-loading">
          <div className="app-loading-spinner" />
          <div style={{ marginTop: "0.75rem", opacity: 0.6 }}>Replaying session…</div>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <div className="page-error">{error}</div>
          <div>
            <button className="btn-secondary" onClick={runReplay}>
              Retry
            </button>
          </div>
        </div>
      )}

      {/* Report */}
      {report && !loading && (
        <>
          {/* Summary cards */}
          <div
            className="dash-grid"
            style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: "1.25rem" }}
          >
            <MetricCard label="Total Steps" value={report.total_steps} />
            <MetricCard label="Matched" value={report.matched} accent="#2563eb" />
            <MetricCard label="Mismatched" value={report.mismatched} accent="#ef4444" />
            <MetricCard
              label="Elapsed"
              value={`${report.elapsed_seconds.toFixed(2)}s`}
            />
          </div>

          {/* Skipped + mode */}
          <div
            style={{
              display: "flex",
              gap: "1.5rem",
              marginBottom: "1.25rem",
              fontSize: "0.875rem",
              opacity: 0.75,
            }}
          >
            <span>Skipped: <strong>{report.skipped}</strong></span>
            <span>Mode: <strong>{report.mode}</strong></span>
          </div>

          {/* Match rate bar */}
          <div style={{ marginBottom: "1.5rem" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: "0.4rem",
                fontSize: "0.875rem",
              }}
            >
              <span>Match Rate</span>
              <span style={{ fontWeight: 600 }}>{matchRate}%</span>
            </div>
            <div
              style={{
                height: "10px",
                borderRadius: "5px",
                background: "var(--border, #2a2a2a)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${matchRate}%`,
                  background:
                    matchRate >= 80
                      ? "#2563eb"
                      : matchRate >= 50
                      ? "#eab308"
                      : "#ef4444",
                  borderRadius: "5px",
                  transition: "width 0.4s ease",
                }}
              />
            </div>
          </div>

          {/* Step table */}
          {report.steps && report.steps.length > 0 && (
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Tool</th>
                    <th>Result</th>
                    <th>Elapsed (ms)</th>
                  </tr>
                </thead>
                <tbody>
                  {report.steps.map((step) => (
                    <tr key={step.index}>
                      <td>{step.index}</td>
                      <td>
                        <code className="code-cell">{step.tool_name}</code>
                      </td>
                      <td>
                        {step.matched ? (
                          <span style={{ color: "#2563eb", fontWeight: 600 }}>✓</span>
                        ) : (
                          <span style={{ color: "#ef4444", fontWeight: 600 }}>✗</span>
                        )}
                      </td>
                      <td>{step.elapsed_ms}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {report.steps && report.steps.length === 0 && (
            <div className="empty-state">No steps recorded for this session.</div>
          )}
        </>
      )}
    </div>
  );
};

export default ReplayView;
