// Discord channel adapter. Uses the Gateway websocket for receiving events
// (Discord has no long-polling equivalent to Telegram's getUpdates) and the
// REST API for sending. Only the pieces yozhan needs are implemented: identify,
// heartbeat, and MESSAGE_CREATE — a full Discord library would be a large
// dependency for a fraction of its surface.
//
// See ARCHITECTURE.md section 3.1, ROADMAP.md Phase 7.

import { WebSocket } from "ws";
import type { ChannelAdapter, IncomingMessage } from "./types.js";

const API_BASE = "https://discord.com/api/v10";
const GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json";

// Intents: GUILD_MESSAGES (1<<9) | DIRECT_MESSAGES (1<<12) | MESSAGE_CONTENT (1<<15)
const INTENTS = (1 << 9) | (1 << 12) | (1 << 15);

const OP_DISPATCH = 0;
const OP_HEARTBEAT = 1;
const OP_IDENTIFY = 2;
const OP_HELLO = 10;

interface DiscordPayload {
  op: number;
  t?: string;
  d?: Record<string, unknown>;
}

/** Pure: decides whether a MESSAGE_CREATE payload is something we should act on. */
export function toIncomingMessage(channel: string, payload: DiscordPayload): IncomingMessage | null {
  if (payload.op !== OP_DISPATCH || payload.t !== "MESSAGE_CREATE") return null;
  const data = payload.d as
    | { content?: string; channel_id?: string; author?: { id?: string; bot?: boolean } }
    | undefined;
  if (!data) return null;
  // Ignore our own messages and other bots, or two bots can loop forever.
  if (data.author?.bot) return null;
  if (typeof data.content !== "string" || !data.content.trim()) return null;
  if (!data.channel_id) return null;
  return { channel, externalId: data.channel_id, text: data.content };
}

export class DiscordAdapter implements ChannelAdapter {
  readonly name = "discord";
  private readonly token: string;
  private socket: WebSocket | null = null;
  private heartbeat: NodeJS.Timeout | null = null;
  private running = false;

  constructor(token: string) {
    this.token = token;
  }

  async start(onMessage: (msg: IncomingMessage) => Promise<void>): Promise<void> {
    this.running = true;
    this.connect(onMessage);
  }

  private connect(onMessage: (msg: IncomingMessage) => Promise<void>): void {
    if (!this.running) return;
    const socket = new WebSocket(GATEWAY_URL);
    this.socket = socket;

    socket.on("message", async (raw: Buffer) => {
      let payload: DiscordPayload;
      try {
        payload = JSON.parse(raw.toString());
      } catch {
        return;
      }

      if (payload.op === OP_HELLO) {
        const interval = (payload.d?.heartbeat_interval as number) ?? 45000;
        this.heartbeat = setInterval(() => socket.send(JSON.stringify({ op: OP_HEARTBEAT, d: null })), interval);
        socket.send(
          JSON.stringify({
            op: OP_IDENTIFY,
            d: { token: this.token, intents: INTENTS, properties: { os: "linux", browser: "yozhan", device: "yozhan" } },
          })
        );
        return;
      }

      const message = toIncomingMessage(this.name, payload);
      if (message) await onMessage(message);
    });

    socket.on("close", () => {
      this.clearHeartbeat();
      if (this.running) setTimeout(() => this.connect(onMessage), 5000);
    });
    socket.on("error", (err) => console.error("[discord] socket error:", err));
  }

  private clearHeartbeat(): void {
    if (this.heartbeat) {
      clearInterval(this.heartbeat);
      this.heartbeat = null;
    }
  }

  async stop(): Promise<void> {
    this.running = false;
    this.clearHeartbeat();
    this.socket?.close();
  }

  async sendMessage(externalId: string, text: string): Promise<void> {
    await fetch(`${API_BASE}/channels/${externalId}/messages`, {
      method: "POST",
      headers: { authorization: `Bot ${this.token}`, "content-type": "application/json" },
      body: JSON.stringify({ content: text }),
    });
  }
}
