/**
 * NodesView — Remote node management for Cato.
 * Shows connected physical devices (Mac, Pi, phone, etc.) and their capabilities.
 */
import React, { useState, useEffect, useCallback } from "react";

interface NodesViewProps {
  httpPort: number;
}

interface NodeEntry {
  node_id: string;
  name: string;
  capabilities: string[];
  registered_at: number;
  last_seen: number;
  stale: boolean;
}

export const NodesView: React.FC<NodesViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [nodes, setNodes] = useState<NodeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchNodes = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/nodes`);
      const data = await r.json();
      setNodes(Array.isArray(data) ? data : []);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchNodes();
    const t = setInterval(fetchNodes, 15000);
    return () => clearInterval(t);
  }, [fetchNodes]);

  const disconnect = useCallback(async (nodeId: string) => {
    if (!confirm(`Disconnect node "${nodeId}"?`)) return;
    try {
      await fetch(`${base}/api/nodes/${nodeId}`, { method: "DELETE" });
      fetchNodes();
    } catch (e) {
      setError(String(e));
    }
  }, [base, fetchNodes]);

  const fmtTime = (ts: number) => {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString();
  };

  const timeSince = (ts: number) => {
    const secs = Math.floor(Date.now() / 1000 - ts);
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    return `${Math.floor(secs / 3600)}h ago`;
  };

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: "#f1f5f9" }}>Remote Nodes</h1>
        <button className="btn btn-secondary btn-sm" onClick={fetchNodes}>Refresh</button>
      </div>

      {error && (
        <div className="error-banner" style={{ marginBottom: 16 }}>&#9888; {error}</div>
      )}

      {loading && (
        <div style={{ color: "#64748b", textAlign: "center", padding: 40 }}>Loading...</div>
      )}

      {!loading && nodes.length === 0 && (
        <div className="card" style={{ textAlign: "center", padding: 48 }}>
          <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.5 }}>&#128421;</div>
          <p style={{ color: "#64748b", fontSize: 13 }}>No remote nodes connected.</p>
          <p style={{ color: "#4b5563", fontSize: 12, marginTop: 8 }}>
            Nodes register via WebSocket with <code>type: &quot;node_register&quot;</code>.
          </p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {nodes.map(node => (
          <div key={node.node_id} className="card" style={{ borderTop: `3px solid ${node.stale ? "#ef4444" : "#2563eb"}` }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: node.stale ? "#ef4444" : "#2563eb", display: "inline-block" }} />
                  <span style={{ fontWeight: 700, color: "#f1f5f9", fontSize: 15 }}>{node.name}</span>
                  <code style={{ fontSize: 11, color: "#64748b", background: "#0f1117", padding: "1px 6px", borderRadius: 4 }}>
                    {node.node_id}
                  </code>
                  {node.stale && (
                    <span className="badge badge-red">Stale</span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: "#64748b", marginBottom: 8 }}>
                  Registered {fmtTime(node.registered_at)} · Last seen {timeSince(node.last_seen)}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {node.capabilities.map(cap => (
                    <span key={cap} className="tag">{cap}</span>
                  ))}
                  {node.capabilities.length === 0 && (
                    <span style={{ color: "#4b5563", fontSize: 11 }}>No capabilities</span>
                  )}
                </div>
              </div>
              <button
                className="btn btn-danger btn-sm"
                onClick={() => disconnect(node.node_id)}
              >
                Disconnect
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginTop: 20, background: "#1a1d26" }}>
        <div className="card-title">About Remote Nodes</div>
        <p style={{ color: "#64748b", fontSize: 12, lineHeight: 1.6 }}>
          Remote nodes are physical devices (Mac, Raspberry Pi, phone, etc.) that connect to Cato&apos;s
          WebSocket gateway and advertise capabilities (screenshot, camera, geolocation, shell, etc.).
          Once registered, each capability is available as a tool in the agent loop as{" "}
          <code>node.&lt;node_id&gt;.&lt;capability&gt;</code>.
        </p>
        <p style={{ color: "#4b5563", fontSize: 11, marginTop: 8 }}>
          Nodes connect via WebSocket to <code>{`ws://127.0.0.1:${httpPort}/ws`}</code> and send a{" "}
          <code>node_register</code> message with their ID, name, and capabilities.
        </p>
      </div>
    </div>
  );
};

export default NodesView;
