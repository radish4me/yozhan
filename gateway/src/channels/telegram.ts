// Telegram channel adapter — long-polling against the Bot API, no public
// URL/webhook required (works from behind NAT, a bare VPS, or a laptop).
// Message parsing is split into a pure function so it's testable without
// mocking fetch/timers. See ARCHITECTURE.md section 3.1, ROADMAP.md Phase 5.

import type { ChannelAdapter, IncomingMessage } from "./types.js";

const API_BASE = "https://api.telegram.org";
const POLL_TIMEOUT_SECONDS = 25;
const ERROR_RETRY_DELAY_MS = 5000;

interface TelegramUpdate {
  update_id: number;
  message?: {
    chat?: { id: number };
    text?: string;
  };
}

export function extractIncomingMessages(
  channel: string,
  updates: TelegramUpdate[]
): { messages: IncomingMessage[]; nextOffset: number | null } {
  const messages: IncomingMessage[] = [];
  let nextOffset: number | null = null;

  for (const update of updates) {
    nextOffset = update.update_id + 1;
    const text = update.message?.text;
    const chatId = update.message?.chat?.id;
    if (typeof text === "string" && chatId != null) {
      messages.push({ channel, externalId: String(chatId), text });
    }
  }

  return { messages, nextOffset };
}

export class TelegramAdapter implements ChannelAdapter {
  readonly name = "telegram";
  private readonly token: string;
  private offset = 0;
  private polling = false;

  constructor(token: string) {
    this.token = token;
  }

  private apiUrl(method: string): string {
    return `${API_BASE}/bot${this.token}/${method}`;
  }

  async start(onMessage: (msg: IncomingMessage) => Promise<void>): Promise<void> {
    this.polling = true;
    void this.pollLoop(onMessage);
  }

  private async pollLoop(onMessage: (msg: IncomingMessage) => Promise<void>): Promise<void> {
    while (this.polling) {
      try {
        const resp = await fetch(this.apiUrl("getUpdates"), {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ offset: this.offset, timeout: POLL_TIMEOUT_SECONDS }),
        });
        const data = (await resp.json()) as { ok: boolean; result?: TelegramUpdate[] };
        if (data.ok && data.result) {
          const { messages, nextOffset } = extractIncomingMessages(this.name, data.result);
          if (nextOffset !== null) this.offset = nextOffset;
          for (const msg of messages) {
            await onMessage(msg);
          }
        }
      } catch (err) {
        console.error("[telegram] poll error:", err);
        await new Promise((resolve) => setTimeout(resolve, ERROR_RETRY_DELAY_MS));
      }
    }
  }

  async stop(): Promise<void> {
    this.polling = false;
  }

  async sendMessage(externalId: string, text: string): Promise<void> {
    await fetch(this.apiUrl("sendMessage"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: externalId, text }),
    });
  }
}
