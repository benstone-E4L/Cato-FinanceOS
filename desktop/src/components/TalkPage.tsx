/**
 * TalkPage.tsx — Main conversation UI for the Cato coding agent.
 */

import React, { useEffect, useRef, useCallback } from "react";
import { MessageBubble } from "./MessageBubble";
import type { TalkMessage } from "./MessageBubble";
import { ConfidenceBadge } from "./ConfidenceBadge";

export interface SynthesisResult {
  primary: {
    model: string;
    response: string;
    confidence: number;
    confidence_level: string;
    latency_ms?: number;
  };
  runners_up: Array<{
    model: string;
    response: string;
    confidence: number;
    confidence_level: string;
  }>;
  early_exit?: boolean;
}

export interface TalkPageProps {
  task: string;
  models: string[];
  messages: TalkMessage[];
  isLoading: boolean;
  synthesis: SynthesisResult | null;
  error?: string | null;
  connectionStatus?: "connecting" | "connected" | "disconnected" | "reconnecting" | "closed";
}

const MODEL_CONFIG: Record<string, { label: string; color: string }> = {
  claude: { label: "Claude",  color: "#3B82F6" },
  codex:  { label: "Codex",   color: "#F59E0B" },
  gemini: { label: "Gemini",  color: "#A855F7" },
};

const MODELS_RESPONDED = (messages: TalkMessage[], model: string): boolean =>
  messages.some((m) => m.model.toLowerCase() === model.toLowerCase());

interface ModelIndicatorProps {
  model: string;
  loading: boolean;
}

const ModelIndicator: React.FC<ModelIndicatorProps> = ({ model, loading }) => {
  const cfg = MODEL_CONFIG[model.toLowerCase()] ?? { label: model, color: "#94a3b8" };

  return (
    <div
      className={`model-indicator ${model.toLowerCase()} ${!loading ? "active" : ""}`}
      role="status"
      aria-label={`${cfg.label}: ${loading ? "waiting" : "responded"}`}
    >
      {loading ? (
        <span className="model-spinner" aria-hidden="true" />
      ) : (
        <span className="model-dot" aria-hidden="true" />
      )}
      {cfg.label}
    </div>
  );
};

interface SynthesisFooterProps {
  synthesis: SynthesisResult | null;
  isLoading: boolean;
  responseCount: number;
  totalModels: number;
}

const SynthesisFooter: React.FC<SynthesisFooterProps> = ({
  synthesis,
  isLoading,
  responseCount,
  totalModels,
}) => {
  if (!synthesis && isLoading) {
    const remaining = totalModels - responseCount;
    return (
      <div className="talk-footer">
        <div className="awaiting-text" role="status" aria-live="polite">
          <div className="awaiting-dots" aria-hidden="true">
            <span /><span /><span />
          </div>
          {responseCount > 0
            ? `${responseCount} response${responseCount > 1 ? "s" : ""} in\u2026 waiting for ${remaining} more`
            : `${totalModels} responses in progress...`}
        </div>
      </div>
    );
  }

  if (!synthesis) return null;

  const { primary } = synthesis;
  const modelCfg = MODEL_CONFIG[primary.model.toLowerCase()] ?? { label: primary.model, color: "#94a3b8" };

  return (
    <div className="talk-footer" role="region" aria-label="Synthesis result">
      <div className="synthesis-result" data-testid="synthesis-result">
        <div className="synthesis-label">
          <span className="synthesis-label-icon" aria-hidden="true">\u2605</span>
          Best Answer
        </div>
        <div className="synthesis-model">
          <span style={{ color: modelCfg.color }}>{modelCfg.label}</span>
          <ConfidenceBadge confidence={primary.confidence} />
          {synthesis.early_exit && (
            <span className="early-exit-badge" title="High confidence early termination">
              Early Exit
            </span>
          )}
        </div>
        <p className="synthesis-text">{primary.response}</p>
      </div>
    </div>
  );
};

export const TalkPage: React.FC<TalkPageProps> = ({
  task,
  models,
  messages,
  isLoading,
  synthesis,
  error,
  connectionStatus = "connected",
}) => {
  const messagesEndRef  = useRef<HTMLDivElement>(null);
  const messagesAreaRef = useRef<HTMLDivElement>(null);
  const userScrolledUp  = useRef(false);

  const scrollToBottom = useCallback(() => {
    if (!userScrolledUp.current && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const handleScroll = useCallback(() => {
    const el = messagesAreaRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    userScrolledUp.current = distFromBottom > 80;
  }, []);

  const responseCount = models.filter((m) => MODELS_RESPONDED(messages, m)).length;

  return (
    <section className="talk-page" aria-label="Model conversation" data-testid="talk-page">
      {connectionStatus === "reconnecting" && (
        <div className="connection-warning mx-4 mt-2" role="alert" aria-live="assertive">
          <span aria-hidden="true">\u26A0</span>
          Reconnecting to server...
        </div>
      )}
      {connectionStatus === "disconnected" && (
        <div className="connection-error mx-4 mt-2" role="alert" aria-live="assertive">
          <span aria-hidden="true">\u2715</span>
          Connection lost — results may be incomplete.
        </div>
      )}

      <header className="talk-header">
        <div className="talk-header-task" title={task}>{task}</div>
        <div className="model-indicators" role="group" aria-label="Model status">
          {models.map((model) => (
            <ModelIndicator
              key={model}
              model={model}
              loading={isLoading && !MODELS_RESPONDED(messages, model)}
            />
          ))}
        </div>
      </header>

      <div
        className="talk-messages"
        ref={messagesAreaRef}
        onScroll={handleScroll}
        role="log"
        aria-live="polite"
        aria-label="Model responses"
      >
        {messages.length === 0 && isLoading && (
          <p className="empty-state" aria-live="polite">
            Waiting for model responses...
          </p>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {error && (
          <div className="error-banner" role="alert" aria-live="assertive">
            <span>Error: {error}</span>
          </div>
        )}

        <div ref={messagesEndRef} aria-hidden="true" />
      </div>

      <SynthesisFooter
        synthesis={synthesis}
        isLoading={isLoading}
        responseCount={responseCount}
        totalModels={models.length}
      />
    </section>
  );
};

export default TalkPage;
export type { TalkMessage };
