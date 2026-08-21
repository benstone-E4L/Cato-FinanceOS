/**
 * AuthKeysView — model/integration credentials, CLI status, and vault management.
 * All data is live from daemon APIs.
 */
import React, { useState, useEffect, useCallback } from "react";

interface AuthKeysViewProps {
  httpPort: number;
}

// Which vault keys go here and what they're for
const VAULT_KEY_META: Record<string, string> = {
  ANTHROPIC_API_KEY:   "Anthropic API key — Cato's direct model-execution credential",
  OPENROUTER_API_KEY:  "OpenRouter API key — retained for non-production/legacy integrations",
  SWARMSYNC_API_KEY:   "SwarmSync key — optional non-model integrations only",
  TELEGRAM_BOT_TOKEN:  "Telegram bot token — Cato's Telegram interface",
  brave_api_key:       "Brave web search",
  exa_api_key:         "Exa semantic search",
  tavily_api_key:      "Tavily web search",
};

// CLI backend metadata (labels, login commands). Status is fetched live.
const CLI_META: Record<string, { label: string; loginCmd: string | null }> = {
  claude: { label: "Claude Code", loginCmd: "claude login" },
  codex:  { label: "Codex",       loginCmd: null },
  gemini: { label: "Gemini",      loginCmd: "gemini auth login" },
  cursor: { label: "Cursor Agent", loginCmd: null },
};

interface CliToolStatus {
  installed: boolean;
  logged_in: boolean;
  version: string;
  version_check_ok?: boolean;
}

export const AuthKeysView: React.FC<AuthKeysViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [vaultKeys, setVaultKeys] = useState<string[]>([]);
  const [cliStatus, setCliStatus] = useState<Record<string, CliToolStatus>>({});
  const [restartingCli, setRestartingCli] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Direct Anthropic model credential
  const [anthropicKey, setAnthropicKey] = useState("");
  const [anthropicSaving, setAnthropicSaving] = useState(false);
  const [anthropicMsg, setAnthropicMsg] = useState("");
  // SwarmSync key entry
  const [ssKey, setSsKey] = useState("");
  const [ssSaving, setSsSaving] = useState(false);
  const [ssMsg, setSsMsg] = useState("");

  // Add vault key form
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState("");
  const [addingSaving, setAddingSaving] = useState(false);
  const [addMsg, setAddMsg] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [kr, cs] = await Promise.all([
        fetch(`${base}/api/vault/keys`).then((r) => r.json()),
        fetch(`${base}/api/cli/status`).then((r) => r.json()).catch(() => ({})),
      ]);
      setVaultKeys(kr as string[]);
      setCliStatus(cs as Record<string, CliToolStatus>);
    } catch {
      // silently ignore; show whatever we have
    } finally {
      setLoading(false);
    }
  }, [base]);

  const restartCli = async (name: string) => {
    setRestartingCli(name);
    try {
      await fetch(`${base}/api/cli/${name}/restart`, { method: "POST" });
      // Refresh status after restart
      setTimeout(() => fetchData(), 1500);
    } catch {
      // ignore
    } finally {
      setTimeout(() => setRestartingCli(null), 2000);
    }
  };

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const saveVaultKey = async (
    vaultKey: string, value: string,
    setMsg: (m: string) => void, setSaving: (s: boolean) => void, clearVal: () => void,
  ) => {
    if (!value.trim()) return;
    setSaving(true);
    try {
      const r = await fetch(`${base}/api/vault/set`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: vaultKey, value: value.trim() }),
      });
      const d = await r.json();
      if (d.status === "ok") {
        setMsg("Saved");
        clearVal();
        await fetchData();
      } else {
        setMsg(`Error: ${d.message}`);
      }
    } catch (e) {
      setMsg(String(e));
    } finally {
      setSaving(false);
      setTimeout(() => setMsg(""), 3000);
    }
  };

  const addKey = async () => {
    if (!newKeyName.trim() || !newKeyValue.trim()) return;
    setAddingSaving(true);
    try {
      await fetch(`${base}/api/vault/set`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: newKeyName.trim(), value: newKeyValue.trim() }),
      });
      setNewKeyName(""); setNewKeyValue("");
      setAddMsg("Key added");
      await fetchData();
    } catch (e) {
      setAddMsg(String(e));
    } finally {
      setAddingSaving(false);
      setTimeout(() => setAddMsg(""), 3000);
    }
  };

  const deleteKey = async (key: string) => {
    try {
      const r = await fetch(`${base}/api/vault/delete`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      });
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        console.error("Delete key failed:", data.message || r.statusText);
      }
    } catch (e) {
      console.error("Delete key error:", e);
    }
    await fetchData();
  };

  const hasAnthropic   = vaultKeys.includes("ANTHROPIC_API_KEY");
  const hasSwarmSync   = vaultKeys.includes("SWARMSYNC_API_KEY");

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Auth & Keys</h1>
        <button className="btn-secondary" onClick={fetchData}>Refresh</button>
      </div>

      <div className="info-note">
        Chat and compaction call <strong>Anthropic directly</strong> under deterministic policy.
        Other stored provider keys do not participate in model execution.
        Coding agents (Codex, Cursor) use local sessions — no API keys required.
      </div>

      {/* Anthropic Key */}
      <div className="section-block">
        <div className="section-title">
          Anthropic API Key
          {hasAnthropic
            ? <span className="badge-blue">Configured</span>
            : <span className="badge-red">Missing</span>}
        </div>
        <div className="section-desc">
          The only credential used by Cato's model-execution path. Stored in the encrypted vault.
        </div>
        <div className="form-row">
          <input
            type="password"
            className="form-input form-input-wide"
            placeholder="Anthropic API key"
            value={anthropicKey}
            onChange={(e) => setAnthropicKey(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && saveVaultKey("ANTHROPIC_API_KEY", anthropicKey, setAnthropicMsg, setAnthropicSaving, () => setAnthropicKey(""))}
          />
          <button
            className="btn-primary"
            onClick={() => saveVaultKey("ANTHROPIC_API_KEY", anthropicKey, setAnthropicMsg, setAnthropicSaving, () => setAnthropicKey(""))}
            disabled={anthropicSaving || !anthropicKey.trim()}
          >
            {anthropicSaving ? "Saving…" : "Save"}
          </button>
          {anthropicMsg && <span className="save-msg">{anthropicMsg}</span>}
        </div>
        <div className="form-row" style={{ marginTop: 8 }}>
          <label>Selection policy</label>
          <code className="code-cell">cato/model_policy.py (direct Anthropic)</code>
        </div>
      </div>

      {/* SwarmSync Key */}
      <div className="section-block">
        <div className="section-title">
          SwarmSync Key
          {hasSwarmSync
            ? <span className="badge-blue">Configured</span>
            : <span className="badge-gray">Optional</span>}
        </div>
        <div className="section-desc">
          Optional credential for Genesis, the integration registry, and site-services bridge.
          It is never used for chat or model selection.
        </div>
        <div className="form-row">
          <input
            type="password"
            className="form-input form-input-wide"
            placeholder="sk-ss-..."
            value={ssKey}
            onChange={(e) => setSsKey(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && saveVaultKey("SWARMSYNC_API_KEY", ssKey, setSsMsg, setSsSaving, () => setSsKey(""))}
          />
          <button
            className="btn-primary"
            onClick={() => saveVaultKey("SWARMSYNC_API_KEY", ssKey, setSsMsg, setSsSaving, () => setSsKey(""))}
            disabled={ssSaving || !ssKey.trim()}
          >
            {ssSaving ? "Saving…" : "Save"}
          </button>
          {ssMsg && <span className="save-msg">{ssMsg}</span>}
        </div>
      </div>

      {/* CLI backend status — live from /api/cli/status */}
      <div className="section-block">
        <div className="section-title">Coding Agent Backends</div>
        <div className="section-desc">
          Coding tasks dispatch to these CLI backends. Status is live from the daemon.
        </div>
        <div className="cli-status-list">
          {Object.entries(CLI_META).map(([id, meta]) => {
            const tool = cliStatus[id];
            const isWarm = tool?.installed && tool?.logged_in;
            const statusLabel = !tool ? "unknown" : isWarm ? "Working" : tool.installed ? "Cold" : "Not Installed";
            const badgeClass = isWarm ? "badge-blue" : tool?.installed ? "badge-yellow" : "badge-red";

            return (
              <div key={id} className="cli-status-row">
                <div className="cli-status-info">
                  <span className="cli-label">{meta.label}</span>
                  <span
                    className={badgeClass}
                    style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8, fontWeight: 700 }}
                  >
                    {statusLabel}
                  </span>
                  {tool?.version && (
                    <span style={{ fontSize: 10, color: "var(--text-muted, #888)", marginLeft: 6 }}>
                      {tool.version}
                    </span>
                  )}
                </div>
                <div className="cli-status-actions">
                  {meta.loginCmd && (
                    <code className="cli-cmd" style={{ marginTop: 4 }}>{meta.loginCmd}</code>
                  )}
                  <button
                    className="btn-secondary"
                    style={{ fontSize: 11, padding: "2px 8px", marginLeft: 8 }}
                    onClick={() => restartCli(id)}
                    disabled={restartingCli === id}
                  >
                    {restartingCli === id ? "Restarting..." : "Restart"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Vault keys */}
      <div className="section-block">
        <div className="section-title">Vault Keys</div>
        <div className="section-desc">
          Stored keys (values are encrypted — only names are shown).
        </div>
        <div className="vault-key-list">
          {Object.entries(VAULT_KEY_META).map(([key, desc]) => {
            const present = vaultKeys.includes(key);
            return (
              <div key={key} className="vault-key-row">
                <span className={`status-dot ${present ? "status-ready" : "status-error"}`} />
                <div className="vault-key-info">
                  <code className="vault-key-name">{key}</code>
                  <span className="vault-key-desc">{desc}</span>
                </div>
                {present && (
                  <button className="btn-danger-sm" onClick={() => deleteKey(key)}>Delete</button>
                )}
              </div>
            );
          })}

          {/* Any other vault keys not in the predefined list */}
          {vaultKeys
            .filter((k) => !(k in VAULT_KEY_META))
            .map((key) => (
              <div key={key} className="vault-key-row">
                <span className="status-dot status-ready" />
                <div className="vault-key-info">
                  <code className="vault-key-name">{key}</code>
                  <span className="vault-key-desc">Custom key</span>
                </div>
                <button className="btn-danger-sm" onClick={() => deleteKey(key)}>Delete</button>
              </div>
            ))}
        </div>

        {/* Add key form */}
        <div className="add-key-form">
          <div className="form-row">
            <input
              className="form-input"
              placeholder="KEY_NAME"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
            />
            <input
              type="password"
              className="form-input form-input-wide"
              placeholder="value"
              value={newKeyValue}
              onChange={(e) => setNewKeyValue(e.target.value)}
            />
            <button
              className="btn-secondary"
              onClick={addKey}
              disabled={addingSaving || !newKeyName.trim() || !newKeyValue.trim()}
            >
              {addingSaving ? "Adding…" : "Add Key"}
            </button>
          </div>
          {addMsg && <span className="save-msg">{addMsg}</span>}
        </div>
      </div>
    </div>
  );
};

export default AuthKeysView;
