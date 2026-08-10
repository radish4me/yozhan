// Thin client for the Agent Runtime's /chat endpoint, shared by the /chat
// proxy route and channel message handling in index.ts.

export interface RuntimeChatResponse {
  content?: string;
  error?: string;
  metadata?: Record<string, unknown>;
}

export async function callRuntimeChat(
  runtimeUrl: string,
  message: string,
  sessionId: string
): Promise<RuntimeChatResponse> {
  const resp = await fetch(`${runtimeUrl}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  return (await resp.json()) as RuntimeChatResponse;
}
