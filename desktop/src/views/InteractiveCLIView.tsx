/**
 * InteractiveCLIView.tsx — PTY-backed interactive CLI sessions (Claude, Codex, Gemini).
 * Tabs per CLI; Start/Kill/Clear; terminal pane connected via WebSocket to daemon.
 */

import React, { useState, useCallback } from "react";

import { TerminalPane } from "../components/TerminalPane";

const CLIS = ["claude", "codex", "gemini"] as const;
const CLI_LABELS: Record<string, string> = {
  claude: "Claude",
  codex: "Codex",
  gemini: "Gemini",
};

interface InteractiveCLIViewProps {
  httpPort: number;
}

export const InteractiveCLIView: React.FC<InteractiveCLIViewProps> = ({ httpPort }) => {
  const [activeCli, setActiveCli] = useState<(typeof CLIS)[number]>("claude");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionCli, setSessionCli] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const apiBase = `http://127.0.0.1:${httpPort}`;
  const wsBase = `127.0.0.1:${httpPort}`;

  const startSession = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/api/pty/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cli: activeCli }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.error || `Failed to start session (${res.status})`);
        return;
      }
      setSessionId(data.session_id ?? null);
      setSessionCli(data.cli ?? activeCli);
    } finally {
      setLoading(false);
    }
  }, [activeCli, apiBase]);

  const killSession = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    try {
      await fetch(`${apiBase}/api/pty/sessions/${sessionId}`, { method: "DELETE" });
    } catch (e) {
      setError(String(e));
    }
    setSessionId(null);
    setSessionCli(null);
  }, [sessionId, apiBase]);

  const clearTerminal = useCallback(() => {
    setSessionId(null);
    setSessionCli(null);
    setError(null);
  }, []);

  return (
    <div className="interactive-cli-view" style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="interactive-cli-header" style={{ padding: "12px 16px", borderBottom: "1px solid var(--border, #333)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div role="tablist" style={{ display: "flex", gap: 4 }}>
            {CLIS.map((cli) => (
              <button
                key={cli}
                role="tab"
                aria-selected={activeCli === cli}
                className={activeCli === cli ? "active" : ""}
                onClick={() => setActiveCli(cli)}
                style={{
                  padding: "8px 14px",
                  border: "1px solid #555",
                  borderRadius: 6,
                  background: activeCli === cli ? "#333" : "transparent",
                  color: "#eee",
                  cursor: "pointer",
                }}
              >
                {CLI_LABELS[cli] ?? cli}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {sessionCli && (
              <span style={{ fontSize: 13, color: "#94a3b8" }}>
                Session: {CLI_LABELS[sessionCli] ?? sessionCli}
              </span>
            )}
            <button
              onClick={startSession}
              disabled={loading || sessionId != null}
              style={{
                padding: "8px 14px",
                borderRadius: 6,
                border: "none",
                background: "#0d9488",
                color: "#fff",
                cursor: loading ? "not-allowed" : "pointer",
              }}
            >
              {loading ? "Starting…" : "Start Session"}
            </button>
            <button
              onClick={killSession}
              disabled={!sessionId}
              style={{
                padding: "8px 14px",
                borderRadius: 6,
                border: "1px solid #ef4444",
                background: "transparent",
                color: "#ef4444",
                cursor: sessionId ? "pointer" : "not-allowed",
              }}
            >
              Kill
            </button>
            <button
              onClick={clearTerminal}
              style={{
                padding: "8px 14px",
                borderRadius: 6,
                border: "1px solid #666",
                background: "transparent",
                color: "#aaa",
                cursor: "pointer",
              }}
            >
              Clear
            </button>
          </div>
        </div>
        {error && (
          <p style={{ color: "#f87171", fontSize: 13, marginTop: 8 }} role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="interactive-cli-terminal" style={{ flex: 1, minHeight: 0, padding: 8 }}>
        <TerminalPane
          sessionId={sessionId}
          wsBase={wsBase}
          className="terminal-pane-full"
        />
      </div>
    </div>
  );
};

export default InteractiveCLIView;
