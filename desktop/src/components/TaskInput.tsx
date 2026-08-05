/**
 * TaskInput.tsx — Task submission form for the Cato coding agent.
 */

import React, {
  useState,
  useCallback,
  useRef,
  type ChangeEvent,
  type FormEvent,
} from "react";

export interface TaskInputProps {
  onTaskCreated?: (taskId: string) => void;
  readOnly?: boolean;
  defaultTask?: string;
  apiBase?: string;
}

const SUPPORTED_LANGUAGES = [
  { value: "",           label: "Any / Auto-detect" },
  { value: "python",     label: "Python" },
  { value: "javascript", label: "JavaScript" },
  { value: "typescript", label: "TypeScript" },
  { value: "java",       label: "Java" },
  { value: "go",         label: "Go" },
  { value: "rust",       label: "Rust" },
  { value: "cpp",        label: "C++" },
  { value: "csharp",     label: "C#" },
  { value: "ruby",       label: "Ruby" },
];

const ALLOWED_EXTENSIONS = [".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".cs", ".rb"];
const MIN_TASK_LEN = 10;
const MAX_TASK_LEN = 500;

function charCountClass(len: number): string {
  if (len > MAX_TASK_LEN) return "char-count over";
  if (len > MAX_TASK_LEN * 0.85) return "char-count warn";
  return "char-count ok";
}

async function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Could not read file"));
    reader.readAsText(file);
  });
}

export const TaskInput: React.FC<TaskInputProps> = ({
  onTaskCreated,
  readOnly = false,
  defaultTask = "",
  apiBase = "",
}) => {
  const [task, setTask]         = useState(defaultTask);
  const [language, setLanguage] = useState("");
  const [fileContext, setFileContext] = useState<string>("");
  const [fileName, setFileName]      = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError]   = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const taskTooShort = task.trim().length > 0 && task.trim().length < MIN_TASK_LEN;
  const taskTooLong  = task.trim().length > MAX_TASK_LEN;
  const formValid    = task.trim().length >= MIN_TASK_LEN && !taskTooLong && !isSubmitting;

  const handleTaskChange = useCallback((e: ChangeEvent<HTMLTextAreaElement>) => {
    setTask(e.target.value);
    setSubmitError(null);
  }, []);

  const handleLanguageChange = useCallback((e: ChangeEvent<HTMLSelectElement>) => {
    setLanguage(e.target.value);
  }, []);

  const handleFileChange = useCallback(async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) {
      setFileContext("");
      setFileName("");
      return;
    }

    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      setSubmitError(`Unsupported file type. Allowed: ${ALLOWED_EXTENSIONS.join(", ")}`);
      e.target.value = "";
      return;
    }

    try {
      const text = await readFileAsText(file);
      setFileContext(text);
      setFileName(file.name);
      setSubmitError(null);
    } catch {
      setSubmitError("Failed to read file.");
    }
  }, []);

  const handleSubmit = useCallback(
    async (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (!formValid) return;

      setIsSubmitting(true);
      setSubmitError(null);

      try {
        const response = await fetch(`${apiBase}/api/coding-agent/invoke`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            task:     task.trim(),
            language: language || undefined,
            context:  fileContext || undefined,
          }),
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({ error: "Request failed" }));
          throw new Error(err.error ?? `HTTP ${response.status}`);
        }

        const data = await response.json();
        const taskId: string = data.task_id;

        if (onTaskCreated) {
          onTaskCreated(taskId);
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        setSubmitError(msg);
      } finally {
        setIsSubmitting(false);
      }
    },
    [formValid, task, language, fileContext, apiBase, onTaskCreated],
  );

  return (
    <form
      className="task-input-form"
      onSubmit={handleSubmit}
      aria-label="Submit coding task"
      data-testid="task-input-form"
      noValidate
    >
      <div className="form-field">
        <label className="form-label" htmlFor="task-desc">
          Task Description<span className="required" aria-hidden="true">*</span>
        </label>
        <textarea
          id="task-desc"
          className="form-textarea"
          placeholder="e.g., Review this sorting algorithm, Optimize this query"
          value={task}
          onChange={handleTaskChange}
          disabled={readOnly || isSubmitting}
          aria-required="true"
          aria-invalid={taskTooShort || taskTooLong}
          minLength={MIN_TASK_LEN}
          maxLength={MAX_TASK_LEN + 100}
          data-testid="task-textarea"
          rows={4}
        />
        <span className={charCountClass(task.length)} aria-live="polite">
          {task.length} / {MAX_TASK_LEN}
        </span>
        {taskTooShort && (
          <span className="validation-error" role="alert">
            Minimum {MIN_TASK_LEN} characters required.
          </span>
        )}
        {taskTooLong && (
          <span className="validation-error" role="alert">
            Maximum {MAX_TASK_LEN} characters allowed.
          </span>
        )}
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="task-lang">Language (optional)</label>
        <select
          id="task-lang"
          className="form-select"
          value={language}
          onChange={handleLanguageChange}
          disabled={readOnly || isSubmitting}
          data-testid="language-select"
        >
          {SUPPORTED_LANGUAGES.map((lang) => (
            <option key={lang.value} value={lang.value}>{lang.label}</option>
          ))}
        </select>
      </div>

      {!readOnly && (
        <div className="form-field">
          <label className="form-label" htmlFor="task-file">File Context (optional)</label>
          <label className="form-file-label" htmlFor="task-file" tabIndex={0}>
            {fileName ? `${fileName} (click to replace)` : `Attach file (${ALLOWED_EXTENSIONS.join(", ")})`}
          </label>
          <input
            ref={fileInputRef}
            id="task-file"
            type="file"
            className="form-file-input"
            accept={ALLOWED_EXTENSIONS.join(",")}
            onChange={handleFileChange}
            disabled={readOnly || isSubmitting}
            data-testid="file-input"
          />
          {fileContext && (
            <pre className="file-preview" data-testid="file-preview">
              {fileContext.slice(0, 500)}
              {fileContext.length > 500 ? "\n... (truncated)" : ""}
            </pre>
          )}
        </div>
      )}

      {submitError && (
        <div className="connection-error" role="alert" aria-live="assertive">
          <span aria-hidden="true">{"\u2715"}</span>
          {submitError}
        </div>
      )}

      {!readOnly && (
        <button
          type="submit"
          className="submit-btn"
          disabled={!formValid}
          data-testid="submit-btn"
        >
          {isSubmitting ? (
            <>
              <span className="submit-spinner" aria-hidden="true" />
              Submitting...
            </>
          ) : (
            <>
              <span aria-hidden="true">{"\u25B6"}</span>
              Run Agents
            </>
          )}
        </button>
      )}
    </form>
  );
};

export default TaskInput;
