/**
 * MessageBubble.tsx — Individual message card in the Talk Page conversation thread.
 *
 * Features:
 *  - Left color bar per model (Claude=Blue, Codex=Amber, Gemini=Purple)
 *  - Model name button that expands full reasoning on click
 *  - Confidence badge (Green/Yellow/Orange per tier)
 *  - Message text with pre-wrap formatting
 *  - Code block with copy-to-clipboard button
 *  - Timestamp display
 *  - Keyboard accessible (Enter/Space toggles reasoning)
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

/** Map model name → display label */
const MODEL_LABELS: Record<string, string> = {
  claude: "Claude",
  codex:  "Codex",
  gemini: "Gemini",
};

/** Map model name → single-letter icon */
const MODEL_ICON_LETTER: Record<string, string> = {
  claude: "C",
  codex:  "X",
  gemini: "G",
};

/** Format a Unix timestamp (ms) to HH:MM:SS */
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
      // Fallback for environments without clipboard API
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
      {/* ── Header ── */}
      <div className="message-header">
        {/* Model name button (expands reasoning) */}
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

        {/* Confidence badge */}
        <ConfidenceBadge confidence={message.confidence} />

        {/* Timestamp */}
        <time
          className="message-timestamp"
          dateTime={new Date(message.timestamp).toISOString()}
          aria-label={`Received at ${formatTime(message.timestamp)}`}
        >
          {formatTime(message.timestamp)}
        </time>
      </div>

      {/* ── Message Text ── */}
      <p className="message-text" data-testid="message-text">
        {message.text}
      </p>

      {/* ── Expandable Reasoning ── */}
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

      {/* ── Code Block ── */}
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
            {copied ? "✓ Copied" : "Copy"}
          </button>
        </div>
      )}
    </article>
  );
};

export default MessageBubble;
