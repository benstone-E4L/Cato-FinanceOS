/**
 * FlowsView — Catoflows (proactive workflow automation) management.
 * Lists, creates, edits, deletes, and runs YAML-defined multi-step flows.
 */
import React, { useState, useEffect, useCallback } from "react";

interface FlowsViewProps {
  httpPort: number;
}

interface Flow {
  name: string;
  trigger_type: string;
  step_count: number;
  budget_cap: number | null;
}

interface FlowRun {
  id: number;
  flow_name: string;
  current_step: number;
  status: string;
  started_at: number;
  updated_at: number;
}

const DEFAULT_YAML = `name: my-flow
trigger:
  type: manual
steps:
  - skill: web_search
    args:
      query: "AI news today"
budget_cap: 50
`;

export const FlowsView: React.FC<FlowsViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [flows, setFlows] = useState<Flow[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [running, setRunning] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<string | null>(null);
  const [runs, setRuns] = useState<FlowRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchFlows = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/flows`);
      const data = await r.json();
      setFlows(Array.isArray(data) ? data : []);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => { fetchFlows(); }, [fetchFlows]);

  const selectFlow = useCallback(async (name: string) => {
    setSelected(name);
    setRunResult(null);
    try {
      const [contentRes, runsRes] = await Promise.all([
        fetch(`${base}/api/flows/${name}`).then(r => r.json()),
        fetch(`${base}/api/flows/${name}/runs`).then(r => r.json()),
      ]);
      setEditorContent(contentRes.content ?? "");
      setRuns(Array.isArray(runsRes) ? runsRes : []);
    } catch {
      setEditorContent("");
      setRuns([]);
    }
  }, [base]);

  const saveFlow = useCallback(async () => {
    if (!selected) return;
    try {
      await fetch(`${base}/api/flows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: selected, content: editorContent }),
      });
      fetchFlows();
    } catch (e) {
      setError(String(e));
    }
  }, [base, selected, editorContent, fetchFlows]);

  const createFlow = useCallback(async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      await fetch(`${base}/api/flows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, content: DEFAULT_YAML.replace("my-flow", name) }),
      });
      setNewName("");
      setCreating(false);
      await fetchFlows();
      selectFlow(name);
    } catch (e) {
      setError(String(e));
    }
  }, [base, newName, fetchFlows, selectFlow]);

  const deleteFlow = useCallback(async (name: string) => {
    if (!confirm(`Delete flow "${name}"?`)) return;
    try {
      await fetch(`${base}/api/flows/${name}`, { method: "DELETE" });
      if (selected === name) { setSelected(null); setEditorContent(""); }
      fetchFlows();
    } catch (e) {
      setError(String(e));
    }
  }, [base, selected, fetchFlows]);

  const runFlow = useCallback(async (name: string) => {
    setRunning(name);
    setRunResult(null);
    try {
      const r = await fetch(`${base}/api/flows/${name}/run`, { method: "POST" });
      const data = await r.json();
      setRunResult(JSON.stringify(data, null, 2));
      if (selected === name) {
        const runsRes = await fetch(`${base}/api/flows/${name}/runs`).then(r2 => r2.json());
        setRuns(Array.isArray(runsRes) ? runsRes : []);
      }
    } catch (e) {
      setRunResult(`Error: ${e}`);
    } finally {
      setRunning(null);
    }
  }, [base, selected]);

  const statusColor = (status: string) => {
    if (status === "COMPLETED") return "#2563eb";
    if (status === "FAILED") return "#ef4444";
    return "#eab308";
  };

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {/* Left: flow list */}
      <div style={{ width: 260, borderRight: "1px solid #1e2433", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid #1e2433", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#f1f5f9" }}>Flows</span>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setCreating(true)}
          >+ New</button>
        </div>

        {creating && (
          <div style={{ padding: "10px 16px", borderBottom: "1px solid #1e2433", display: "flex", gap: 6 }}>
            <input
              className="form-input"
              placeholder="flow-name"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === "Enter" && createFlow()}
              style={{ flex: 1 }}
              autoFocus
            />
            <button className="btn btn-primary btn-sm" onClick={createFlow}>&#10003;</button>
            <button className="btn btn-secondary btn-sm" onClick={() => { setCreating(false); setNewName(""); }}>&#10005;</button>
          </div>
        )}

        <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
          {loading && <div style={{ padding: "20px 16px", color: "#64748b", fontSize: 12 }}>Loading...</div>}
          {!loading && flows.length === 0 && (
            <div style={{ padding: "20px 16px", color: "#64748b", fontSize: 12, textAlign: "center" }}>
              No flows yet.<br />Click + New to create one.
            </div>
          )}
          {flows.map(flow => (
            <div
              key={flow.name}
              style={{
                padding: "8px 16px",
                cursor: "pointer",
                background: selected === flow.name ? "#3b82f610" : "transparent",
                borderLeft: selected === flow.name ? "2px solid #3b82f6" : "2px solid transparent",
                marginBottom: 1,
              }}
              onClick={() => selectFlow(flow.name)}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontWeight: 600, color: selected === flow.name ? "#3b82f6" : "#e2e8f0", fontSize: 13 }}>
                  {flow.name}
                </span>
                <div style={{ display: "flex", gap: 4 }}>
                  <button
                    className="btn btn-ghost btn-sm"
                    style={{ padding: "2px 6px", fontSize: 11 }}
                    title="Run now"
                    onClick={e => { e.stopPropagation(); runFlow(flow.name); }}
                    disabled={running === flow.name}
                  >
                    {running === flow.name ? "..." : "▶"}
                  </button>
                  <button
                    className="btn btn-ghost btn-sm"
                    style={{ padding: "2px 6px", fontSize: 11, color: "#ef4444" }}
                    title="Delete"
                    onClick={e => { e.stopPropagation(); deleteFlow(flow.name); }}
                  >&#10005;</button>
                </div>
              </div>
              <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
                {flow.trigger_type} · {flow.step_count} step{flow.step_count !== 1 ? "s" : ""}
                {flow.budget_cap != null ? ` · $${flow.budget_cap} cap` : ""}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right: editor + run history */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {error && (
          <div className="error-banner" style={{ margin: "8px 16px" }}>&#9888; {error}</div>
        )}
        {!selected ? (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12, color: "#64748b" }}>
            <span style={{ fontSize: 32 }}>&#9889;</span>
            <p style={{ fontSize: 13 }}>Select a flow to edit, or create a new one.</p>
          </div>
        ) : (
          <>
            <div style={{ padding: "10px 16px", borderBottom: "1px solid #1e2433", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontWeight: 600, color: "#f1f5f9", fontSize: 13, flex: 1 }}>{selected}.yaml</span>
              <button className="btn btn-ghost btn-sm" onClick={() => runFlow(selected)} disabled={running === selected}>
                {running === selected ? "Running..." : "▶ Run Now"}
              </button>
              <button className="btn btn-primary btn-sm" onClick={saveFlow}>Save</button>
            </div>

            <textarea
              style={{
                flex: 1,
                background: "#0f1117",
                border: "none",
                color: "#e2e8f0",
                fontFamily: "'Cascadia Code', 'Fira Code', 'Consolas', monospace",
                fontSize: 13,
                padding: "16px",
                resize: "none",
                outline: "none",
              }}
              value={editorContent}
              onChange={e => setEditorContent(e.target.value)}
              spellCheck={false}
            />

            {runResult && (
              <div style={{ borderTop: "1px solid #1e2433", padding: 12, maxHeight: 160, overflowY: "auto", background: "#1a1d26" }}>
                <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>Last Run Result</div>
                <pre style={{ fontSize: 12, color: "#e2e8f0", margin: 0 }}>{runResult}</pre>
              </div>
            )}

            {runs.length > 0 && (
              <div style={{ borderTop: "1px solid #1e2433", padding: 12, maxHeight: 180, overflowY: "auto", background: "#1a1d26" }}>
                <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>Run History</div>
                {runs.map(run => (
                  <div key={run.id} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, fontSize: 12 }}>
                    <span style={{ color: statusColor(run.status), fontWeight: 700, minWidth: 90 }}>{run.status}</span>
                    <span style={{ color: "#64748b" }}>step {run.current_step}</span>
                    <span style={{ color: "#64748b", marginLeft: "auto" }}>
                      {new Date(run.started_at * 1000).toLocaleTimeString()}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default FlowsView;
