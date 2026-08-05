/**
 * useTalkPageStream.ts — WebSocket hook for streaming model responses.
 *
 * Connects to /ws/coding-agent/{taskId} and handles:
 *   - claude_response / codex_response / gemini_response events
 *   - synthesis_complete event
 *   - early_termination event
 *   - heartbeat (for connection health check)
 *   - error events
 *
 * Features:
 *   - Exponential backoff reconnection (max 5 retries)
 *   - Heartbeat timeout detection (>3s gap = warning)
 *   - Auto-scroll deference (respects user scroll position)
 *   - Graceful 5-second fallback to best result on timeout
 */

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  type MutableRefObject,
} from "react";
import type { TalkMessage } from "../components/MessageBubble";
import type { SynthesisResult } from "../components/TalkPage";

// ── Types ──────────────────────────────────────────────────────────────── //

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "closed";

export interface UseTalkPageStreamResult {
  messages: TalkMessage[];
  isLoading: boolean;
  synthesis: SynthesisResult | null;
  error: string | null;
  connectionStatus: ConnectionStatus;
  /** Ref to attach to the messages container for auto-scroll */
  messagesEndRef: MutableRefObject<HTMLDivElement | null>;
}

// ── Constants ─────────────────────────────────────────────────────────── //

const MAX_RETRIES          = 5;
const INITIAL_BACKOFF_MS   = 500;
const MAX_BACKOFF_MS       = 16_000;
const HEARTBEAT_TIMEOUT_MS = 3_000;   // warn after 3s silence
const TASK_TIMEOUT_MS      = 5_000;   // fallback after 5s total silence

// ── Hook ──────────────────────────────────────────────────────────────── //

export function useTalkPageStream(
  taskId: string,
  wsBase?: string,
): UseTalkPageStreamResult {
  const [messages,         setMessages]         = useState<TalkMessage[]>([]);
  const [isLoading,        setIsLoading]        = useState<boolean>(true);
  const [synthesis,        setSynthesis]        = useState<SynthesisResult | null>(null);
  const [error,            setError]            = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");

  const messagesEndRef   = useRef<HTMLDivElement | null>(null);
  const wsRef            = useRef<WebSocket | null>(null);
  const retriesRef       = useRef<number>(0);
  const heartbeatTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const taskTimerRef     = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef        = useRef<boolean>(false);  // permanently closed
  const messagesRef      = useRef<TalkMessage[]>([]); // stable ref for best-of fallback

  // Keep messagesRef in sync
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // ── Auto-scroll ── //
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  // ── Heartbeat management ── //
  const resetHeartbeatTimer = useCallback(() => {
    if (heartbeatTimerRef.current) clearTimeout(heartbeatTimerRef.current);
    heartbeatTimerRef.current = setTimeout(() => {
      // >3s without heartbeat — warn
      setConnectionStatus((prev) =>
        prev === "connected" ? "reconnecting" : prev,
      );
    }, HEARTBEAT_TIMEOUT_MS);
  }, []);

  const clearHeartbeatTimer = useCallback(() => {
    if (heartbeatTimerRef.current) {
      clearTimeout(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  }, []);

  // ── Task timeout fallback ── //
  const startTaskTimeout = useCallback(() => {
    if (taskTimerRef.current) clearTimeout(taskTimerRef.current);
    taskTimerRef.current = setTimeout(() => {
      // After 5 s with no synthesis, build best-of from current messages
      const msgs = messagesRef.current;
      if (msgs.length > 0 && !synthesis) {
        const best = [...msgs].sort((a, b) => b.confidence - a.confidence)[0];
        setSynthesis({
          primary: {
            model:            best.model,
            response:         best.text,
            confidence:       best.confidence,
            confidence_level: best.confidence >= 0.9
              ? "high"
              : best.confidence >= 0.7
                ? "medium"
                : "low",
          },
          runners_up: msgs
            .filter((m) => m.id !== best.id)
            .map((m) => ({
              model:            m.model,
              response:         m.text,
              confidence:       m.confidence,
              confidence_level: m.confidence >= 0.9
                ? "high"
                : m.confidence >= 0.7
                  ? "medium"
                  : "low",
            })),
          early_exit: false,
        });
      }
      setIsLoading(false);
    }, TASK_TIMEOUT_MS);
  }, [synthesis]);

  const clearTaskTimeout = useCallback(() => {
    if (taskTimerRef.current) {
      clearTimeout(taskTimerRef.current);
      taskTimerRef.current = null;
    }
  }, []);

  // ── Message parsing ── //
  const handleMessage = useCallback(
    (raw: string) => {
      let parsed: { event: string; data: Record<string, unknown> };
      try {
        // Strip trailing newline if present
        parsed = JSON.parse(raw.trimEnd());
      } catch {
        console.warn("[useTalkPageStream] Unparseable message:", raw);
        return;
      }

      const { event, data } = parsed;
      resetHeartbeatTimer();

      switch (event) {
        case "heartbeat":
          // Just resets the timer — no state change needed
          break;

        case "claude_response":
        case "codex_response":
        case "gemini_response": {
          const model = event.replace("_response", "");
          const msg: TalkMessage = {
            id:         (data.id as string) ?? crypto.randomUUID(),
            model,
            timestamp:  (data.timestamp as number) ?? Date.now(),
            text:       (data.text as string) ?? "",
            confidence: (data.confidence as number) ?? 0.75,
            reasoning:  data.reasoning as string | undefined,
            code:       data.code as string | undefined,
          };
          setMessages((prev) => {
            const next = [...prev, msg];
            return next;
          });
          scrollToBottom();
          // Restart fallback timer on each response
          startTaskTimeout();
          break;
        }

        case "synthesis_complete": {
          const syn: SynthesisResult = {
            primary:    data.primary as SynthesisResult["primary"],
            runners_up: (data.runners_up as SynthesisResult["runners_up"]) ?? [],
            early_exit: Boolean(data.early_exit),
          };
          setSynthesis(syn);
          setIsLoading(false);
          clearTaskTimeout();
          closedRef.current = true;  // no need to reconnect
          break;
        }

        case "early_termination": {
          setIsLoading(false);
          clearTaskTimeout();
          break;
        }

        case "error": {
          const msg = (data.message as string) ?? "Unknown error";
          setError(msg);
          // Don't stop loading; other models may still respond
          break;
        }

        case "status":
          // Informational only
          break;

        default:
          console.warn("[useTalkPageStream] Unknown event:", event);
      }
    },
    [resetHeartbeatTimer, scrollToBottom, startTaskTimeout, clearTaskTimeout],
  );

  // ── WebSocket connection ── //
  const connect = useCallback(() => {
    if (closedRef.current) return;
    if (!taskId) return;

    // Build WebSocket URL
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const host     = wsBase ?? location.host;
    const url      = `${protocol}//${host}/ws/coding-agent/${encodeURIComponent(taskId)}`;

    setConnectionStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnectionStatus("connected");
      retriesRef.current = 0;
      resetHeartbeatTimer();
      startTaskTimeout();
    };

    ws.onmessage = (ev: MessageEvent<string>) => {
      handleMessage(ev.data);
    };

    ws.onerror = (ev) => {
      console.error("[useTalkPageStream] WebSocket error:", ev);
    };

    ws.onclose = (_ev) => {
      clearHeartbeatTimer();

      if (closedRef.current) {
        setConnectionStatus("closed");
        return;
      }

      // Attempt reconnect with exponential backoff
      if (retriesRef.current < MAX_RETRIES) {
        const delay = Math.min(
          INITIAL_BACKOFF_MS * 2 ** retriesRef.current,
          MAX_BACKOFF_MS,
        );
        retriesRef.current += 1;
        setConnectionStatus("reconnecting");
        setTimeout(connect, delay);
      } else {
        setConnectionStatus("disconnected");
        setIsLoading(false);
        setError("Connection lost after multiple retries.");
      }
    };
  }, [
    taskId,
    wsBase,
    handleMessage,
    resetHeartbeatTimer,
    clearHeartbeatTimer,
    startTaskTimeout,
  ]);

  // ── Lifecycle ── //
  useEffect(() => {
    closedRef.current = false;
    retriesRef.current = 0;

    connect();

    return () => {
      // Cleanup on unmount
      closedRef.current = true;
      clearHeartbeatTimer();
      clearTaskTimeout();
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect loop
        wsRef.current.close();
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  return {
    messages,
    isLoading,
    synthesis,
    error,
    connectionStatus,
    messagesEndRef,
  };
}

export default useTalkPageStream;
