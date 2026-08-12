// User and session storage, JSON-file backed in the gateway's data volume —
// the same approach as PairingStore, for the same reason: a single-admin
// self-hosted deployment doesn't need a database, and a file is easy to back
// up and inspect.
//
// Session tokens are stored HASHED. The file sits next to the pairing state
// on a volume that gets backed up and copied around; if it leaks, plaintext
// tokens would be immediately usable as logged-in sessions, whereas hashes
// are not.

import { createHash, randomBytes, randomUUID } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { hashPassword, verifyPassword } from "./passwords.js";

export interface User {
  id: string;
  username: string;
  passwordHash: string;
  createdAt: string;
}

export interface Session {
  tokenHash: string;
  userId: string;
  createdAt: string;
  expiresAt: string;
}

interface StoreData {
  users: User[];
  sessions: Session[];
}

const SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export function normalizeUsername(username: string): string {
  return username.trim().toLowerCase();
}

export function validateUsername(username: string): string | null {
  const name = normalizeUsername(username);
  if (!/^[a-z0-9][a-z0-9._-]{2,31}$/.test(name)) {
    return "Username must be 3-32 characters: letters, digits, dot, dash or underscore.";
  }
  return null;
}

export class AuthStore {
  private readonly path: string;
  private data: StoreData;

  constructor(dataDir: string) {
    this.path = join(dataDir, "auth.json");
    this.data = this.load();
  }

  private load(): StoreData {
    if (existsSync(this.path)) {
      try {
        const parsed = JSON.parse(readFileSync(this.path, "utf-8")) as Partial<StoreData>;
        return { users: parsed.users ?? [], sessions: parsed.sessions ?? [] };
      } catch {
        // A corrupt auth file must not silently become "no users", which would
        // re-open first-run setup to whoever asks. Fail loudly instead.
        throw new Error(
          `${this.path} exists but could not be parsed. Refusing to start with an ` +
            `unreadable user store — restore it from backup or delete it deliberately.`
        );
      }
    }
    return { users: [], sessions: [] };
  }

  private save(): void {
    mkdirSync(dirname(this.path), { recursive: true });
    const tmp = `${this.path}.tmp`;
    writeFileSync(tmp, JSON.stringify(this.data, null, 2), { encoding: "utf-8", mode: 0o600 });
    renameSync(tmp, this.path); // atomic: never leave a half-written user store
    try {
      chmodSync(this.path, 0o600);
    } catch {
      // Best effort — some filesystems (e.g. a Windows bind mount) don't support it.
    }
  }

  // --- users ---------------------------------------------------------------

  hasUsers(): boolean {
    return this.data.users.length > 0;
  }

  listUsers(): Array<Omit<User, "passwordHash">> {
    return this.data.users.map(({ passwordHash: _ignored, ...rest }) => rest);
  }

  findByUsername(username: string): User | undefined {
    const name = normalizeUsername(username);
    return this.data.users.find((u) => u.username === name);
  }

  async createUser(username: string, password: string): Promise<User> {
    const name = normalizeUsername(username);
    if (this.findByUsername(name)) throw new Error(`user '${name}' already exists`);
    const user: User = {
      id: randomUUID(),
      username: name,
      passwordHash: await hashPassword(password),
      createdAt: new Date().toISOString(),
    };
    this.data.users.push(user);
    this.save();
    return user;
  }

  async verifyCredentials(username: string, password: string): Promise<User | null> {
    const user = this.findByUsername(username);
    if (!user) return null;
    return (await verifyPassword(password, user.passwordHash)) ? user : null;
  }

  async setPassword(userId: string, password: string): Promise<void> {
    const user = this.data.users.find((u) => u.id === userId);
    if (!user) throw new Error("no such user");
    user.passwordHash = await hashPassword(password);
    // Changing a password invalidates every other session for that user —
    // otherwise "change my password because it leaked" doesn't lock anyone out.
    this.data.sessions = this.data.sessions.filter((s) => s.userId !== userId);
    this.save();
  }

  deleteUser(userId: string): void {
    if (this.data.users.length <= 1) {
      throw new Error("cannot delete the last remaining user");
    }
    this.data.users = this.data.users.filter((u) => u.id !== userId);
    this.data.sessions = this.data.sessions.filter((s) => s.userId !== userId);
    this.save();
  }

  // --- sessions ------------------------------------------------------------

  /** Returns the plaintext token; only its hash is persisted. */
  createSession(userId: string, ttlMs: number = SESSION_TTL_MS): string {
    this.pruneExpired();
    const token = randomBytes(32).toString("hex");
    this.data.sessions.push({
      tokenHash: hashToken(token),
      userId,
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + ttlMs).toISOString(),
    });
    this.save();
    return token;
  }

  resolveSession(token: string): User | null {
    const session = this.data.sessions.find((s) => s.tokenHash === hashToken(token));
    if (!session) return null;
    if (new Date(session.expiresAt).getTime() < Date.now()) {
      this.destroySession(token);
      return null;
    }
    return this.data.users.find((u) => u.id === session.userId) ?? null;
  }

  destroySession(token: string): void {
    const hash = hashToken(token);
    const before = this.data.sessions.length;
    this.data.sessions = this.data.sessions.filter((s) => s.tokenHash !== hash);
    if (this.data.sessions.length !== before) this.save();
  }

  destroyAllSessions(userId: string): void {
    this.data.sessions = this.data.sessions.filter((s) => s.userId !== userId);
    this.save();
  }

  countSessions(userId: string): number {
    this.pruneExpired();
    return this.data.sessions.filter((s) => s.userId === userId).length;
  }

  private pruneExpired(): void {
    const now = Date.now();
    const before = this.data.sessions.length;
    this.data.sessions = this.data.sessions.filter((s) => new Date(s.expiresAt).getTime() >= now);
    if (this.data.sessions.length !== before) this.save();
  }
}
