/**
 * CodingAgentPage.tsx — Main route component for /coding-agent/{task_id}.
 *
 * Layout:
 *   Desktop  (≥1024px): Left sidebar | TalkPage | Right sidebar
 *   Tablet   (640-1023px): Left + Main | Right below
 *   Mobile   (<640px): Stacked (left → main → right hidden unless complete)
 *
 * States:
 *   - Loading:    Spinners for 3 models
 *   - In Progress: Messages arrive in real-time
 *   - Complete:    Synthesis shown, right sidebar with alternatives
 *   - Error:       Error banner with retry option
 */

import React, { useCallback, useState } from "react";
import { TalkPage } from "../components/TalkPage";
import { TaskInput } from "../components/TaskInput";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { useTalkPageStream } from "../hooks/useTalkPageStream";
import { useLocalStorage } from "../hooks/useLocalStorage";

// ── Types ──────────────────────────────────────────────────────────────── //

export interface CodingAgentPageProps {
  taskId: string;
  /** Task description (if known at render time, e.g. from SSR) */
  initialTask?: string;
  /** Override WebSocket host */
  wsBase?: string;
}

interface RecentTask {
  taskId: string;
  task: string;
  createdAt: number;
}

// ── Constants ─────────────────────────────────────────────────────────── //

const MODELS = ["claude", "codex", "gemini"] as const;

const MODEL_CONFIG: Record<string, { label: string; color: string }> = {
  claude: { label: "Claude",  color: "#3B82F6" },
  codex:  { label: "Codex",   color: "#F59E0B" },
  gemini: { label: "Gemini",  color: "#A855F7" },
};

const MAX_RECENT_TASKS = 10;

// ── Sub-components ─────────────────────────────────────────────────────── //

interface RightSidebarProps {
  synthesis: import("../components/TalkPage").SynthesisResult | null;
  isLoading: boolean;
  onCopy: (text: string) => void;
  onSave: (text: string, model: string) => void;
  onShare: (taskId: string) => void;
  taskId: string;
  copiedState: boolean;
}

const RightSidebar: React.FC<RightSidebarProps> = ({
  synthesis,
  isLoading,
  onCopy,
  onSave,
  onShare,
  taskId,
  copiedState,
}) => {
  if (isLoading && !synthesis) {
    return (
      <aside className="sidebar-right" aria-label="Results panel" data-testid="right-sidebar">
        <div className="sidebar-header-section">
          <span>Results</span>
        </div>
        <div className="sidebar-content">
          <p className="text-xs text-gray-500 text-center mt-4" aria-live="polite">
            Awaiting responses...
          </p>
        </div>
      </aside>
    );
  }

  if (!synthesis) return null;

  const { primary, runners_up } = synthesis;
  const modelCfg = MODEL_CONFIG[primary.model.toLowerCase()] ?? { label: primary.model, color: "#94a3b8" };

  return (
    <aside
      className="sidebar-right"
      aria-label="Synthesis results"
      data-testid="right-sidebar"
    >
      <div className="sidebar-header-section">
        <span>Results</span>
        <span className="text-green-400 text-xs" aria-live="polite">Complete</span>
      </div>

      <div className="sidebar-content">
        {/* Primary result */}
        <div className="synthesis-sidebar-result" data-testid="primary-result">
          <div className="synthesis-label">
            <span className="synthesis-label-icon" aria-hidden="true">★</span>
            Primary Answer
          </div>
          <div className="synthesis-model" style={{ color: modelCfg.color }}>
            {modelCfg.label}
            <ConfidenceBadge confidence={primary.confidence} />
          </div>
          <p className="synthesis-text" style={{ maxHeight: "200px", overflowY: "auto" }}>
            {primary.response}
          </p>

          {/* Action buttons */}
          <div className="synthesis-actions">
            <button
              className={`action-btn ${copiedState ? "copied" : ""}`}
              onClick={() => onCopy(primary.response)}
              aria-label="Copy primary answer to clipboard"
              data-testid="copy-primary-btn"
            >
              {copiedState ? "✓ Copied" : "Copy"}
            </button>
            <button
              className="action-btn"
              onClick={() => onSave(primary.response, primary.model)}
              aria-label="Save primary answer"
              data-testid="save-btn"
            >
              Save
            </button>
            <button
              className="action-btn"
              onClick={() => onShare(taskId)}
              aria-label="Share this task result"
              data-testid="share-btn"
            >
              Share
            </button>
          </div>
        </div>

        {/* Runners-up */}
        {runners_up.length > 0 && (
          <div>
            <div className="sidebar-header-section" style={{ border: "none", padding: "10px 0 6px" }}>
              <span>Alternatives</span>
            </div>
            {runners_up.map((alt, idx) => {
              const altCfg = MODEL_CONFIG[alt.model.toLowerCase()] ?? { label: alt.model, color: "#94a3b8" };
              return (
                <div
                  key={idx}
                  className="synthesis-sidebar-result mb-2"
                  data-testid={`runner-up-${idx}`}
                >
                  <div className="synthesis-model" style={{ color: altCfg.color }}>
                    {altCfg.label}
                    <ConfidenceBadge confidence={alt.confidence} />
                  </div>
                  <p
                    className="synthesis-text"
                    style={{ maxHeight: "120px", overflowY: "auto", fontSize: "12px" }}
                  >
                    {alt.response}
                  </p>
                  <button
                    className="action-btn mt-2"
                    onClick={() => onCopy(alt.response)}
                    aria-label={`Copy ${altCfg.label} response`}
                  >
                    Copy
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
};

// ── Main Component ─────────────────────────────────────────────────────── //

export const CodingAgentPage: React.FC<CodingAgentPageProps> = ({
  taskId,
  initialTask = "",
  wsBase,
}) => {
  const { messages, isLoading, synthesis, error, connectionStatus } =
    useTalkPageStream(taskId, wsBase);

  const [taskDescription, setTaskDescription] = useState(initialTask);
  const [copiedState,      setCopiedState]     = useState(false);
  const [recentTasks,      setRecentTasks]     = useLocalStorage<RecentTask[]>(
    "cato-recent-tasks",
    [],
  );

  // Fetch task description if not provided
  React.useEffect(() => {
    if (taskDescription || !taskId) return;
    fetch(`/api/coding-agent/${encodeURIComponent(taskId)}`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data?.task) setTaskDescription(data.task);
      })
      .catch(() => {});
  }, [taskId, taskDescription]);

  // Persist to recent tasks when synthesis arrives
  React.useEffect(() => {
    if (!synthesis || !taskDescription) return;
    setRecentTasks((prev) => {
      const exists = prev.some((t) => t.taskId === taskId);
      if (exists) return prev;
      return [
        { taskId, task: taskDescription, createdAt: Date.now() },
        ...prev,
      ].slice(0, MAX_RECENT_TASKS);
    });
  }, [synthesis, taskId, taskDescription, setRecentTasks]);

  // ── Handlers ── //

  const handleCopy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const el = document.createElement("textarea");
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopiedState(true);
    setTimeout(() => setCopiedState(false), 2000);
  }, []);

  const handleSave = useCallback((text: string, model: string) => {
    const blob = new Blob([text], { type: "text/plain" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `cato-${model}-result.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  const handleShare = useCallback((tId: string) => {
    const url = `${location.origin}/coding-agent/${tId}`;
    navigator.clipboard.writeText(url).catch(() => {});
    alert(`Link copied: ${url}`);
  }, []);

  const handleRetry = useCallback(() => {
    window.location.reload();
  }, []);

  const handleRecentTask = useCallback((rt: RecentTask) => {
    window.location.href = `/coding-agent/${rt.taskId}`;
  }, []);

  // ── Render ── //

  return (
    <main
      className="coding-agent-page"
      data-testid="coding-agent-page"
      aria-label="Coding agent results"
    >
      {/* ── Left Sidebar ── */}
      <aside
        className="sidebar-left"
        aria-label="Task details"
        data-testid="left-sidebar"
      >
        <div className="sidebar-header-section">
          <span>Task</span>
          {isLoading && (
            <span
              className="text-xs text-blue-400"
              role="status"
              aria-live="polite"
              data-testid="loading-status"
            >
              Running...
            </span>
          )}
        </div>

        <div className="sidebar-content">
          {/* Task form (read-only during execution) */}
          <TaskInput
            readOnly={isLoading}
            defaultTask={taskDescription}
            onTaskCreated={(newId) => {
              window.location.href = `/coding-agent/${newId}`;
            }}
          />

          {/* Recent tasks */}
          {recentTasks.length > 0 && (
            <div style={{ marginTop: "20px" }}>
              <div
                className="sidebar-header-section"
                style={{ border: "none", padding: "0 0 6px" }}
              >
                <span>Recent Tasks</span>
              </div>
              <nav aria-label="Recent tasks">
                {recentTasks.map((rt) => (
                  <button
                    key={rt.taskId}
                    className={`recent-task-item w-full text-left ${
                      rt.taskId === taskId ? "border-blue-500 border" : ""
                    }`}
                    onClick={() => handleRecentTask(rt)}
                    aria-label={`Resume task: ${rt.task}`}
                    aria-current={rt.taskId === taskId ? "page" : undefined}
                    data-testid="recent-task-item"
                  >
                    {rt.task.slice(0, 60)}{rt.task.length > 60 ? "…" : ""}
                  </button>
                ))}
              </nav>
            </div>
          )}
        </div>
      </aside>

      {/* ── Main Talk Area ── */}
      <div className="talk-main" data-testid="talk-main">
        {/* Error state banner */}
        {error && !isLoading && (
          <div
            className="error-banner m-4"
            role="alert"
            data-testid="page-error-banner"
          >
            <span>Error: {error}</span>
            <button
              className="retry-btn"
              onClick={handleRetry}
              aria-label="Retry task"
              data-testid="retry-btn"
            >
              Retry
            </button>
          </div>
        )}

        <TalkPage
          task={taskDescription || `Task ${taskId}`}
          models={[...MODELS]}
          messages={messages}
          isLoading={isLoading}
          synthesis={synthesis}
          error={error}
          connectionStatus={connectionStatus}
        />
      </div>

      {/* ── Right Sidebar ── */}
      <RightSidebar
        synthesis={synthesis}
        isLoading={isLoading}
        onCopy={handleCopy}
        onSave={handleSave}
        onShare={handleShare}
        taskId={taskId}
        copiedState={copiedState}
      />
    </main>
  );
};

export default CodingAgentPage;
