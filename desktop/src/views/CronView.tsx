/**
 * CronView — Live cron job list with enable/disable, manual trigger, create, delete.
 */
import React, { useState, useEffect, useCallback } from "react";

interface CronViewProps {
  httpPort: number;
}

interface CronJob {
  name: string;
  cron: string;
  skill: string;
  args: Record<string, unknown>;
  budget_cap: number;
  enabled: boolean;
  created_at: number;
}

function humanCron(expr: string): string {
  // Simple human-readable preview for common patterns
  const map: Record<string, string> = {
    "* * * * *":    "Every minute",
    "0 * * * *":    "Every hour",
    "0 9 * * *":    "Daily at 9am",
    "0 9 * * 1-5":  "Weekdays at 9am",
    "0 0 * * *":    "Daily at midnight",
    "0 0 * * 0":    "Weekly on Sunday",
  };
  return map[expr] ?? expr;
}

export const CronView: React.FC<CronViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newCron, setNewCron] = useState("0 9 * * *");
  const [newSkill, setNewSkill] = useState("");
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState<string | null>(null);

  const fetchJobs = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/cron/jobs`);
      setJobs(await r.json());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const toggle = async (name: string, enabled: boolean) => {
    await fetch(`${base}/api/cron/jobs/${encodeURIComponent(name)}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    await fetchJobs();
  };

  const deleteJob = async (name: string) => {
    await fetch(`${base}/api/cron/jobs/${encodeURIComponent(name)}`, { method: "DELETE" });
    await fetchJobs();
  };

  const triggerNow = async (name: string) => {
    setTriggering(name);
    try {
      await fetch(`${base}/api/cron/jobs/${encodeURIComponent(name)}/run`, { method: "POST" });
    } catch (e) {
      setError(String(e));
    } finally {
      setTriggering(null);
    }
  };

  const createJob = async () => {
    if (!newName || !newCron || !newSkill) return;
    setSaving(true);
    try {
      await fetch(`${base}/api/cron/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName, cron: newCron, skill: newSkill, enabled: true }),
      });
      setShowCreate(false);
      setNewName(""); setNewCron("0 9 * * *"); setNewSkill("");
      await fetchJobs();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Cron Jobs</h1>
        <div className="page-controls">
          <button className="btn-secondary" onClick={fetchJobs}>Refresh</button>
          <button className="btn-primary" onClick={() => setShowCreate(!showCreate)}>
            {showCreate ? "Cancel" : "+ New Job"}
          </button>
        </div>
      </div>
      {error && <div className="page-error">{error}</div>}

      {showCreate && (
        <div className="create-form">
          <div className="create-form-title">New Cron Job</div>
          <div className="form-row">
            <label>Name</label>
            <input className="form-input" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="my-job" />
          </div>
          <div className="form-row">
            <label>Cron Expression</label>
            <input className="form-input" value={newCron} onChange={(e) => setNewCron(e.target.value)} placeholder="0 9 * * *" />
            <span className="form-hint">{humanCron(newCron)}</span>
          </div>
          <div className="form-row">
            <label>Skill</label>
            <input className="form-input" value={newSkill} onChange={(e) => setNewSkill(e.target.value)} placeholder="skill-name" />
          </div>
          <button className="btn-primary" onClick={createJob} disabled={saving || !newName || !newSkill}>
            {saving ? "Saving…" : "Create"}
          </button>
        </div>
      )}

      {jobs.length === 0 ? (
        <div className="empty-state">No cron jobs configured</div>
      ) : (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Schedule</th>
                <th>Skill</th>
                <th>Budget Cap</th>
                <th>Enabled</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.name}>
                  <td><strong>{j.name}</strong></td>
                  <td>
                    <code className="code-cell">{j.cron}</code>
                    <div className="cron-human">{humanCron(j.cron)}</div>
                  </td>
                  <td>{j.skill}</td>
                  <td>¢{j.budget_cap}</td>
                  <td>
                    <button
                      className={`settings-toggle ${j.enabled ? "toggle-on" : "toggle-off"}`}
                      onClick={() => toggle(j.name, !j.enabled)}
                      aria-label={j.enabled ? "Disable" : "Enable"}
                    >
                      <span className="toggle-knob" />
                    </button>
                  </td>
                  <td className="action-cell">
                    <button
                      className="btn-secondary-sm"
                      onClick={() => triggerNow(j.name)}
                      disabled={triggering === j.name}
                    >
                      {triggering === j.name ? "Running…" : "Run Now"}
                    </button>
                    <button className="btn-danger-sm" onClick={() => deleteJob(j.name)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default CronView;
