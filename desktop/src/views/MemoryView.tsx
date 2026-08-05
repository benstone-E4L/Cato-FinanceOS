/**
 * MemoryView — Browse and search agent memory: stats, facts, and knowledge graph.
 * Tabs: Stats | Facts | Graph
 */
import React, { useState, useEffect, useCallback } from "react";

interface MemoryViewProps {
  httpPort: number;
}

interface MemoryStats {
  facts: number;
  kg_nodes: number;
  kg_edges: number;
}

interface MemoryChunk {
  source_file?: string;
  content: string;
  score?: number;
  [key: string]: unknown;
}

interface MemoryFile {
  filename: string;
  entries?: number;
  size?: number;
  [key: string]: unknown;
}

type Tab = "stats" | "facts" | "graph";

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  sub?: string;
  accent?: string;
}

const MetricCard: React.FC<MetricCardProps> = ({ label, value, sub, accent }) => (
  <div className="dash-card" style={accent ? { borderTop: `3px solid ${accent}` } : {}}>
    <div className="dash-card-label">{label}</div>
    <div className="dash-card-value">{value}</div>
    {sub && <div className="dash-card-sub">{sub}</div>}
  </div>
);

export const MemoryView: React.FC<MemoryViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [activeTab, setActiveTab] = useState<Tab>("stats");

  // Stats state
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);

  // Facts state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [facts, setFacts] = useState<MemoryChunk[]>([]);
  const [factsLoading, setFactsLoading] = useState(false);
  const [factsError, setFactsError] = useState<string | null>(null);
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  // Graph/files state
  const [files, setFiles] = useState<MemoryFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState<string | null>(null);

  // --- Stats fetch (auto-refresh every 30s) ---
  const fetchStats = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/memory/stats`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setStats(await r.json());
      setStatsError(null);
    } catch (e) {
      setStatsError(String(e));
    } finally {
      setStatsLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchStats();
    const t = setInterval(fetchStats, 30000);
    return () => clearInterval(t);
  }, [fetchStats]);

  // --- Facts fetch ---
  const fetchFacts = useCallback(async (query: string) => {
    setFactsLoading(true);
    setExpandedIndex(null);
    try {
      const params = new URLSearchParams();
      if (query) params.set("query", query);
      const r = await fetch(`${base}/api/memory/content?${params}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      // API may return array or object with chunks/facts key
      if (Array.isArray(data)) {
        setFacts(data as MemoryChunk[]);
      } else if (data.chunks) {
        setFacts(data.chunks as MemoryChunk[]);
      } else if (data.facts) {
        setFacts(data.facts as MemoryChunk[]);
      } else {
        setFacts([]);
      }
      setFactsError(null);
    } catch (e) {
      setFactsError(String(e));
    } finally {
      setFactsLoading(false);
    }
  }, [base]);

  // Load facts on first switch to facts tab
  useEffect(() => {
    if (activeTab === "facts") {
      fetchFacts(searchQuery);
    }
  }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearchQuery(searchInput);
    fetchFacts(searchInput);
  };

  // --- Files fetch ---
  const fetchFiles = useCallback(async () => {
    setFilesLoading(true);
    try {
      const r = await fetch(`${base}/api/memory/files`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      if (Array.isArray(data)) {
        setFiles(data as MemoryFile[]);
      } else if (data.files) {
        setFiles(data.files as MemoryFile[]);
      } else {
        setFiles([]);
      }
      setFilesError(null);
    } catch (e) {
      setFilesError(String(e));
    } finally {
      setFilesLoading(false);
    }
  }, [base]);

  useEffect(() => {
    if (activeTab === "graph") {
      fetchFiles();
    }
  }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const tabs: { id: Tab; label: string }[] = [
    { id: "stats", label: "Stats" },
    { id: "facts", label: "Facts" },
    { id: "graph", label: "Graph" },
  ];

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Memory</h1>
        <div className="page-controls">
          {activeTab === "stats" && (
            <button className="btn-secondary" onClick={fetchStats}>
              Refresh
            </button>
          )}
          {activeTab === "graph" && (
            <button className="btn-secondary" onClick={fetchFiles}>
              Refresh
            </button>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div className="tab-bar">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={`tab-btn${activeTab === t.id ? " active" : ""}`}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* STATS TAB */}
      {activeTab === "stats" && (
        <>
          {statsLoading && (
            <div className="view-loading">
              <div className="app-loading-spinner" />
            </div>
          )}
          {statsError && <div className="page-error">{statsError}</div>}
          {!statsLoading && !statsError && stats && (
            <div className="dash-grid">
              <MetricCard
                label="Facts"
                value={stats.facts.toLocaleString()}
                accent="#2563eb"
                sub="stored memory facts"
              />
              <MetricCard
                label="KG Nodes"
                value={stats.kg_nodes.toLocaleString()}
                accent="#3b82f6"
                sub="knowledge graph nodes"
              />
              <MetricCard
                label="KG Edges"
                value={stats.kg_edges.toLocaleString()}
                accent="#a855f7"
                sub="knowledge graph edges"
              />
            </div>
          )}
          {!statsLoading && !statsError && !stats && (
            <div className="empty-state">No memory stats available</div>
          )}
        </>
      )}

      {/* FACTS TAB */}
      {activeTab === "facts" && (
        <div className="section-block">
          <form className="page-controls" onSubmit={handleSearch} style={{ marginBottom: "1rem" }}>
            <input
              className="filter-input"
              placeholder="Search memory..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              style={{ flex: 1 }}
            />
            <button className="btn-primary" type="submit">
              Search
            </button>
            {searchQuery && (
              <button
                className="btn-secondary"
                type="button"
                onClick={() => {
                  setSearchInput("");
                  setSearchQuery("");
                  fetchFacts("");
                }}
              >
                Clear
              </button>
            )}
          </form>

          {factsLoading && (
            <div className="view-loading">
              <div className="app-loading-spinner" />
            </div>
          )}
          {factsError && <div className="page-error">{factsError}</div>}

          {!factsLoading && !factsError && facts.length === 0 && (
            <div className="empty-state">
              {searchQuery ? `No results for "${searchQuery}"` : "No memory facts found"}
            </div>
          )}

          {!factsLoading && facts.length > 0 && (
            <div className="memory-fact-list">
              {facts.map((fact, i) => {
                const isExpanded = expandedIndex === i;
                const content = fact.content ?? "";
                const preview = content.length > 200 ? content.slice(0, 200) + "…" : content;
                const sourceFile = fact.source_file ?? "unknown";

                return (
                  <div key={i} className="memory-fact-card">
                    <div className="memory-fact-header">
                      <span className="action-badge">{sourceFile}</span>
                      {fact.score != null && (
                        <span className="dash-card-sub" style={{ marginLeft: "0.5rem" }}>
                          score: {(fact.score as number).toFixed(3)}
                        </span>
                      )}
                    </div>
                    <div className="memory-fact-content">
                      {isExpanded ? content : preview}
                    </div>
                    {content.length > 200 && (
                      <button
                        className="btn-secondary"
                        style={{ marginTop: "0.5rem", fontSize: "0.75rem", padding: "2px 8px" }}
                        onClick={() => setExpandedIndex(isExpanded ? null : i)}
                      >
                        {isExpanded ? "Collapse" : "Expand"}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* GRAPH TAB */}
      {activeTab === "graph" && (
        <>
          {/* Node/edge counts from stats */}
          {stats && (
            <div className="dash-grid" style={{ marginBottom: "1.5rem" }}>
              <MetricCard
                label="KG Nodes"
                value={stats.kg_nodes.toLocaleString()}
                accent="#3b82f6"
              />
              <MetricCard
                label="KG Edges"
                value={stats.kg_edges.toLocaleString()}
                accent="#a855f7"
              />
            </div>
          )}

          <div className="section-block">
            <div className="section-title">Memory Files</div>

            {filesLoading && (
              <div className="view-loading">
                <div className="app-loading-spinner" />
              </div>
            )}
            {filesError && <div className="page-error">{filesError}</div>}

            {!filesLoading && !filesError && files.length === 0 && (
              <div className="empty-state">No memory files found</div>
            )}

            {!filesLoading && files.length > 0 && (
              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Filename</th>
                      <th>Entries</th>
                      <th>Size</th>
                    </tr>
                  </thead>
                  <tbody>
                    {files.map((f, i) => (
                      <tr key={i}>
                        <td>
                          <code className="code-cell">
                            {typeof f === "string" ? f : (f.filename ?? String(f))}
                          </code>
                        </td>
                        <td>{f.entries != null ? f.entries : "—"}</td>
                        <td>
                          {f.size != null
                            ? f.size > 1024
                              ? `${(f.size / 1024).toFixed(1)} KB`
                              : `${f.size} B`
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default MemoryView;
