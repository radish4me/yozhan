// Pairing-code generation. Excludes visually ambiguous characters (0/O, 1/I)
// so a code is easy to read aloud or retype — see ARCHITECTURE.md section 3.1.

import { randomInt } from "node:crypto";

const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

export function generatePairingCode(length = 8): string {
  let code = "";
  for (let i = 0; i < length; i++) {
    code += ALPHABET[randomInt(ALPHABET.length)];
  }
  return code;
}
