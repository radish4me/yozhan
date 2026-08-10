import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { ChannelAdapter, IncomingMessage } from "./channels/types.js";
import { handleIncoming } from "./index.js";
import { PairingStore } from "./pairing/store.js";

class RecordingAdapter implements ChannelAdapter {
  readonly name = "telegram";
  sent: Array<{ externalId: string; text: string }> = [];

  async start(): Promise<void> {}
  async stop(): Promise<void> {}
  async sendMessage(externalId: string, text: string): Promise<void> {
    this.sent.push({ externalId, text });
  }
}

function makeStore(): { store: PairingStore; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), "yozhan-gw-index-"));
  return { store: new PairingStore(join(dir, "pairings.json")), dir };
}

test("unpaired sender gets a pairing-code prompt and becomes pending", async () => {
  const { store, dir } = makeStore();
  const adapter = new RecordingAdapter();
  const msg: IncomingMessage = { channel: "telegram", externalId: "111", text: "hello" };

  await handleIncoming(store, "http://runtime:8787", adapter, msg);

  assert.equal(adapter.sent.length, 1);
  assert.match(adapter.sent[0].text, /not paired yet/);
  assert.equal(store.listPending().length, 1);
  assert.equal(store.isPaired("telegram", "111"), false);
  rmSync(dir, { recursive: true, force: true });
});

test("paired sender's message is routed to the runtime and the reply sent back", async () => {
  const { store, dir } = makeStore();
  const pending = store.getOrCreatePendingCode("telegram", "111");
  store.approve(pending.code);

  const adapter = new RecordingAdapter();
  const msg: IncomingMessage = { channel: "telegram", externalId: "111", text: "hi there" };

  const originalFetch = globalThis.fetch;
  let capturedBody: unknown;
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    capturedBody = JSON.parse(init?.body as string);
    return { json: async () => ({ content: "hello back" }) } as Response;
  }) as typeof fetch;

  try {
    await handleIncoming(store, "http://runtime:8787", adapter, msg);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(capturedBody, { message: "hi there", session_id: "telegram:111" });
  assert.deepEqual(adapter.sent, [{ externalId: "111", text: "hello back" }]);
  rmSync(dir, { recursive: true, force: true });
});

test("runtime failure is reported back to the sender instead of throwing", async () => {
  const { store, dir } = makeStore();
  const pending = store.getOrCreatePendingCode("telegram", "111");
  store.approve(pending.code);

  const adapter = new RecordingAdapter();
  const msg: IncomingMessage = { channel: "telegram", externalId: "111", text: "hi" };

  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => {
    throw new Error("connection refused");
  }) as typeof fetch;

  try {
    await handleIncoming(store, "http://runtime:8787", adapter, msg);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(adapter.sent.length, 1);
  assert.match(adapter.sent[0].text, /error reaching yozhan runtime/);
  rmSync(dir, { recursive: true, force: true });
});
