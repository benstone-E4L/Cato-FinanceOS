/**
 * SessionsView — Live session list with kill, queue depth, transcript download, replay,
 * checkpoint inspection, and receipt download.
 */
import React, { useState, useEffect, useCallback } from "react";
import { ReplayView } from "./ReplayView";

interface SessionsViewProps {
  httpPort: number;
}

interface SessionEntry {
  session_id: string;
  queue_depth: number;
  running: boolean;
}

interface CheckpointEntry {
  checkpoint_id: string;
  task_description: string;
  token_count: number;
  timestamp: string;
  current_plan: string;
  decisions_made: string[];
  files_modified: string[];
}

interface CheckpointDetail {
  checkpoint_id: string;
  task_description: string;
  token_count: number;
  timestamp: string;
  summary: string;
}

export const SessionsView: React.FC<SessionsViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [killing, setKilling] = useState<string | null>(null);
  const [replaySessionId, setReplaySessionId] = useState<string | null>(null);
  const [showReplay, setShowReplay] = useState(false);

  // Checkpoint panel state
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"checkpoints">("checkpoints");
  const [checkpoints, setCheckpoints] = useState<CheckpointEntry[]>([]);
  const [checkpointDetail, setCheckpointDetail] = useState<CheckpointDetail | null>(null);
  const [checkpointsLoading, setCheckpointsLoading] = useState(false);
  const [checkpointError, setCheckpointError] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/sessions`);
      setSessions(await r.json());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchSessions();
    const t = setInterval(fetchSessions, 5000);
    return () => clearInterval(t);
  }, [fetchSessions]);

  const killSession = async (sessionId: string) => {
    setKilling(sessionId);
    try {
      await fetch(`${base}/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
      await fetchSessions();
      if (selectedSessionId === sessionId) {
        setSelectedSessionId(null);
        setCheckpoints([]);
        setCheckpointDetail(null);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setKilling(null);
    }
  };

  const downloadTranscript = async (sessionId: string) => {
    try {
      const r = await fetch(`${base}/api/audit/entries?session_id=${encodeURIComponent(sessionId)}&limit=1000`);
      const entries = await r.json();
      const jsonl = entries.map((e: Record<string, unknown>) => JSON.stringify(e)).join("\n");
      const blob = new Blob([jsonl], { type: "application/x-ndjson" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `cato-session-${sessionId.slice(0, 12)}.jsonl`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    }
  };

  const openCheckpoints = async (sessionId: string) => {
    setSelectedSessionId(sessionId);
    setCheckpointDetail(null);
    setCheckpointError(null);
    setCheckpointsLoading(true);
    try {
      const r = await fetch(`${base}/api/sessions/${encodeURIComponent(sessionId)}/checkpoints`);
      const data = await r.json();
      setCheckpoints(Array.isArray(data) ? data : []);
    } catch (e) {
      setCheckpointError(String(e));
      setCheckpoints([]);
    } finally {
      setCheckpointsLoading(false);
    }
  };

  const openCheckpointDetail = async (sessionId: string, cid: string) => {
    setCheckpointError(null);
    try {
      const r = await fetch(
        `${base}/api/sessions/${encodeURIComponent(sessionId)}/checkpoints/${encodeURIComponent(cid)}`
      );
      if (!r.ok) {
        setCheckpointError(`Checkpoint not found (${r.status})`);
        return;
      }
      const data: CheckpointDetail = await r.json();
      setCheckpointDetail(data);
    } catch (e) {
      setCheckpointError(String(e));
    }
  };

  const downloadReceipt = async (sessionId: string) => {
    try {
      const r = await fetch(`${base}/api/sessions/${encodeURIComponent(sessionId)}/receipt`);
      const data = await r.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `cato-receipt-${sessionId.slice(0, 12)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    }
  };

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  if (showReplay && replaySessionId) {
    return (
      <ReplayView
        httpPort={httpPort}
        sessionId={replaySessionId}
        onBack={() => { setShowReplay(false); setReplaySessionId(null); }}
      />
    );
  }

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Sessions</h1>
        <button className="btn-secondary" onClick={fetchSessions}>Refresh</button>
      </div>
      {error && <div className="page-error">{error}</div>}

      {sessions.length === 0 ? (
        <div className="empty-state">No active sessions</div>
      ) : (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Session ID</th>
                <th>Status</th>
                <th>Queue Depth</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.session_id} className={selectedSessionId === s.session_id ? "row-selected" : ""}>
                  <td><code className="code-cell">{s.session_id}</code></td>
                  <td>
                    <span className={`status-badge ${s.running ? "status-badge-blue" : "status-badge-gray"}`}>
                      {s.running ? "Running" : "Idle"}
                    </span>
                  </td>
                  <td>{s.queue_depth}</td>
                  <td className="action-cell">
                    <button
                      className="btn-danger-sm"
                      onClick={() => killSession(s.session_id)}
                      disabled={killing === s.session_id}
                    >
                      {killing === s.session_id ? "Killing..." : "Kill"}
                    </button>
                    <button
                      className="btn-secondary-sm"
                      onClick={() => downloadTranscript(s.session_id)}
                    >
                      Export
                    </button>
                    <button
                      className="btn-secondary-sm"
                      onClick={() => { setReplaySessionId(s.session_id); setShowReplay(true); }}
                      title="Dry-run replay this session"
                    >
                      Replay
                    </button>
                    <button
                      className="btn-secondary-sm"
                      onClick={() => openCheckpoints(s.session_id)}
                      title="View checkpoints for this session"
                    >
                      Checkpoints
                    </button>
                    <button
                      className="btn-secondary-sm"
                      onClick={() => downloadReceipt(s.session_id)}
                      title="Download signed receipt as JSON"
                    >
                      Receipt
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Checkpoint panel */}
      {selectedSessionId && (
        <div className="checkpoint-panel" style={{ marginTop: "1.5rem" }}>
          <div className="page-header" style={{ marginBottom: "0.75rem" }}>
            <h2 className="page-title" style={{ fontSize: "1rem" }}>
              Checkpoints — <code>{selectedSessionId}</code>
            </h2>
            <button
              className="btn-secondary-sm"
              onClick={() => { setSelectedSessionId(null); setCheckpoints([]); setCheckpointDetail(null); }}
            >
              Close
            </button>
          </div>

          {/* Tab bar (single tab for now; easy to extend) */}
          <div className="tab-bar" style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem" }}>
            <button
              className={`tab-btn${activeTab === "checkpoints" ? " tab-btn-active" : ""}`}
              onClick={() => setActiveTab("checkpoints")}
            >
              Checkpoints
            </button>
          </div>

          {checkpointError && <div className="page-error">{checkpointError}</div>}

          {checkpointsLoading ? (
            <div className="view-loading"><div className="app-loading-spinner" /></div>
          ) : checkpoints.length === 0 ? (
            <div className="empty-state">No checkpoints recorded for this session</div>
          ) : (
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Checkpoint ID</th>
                    <th>Task Description</th>
                    <th>Token Count</th>
                    <th>Timestamp</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {checkpoints.map((c) => (
                    <tr key={c.checkpoint_id}>
                      <td><code className="code-cell">{c.checkpoint_id.slice(0, 16)}</code></td>
                      <td>{c.task_description || "(none)"}</td>
                      <td>{c.token_count.toLocaleString()}</td>
                      <td>{c.timestamp}</td>
                      <td className="action-cell">
                        <button
                          className="btn-secondary-sm"
                          onClick={() => openCheckpointDetail(selectedSessionId, c.checkpoint_id)}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Checkpoint detail */}
          {checkpointDetail && (
            <div className="checkpoint-detail" style={{ marginTop: "1rem", padding: "1rem", background: "var(--surface-2, #1e1e2e)", borderRadius: "6px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                <strong>Checkpoint Summary</strong>
                <button className="btn-secondary-sm" onClick={() => setCheckpointDetail(null)}>Dismiss</button>
              </div>
              <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "0.25rem 1rem", fontSize: "0.85rem" }}>
                <dt>Task</dt><dd>{checkpointDetail.task_description || "(none)"}</dd>
                <dt>Tokens</dt><dd>{checkpointDetail.token_count.toLocaleString()}</dd>
                <dt>Saved at</dt><dd>{checkpointDetail.timestamp}</dd>
              </dl>
              <pre style={{ marginTop: "0.75rem", fontSize: "0.75rem", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "300px", overflowY: "auto" }}>
                {checkpointDetail.summary}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default SessionsView;
