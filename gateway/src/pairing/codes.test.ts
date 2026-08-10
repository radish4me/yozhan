import assert from "node:assert/strict";
import { test } from "node:test";
import { generatePairingCode } from "./codes.js";

test("generates a code of the requested length", () => {
  const code = generatePairingCode(8);
  assert.equal(code.length, 8);
});

test("defaults to length 8", () => {
  assert.equal(generatePairingCode().length, 8);
});

test("excludes visually ambiguous characters", () => {
  const code = generatePairingCode(300); // long enough to very likely hit any excluded char if present
  for (const ch of ["0", "O", "1", "I"]) {
    assert.equal(code.includes(ch), false, `code should not contain '${ch}'`);
  }
});
