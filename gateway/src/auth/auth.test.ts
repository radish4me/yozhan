import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { LoginThrottle, parseCookies } from "./middleware.js";
import { MIN_PASSWORD_LENGTH, hashPassword, validatePassword, verifyPassword } from "./passwords.js";
import { AuthStore, hashToken, validateUsername } from "./store.js";

function tempDir(): string {
  return mkdtempSync(join(tmpdir(), "yozhan-auth-"));
}

// --- password hashing -------------------------------------------------------

test("a correct password verifies", async () => {
  const hash = await hashPassword("correct horse battery staple");
  assert.equal(await verifyPassword("correct horse battery staple", hash), true);
});

test("a wrong password does not verify", async () => {
  const hash = await hashPassword("correct horse battery staple");
  assert.equal(await verifyPassword("correct horse battery stapl", hash), false);
});

test("the same password hashes differently each time", async () => {
  // Per-password salt: identical passwords must not produce identical hashes,
  // or the store leaks which users share a password.
  const [a, b] = await Promise.all([hashPassword("same password here"), hashPassword("same password here")]);
  assert.notEqual(a, b);
});

test("the stored hash does not contain the password", async () => {
  const hash = await hashPassword("hunter2hunter2hunter2");
  assert.equal(hash.includes("hunter2"), false);
  assert.match(hash, /^scrypt\$[0-9a-f]+\$[0-9a-f]+$/);
});

test("a malformed stored hash fails closed", async () => {
  for (const bad of ["", "notahash", "md5$aa$bb", "scrypt$onlyonepart"]) {
    assert.equal(await verifyPassword("anything", bad), false);
  }
});

test("short passwords are rejected", () => {
  assert.ok(validatePassword("a".repeat(MIN_PASSWORD_LENGTH - 1)));
  assert.equal(validatePassword("a".repeat(MIN_PASSWORD_LENGTH)), null);
});

test("absurdly long passwords are rejected", () => {
  // Bounds the scrypt work an unauthenticated caller can trigger.
  assert.ok(validatePassword("a".repeat(2000)));
});

// --- usernames --------------------------------------------------------------

test("valid usernames are accepted", () => {
  for (const name of ["radha", "user_1", "a.b-c", "abc"]) {
    assert.equal(validateUsername(name), null, name);
  }
});

test("invalid usernames are rejected", () => {
  for (const name of ["ab", "", "has space", "-leading", "user@host", "a".repeat(33)]) {
    assert.ok(validateUsername(name), name);
  }
});

// --- user store -------------------------------------------------------------

test("a fresh store has no users", () => {
  const dir = tempDir();
  assert.equal(new AuthStore(dir).hasUsers(), false);
  rmSync(dir, { recursive: true, force: true });
});

test("users and credentials persist across restarts", async () => {
  const dir = tempDir();
  const first = new AuthStore(dir);
  await first.createUser("Radha", "a-good-long-password");

  const second = new AuthStore(dir);
  assert.equal(second.hasUsers(), true);
  assert.ok(await second.verifyCredentials("radha", "a-good-long-password"));
  rmSync(dir, { recursive: true, force: true });
});

test("usernames are case-insensitive and cannot be duplicated", async () => {
  const dir = tempDir();
  const store = new AuthStore(dir);
  await store.createUser("Radha", "a-good-long-password");
  await assert.rejects(() => store.createUser("RADHA", "another-long-password"));
  rmSync(dir, { recursive: true, force: true });
});

test("the password hash is never returned by listUsers", async () => {
  const dir = tempDir();
  const store = new AuthStore(dir);
  await store.createUser("radha", "a-good-long-password");
  assert.equal("passwordHash" in store.listUsers()[0], false);
  rmSync(dir, { recursive: true, force: true });
});

test("a corrupt auth file refuses to start rather than reopening setup", () => {
  // Treating an unreadable store as "no users" would silently re-expose
  // first-run setup to whoever asks for it.
  const dir = tempDir();
  writeFileSync(join(dir, "auth.json"), "{ not json", "utf-8");
  assert.throws(() => new AuthStore(dir), /could not be parsed/);
  rmSync(dir, { recursive: true, force: true });
});

// --- sessions ---------------------------------------------------------------

test("a session token resolves to its user", async () => {
  const dir = tempDir();
  const store = new AuthStore(dir);
  const user = await store.createUser("radha", "a-good-long-password");
  const token = store.createSession(user.id);
  assert.equal(store.resolveSession(token)?.id, user.id);
  rmSync(dir, { recursive: true, force: true });
});

test("session tokens are stored hashed, not in plaintext", async () => {
  const dir = tempDir();
  const store = new AuthStore(dir);
  const user = await store.createUser("radha", "a-good-long-password");
  const token = store.createSession(user.id);

  const onDisk = readFileSync(join(dir, "auth.json"), "utf-8");
  assert.equal(onDisk.includes(token), false, "raw token must not be written to disk");
  assert.ok(onDisk.includes(hashToken(token)));
  rmSync(dir, { recursive: true, force: true });
});

test("an unknown or destroyed token resolves to nothing", async () => {
  const dir = tempDir();
  const store = new AuthStore(dir);
  const user = await store.createUser("radha", "a-good-long-password");
  const token = store.createSession(user.id);

  assert.equal(store.resolveSession("deadbeef"), null);
  store.destroySession(token);
  assert.equal(store.resolveSession(token), null);
  rmSync(dir, { recursive: true, force: true });
});

test("an expired session is rejected", async () => {
  const dir = tempDir();
  const store = new AuthStore(dir);
  const user = await store.createUser("radha", "a-good-long-password");
  const token = store.createSession(user.id, -1000); // already expired
  assert.equal(store.resolveSession(token), null);
  rmSync(dir, { recursive: true, force: true });
});

test("changing a password invalidates existing sessions", async () => {
  // "Change my password because it leaked" has to actually lock out whoever
  // holds a stolen session.
  const dir = tempDir();
  const store = new AuthStore(dir);
  const user = await store.createUser("radha", "a-good-long-password");
  const stolen = store.createSession(user.id);

  await store.setPassword(user.id, "a-brand-new-password");

  assert.equal(store.resolveSession(stolen), null);
  assert.ok(await store.verifyCredentials("radha", "a-brand-new-password"));
  assert.equal(await store.verifyCredentials("radha", "a-good-long-password"), null);
  rmSync(dir, { recursive: true, force: true });
});

test("revoking all sessions signs every device out", async () => {
  const dir = tempDir();
  const store = new AuthStore(dir);
  const user = await store.createUser("radha", "a-good-long-password");
  const a = store.createSession(user.id);
  const b = store.createSession(user.id);

  store.destroyAllSessions(user.id);

  assert.equal(store.resolveSession(a), null);
  assert.equal(store.resolveSession(b), null);
  rmSync(dir, { recursive: true, force: true });
});

test("the last user cannot be deleted", async () => {
  const dir = tempDir();
  const store = new AuthStore(dir);
  const user = await store.createUser("radha", "a-good-long-password");
  assert.throws(() => store.deleteUser(user.id), /last remaining user/);
  rmSync(dir, { recursive: true, force: true });
});

// --- cookies ----------------------------------------------------------------

test("cookie parsing handles multiple values and encoding", () => {
  const cookies = parseCookies("a=1; yozhan_session=abc%20def; b=2");
  assert.equal(cookies.yozhan_session, "abc def");
  assert.equal(cookies.a, "1");
});

test("cookie parsing tolerates a missing or malformed header", () => {
  assert.deepEqual(parseCookies(undefined), {});
  assert.deepEqual(parseCookies("nonsense"), {});
});

// --- login throttle ---------------------------------------------------------

test("the first few failures are not blocked", () => {
  const throttle = new LoginThrottle(3, 1000);
  for (let i = 0; i < 3; i++) throttle.recordFailure("radha", "1.2.3.4");
  assert.equal(throttle.retryAfterMs("radha", "1.2.3.4"), 0);
});

test("repeated failures start blocking, and the delay grows", () => {
  const throttle = new LoginThrottle(3, 1000);
  for (let i = 0; i < 4; i++) throttle.recordFailure("radha", "1.2.3.4");
  const first = throttle.retryAfterMs("radha", "1.2.3.4");
  assert.ok(first > 0);

  throttle.recordFailure("radha", "1.2.3.4");
  assert.ok(throttle.retryAfterMs("radha", "1.2.3.4") > first);
});

test("a successful login clears the throttle", () => {
  const throttle = new LoginThrottle(1, 1000);
  throttle.recordFailure("radha", "1.2.3.4");
  throttle.recordFailure("radha", "1.2.3.4");
  assert.ok(throttle.retryAfterMs("radha", "1.2.3.4") > 0);

  throttle.recordSuccess("radha", "1.2.3.4");
  assert.equal(throttle.retryAfterMs("radha", "1.2.3.4"), 0);
});

test("throttling one account does not lock out another", () => {
  const throttle = new LoginThrottle(1, 1000);
  for (let i = 0; i < 3; i++) throttle.recordFailure("radha", "1.2.3.4");
  assert.equal(throttle.retryAfterMs("someone-else", "1.2.3.4"), 0);
});
