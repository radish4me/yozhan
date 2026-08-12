// Password hashing with scrypt from node:crypto — a memory-hard KDF, and
// already in the standard library, so this adds no dependency to audit.
//
// Never compare hashes with ===. String comparison short-circuits on the
// first differing byte, which leaks how much of a guess was correct through
// timing; timingSafeEqual does not.

import { randomBytes, scrypt, timingSafeEqual, type ScryptOptions } from "node:crypto";

// promisify() resolves to scrypt's 3-argument overload and drops the options
// parameter, so the cost parameters below would be silently ignored. Wrap it
// by hand instead.
function scryptAsync(
  password: string,
  salt: Buffer,
  keylen: number,
  options: ScryptOptions
): Promise<Buffer> {
  return new Promise((resolvePromise, reject) => {
    scrypt(password, salt, keylen, options, (err, derivedKey) =>
      err ? reject(err) : resolvePromise(derivedKey)
    );
  });
}

const KEY_LENGTH = 64;
const SALT_LENGTH = 16;
// 128 * N * r bytes of memory = 16 MB per hash. Costly enough to make offline
// cracking slow, cheap enough that a login on a 2-vCPU VPS stays snappy.
const SCRYPT_PARAMS = { N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };

export const MIN_PASSWORD_LENGTH = 12;

export function validatePassword(password: string): string | null {
  if (typeof password !== "string" || password.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (password.length > 1024) {
    // Bound the work an unauthenticated caller can make us do.
    return "Password must be at most 1024 characters.";
  }
  return null;
}

/** Returns "scrypt$<salt hex>$<hash hex>". */
export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(SALT_LENGTH);
  const derived = await scryptAsync(password, salt, KEY_LENGTH, SCRYPT_PARAMS);
  return `scrypt$${salt.toString("hex")}$${derived.toString("hex")}`;
}

export async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const [scheme, saltHex, hashHex] = stored.split("$");
  if (scheme !== "scrypt" || !saltHex || !hashHex) return false;

  const expected = Buffer.from(hashHex, "hex");
  const derived = await scryptAsync(
    password,
    Buffer.from(saltHex, "hex"),
    expected.length,
    SCRYPT_PARAMS
  );
  return derived.length === expected.length && timingSafeEqual(derived, expected);
}
