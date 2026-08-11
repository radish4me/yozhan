// yozhan Gateway entrypoint. Phase 5: pairing/auth (unknown senders get a
// short-lived code, an admin approves it once — see pairing/store.ts and
// pairing-cli.ts) plus the first channel adapter (Telegram, long-polling).
// Paired identities round-trip through the same Agent Runtime /chat endpoint
// the CLI uses, each in its own persisted session ("<channel>:<externalId>").
// See ARCHITECTURE.md section 3.1 and ROADMAP.md Phase 5.

import express, { type Request, type Response } from "express";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { DiscordAdapter } from "./channels/discord.js";
import { SlackAdapter } from "./channels/slack.js";
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

// Read-only runtime views the dashboard renders. These proxy straight through;
// the runtime is the source of truth and is not exposed to the host network.
for (const path of ["/agents", "/skills", "/providers", "/costs", "/proposals"]) {
  app.get(path, async (req, res) => {
    const query = new URLSearchParams(req.query as Record<string, string>).toString();
    const response = await fetch(`${RUNTIME_URL}${path}${query ? `?${query}` : ""}`);
    res.status(response.status).json(await response.json());
  });
}

// Approving a proposal writes a new skill to disk, so it is admin-gated —
// unlike the read-only views above.
for (const action of ["approve", "reject"]) {
  app.post(`/proposals/:id/${action}`, async (req, res) => {
    if (!requireAdmin(req, res)) return;
    const response = await fetch(`${RUNTIME_URL}/proposals/${req.params.id}/${action}`, { method: "POST" });
    res.status(response.status).json(await response.json());
  });
}

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

  const start = async (adapter: ChannelAdapter) => {
    adapters.push(adapter);
    await adapter.start((msg) => handleIncoming(pairingStore, RUNTIME_URL, adapter, msg));
    console.log(`[gateway] ${adapter.name} channel started`);
  };

  const telegramToken = process.env.TELEGRAM_BOT_TOKEN;
  if (telegramToken) {
    await start(new TelegramAdapter(telegramToken));
  } else {
    console.log("[gateway] TELEGRAM_BOT_TOKEN not set — telegram channel disabled");
  }

  const discordToken = process.env.DISCORD_BOT_TOKEN;
  if (discordToken) {
    await start(new DiscordAdapter(discordToken));
  }

  const slackAppToken = process.env.SLACK_APP_TOKEN;
  const slackBotToken = process.env.SLACK_BOT_TOKEN;
  if (slackAppToken && slackBotToken) {
    await start(new SlackAdapter(slackAppToken, slackBotToken));
  } else if (slackAppToken || slackBotToken) {
    // Half-configured is almost always a mistake worth naming out loud.
    console.warn("[gateway] slack needs BOTH SLACK_APP_TOKEN and SLACK_BOT_TOKEN — channel disabled");
  }

  if (adapters.length === 0) {
    console.log("[gateway] no channels configured — HTTP API only");
  }
  return adapters;
}

// Serve the built dashboard, when one has been built into the image. Mounted
// last so it never shadows an API route above.
const dashboardDir = process.env.DASHBOARD_DIR ?? "../dashboard/dist";
if (existsSync(dashboardDir)) {
  app.use(express.static(dashboardDir));
  app.get("*", (_req, res) => res.sendFile(resolve(dashboardDir, "index.html")));
  console.log(`[gateway] serving dashboard from ${dashboardDir}`);
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
