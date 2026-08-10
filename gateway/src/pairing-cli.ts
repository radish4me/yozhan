#!/usr/bin/env node
// Admin CLI for approving pairing requests without needing a dashboard yet
// (that lands in Phase 7). Talks to the Gateway's own /pairing/* endpoints.
//
//   GATEWAY_URL=http://localhost:3000 GATEWAY_ADMIN_TOKEN=... \
//     node dist/pairing-cli.js list
//   ... node dist/pairing-cli.js approve ABCD1234

const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://localhost:3000";
const ADMIN_TOKEN = process.env.GATEWAY_ADMIN_TOKEN;

async function main(): Promise<void> {
  const [, , command, arg] = process.argv;

  if (!ADMIN_TOKEN) {
    console.error("GATEWAY_ADMIN_TOKEN is not set in this shell's environment");
    process.exitCode = 1;
    return;
  }
  const headers = { authorization: `Bearer ${ADMIN_TOKEN}`, "content-type": "application/json" };

  if (command === "list") {
    const resp = await fetch(`${GATEWAY_URL}/pairing/pending`, { headers });
    const pending = (await resp.json()) as Array<{ code: string; channel: string; externalId: string; expiresAt: string }>;
    if (!Array.isArray(pending) || pending.length === 0) {
      console.log("no pending pairing requests");
      return;
    }
    for (const p of pending) {
      console.log(`${p.code}  ${p.channel}:${p.externalId}  expires ${p.expiresAt}`);
    }
    return;
  }

  if (command === "approve") {
    if (!arg) {
      console.error("usage: pairing-cli approve <code>");
      process.exitCode = 1;
      return;
    }
    const resp = await fetch(`${GATEWAY_URL}/pairing/approve`, {
      method: "POST",
      headers,
      body: JSON.stringify({ code: arg }),
    });
    const data = (await resp.json()) as { error?: string; channel?: string; externalId?: string };
    if (!resp.ok) {
      console.error(`error: ${data.error ?? resp.statusText}`);
      process.exitCode = 1;
      return;
    }
    console.log(`paired ${data.channel}:${data.externalId}`);
    return;
  }

  console.error("usage: pairing-cli <list|approve> [code]");
  process.exitCode = 1;
}

main();
