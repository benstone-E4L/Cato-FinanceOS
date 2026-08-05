/**
 * MessageBubble.tsx — Individual message card in the Talk Page conversation thread.
 */

import React, { useState, useCallback } from "react";
import { ConfidenceBadge } from "./ConfidenceBadge";

export interface TalkMessage {
  id: string;
  model: string;
  timestamp: number;
  text: string;
  confidence: number;
  reasoning?: string;
  code?: string;
}

export interface MessageBubbleProps {
  message: TalkMessage;
}

const MODEL_LABELS: Record<string, string> = {
  claude: "Claude",
  codex:  "Codex",
  gemini: "Gemini",
};

const MODEL_ICON_LETTER: Record<string, string> = {
  claude: "C",
  codex:  "X",
  gemini: "G",
};

function formatTime(timestamp: number): string {
  const d = new Date(timestamp);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message }) => {
  const [reasoningExpanded, setReasoningExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const model       = message.model.toLowerCase();
  const displayName = MODEL_LABELS[model] ?? message.model;
  const iconLetter  = MODEL_ICON_LETTER[model] ?? model[0]?.toUpperCase() ?? "?";

  const toggleReasoning = useCallback(() => {
    setReasoningExpanded((prev) => !prev);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleReasoning();
      }
    },
    [toggleReasoning],
  );

  const copyCode = useCallback(async () => {
    if (!message.code) return;
    try {
      await navigator.clipboard.writeText(message.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const el = document.createElement("textarea");
      el.value = message.code;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [message.code]);

  return (
    <article
      className={`message-bubble ${model}`}
      data-testid="message-bubble"
      data-model={model}
      role="article"
      aria-label={`${displayName} response with ${Math.round(message.confidence * 100)}% confidence`}
    >
      <div className="message-header">
        <button
          className={`model-name-btn ${model}`}
          onClick={toggleReasoning}
          onKeyDown={handleKeyDown}
          aria-expanded={reasoningExpanded}
          aria-label={`${displayName}: click to ${reasoningExpanded ? "hide" : "show"} reasoning`}
          data-testid={`model-btn-${model}`}
        >
          <span className={`model-icon ${model}`} aria-hidden="true">
            {iconLetter}
          </span>
          {displayName}
          {message.reasoning && (
            <span className={`expand-arrow ${reasoningExpanded ? "open" : ""}`} aria-hidden="true">
              ▶
            </span>
          )}
        </button>

        <ConfidenceBadge confidence={message.confidence} />

        <time
          className="message-timestamp"
          dateTime={new Date(message.timestamp).toISOString()}
          aria-label={`Received at ${formatTime(message.timestamp)}`}
        >
          {formatTime(message.timestamp)}
        </time>
      </div>

      <p className="message-text" data-testid="message-text">
        {message.text}
      </p>

      {message.reasoning && reasoningExpanded && (
        <div
          className="message-reasoning"
          role="region"
          aria-label={`${displayName} reasoning`}
          data-testid="message-reasoning"
        >
          <div className="reasoning-label">Reasoning</div>
          {message.reasoning}
        </div>
      )}

      {message.code && (
        <div className="code-block-wrapper" data-testid="code-block-wrapper">
          <pre
            className="code-block"
            aria-label={`${displayName} code output`}
            data-testid="code-block"
          >
            <code>{message.code}</code>
          </pre>
          <button
            className={`copy-btn ${copied ? "copied" : ""}`}
            onClick={copyCode}
            aria-label={copied ? "Copied!" : "Copy code to clipboard"}
            data-testid="copy-btn"
          >
            {copied ? "\u2713 Copied" : "Copy"}
          </button>
        </div>
      )}
    </article>
  );
};

export default MessageBubble;
