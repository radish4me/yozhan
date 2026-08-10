import assert from "node:assert/strict";
import { test } from "node:test";
import { extractIncomingMessages } from "./telegram.js";

test("extracts text messages and computes the next offset", () => {
  const updates = [
    { update_id: 5, message: { chat: { id: 111 }, text: "hi" } },
    { update_id: 6, message: { chat: { id: 111 }, text: "second" } },
  ];
  const { messages, nextOffset } = extractIncomingMessages("telegram", updates);

  assert.deepEqual(messages, [
    { channel: "telegram", externalId: "111", text: "hi" },
    { channel: "telegram", externalId: "111", text: "second" },
  ]);
  assert.equal(nextOffset, 7);
});

test("skips non-text updates (e.g. stickers) but still advances the offset", () => {
  const updates = [{ update_id: 9, message: { chat: { id: 111 } } }];
  const { messages, nextOffset } = extractIncomingMessages("telegram", updates);

  assert.deepEqual(messages, []);
  assert.equal(nextOffset, 10);
});

test("empty updates yields no messages and a null offset", () => {
  const { messages, nextOffset } = extractIncomingMessages("telegram", []);
  assert.deepEqual(messages, []);
  assert.equal(nextOffset, null);
});
