import assert from "node:assert/strict";
import { test } from "node:test";
import { toIncomingMessage } from "./discord.js";

const dispatch = (d: Record<string, unknown>) => ({ op: 0, t: "MESSAGE_CREATE", d });

test("extracts a user message", () => {
  const msg = toIncomingMessage("discord", dispatch({ content: "hello", channel_id: "42", author: { id: "u1" } }));
  assert.deepEqual(msg, { channel: "discord", externalId: "42", text: "hello" });
});

test("ignores messages from bots so two bots cannot loop", () => {
  const payload = dispatch({ content: "hi", channel_id: "42", author: { id: "b1", bot: true } });
  assert.equal(toIncomingMessage("discord", payload), null);
});

test("ignores empty and whitespace-only content", () => {
  assert.equal(toIncomingMessage("discord", dispatch({ content: "   ", channel_id: "42", author: {} })), null);
});

test("ignores non-dispatch opcodes", () => {
  assert.equal(toIncomingMessage("discord", { op: 11, t: "MESSAGE_CREATE", d: { content: "x" } }), null);
});

test("ignores other dispatch events", () => {
  assert.equal(toIncomingMessage("discord", { op: 0, t: "TYPING_START", d: { content: "x" } }), null);
});

test("ignores a payload with no channel", () => {
  assert.equal(toIncomingMessage("discord", dispatch({ content: "hi", author: {} })), null);
});
