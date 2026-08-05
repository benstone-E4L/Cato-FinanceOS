/**
 * IdentityView — Edit Cato's workspace identity files (SOUL.md, IDENTITY.md, etc.)
 * These files are loaded into every prompt to define who Cato is.
 */
import React, { useState, useEffect, useCallback } from "react";

interface IdentityViewProps {
  httpPort: number;
}

const FILE_DESCRIPTIONS: Record<string, string> = {
  "SOUL.md":     "Core identity: who Cato is, values, personality. CRITICAL — loaded into every prompt.",
  "IDENTITY.md": "Technical self-knowledge: ports, LLMs, capabilities, views.",
  "USER.md":     "Who the user is, preferences, communication style.",
  "AGENTS.md":   "Available CLI coding backends and their status.",
  "TOOLS.md":    "Skill notes and environment-specific tool configuration.",
  "HEARTBEAT.md":"Heartbeat / status template (auto-generated).",
};

const DEFAULT_FILES = ["SOUL.md", "IDENTITY.md", "USER.md", "AGENTS.md"];

export const IdentityView: React.FC<IdentityViewProps> = ({ httpPort }) => {
  const base = `http://127.0.0.1:${httpPort}`;
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("SOUL.md");
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const fetchFiles = useCallback(async () => {
    try {
      const r = await fetch(`${base}/api/workspace/files`);
      const data = await r.json() as string[];
      // Merge default files even if not yet on disk
      const all = Array.from(new Set([...DEFAULT_FILES, ...data]));
      setFiles(all);
    } catch {
      setFiles(DEFAULT_FILES);
    }
  }, [base]);

  const fetchFile = useCallback(async (name: string) => {
    setLoading(true);
    try {
      const r = await fetch(`${base}/api/workspace/file?name=${encodeURIComponent(name)}`);
      const data = await r.json() as { name: string; content: string };
      const fileContent = data.content ?? "";
      setContent(fileContent);
      setOriginalContent(fileContent);
    } catch {
      setContent("");
      setOriginalContent("");
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  useEffect(() => {
    fetchFile(selected);
  }, [selected, fetchFile]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await fetch(`${base}/api/workspace/file`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: selected, content }),
      });
      const d = await r.json() as { status?: string; error?: string };
      if (d.status === "ok") {
        setOriginalContent(content);
        setSaveMsg({ ok: true, text: "Saved — will take effect on next prompt" });
      } else {
        setSaveMsg({ ok: false, text: d.error ?? "Save failed" });
      }
    } catch (e) {
      setSaveMsg({ ok: false, text: String(e) });
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 4000);
    }
  };

  const isDirty = content !== originalContent;

  return (
    <div className="page-view identity-view">
      <div className="page-header">
        <h1 className="page-title">Identity Files</h1>
        <div className="page-controls">
          <button className="btn-secondary" onClick={() => fetchFile(selected)}>Reload</button>
          <button
            className="btn-primary"
            onClick={save}
            disabled={saving || !isDirty}
            title={!isDirty ? "No unsaved changes" : "Save changes"}
          >
            {saving ? "Saving…" : isDirty ? "Save" : "Saved"}
          </button>
        </div>
      </div>

      {saveMsg && (
        <div className={`save-banner ${saveMsg.ok ? "save-banner-ok" : "save-banner-err"}`}>
          {saveMsg.text}
        </div>
      )}

      <div className="info-note" style={{ marginBottom: 0 }}>
        These files are loaded into Cato's system prompt on every conversation.
        Changes take effect immediately on the next message.
      </div>

      <div className="identity-layout">
        {/* File list sidebar */}
        <aside className="identity-file-list">
          {files.map((f) => (
            <button
              key={f}
              className={`identity-file-btn ${selected === f ? "active" : ""}`}
              onClick={() => {
                if (isDirty && !window.confirm("Discard unsaved changes?")) return;
                setSelected(f);
              }}
            >
              <span className="identity-file-name">{f}</span>
              {selected === f && isDirty && (
                <span className="identity-dirty-dot" title="Unsaved changes" />
              )}
            </button>
          ))}
        </aside>

        {/* Editor */}
        <div className="identity-editor-wrap">
          <div className="identity-file-desc">
            {FILE_DESCRIPTIONS[selected] ?? "Workspace identity file."}
          </div>
          {loading ? (
            <div className="view-loading"><div className="app-loading-spinner" /></div>
          ) : (
            <textarea
              className="identity-editor"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              spellCheck={false}
              aria-label={`Edit ${selected}`}
            />
          )}
        </div>
      </div>
    </div>
  );
};

export default IdentityView;
