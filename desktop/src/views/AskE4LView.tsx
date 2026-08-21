/**
 * AskE4LView — the master spec's §10 "Ask E4L" nav item.
 *
 * This surface mounts general ChatView plus Memory search. The agent loop
 * offers an optional Ask-E4L Vault retrieval tool, but ordinary chat is not
 * universally retrieval-grounded and does not imply citations or refusal.
 */
import React, { useState } from "react";
import { ChatView } from "./ChatView";
import { MemoryView } from "./MemoryView";
import type { ChatConnectionStatus } from "../hooks/useChatStream";

interface AskE4LViewProps {
  wsBase: string;
  httpPort: number;
  daemonToken?: string;
  onConnectionStatusChange?: (status: ChatConnectionStatus) => void;
  initialTab?: "chat" | "memory";
}

export const AskE4LView: React.FC<AskE4LViewProps> = ({
  wsBase, httpPort, daemonToken, onConnectionStatusChange, initialTab,
}) => {
  const [tab, setTab] = useState<"chat" | "memory">(initialTab ?? "chat");

  React.useEffect(() => {
    if (initialTab) setTab(initialTab);
  }, [initialTab]);

  return (
    <div className="ask-e4l-view" data-active-tab={tab} style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="tab-hub-strip" role="tablist" aria-label="Ask E4L" style={{ padding: "12px 24px 0" }}>
        <button role="tab" aria-selected={tab === "chat"} className={`tab-hub-tab${tab === "chat" ? " active" : ""}`} onClick={() => setTab("chat")}>
          Chat
        </button>
        <button role="tab" aria-selected={tab === "memory"} className={`tab-hub-tab${tab === "memory" ? " active" : ""}`} onClick={() => setTab("memory")}>
          Memory search
        </button>
      </div>
      <div style={{ flex: "1 1 0", minHeight: 0, display: "flex" }}>
        {tab === "chat" ? (
          <ChatView
            wsBase={wsBase}
            httpPort={httpPort}
            daemonToken={daemonToken}
            onConnectionStatusChange={onConnectionStatusChange}
          />
        ) : (
          <MemoryView httpPort={httpPort} />
        )}
      </div>
    </div>
  );
};

export default AskE4LView;
