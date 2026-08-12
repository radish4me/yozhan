// Session cookie handling and the guard that every API route sits behind.

import type { NextFunction, Request, Response } from "express";
import type { AuthStore, User } from "./store.js";

export const SESSION_COOKIE = "yozhan_session";

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      user?: Omit<User, "passwordHash">;
      sessionToken?: string;
    }
  }
}

export function parseCookies(header: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const index = part.indexOf("=");
    if (index < 0) continue;
    const name = part.slice(0, index).trim();
    if (name) out[name] = decodeURIComponent(part.slice(index + 1).trim());
  }
  return out;
}

/** True when the original client request used HTTPS, including via a proxy. */
export function isSecureRequest(req: Request): boolean {
  if (req.protocol === "https") return true;
  // nginx/Caddy terminate TLS and forward over plain HTTP; the original scheme
  // survives only in this header. Take the first value — a proxy chain appends.
  const forwarded = req.header("x-forwarded-proto");
  return forwarded?.split(",")[0].trim().toLowerCase() === "https";
}

export function setSessionCookie(req: Request, res: Response, token: string, maxAgeMs: number): void {
  res.cookie(SESSION_COOKIE, token, {
    httpOnly: true, // not readable from JavaScript, so XSS can't lift the session
    sameSite: "strict", // browsers won't attach it to cross-site requests, which covers CSRF
    secure: isSecureRequest(req), // set automatically once you're behind TLS
    maxAge: maxAgeMs,
    path: "/",
  });
}

export function clearSessionCookie(req: Request, res: Response): void {
  res.clearCookie(SESSION_COOKIE, {
    httpOnly: true,
    sameSite: "strict",
    secure: isSecureRequest(req),
    path: "/",
  });
}

/**
 * Accepts either a session cookie (humans in the dashboard) or the admin
 * bearer token (CLI and automation, e.g. pairing-cli), so adding logins does
 * not break existing scripted access.
 */
export function buildRequireAuth(store: AuthStore, adminToken: string | undefined) {
  return function requireAuth(req: Request, res: Response, next: NextFunction): void {
    const authorization = req.header("authorization");
    if (adminToken && authorization === `Bearer ${adminToken}`) {
      req.user = { id: "admin-token", username: "admin-token", createdAt: "" };
      next();
      return;
    }

    const token = parseCookies(req.header("cookie"))[SESSION_COOKIE];
    const user = token ? store.resolveSession(token) : null;
    if (!user) {
      res.status(401).json({ error: "unauthorized" });
      return;
    }

    const { passwordHash: _ignored, ...safe } = user;
    req.user = safe;
    req.sessionToken = token;
    next();
  };
}

/**
 * Slows down password guessing. Failures are counted per username+IP and the
 * lockout grows with each one; a success clears the counter.
 *
 * Deliberately in memory: it resets on restart, but restarting the gateway is
 * not something an unauthenticated attacker can do, and it keeps failed-login
 * bookkeeping out of a file that is written on every attempt.
 */
export class LoginThrottle {
  private readonly attempts = new Map<string, { count: number; blockedUntil: number }>();

  constructor(
    private readonly freeAttempts = 5,
    private readonly baseDelayMs = 2000,
    private readonly maxDelayMs = 15 * 60 * 1000
  ) {}

  private key(username: string, ip: string): string {
    return `${username.toLowerCase()}|${ip}`;
  }

  /** Milliseconds remaining before another attempt is allowed; 0 if allowed now. */
  retryAfterMs(username: string, ip: string): number {
    const entry = this.attempts.get(this.key(username, ip));
    if (!entry) return 0;
    return Math.max(0, entry.blockedUntil - Date.now());
  }

  recordFailure(username: string, ip: string): void {
    const key = this.key(username, ip);
    const entry = this.attempts.get(key) ?? { count: 0, blockedUntil: 0 };
    entry.count += 1;
    if (entry.count > this.freeAttempts) {
      const over = entry.count - this.freeAttempts;
      const delay = Math.min(this.baseDelayMs * 2 ** (over - 1), this.maxDelayMs);
      entry.blockedUntil = Date.now() + delay;
    }
    this.attempts.set(key, entry);
  }

  recordSuccess(username: string, ip: string): void {
    this.attempts.delete(this.key(username, ip));
  }
}
