import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { PairingStore } from "./store.js";

function makeStore(ttlMs?: number): { store: PairingStore; dir: string; path: string } {
  const dir = mkdtempSync(join(tmpdir(), "yozhan-pairing-"));
  const path = join(dir, "pairings.json");
  return { store: ttlMs === undefined ? new PairingStore(path) : new PairingStore(path, ttlMs), dir, path };
}

test("unknown identity is not paired", () => {
  const { store, dir } = makeStore();
  assert.equal(store.isPaired("telegram", "123"), false);
  rmSync(dir, { recursive: true, force: true });
});

test("approving a pending code pairs the identity", () => {
  const { store, dir } = makeStore();
  const pending = store.getOrCreatePendingCode("telegram", "123");
  assert.equal(pending.channel, "telegram");
  assert.equal(store.isPaired("telegram", "123"), false);

  const identity = store.approve(pending.code);
  assert.ok(identity);
  assert.equal(identity?.externalId, "123");
  assert.equal(store.isPaired("telegram", "123"), true);
  rmSync(dir, { recursive: true, force: true });
});

test("approving an unknown code returns null", () => {
  const { store, dir } = makeStore();
  assert.equal(store.approve("NOPE1234"), null);
  rmSync(dir, { recursive: true, force: true });
});

test("requesting a pending code twice for the same identity returns the same code", () => {
  const { store, dir } = makeStore();
  const first = store.getOrCreatePendingCode("telegram", "123");
  const second = store.getOrCreatePendingCode("telegram", "123");
  assert.equal(first.code, second.code);
  rmSync(dir, { recursive: true, force: true });
});

test("different identities get different pending codes", () => {
  const { store, dir } = makeStore();
  const a = store.getOrCreatePendingCode("telegram", "123");
  const b = store.getOrCreatePendingCode("telegram", "456");
  assert.notEqual(a.code, b.code);
  rmSync(dir, { recursive: true, force: true });
});

test("pairing state persists across store instances (same file)", () => {
  const { store: store1, dir, path } = makeStore();
  const pending = store1.getOrCreatePendingCode("telegram", "123");
  store1.approve(pending.code);

  const store2 = new PairingStore(path);
  assert.equal(store2.isPaired("telegram", "123"), true);
  rmSync(dir, { recursive: true, force: true });
});

test("expired pending codes cannot be approved and are cleaned up", () => {
  const { store, dir } = makeStore(-1000); // already expired the instant it's created
  const pending = store.getOrCreatePendingCode("telegram", "123");
  assert.equal(store.approve(pending.code), null);
  assert.equal(store.listPending().length, 0);
  rmSync(dir, { recursive: true, force: true });
});
