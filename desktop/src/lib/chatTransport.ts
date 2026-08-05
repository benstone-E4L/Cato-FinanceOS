export interface ChatSocketPayload {
  type: "message" | "health";
  text?: string;
  session_id?: string;
  client_message_id?: string;
}

export function buildChatMessagePayload(
  text: string,
  sessionId: string,
  clientMessageId: string = crypto.randomUUID(),
): ChatSocketPayload {
  return {
    type: "message",
    text,
    session_id: sessionId,
    client_message_id: clientMessageId,
  };
}

export function sendChatSocketPayload(ws: WebSocket, payload: ChatSocketPayload): void {
  ws.send(JSON.stringify(payload));
}
