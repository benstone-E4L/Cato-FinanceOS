/**
 * FinanceView — read-only FinanceOS control-room status (CHUNK_5_FINANCE_VIEW).
 *
 * Consumes Cato's local `/api/finance-os/control-room` proxy, which itself
 * relays FinanceOS's `/api/v1/control-room` and `/api/v1/control-room/
 * integrations-health` endpoints (read-only). Renders close status,
 * exceptions/HOLDs, integration health, and write-gate state.
 *
 * No control on this view ever writes back to FinanceOS or Xero from Cato —
 * that boundary is enforced server-side (financeos_client.py never sends a
 * mutating call for this feature) and there are no write actions here.
 *
 * When FinanceOS is unreachable, or refuses because no capability-token
 * mint endpoint exists yet (O2O-FOS-1), the last-known state renders with a
 * visible "stale" banner instead of a blank screen or a crash.
 */
import React, { useCallback, useEffect, useState } from "react";

interface FinanceViewProps {
  httpPort: number;
}

interface ControlRoomData {
  control_room?: Record<string, unknown>;
  integrations_health?: Record<string, unknown>;
}

interface ControlRoomPayload {
  connected: boolean;
  stale: boolean;
  data: ControlRoomData | null;
  cached_at: string | null;
}

function formatTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export const FinanceView: React.FC<FinanceViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [payload, setPayload] = useState<ControlRoomPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/finance-os/control-room`, { signal: AbortSignal.timeout(6000) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = (await r.json()) as ControlRoomPayload;
      if (!body || typeof body !== "object") throw new Error("Finance view returned an invalid response");
      setPayload(body);
      setError(null);
    } catch (e) {
      // The proxy route itself never crashes and never returns non-200 for a
      // downstream FinanceOS outage — an error here means Cato's own daemon
      // is unreachable, a materially different failure than "FinanceOS is
      // down". Surface it distinctly rather than silently showing stale data.
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  const controlRoom = payload?.data?.control_room ?? null;
  const integrationsHealth = payload?.data?.integrations_health ?? null;
  const stale = payload?.stale ?? false;
  const writeGateEnabled = controlRoom?.["write_gate_enabled"] ?? controlRoom?.["production_write_enabled"];

  return (
    <div className="page-view finance-view">
      <div className="page-header">
        <h1 className="page-title">Finance</h1>
        <div className="page-controls">
          <button className="btn-secondary" onClick={refresh}>Refresh</button>
        </div>
      </div>

      {error && <div className="page-error">Cato daemon unreachable: {error}</div>}

      {!error && stale && (
        <div className="page-error" role="status">
          Showing last-known FinanceOS state — the control-room API is currently unreachable
          {payload?.cached_at ? ` (as of ${formatTime(payload.cached_at)})` : " and no prior state has been cached yet"}.
        </div>
      )}

      {!error && !controlRoom && !integrationsHealth && (
        <div className="empty-state">
          FinanceOS is not connected yet. Cato remains read-only and will not attempt to write.
        </div>
      )}

      {(controlRoom || integrationsHealth) && (
        <>
          <div className="dash-grid">
            <div className="dash-card">
              <div className="dash-card-label">Close status</div>
              <div className="dash-card-value">{renderValue(controlRoom?.["close_status"])}</div>
              <div className="dash-card-sub">from FinanceOS control-room</div>
            </div>
            <div className="dash-card">
              <div className="dash-card-label">Open holds / exceptions</div>
              <div className="dash-card-value">{renderValue(controlRoom?.["holds"] ?? controlRoom?.["exceptions"])}</div>
              <div className="dash-card-sub">read-only — approve in FinanceOS/Airtable</div>
            </div>
            <div className="dash-card">
              <div className="dash-card-label">Xero write gate</div>
              <div className="dash-card-value">{writeGateEnabled === undefined ? "—" : writeGateEnabled ? "Enabled" : "Protected"}</div>
              <div className="dash-card-sub">Cato never writes to FinanceOS or Xero</div>
            </div>
          </div>

          <div className="section-block">
            <div className="section-title">Integration health</div>
            {!integrationsHealth || Object.keys(integrationsHealth).length === 0 ? (
              <div className="empty-state">No integration health data available</div>
            ) : (
              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr><th>Integration</th><th>Status</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(integrationsHealth).map(([name, status]) => (
                      <tr key={name}>
                        <td>{name}</td>
                        <td><span className="action-badge">{renderValue(status)}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {controlRoom && (
            <div className="section-block">
              <div className="section-title">Control room detail</div>
              <div className="table-container">
                <table className="data-table">
                  <tbody>
                    {Object.entries(controlRoom).map(([field, value]) => (
                      <tr key={field}>
                        <td className="code-cell">{field}</td>
                        <td>{renderValue(value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default FinanceView;
