/**
 * AlertsView — Budget alert threshold configuration.
 */
import React, { useState, useEffect, useCallback } from "react";

interface AlertsViewProps {
  httpPort: number;
}

export const AlertsView: React.FC<AlertsViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [warnThreshold, setWarnThreshold] = useState(80);

  const fetchConfig = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/config`);
      const data = await r.json();
      setConfig(data);
      if (typeof data.budget_warn_pct === "number") setWarnThreshold(data.budget_warn_pct);
    } catch {
      // config endpoint may not have this field yet
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const save = async () => {
    setSaving(true);
    try {
      await fetch(`${base}/api/config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ budget_warn_pct: warnThreshold }),
      });
      setSaveMsg("Saved");
      setTimeout(() => setSaveMsg(""), 2000);
    } catch (e) {
      setSaveMsg(`Error: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Alerts</h1>
      </div>

      <div className="section-block">
        <div className="section-title">Budget Alert Threshold</div>
        <div className="section-desc">
          Cato will show a warning when this percentage of your monthly budget is used.
        </div>
        <div className="form-row">
          <label>Warn at</label>
          <input
            type="number"
            className="form-input form-input-narrow"
            min={1}
            max={99}
            value={warnThreshold}
            onChange={(e) => setWarnThreshold(Number(e.target.value))}
          />
          <span className="form-hint">% of monthly cap used</span>
        </div>
        <button className="btn-primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        {saveMsg && <span className="save-msg">{saveMsg}</span>}
      </div>

      <div className="section-block">
        <div className="section-title">Current Config</div>
        <pre className="raw-json">{JSON.stringify(config, null, 2)}</pre>
      </div>
    </div>
  );
};

export default AlertsView;
