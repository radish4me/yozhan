import assert from "node:assert/strict";
import { test } from "node:test";
import { toIncomingMessage } from "./slack.js";

const envelope = (event: Record<string, unknown>) => ({
  type: "events_api",
  envelope_id: "e1",
  payload: { event },
});

test("extracts a user message", () => {
  const msg = toIncomingMessage("slack", envelope({ type: "message", text: "hello", channel: "C1" }));
  assert.deepEqual(msg, { channel: "slack", externalId: "C1", text: "hello" });
});

test("ignores bot messages", () => {
  const payload = envelope({ type: "message", text: "hi", channel: "C1", bot_id: "B1" });
  assert.equal(toIncomingMessage("slack", payload), null);
});

test("ignores subtyped events like edits and joins", () => {
  const payload = envelope({ type: "message", text: "hi", channel: "C1", subtype: "message_changed" });
  assert.equal(toIncomingMessage("slack", payload), null);
});

test("ignores non-events_api envelopes such as hello/disconnect", () => {
  assert.equal(toIncomingMessage("slack", { type: "hello" }), null);
});

test("ignores non-message events", () => {
  assert.equal(toIncomingMessage("slack", envelope({ type: "reaction_added", channel: "C1" })), null);
});

test("ignores empty text", () => {
  assert.equal(toIncomingMessage("slack", envelope({ type: "message", text: "", channel: "C1" })), null);
});
