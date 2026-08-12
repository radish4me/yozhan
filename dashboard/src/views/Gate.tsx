// The unauthenticated screens: first-run setup and login. One component
// because they are the same form with different stakes.

import { useState } from "react";
import { auth, type AuthStatus } from "../auth";

interface GateProps {
  status: AuthStatus;
  onAuthenticated: () => void;
}

export function Gate({ status, onAuthenticated }: GateProps) {
  const isSetup = status.needsSetup;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (isSetup && password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setBusy(true);
    try {
      if (isSetup) await auth.setup(username, password);
      else await auth.login(username, password);
      onAuthenticated();
    } catch (err) {
      setError((err as Error).message);
      setPassword("");
      setConfirm("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gate">
      <form className="gate-card" onSubmit={submit}>
        <div className="brand" style={{ padding: 0, marginBottom: 4 }}>
          yozhan
        </div>
        <h1>{isSetup ? "Create your admin account" : "Sign in"}</h1>
        <p className="subtitle">
          {isSetup
            ? "This is the first run, so no account exists yet. The account you create here becomes the administrator, and this page closes permanently afterwards."
            : "Enter your credentials to continue."}
        </p>

        {!status.secure && (
          <p className="warn-banner">
            This page is being served over plain HTTP, so your password and session cookie travel
            unencrypted. Put yozhan behind HTTPS before using it over the internet.
          </p>
        )}

        <label htmlFor="username">Username</label>
        <input
          id="username"
          type="text"
          autoComplete="username"
          autoFocus
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete={isSetup ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        {isSetup && (
          <>
            <label htmlFor="confirm">Confirm password</label>
            <input
              id="confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
            <p className="muted" style={{ marginTop: 0 }}>
              At least {status.minPasswordLength} characters. There is no password reset — if you
              lose it you'll need shell access to the server to clear the user store.
            </p>
          </>
        )}

        {error && <p className="error">{error}</p>}

        <button className="action primary" type="submit" disabled={busy || !username || !password}>
          {busy ? "Working…" : isSetup ? "Create account" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
