// yozhan Gateway entrypoint. Channels (Telegram/Discord/Slack) with pairing,
// the dashboard API, and — since Phase 9 — session-based authentication in
// front of all of it.
//
// Every API route below requires a logged-in session or the admin bearer
// token. The only unauthenticated endpoints are /health (for container
// healthchecks), the /auth/* endpoints themselves, and the dashboard's static
// assets, which contain no data.
//
// See ARCHITECTURE.md section 3.1 and ROADMAP.md Phases 5 and 9.

import express, { type Request, type Response } from "express";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { buildRequireAuth } from "./auth/middleware.js";
import { buildAuthRouter } from "./auth/routes.js";
import { AuthStore } from "./auth/store.js";
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
const authStore = new AuthStore(DATA_DIR);
const requireAuth = buildRequireAuth(authStore, ADMIN_TOKEN);

const app = express();
// Behind nginx/Caddy, req.protocol should reflect the client's scheme rather
// than the plain-HTTP hop from the proxy — that is what decides whether the
// session cookie gets the Secure flag.
app.set("trust proxy", process.env.TRUST_PROXY ?? true);
app.use(express.json());

// Unauthenticated: container healthchecks need it. Deliberately says nothing
// about the deployment beyond liveness.
app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.use(buildAuthRouter(authStore, requireAuth));

// The dashboard's static assets are served unauthenticated on purpose: they
// contain no data, and the app has to load before it can render a login form.
// Everything it *fetches* is behind requireAuth below.
const dashboardDir = process.env.DASHBOARD_DIR ?? "../dashboard/dist";
const hasDashboard = existsSync(dashboardDir);
// Paths the SPA fallback must not answer with HTML. Keep in sync with the
// routes below — a missing entry here turns a broken API call into a
// confusing "why did I get the index page?".
const API_PREFIXES = [
  "/auth",
  "/chat",
  "/agents",
  "/skills",
  "/providers",
  "/costs",
  "/proposals",
  "/pairing",
  "/health",
  "/config",
  "/secrets",
  "/memory",
  "/orchestrate",
];

if (hasDashboard) {
  app.use(express.static(dashboardDir));
  // SPA fallback, in front of the guard so a deep link still loads the app and
  // can render the login form. API paths are handed onward to their real
  // handlers (and the guard) rather than being answered with HTML.
  app.get("*", (req, res, next) => {
    if (API_PREFIXES.some((prefix) => req.path === prefix || req.path.startsWith(`${prefix}/`))) {
      next();
      return;
    }
    res.sendFile(resolve(dashboardDir, "index.html"));
  });
  console.log(`[gateway] serving dashboard from ${dashboardDir}`);
}

// Everything past this point requires authentication.
app.use(requireAuth);

app.post("/chat", async (req, res) => {
  const response = await fetch(`${RUNTIME_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req.body),
  });
  const data = await response.json();
  res.status(response.status).json(data);
});

/**
 * Forwards a request to the runtime, preserving method, query and body.
 *
 * The logged-in username rides along in X-Yozhan-User so the runtime can
 * record who changed a config file — the gateway is the only component that
 * knows who is signed in.
 */
async function proxyToRuntime(req: Request, res: Response): Promise<void> {
  const query = new URLSearchParams(req.query as Record<string, string>).toString();
  const hasBody = req.method !== "GET" && req.method !== "DELETE" && req.body !== undefined;

  try {
    const response = await fetch(`${RUNTIME_URL}${req.path}${query ? `?${query}` : ""}`, {
      method: req.method,
      headers: {
        "content-type": "application/json",
        "x-yozhan-user": req.user?.username ?? "unknown",
      },
      body: hasBody ? JSON.stringify(req.body) : undefined,
    });
    const text = await response.text();
    res.status(response.status);
    try {
      res.json(JSON.parse(text));
    } catch {
      res.send(text);
    }
  } catch (err) {
    res.status(502).json({ error: `runtime unreachable: ${(err as Error).message}` });
  }
}

// Everything the dashboard reads or edits lives on the runtime, which is not
// exposed to the host network; the gateway is its only way in.
const PROXIED = [
  "/agents",
  "/skills",
  "/skills/*",
  "/providers",
  "/costs",
  "/proposals",
  "/proposals/*",
  "/config",
  "/config/*",
  "/secrets",
  "/secrets/*",
  "/memory/*",
  "/orchestrate",
];
for (const path of PROXIED) {
  app.all(path, proxyToRuntime);
}

app.get("/pairing/pending", (_req, res) => {
  res.json(pairingStore.listPending());
});

app.get("/pairing/paired", (_req, res) => {
  res.json(pairingStore.listPaired());
});

app.post("/pairing/approve", (req, res) => {
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
