// Auth endpoints: first-run setup, login/logout, and account management.

import { Router, type Request, type Response } from "express";
import { MIN_PASSWORD_LENGTH, validatePassword } from "./passwords.js";
import {
  LoginThrottle,
  SESSION_COOKIE,
  clearSessionCookie,
  isSecureRequest,
  parseCookies,
  setSessionCookie,
} from "./middleware.js";
import { AuthStore, validateUsername } from "./store.js";

const SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000;

function clientIp(req: Request): string {
  const forwarded = req.header("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  return req.socket.remoteAddress ?? "unknown";
}

export function buildAuthRouter(store: AuthStore, requireAuth: ReturnType<typeof import("./middleware.js").buildRequireAuth>): Router {
  const router = Router();
  const throttle = new LoginThrottle();

  /** Whether the dashboard should show setup, login, or the app.
   *
   * This route sits in front of requireAuth (the app must be able to ask
   * "am I logged in?" while logged out), so req.user is never populated here
   * and the session has to be resolved from the cookie directly. */
  router.get("/auth/status", (req, res) => {
    const token = parseCookies(req.header("cookie"))[SESSION_COOKIE];
    res.json({
      needsSetup: !store.hasUsers(),
      authenticated: Boolean(token && store.resolveSession(token)),
      secure: isSecureRequest(req),
      minPasswordLength: MIN_PASSWORD_LENGTH,
    });
  });

  // First-run only. Once any user exists this is closed permanently —
  // otherwise it is an unauthenticated "create an admin account" endpoint.
  router.post("/auth/setup", async (req, res) => {
    if (store.hasUsers()) {
      res.status(410).json({ error: "setup has already been completed" });
      return;
    }

    const { username, password } = req.body ?? {};
    const usernameError = validateUsername(String(username ?? ""));
    if (usernameError) {
      res.status(400).json({ error: usernameError });
      return;
    }
    const passwordError = validatePassword(String(password ?? ""));
    if (passwordError) {
      res.status(400).json({ error: passwordError });
      return;
    }

    const user = await store.createUser(String(username), String(password));
    const token = store.createSession(user.id, SESSION_TTL_MS);
    setSessionCookie(req, res, token, SESSION_TTL_MS);
    res.status(201).json({ id: user.id, username: user.username });
  });

  router.post("/auth/login", async (req, res) => {
    const username = String(req.body?.username ?? "");
    const password = String(req.body?.password ?? "");
    const ip = clientIp(req);

    const retryAfterMs = throttle.retryAfterMs(username, ip);
    if (retryAfterMs > 0) {
      res.set("Retry-After", String(Math.ceil(retryAfterMs / 1000)));
      res.status(429).json({
        error: `Too many failed attempts. Try again in ${Math.ceil(retryAfterMs / 1000)}s.`,
      });
      return;
    }

    const user = await store.verifyCredentials(username, password);
    if (!user) {
      throttle.recordFailure(username, ip);
      // One message for both "no such user" and "wrong password", so this
      // can't be used to enumerate which usernames exist.
      res.status(401).json({ error: "Invalid username or password." });
      return;
    }

    throttle.recordSuccess(username, ip);
    const token = store.createSession(user.id, SESSION_TTL_MS);
    setSessionCookie(req, res, token, SESSION_TTL_MS);
    res.json({ id: user.id, username: user.username });
  });

  router.post("/auth/logout", requireAuth, (req: Request, res: Response) => {
    if (req.sessionToken) store.destroySession(req.sessionToken);
    clearSessionCookie(req, res);
    res.json({ ok: true });
  });

  router.get("/auth/me", requireAuth, (req: Request, res: Response) => {
    res.json({ ...req.user, sessions: req.user ? store.countSessions(req.user.id) : 0 });
  });

  router.post("/auth/password", requireAuth, async (req: Request, res: Response) => {
    const currentPassword = String(req.body?.currentPassword ?? "");
    const newPassword = String(req.body?.newPassword ?? "");

    if (!req.user || req.user.id === "admin-token") {
      res.status(400).json({ error: "the admin token has no password to change" });
      return;
    }
    // Re-check the current password: a hijacked session shouldn't be able to
    // lock the real owner out by silently changing their credentials.
    if (!(await store.verifyCredentials(req.user.username, currentPassword))) {
      res.status(401).json({ error: "Current password is incorrect." });
      return;
    }
    const passwordError = validatePassword(newPassword);
    if (passwordError) {
      res.status(400).json({ error: passwordError });
      return;
    }

    await store.setPassword(req.user.id, newPassword);
    // setPassword drops every session, including this one — issue a fresh one
    // so the user isn't bounced to the login screen for succeeding.
    const token = store.createSession(req.user.id, SESSION_TTL_MS);
    setSessionCookie(req, res, token, SESSION_TTL_MS);
    res.json({ ok: true });
  });

  router.get("/auth/users", requireAuth, (_req, res) => {
    res.json(store.listUsers());
  });

  router.post("/auth/users", requireAuth, async (req, res) => {
    const { username, password } = req.body ?? {};
    const usernameError = validateUsername(String(username ?? ""));
    if (usernameError) {
      res.status(400).json({ error: usernameError });
      return;
    }
    const passwordError = validatePassword(String(password ?? ""));
    if (passwordError) {
      res.status(400).json({ error: passwordError });
      return;
    }
    try {
      const user = await store.createUser(String(username), String(password));
      res.status(201).json({ id: user.id, username: user.username });
    } catch (err) {
      res.status(409).json({ error: (err as Error).message });
    }
  });

  router.delete("/auth/users/:id", requireAuth, (req, res) => {
    try {
      store.deleteUser(req.params.id);
      res.json({ ok: true });
    } catch (err) {
      res.status(400).json({ error: (err as Error).message });
    }
  });

  /** Sign out everywhere — the lever to pull if a session may have leaked. */
  router.post("/auth/sessions/revoke-all", requireAuth, (req: Request, res: Response) => {
    if (!req.user || req.user.id === "admin-token") {
      res.status(400).json({ error: "the admin token has no sessions" });
      return;
    }
    store.destroyAllSessions(req.user.id);
    clearSessionCookie(req, res);
    res.json({ ok: true });
  });

  return router;
}
