/**
 * SystemView — CLI Process Pool Monitor, Action Guard / Safety Gate, and Daemon Controls.
 */
import React, { useState, useEffect, useCallback } from "react";

interface SystemViewProps {
  httpPort: number;
}

// ---- CLI Pool types ----

interface CliToolStatus {
  installed: boolean;
  logged_in: boolean;
  version: string;
}

interface CliStatusData {
  claude?: CliToolStatus;
  codex?: CliToolStatus;
  gemini?: CliToolStatus;
  cursor?: CliToolStatus;
  [key: string]: CliToolStatus | undefined;
}

// ---- Action Guard types ----

interface ActionCheck {
  rule: string;
  description: string;
  active: boolean;
}

interface ActionGuardData {
  checks: ActionCheck[];
  autonomy_level: number;
}

// ---- CLI Pool Panel ----

const MODEL_ORDER = ["claude", "codex", "gemini", "cursor"];

const MODEL_LABELS: Record<string, string> = {
  claude: "Claude",
  codex:  "Codex",
  gemini: "Gemini",
  cursor: "Cursor",
};

function CliPoolPanel({ httpPort }: { httpPort: number }) {
  const base = `http://127.0.0.1:${httpPort}`;
  const [data, setData] = useState<CliStatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [restartingCli, setRestartingCli] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${base}/api/cli/status`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      setData(json);
      setError(null);
    } catch (e) {
      setData(null);
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const restartCli = async (name: string) => {
    setRestartingCli(name);
    try {
      await fetch(`${base}/api/cli/${name}/restart`, { method: "POST" });
      setTimeout(() => fetchStatus(), 1500);
    } catch {
      // ignore
    } finally {
      setTimeout(() => setRestartingCli(null), 2000);
    }
  };

  const isEmpty = !data || Object.keys(data).length === 0;

  return (
    <div className="card" style={{ marginBottom: "1.5rem" }}>
      <div className="page-header" style={{ marginBottom: "1rem" }}>
        <h2 className="section-title" style={{ margin: 0 }}>CLI Process Pool</h2>
        <button className="btn-secondary" onClick={fetchStatus} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="page-error" style={{ marginBottom: "0.75rem" }}>
          {error}
        </div>
      )}

      {!loading && (isEmpty || error) ? (
        <div style={{ color: "var(--text-muted, #888)", fontSize: "0.9rem" }}>
          Pool status unavailable.
        </div>
      ) : (
        <div className="dash-grid">
          {MODEL_ORDER.map((name) => {
            const tool = data?.[name];
            const isWarm = tool?.installed && tool?.logged_in;
            const badgeColor = isWarm ? "#2563eb" : "#ef4444";
            const badgeLabel = isWarm ? "warm" : (tool?.installed ? "cold" : "unavailable");

            return (
              <div
                key={name}
                className="dash-card"
                style={{ borderTop: `3px solid ${badgeColor}` }}
              >
                <div className="dash-card-label">{MODEL_LABELS[name] ?? name}</div>
                <div style={{ marginTop: "0.5rem" }}>
                  <span
                    style={{
                      display: "inline-block",
                      padding: "0.2rem 0.6rem",
                      borderRadius: "999px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      background: badgeColor,
                      color: "#fff",
                      textTransform: "uppercase",
                      letterSpacing: "0.04em",
                    }}
                  >
                    {badgeLabel}
                  </span>
                </div>
                {tool?.version && (
                  <div className="dash-card-sub" style={{ marginTop: "0.5rem", fontSize: "0.75rem" }}>
                    {tool.version}
                  </div>
                )}
                <button
                  className="btn-secondary"
                  style={{ marginTop: "0.5rem", fontSize: "0.7rem", padding: "2px 8px" }}
                  onClick={() => restartCli(name)}
                  disabled={restartingCli === name}
                >
                  {restartingCli === name ? "Restarting..." : "Restart"}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---- Action Guard Panel ----

function ActionGuardPanel({ httpPort }: { httpPort: number }) {
  const base = `http://127.0.0.1:${httpPort}`;
  const [data, setData] = useState<ActionGuardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchGuard = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/action-guard/status`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchGuard();
  }, [fetchGuard]);

  const autonomy = data?.autonomy_level ?? 0;
  const autonomyPct = Math.round(autonomy * 100);
  const barColor =
    autonomy < 0.4 ? "#2563eb" :
    autonomy < 0.7 ? "#eab308" :
    "#ef4444";

  return (
    <div className="card" style={{ marginBottom: "1.5rem" }}>
      <div className="page-header" style={{ marginBottom: "1rem" }}>
        <h2 className="section-title" style={{ margin: 0 }}>
          <span aria-hidden="true" style={{ marginRight: "0.4rem" }}>🛡</span>
          Safety Gate
        </h2>
      </div>

      {loading && <div className="view-loading"><div className="app-loading-spinner" /></div>}
      {error && <div className="page-error" style={{ marginBottom: "0.75rem" }}>{error}</div>}

      {!loading && data && (
        <>
          {/* Autonomy level bar */}
          <div style={{ marginBottom: "1.25rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", marginBottom: "0.35rem" }}>
              <span style={{ color: "var(--text-muted, #888)" }}>Autonomy Level</span>
              <span style={{ fontWeight: 600 }}>{autonomyPct}%</span>
            </div>
            <div className="cap-bar-track">
              <div
                className="cap-bar-fill"
                style={{ width: `${autonomyPct}%`, background: barColor }}
              />
            </div>
            <div className="cap-bar-pct" style={{ fontSize: "0.75rem" }}>
              {autonomy < 0.4 ? "Low — conservative mode" :
               autonomy < 0.7 ? "Medium — standard operation" :
               "High — permissive mode"}
            </div>
          </div>

          {/* Checks list */}
          <div>
            {data.checks.length === 0 ? (
              <div style={{ color: "var(--text-muted, #888)", fontSize: "0.9rem" }}>No checks configured.</div>
            ) : (
              data.checks.map((check, idx) => (
                <div
                  key={idx}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: "0.75rem",
                    padding: "0.65rem 0",
                    borderBottom: idx < data.checks.length - 1 ? "1px solid var(--border, #333)" : "none",
                  }}
                >
                  <span
                    style={{
                      flexShrink: 0,
                      display: "inline-block",
                      padding: "0.15rem 0.5rem",
                      borderRadius: "999px",
                      fontSize: "0.7rem",
                      fontWeight: 600,
                      background: check.active ? "#2563eb" : "#6b7280",
                      color: "#fff",
                      marginTop: "0.1rem",
                      textTransform: "uppercase",
                      letterSpacing: "0.04em",
                    }}
                  >
                    {check.active ? "active" : "off"}
                  </span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: "0.88rem" }}>{check.rule}</div>
                    <div style={{ color: "var(--text-muted, #888)", fontSize: "0.8rem", marginTop: "0.1rem" }}>
                      {check.description}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ---- Daemon Controls Panel ----

function DaemonControlsPanel({ httpPort }: { httpPort: number }) {
  const base = `http://127.0.0.1:${httpPort}`;
  const [status, setStatus] = useState<"idle" | "restarting" | "done" | "error">("idle");
  const [msg, setMsg] = useState<string | null>(null);

  const handleRestart = async () => {
    const confirmed = window.confirm(
      "Restart Cato daemon? Connection will drop briefly."
    );
    if (!confirmed) return;

    setStatus("restarting");
    setMsg("Restarting…");
    try {
      const r = await fetch(`${base}/api/daemon/restart`, { method: "POST" });
      const json = await r.json();
      if (json.status === "ok") {
        setStatus("done");
        setMsg("Daemon restart scheduled. Reconnecting automatically…");
      } else {
        throw new Error(json.message ?? "Unknown error");
      }
    } catch (e) {
      setStatus("error");
      setMsg(`Restart failed: ${e}`);
    }
  };

  return (
    <div className="card">
      <div className="page-header" style={{ marginBottom: "1rem" }}>
        <h2 className="section-title" style={{ margin: 0 }}>Daemon Controls</h2>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <button
          className="btn-danger"
          onClick={handleRestart}
          disabled={status === "restarting"}
        >
          {status === "restarting" ? "Restarting…" : "Restart Daemon"}
        </button>

        {msg && (
          <span
            style={{
              fontSize: "0.88rem",
              color: status === "error" ? "#ef4444" : "var(--text-muted, #888)",
            }}
          >
            {msg}
          </span>
        )}
      </div>

      <p style={{ marginTop: "0.85rem", fontSize: "0.82rem", color: "var(--text-muted, #888)" }}>
        The app will reconnect automatically after restart.
      </p>
    </div>
  );
}

// ---- Root SystemView ----

export const SystemView: React.FC<SystemViewProps> = ({ httpPort }) => {
  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">System</h1>
      </div>

      <CliPoolPanel httpPort={httpPort} />
      <ActionGuardPanel httpPort={httpPort} />
      <DaemonControlsPanel httpPort={httpPort} />
    </div>
  );
};

export default SystemView;
