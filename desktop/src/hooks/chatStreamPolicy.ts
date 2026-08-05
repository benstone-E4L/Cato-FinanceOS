import type { ChatMessage } from "./useChatStream";

export const CHAT_HISTORY_TTL_MS = 30 * 24 * 60 * 60 * 1_000;
export const CHAT_HISTORY_VERSION = 1;

interface StoredChatHistory {
  version: number;
  savedAt: number;
  messages: ChatMessage[];
}

export function encodeChatHistory(messages: ChatMessage[], now = Date.now()): string {
  return JSON.stringify({
    version: CHAT_HISTORY_VERSION,
    savedAt: now,
    messages,
  } satisfies StoredChatHistory);
}

export function decodeChatHistory(raw: string | null, now = Date.now()): ChatMessage[] {
  if (!raw) return [];
  const parsed: unknown = JSON.parse(raw);

  // Preserve the pre-retention array format as an explicit one-time migration.
  if (Array.isArray(parsed)) return parsed as ChatMessage[];
  if (!parsed || typeof parsed !== "object") return [];

  const stored = parsed as Partial<StoredChatHistory>;
  if (!Array.isArray(stored.messages) || typeof stored.savedAt !== "number") return [];
  if (stored.version !== CHAT_HISTORY_VERSION) return [];
  if (now - stored.savedAt >= CHAT_HISTORY_TTL_MS) return [];
  return stored.messages;
}

export function reconnectDelayMs(
  attempt: number,
  randomValue = Math.random(),
  initialMs = 500,
  maximumMs = 30_000,
): number {
  const exponential = Math.min(initialMs * 2 ** Math.max(0, attempt - 1), maximumMs);
  const boundedRandom = Math.min(1, Math.max(0, randomValue));
  const jitterMultiplier = 0.8 + boundedRandom * 0.4;
  return Math.min(maximumMs, Math.max(0, Math.round(exponential * jitterMultiplier)));
}

export interface ReconnectTimer {
  cancel: () => void;
}

export function scheduleReconnect(
  callback: () => void,
  delayMs: number,
  schedule: (callback: () => void, delayMs: number) => unknown = setTimeout,
  cancelScheduled: (timer: unknown) => void = (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
): ReconnectTimer {
  let active = true;
  const timer = schedule(() => {
    if (!active) return;
    active = false;
    callback();
  }, delayMs);
  return {
    cancel: () => {
      active = false;
      cancelScheduled(timer);
    },
  };
}

export type DecodedSocketFrame =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; error: string };

export function decodeSocketFrame(raw: string): DecodedSocketFrame {
  try {
    const parsed: unknown = JSON.parse(raw.trimEnd());
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, error: "Protocol error: daemon frame must be a JSON object." };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, error: "Protocol error: daemon sent a non-JSON WebSocket frame." };
  }
}
