/**
 * ModelSettings.tsx — Toggle panel for enabling/disabling LLM backends.
 *
 * Reads current config from GET /api/config, lets user toggle each model
 * on/off and set a subagent backend, then PATCHes /api/config to persist.
 */

import React, { useEffect, useState, useCallback } from "react";

const ALL_MODELS = ["claude", "codex", "gemini", "cursor"] as const;
type Model = (typeof ALL_MODELS)[number];

const MODEL_META: Record<Model, { label: string; color: string; desc: string }> = {
  claude: { label: "Claude",  color: "#3B82F6", desc: "Anthropic · Claude Code CLI" },
  codex:  { label: "Codex",   color: "#F59E0B", desc: "OpenAI · Codex CLI" },
  gemini: { label: "Gemini",  color: "#A855F7", desc: "Google · Gemini CLI" },
  cursor: { label: "Cursor",  color: "#22D3EE", desc: "Cursor · cursor-agent CLI (--print mode)" },
};

interface Config {
  enabled_models: Model[];
  subagent_enabled: boolean;
  subagent_coding_backend: Model;
}

interface ModelSettingsProps {
  apiBase: string;
  onClose?: () => void;
}

export const ModelSettings: React.FC<ModelSettingsProps> = ({ apiBase, onClose }) => {
  const [config, setConfig] = useState<Config>({
    enabled_models: ["claude", "codex", "gemini"],
    subagent_enabled: false,
    subagent_coding_backend: "codex",
  });
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "saved" | "error">("idle");

  useEffect(() => {
    fetch(`${apiBase}/api/config`)
      .then((r) => r.json())
      .then((data: Config) => setConfig(data))
      .catch(() => {});
  }, [apiBase]);

  const toggleModel = useCallback((model: Model) => {
    setConfig((prev) => {
      const isOn = prev.enabled_models.includes(model);
      // Must keep at least one model enabled
      if (isOn && prev.enabled_models.length === 1) return prev;
      const next = isOn
        ? prev.enabled_models.filter((m) => m !== model)
        : [...prev.enabled_models, model];
      return { ...prev, enabled_models: next };
    });
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    setStatus("idle");
    try {
      const res = await fetch(`${apiBase}/api/config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      if (!res.ok) throw new Error(await res.text());
      setStatus("saved");
      setTimeout(() => setStatus("idle"), 2000);
    } catch {
      setStatus("error");
    } finally {
      setSaving(false);
    }
  }, [apiBase, config]);

  return (
    <div className="model-settings-panel">
      <div className="settings-header">
        <span className="settings-title">Model Toggles</span>
        {onClose && (
          <button className="settings-close" onClick={onClose} aria-label="Close settings">
            ✕
          </button>
        )}
      </div>

      <div className="settings-section-label">Active backends</div>
      <div className="settings-model-list">
        {ALL_MODELS.map((model) => {
          const meta = MODEL_META[model];
          const enabled = config.enabled_models.includes(model);
          return (
            <div key={model} className={`settings-model-row ${enabled ? "on" : "off"}`}>
              <div className="settings-model-info">
                <span className="settings-model-dot" style={{ background: meta.color }} />
                <div>
                  <span className="settings-model-name">{meta.label}</span>
                  <span className="settings-model-desc">{meta.desc}</span>
                </div>
              </div>
              <button
                className={`settings-toggle ${enabled ? "toggle-on" : "toggle-off"}`}
                onClick={() => toggleModel(model)}
                aria-pressed={enabled}
                aria-label={`${enabled ? "Disable" : "Enable"} ${meta.label}`}
              >
                <span className="toggle-knob" />
              </button>
            </div>
          );
        })}
      </div>

      <div className="settings-section-label" style={{ marginTop: 16 }}>Subagent routing</div>
      <div className="settings-subagent-row">
        <label className="settings-subagent-label">
          <input
            type="checkbox"
            checked={config.subagent_enabled}
            onChange={(e) => setConfig((p) => ({ ...p, subagent_enabled: e.target.checked }))}
          />
          <span>Route coding tasks to a single backend</span>
        </label>
      </div>
      {config.subagent_enabled && (
        <div className="settings-backend-select">
          <label className="settings-section-label">Backend</label>
          <select
            value={config.subagent_coding_backend}
            onChange={(e) =>
              setConfig((p) => ({ ...p, subagent_coding_backend: e.target.value as Model }))
            }
            className="settings-select"
          >
            {ALL_MODELS.map((m) => (
              <option key={m} value={m}>
                {MODEL_META[m].label}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="settings-footer">
        <button className="settings-save-btn" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        {status === "saved" && <span className="settings-status ok">Saved</span>}
        {status === "error" && <span className="settings-status err">Save failed</span>}
      </div>
    </div>
  );
};
