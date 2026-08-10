// yozhan Gateway entrypoint. Phase 5: pairing/auth (unknown senders get a
// short-lived code, an admin approves it once — see pairing/store.ts and
// pairing-cli.ts) plus the first channel adapter (Telegram, long-polling).
// Paired identities round-trip through the same Agent Runtime /chat endpoint
// the CLI uses, each in its own persisted session ("<channel>:<externalId>").
// See ARCHITECTURE.md section 3.1 and ROADMAP.md Phase 5.

import express, { type Request, type Response } from "express";
import { pathToFileURL } from "node:url";
import { TelegramAdapter } from "./channels/telegram.js";
import type { ChannelAdapter, IncomingMessage } from "./channels/types.js";
import { PairingStore } from "./pairing/store.js";
import { callRuntimeChat } from "./runtime-client.js";

const PORT = Number(process.env.PORT ?? 3000);
const RUNTIME_URL = process.env.RUNTIME_URL ?? "http://localhost:8787";
const DATA_DIR = process.env.GATEWAY_DATA_DIR ?? "data";
const ADMIN_TOKEN = process.env.GATEWAY_ADMIN_TOKEN;

const pairingStore = new PairingStore(`${DATA_DIR}/pairings.json`);

const app = express();
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ status: "ok", runtime_url: RUNTIME_URL });
});

app.post("/chat", async (req, res) => {
  const response = await fetch(`${RUNTIME_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req.body),
  });
  const data = await response.json();
  res.status(response.status).json(data);
});

function requireAdmin(req: Request, res: Response): boolean {
  if (!ADMIN_TOKEN) {
    res.status(503).json({ error: "GATEWAY_ADMIN_TOKEN is not configured on this deployment" });
    return false;
  }
  if (req.header("authorization") !== `Bearer ${ADMIN_TOKEN}`) {
    res.status(401).json({ error: "unauthorized" });
    return false;
  }
  return true;
}

app.get("/pairing/pending", (req, res) => {
  if (!requireAdmin(req, res)) return;
  res.json(pairingStore.listPending());
});

app.get("/pairing/paired", (req, res) => {
  if (!requireAdmin(req, res)) return;
  res.json(pairingStore.listPaired());
});

app.post("/pairing/approve", (req, res) => {
  if (!requireAdmin(req, res)) return;
  const code = req.body?.code;
  if (typeof code !== "string") {
    res.status(400).json({ error: "body must include { code: string }" });
    return;
  }
  const identity = pairingStore.approve(code.toUpperCase());
  if (!identity) {
    res.status(404).json({ error: `no pending pairing code '${code}'` });
    return;
  }
  res.json(identity);
});

export async function handleIncoming(
  pairingStore: PairingStore,
  runtimeUrl: string,
  adapter: ChannelAdapter,
  msg: IncomingMessage
): Promise<void> {
  if (!pairingStore.isPaired(msg.channel, msg.externalId)) {
    const pending = pairingStore.getOrCreatePendingCode(msg.channel, msg.externalId);
    const expires = new Date(pending.expiresAt).toLocaleTimeString();
    await adapter.sendMessage(
      msg.externalId,
      `You're not paired yet. Ask your yozhan admin to approve pairing code ${pending.code} (expires ${expires}).`
    );
    return;
  }

  const sessionId = `${msg.channel}:${msg.externalId}`;
  try {
    const result = await callRuntimeChat(runtimeUrl, msg.text, sessionId);
    await adapter.sendMessage(msg.externalId, result.error ? `error: ${result.error}` : result.content ?? "(no reply)");
  } catch (err) {
    await adapter.sendMessage(msg.externalId, `error reaching yozhan runtime: ${(err as Error).message}`);
  }
}

async function startChannels(): Promise<ChannelAdapter[]> {
  const adapters: ChannelAdapter[] = [];
  const telegramToken = process.env.TELEGRAM_BOT_TOKEN;
  if (telegramToken) {
    const telegram = new TelegramAdapter(telegramToken);
    adapters.push(telegram);
    await telegram.start((msg) => handleIncoming(pairingStore, RUNTIME_URL, telegram, msg));
    console.log("[gateway] telegram channel started");
  } else {
    console.log("[gateway] TELEGRAM_BOT_TOKEN not set — telegram channel disabled");
  }
  return adapters;
}

// Only start the HTTP server / channel adapters when this file is run
// directly (`node dist/index.js` / `tsx src/index.ts`) — not when imported,
// e.g. by tests importing handleIncoming().
const isMainModule = process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMainModule) {
  app.listen(PORT, () => {
    console.log(`yozhan gateway listening on :${PORT} (runtime: ${RUNTIME_URL})`);
  });

  startChannels().catch((err) => {
    console.error("[gateway] failed to start channels:", err);
  });
}
