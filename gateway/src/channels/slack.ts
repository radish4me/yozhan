// Slack channel adapter, using Socket Mode so yozhan needs no public URL or
// inbound firewall rule — the same constraint that drove Telegram to long
// polling. Requires an app-level token (xapp-…, connections:write) to open the
// socket and a bot token (xoxb-…) to post.
//
// See ARCHITECTURE.md section 3.1, ROADMAP.md Phase 7.

import { WebSocket } from "ws";
import type { ChannelAdapter, IncomingMessage } from "./types.js";

const API_BASE = "https://slack.com/api";

interface SocketEnvelope {
  envelope_id?: string;
  type?: string;
  payload?: {
    event?: {
      type?: string;
      text?: string;
      channel?: string;
      bot_id?: string;
      subtype?: string;
    };
  };
}

/** Pure: extracts an actionable message from a Socket Mode envelope. */
export function toIncomingMessage(channel: string, envelope: SocketEnvelope): IncomingMessage | null {
  if (envelope.type !== "events_api") return null;
  const event = envelope.payload?.event;
  if (!event || event.type !== "message") return null;
  // Skip bot posts and edits/joins/etc., which would otherwise echo back.
  if (event.bot_id || event.subtype) return null;
  if (typeof event.text !== "string" || !event.text.trim()) return null;
  if (!event.channel) return null;
  return { channel, externalId: event.channel, text: event.text };
}

export class SlackAdapter implements ChannelAdapter {
  readonly name = "slack";
  private readonly appToken: string;
  private readonly botToken: string;
  private socket: WebSocket | null = null;
  private running = false;

  constructor(appToken: string, botToken: string) {
    this.appToken = appToken;
    this.botToken = botToken;
  }

  private async openSocketUrl(): Promise<string> {
    const resp = await fetch(`${API_BASE}/apps.connections.open`, {
      method: "POST",
      headers: { authorization: `Bearer ${this.appToken}`, "content-type": "application/json" },
    });
    const data = (await resp.json()) as { ok: boolean; url?: string; error?: string };
    if (!data.ok || !data.url) throw new Error(`slack connection failed: ${data.error ?? "unknown error"}`);
    return data.url;
  }

  async start(onMessage: (msg: IncomingMessage) => Promise<void>): Promise<void> {
    this.running = true;
    await this.connect(onMessage);
  }

  private async connect(onMessage: (msg: IncomingMessage) => Promise<void>): Promise<void> {
    if (!this.running) return;
    const url = await this.openSocketUrl();
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.on("message", async (raw: Buffer) => {
      let envelope: SocketEnvelope;
      try {
        envelope = JSON.parse(raw.toString());
      } catch {
        return;
      }
      // Slack redelivers anything not acked within 3s, which would double-reply.
      if (envelope.envelope_id) {
        socket.send(JSON.stringify({ envelope_id: envelope.envelope_id }));
      }
      const message = toIncomingMessage(this.name, envelope);
      if (message) await onMessage(message);
    });

    socket.on("close", () => {
      if (this.running) setTimeout(() => void this.connect(onMessage).catch(() => {}), 5000);
    });
    socket.on("error", (err) => console.error("[slack] socket error:", err));
  }

  async stop(): Promise<void> {
    this.running = false;
    this.socket?.close();
  }

  async sendMessage(externalId: string, text: string): Promise<void> {
    await fetch(`${API_BASE}/chat.postMessage`, {
      method: "POST",
      headers: { authorization: `Bearer ${this.botToken}`, "content-type": "application/json" },
      body: JSON.stringify({ channel: externalId, text }),
    });
  }
}
