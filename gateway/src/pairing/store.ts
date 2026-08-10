// PairingStore: unknown senders get a short-lived pairing code; an admin
// approves it once (see index.ts's /pairing/approve and pairing-cli.ts);
// the identity is then persisted as paired. JSON-file backed — no database
// dependency for a single-admin, self-hosted deployment. See ARCHITECTURE.md
// section 3.1 and ROADMAP.md Phase 5.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { generatePairingCode } from "./codes.js";

export interface PendingPairing {
  code: string;
  channel: string;
  externalId: string;
  createdAt: string;
  expiresAt: string;
}

export interface PairedIdentity {
  channel: string;
  externalId: string;
  pairedAt: string;
}

interface StoreData {
  paired: Record<string, PairedIdentity>;
  pending: Record<string, PendingPairing>;
}

const DEFAULT_TTL_MS = 15 * 60 * 1000;

function identityKey(channel: string, externalId: string): string {
  return `${channel}:${externalId}`;
}

export class PairingStore {
  private readonly path: string;
  private readonly ttlMs: number;
  private data: StoreData;

  constructor(path: string, ttlMs: number = DEFAULT_TTL_MS) {
    this.path = path;
    this.ttlMs = ttlMs;
    this.data = this.load();
  }

  private load(): StoreData {
    if (existsSync(this.path)) {
      try {
        return JSON.parse(readFileSync(this.path, "utf-8")) as StoreData;
      } catch {
        // corrupt file — start fresh rather than crash the gateway
      }
    }
    return { paired: {}, pending: {} };
  }

  private save(): void {
    mkdirSync(dirname(this.path), { recursive: true });
    writeFileSync(this.path, JSON.stringify(this.data, null, 2), "utf-8");
  }

  isPaired(channel: string, externalId: string): boolean {
    return identityKey(channel, externalId) in this.data.paired;
  }

  /** Returns the existing pending code for this identity if it hasn't expired, otherwise mints a new one. */
  getOrCreatePendingCode(channel: string, externalId: string): PendingPairing {
    this.cleanExpired();
    const existing = Object.values(this.data.pending).find(
      (p) => p.channel === channel && p.externalId === externalId
    );
    if (existing) return existing;

    const now = Date.now();
    const pending: PendingPairing = {
      code: generatePairingCode(),
      channel,
      externalId,
      createdAt: new Date(now).toISOString(),
      expiresAt: new Date(now + this.ttlMs).toISOString(),
    };
    this.data.pending[pending.code] = pending;
    this.save();
    return pending;
  }

  approve(code: string): PairedIdentity | null {
    this.cleanExpired();
    const pending = this.data.pending[code];
    if (!pending) return null;

    const identity: PairedIdentity = {
      channel: pending.channel,
      externalId: pending.externalId,
      pairedAt: new Date().toISOString(),
    };
    this.data.paired[identityKey(identity.channel, identity.externalId)] = identity;
    delete this.data.pending[code];
    this.save();
    return identity;
  }

  listPending(): PendingPairing[] {
    this.cleanExpired();
    return Object.values(this.data.pending);
  }

  listPaired(): PairedIdentity[] {
    return Object.values(this.data.paired);
  }

  private cleanExpired(): void {
    const now = Date.now();
    let changed = false;
    for (const [code, pending] of Object.entries(this.data.pending)) {
      if (new Date(pending.expiresAt).getTime() < now) {
        delete this.data.pending[code];
        changed = true;
      }
    }
    if (changed) this.save();
  }
}
