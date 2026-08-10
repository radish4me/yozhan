import assert from "node:assert/strict";
import { test } from "node:test";
import { callRuntimeChat } from "./runtime-client.js";

test("posts message and session id, returns the parsed response", async () => {
  const originalFetch = globalThis.fetch;
  let capturedUrl = "";
  let capturedBody: unknown;

  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    capturedUrl = url;
    capturedBody = JSON.parse(init?.body as string);
    return { json: async () => ({ content: "hello" }) } as Response;
  }) as typeof fetch;

  try {
    const result = await callRuntimeChat("http://runtime:8787", "hi", "telegram:123");
    assert.equal(capturedUrl, "http://runtime:8787/chat");
    assert.deepEqual(capturedBody, { message: "hi", session_id: "telegram:123" });
    assert.equal(result.content, "hello");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
