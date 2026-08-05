/**
 * ConfigView — Live config editor: form view + raw JSON, with PATCH save.
 */
import React, { useState, useEffect, useCallback } from "react";

interface ConfigViewProps {
  httpPort: number;
}

interface ConfigData {
  agent_name?: string;
  default_model?: string;
  swarmsync_enabled?: boolean;
  swarmsync_api_url?: string;
  session_cap?: number;
  monthly_cap?: number;
  log_level?: string;
  telegram_enabled?: boolean;
  telegram_bot_token?: string;
  conduit_enabled?: boolean;
  enabled_models?: string[];
  subagent_enabled?: boolean;
  subagent_coding_backend?: string;
  [key: string]: unknown;
}

export const ConfigView: React.FC<ConfigViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [config, setConfig] = useState<ConfigData>({});
  const [rawJson, setRawJson] = useState("");
  const [viewMode, setViewMode] = useState<"form" | "raw">("form");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const fetchConfig = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/config`);
      const data = await r.json();
      setConfig(data);
      setRawJson(JSON.stringify(data, null, 2));
    } catch (e) {
      setSaveMsg({ ok: false, text: `Load failed: ${e}` });
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const setField = (key: keyof ConfigData, value: unknown) => {
    const updated = { ...config, [key]: value };
    setConfig(updated);
    setRawJson(JSON.stringify(updated, null, 2));
  };

  const saveForm = async () => {
    setSaving(true);
    try {
      const r = await fetch(`${base}/api/config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      const data = await r.json();
      if (data.error) throw new Error(data.error);
      setConfig(data);
      setRawJson(JSON.stringify(data, null, 2));
      setSaveMsg({ ok: true, text: "Saved" });
    } catch (e) {
      setSaveMsg({ ok: false, text: String(e) });
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 3000);
    }
  };

  const saveRaw = async () => {
    let parsed: ConfigData;
    try {
      parsed = JSON.parse(rawJson);
    } catch {
      setSaveMsg({ ok: false, text: "Invalid JSON" });
      return;
    }
    setSaving(true);
    try {
      const r = await fetch(`${base}/api/config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed),
      });
      const data = await r.json();
      setConfig(data);
      setRawJson(JSON.stringify(data, null, 2));
      setSaveMsg({ ok: true, text: "Saved" });
    } catch (e) {
      setSaveMsg({ ok: false, text: String(e) });
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 3000);
    }
  };

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Config</h1>
        <div className="page-controls">
          <button
            className={`tab-btn ${viewMode === "form" ? "tab-btn-active" : ""}`}
            onClick={() => setViewMode("form")}
          >Form</button>
          <button
            className={`tab-btn ${viewMode === "raw" ? "tab-btn-active" : ""}`}
            onClick={() => setViewMode("raw")}
          >Raw JSON</button>
          <button className="btn-secondary" onClick={fetchConfig}>Reload</button>
        </div>
      </div>

      {saveMsg && (
        <div className={`save-banner ${saveMsg.ok ? "save-banner-ok" : "save-banner-err"}`}>
          {saveMsg.text}
        </div>
      )}

      {viewMode === "form" ? (
        <div className="config-form">
          <div className="section-title">Identity</div>
          <div className="form-row">
            <label>Agent Name</label>
            <input className="form-input" value={String(config.agent_name ?? "")}
              onChange={(e) => setField("agent_name", e.target.value)} />
          </div>
          <div className="form-row">
            <label>Default Model</label>
            <input className="form-input" value={String(config.default_model ?? "")}
              onChange={(e) => setField("default_model", e.target.value)} />
          </div>
          <div className="form-row">
            <label>Log Level</label>
            <select className="settings-select" value={String(config.log_level ?? "INFO")}
              onChange={(e) => setField("log_level", e.target.value)}>
              <option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option>
            </select>
          </div>

          <div className="section-title">Coding Agent</div>
          <div className="form-row">
            <label>Primary Backend</label>
            <select className="settings-select" value={String(config.subagent_coding_backend ?? "codex")}
              onChange={(e) => setField("subagent_coding_backend", e.target.value)}>
              <option value="codex">Codex (recommended — warm pool)</option>
              <option value="cursor">Cursor Agent</option>
              <option value="claude">Claude Code CLI</option>
              <option value="gemini">Gemini (degraded on this machine)</option>
            </select>
          </div>
          <div className="form-row">
            <label>Subagent Enabled</label>
            <input type="checkbox" checked={Boolean(config.subagent_enabled ?? true)}
              onChange={(e) => setField("subagent_enabled", e.target.checked)} />
          </div>

          <div className="section-title">Chat Model</div>
          <div className="form-row">
            <label>SwarmSync Enabled</label>
            <input type="checkbox" checked={Boolean(config.swarmsync_enabled)}
              onChange={(e) => setField("swarmsync_enabled", e.target.checked)} />
          </div>
          <div className="form-row">
            <label>SwarmSync API URL</label>
            <input className="form-input form-input-wide" value={String(config.swarmsync_api_url ?? "")}
              onChange={(e) => setField("swarmsync_api_url", e.target.value)} />
          </div>

          <div className="section-title">Budget Caps</div>
          <div className="form-row">
            <label>Session Cap ($)</label>
            <input type="number" className="form-input form-input-narrow"
              step="0.01" min="0"
              value={Number(config.session_cap ?? 1)}
              onChange={(e) => setField("session_cap", parseFloat(e.target.value))} />
          </div>
          <div className="form-row">
            <label>Monthly Cap ($)</label>
            <input type="number" className="form-input form-input-narrow"
              step="1" min="0"
              value={Number(config.monthly_cap ?? 20)}
              onChange={(e) => setField("monthly_cap", parseFloat(e.target.value))} />
          </div>

          <div className="section-title">Telegram</div>
          <div className="form-row">
            <label>Telegram Enabled</label>
            <input type="checkbox" checked={Boolean(config.telegram_enabled)}
              onChange={(e) => setField("telegram_enabled", e.target.checked)} />
          </div>
          <div className="form-row">
            <label>Bot Token</label>
            <input type="password" className="form-input form-input-wide"
              value={String(config.telegram_bot_token ?? "")}
              onChange={(e) => setField("telegram_bot_token", e.target.value)}
              placeholder="1234567890:ABC..." />
          </div>

          <div className="section-title">Conduit (Web Search)</div>
          <div className="form-row">
            <label>Conduit Enabled</label>
            <input type="checkbox" checked={Boolean(config.conduit_enabled)}
              onChange={(e) => setField("conduit_enabled", e.target.checked)} />
          </div>

          <div className="form-actions">
            <button className="btn-primary" onClick={saveForm} disabled={saving}>
              {saving ? "Saving…" : "Save Config"}
            </button>
          </div>
        </div>
      ) : (
        <div className="raw-editor-block">
          <textarea
            className="raw-editor"
            value={rawJson}
            onChange={(e) => setRawJson(e.target.value)}
            spellCheck={false}
            aria-label="Config JSON"
          />
          <div className="form-actions">
            <button className="btn-primary" onClick={saveRaw} disabled={saving}>
              {saving ? "Saving…" : "Save JSON"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ConfigView;
