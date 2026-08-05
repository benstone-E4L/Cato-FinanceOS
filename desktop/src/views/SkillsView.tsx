/**
 * SkillsView — Live skills browser with SKILL.md content viewer/editor and toggle.
 */
import React, { useState, useEffect, useCallback } from "react";

interface SkillsViewProps {
  httpPort: number;
}

interface Skill {
  name: string;
  description: string;
  version: string;
  dir: string;
}

export const SkillsView: React.FC<SkillsViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState<string>("");
  const [originalContent, setOriginalContent] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [contentLoading, setContentLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const fetchSkills = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/skills`);
      setSkills(await r.json());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  const openSkill = async (dir: string) => {
    setSelected(dir);
    setContentLoading(true);
    try {
      const r = await fetch(`${base}/api/skills/${encodeURIComponent(dir)}/content`);
      const data = await r.json();
      setContent(data.content ?? "");
      setOriginalContent(data.content ?? "");
    } catch (e) {
      setContent(`Error loading: ${e}`);
    } finally {
      setContentLoading(false);
    }
  };

  const isDirty = content !== originalContent;

  const saveSkill = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const r = await fetch(`${base}/api/skills/${encodeURIComponent(selected)}/content`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      const d = await r.json();
      if (d.status === "ok") {
        setOriginalContent(content);
        setSaveMsg("Saved successfully");
      } else {
        setSaveMsg(`Error: ${d.error ?? "Save failed"}`);
      }
    } catch (e) {
      setSaveMsg(`Error: ${e}`);
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 3000);
    }
  };

  if (loading) return <div className="view-loading"><div className="app-loading-spinner" /></div>;

  return (
    <div className="page-view">
      <div className="page-header">
        <h1 className="page-title">Skills</h1>
        <button className="btn-secondary" onClick={fetchSkills}>Refresh</button>
      </div>
      {error && <div className="page-error">{error}</div>}

      <div className="skills-layout">
        {/* Left: skills list */}
        <div className="skills-list">
          {skills.length === 0 ? (
            <div className="empty-state">No skills installed</div>
          ) : (
            skills.map((s) => (
              <button
                key={s.dir}
                className={`skill-card ${selected === s.dir ? "skill-card-active" : ""}`}
                onClick={() => openSkill(s.dir)}
              >
                <div className="skill-card-name">{s.name}</div>
                {s.version && <div className="skill-card-version">v{s.version}</div>}
                <div className="skill-card-desc">{s.description || "No description"}</div>
              </button>
            ))
          )}
        </div>

        {/* Right: SKILL.md content */}
        {selected && (
          <div className="skills-detail">
            <div className="skills-detail-header">
              <span className="skills-detail-title">{selected}</span>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {saveMsg && (
                  <span style={{ fontSize: 12, color: saveMsg.startsWith("Error") ? "#ef4444" : "#2563eb" }}>
                    {saveMsg}
                  </span>
                )}
                <button
                  className="btn-primary btn-sm"
                  onClick={saveSkill}
                  disabled={!isDirty || saving}
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button className="btn-secondary-sm" onClick={() => { setSelected(null); setOriginalContent(""); }}>Close</button>
              </div>
            </div>
            {contentLoading ? (
              <div className="view-loading"><div className="app-loading-spinner" /></div>
            ) : (
              <textarea
                className="skill-editor"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                spellCheck={false}
                aria-label="SKILL.md content"
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default SkillsView;
