/**
 * AskE4LView — the master spec's §10 "Ask E4L" nav item.
 *
 * Per §10: "Vault-grounded chat via the Retrieval Contract — citations +
 * refusal path; also the command line for the assistant. Absorbs Chat,
 * Memory search." The chat surface itself is the existing ChatView — the
 * agent loop already registers the Ask-E4L retrieval-contract tools
 * (CHUNK_4_ASK_E4L's `_register_ask_e4l_tools`), so this is genuinely the
 * same "command line for the assistant" the spec describes, not a
 * relabeled unrelated chat. Memory search is absorbed as a second tab
 * inside this same nav item rather than kept as its own top-level slot.
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
    <div className="ask-e4l-view" style={{ display: "flex", flexDirection: "column", height: "100%" }}>
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
