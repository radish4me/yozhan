import { useCallback, useEffect, useState } from "react";
import { auth, type AuthStatus } from "./auth";
import { Account } from "./views/Account";
import { Agents } from "./views/Agents";
import { Chat } from "./views/Chat";
import { Costs } from "./views/Costs";
import { Gate } from "./views/Gate";
import { Learning } from "./views/Learning";
import { Pairing } from "./views/Pairing";
import { Providers } from "./views/Providers";

const TABS = ["Chat", "Agents", "Providers", "Costs", "Learning", "Pairing", "Account"] as const;
type Tab = (typeof TABS)[number];

export function App() {
  const [tab, setTab] = useState<Tab>("Chat");
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await auth.status());
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // The session cookie can expire while the tab is open. Rather than let every
  // view fail on its own, listen for the 401 any of them raise and re-gate.
  useEffect(() => {
    function onUnauthorized() {
      setStatus((prev) => (prev ? { ...prev, authenticated: false } : prev));
    }
    window.addEventListener("yozhan:unauthorized", onUnauthorized);
    return () => window.removeEventListener("yozhan:unauthorized", onUnauthorized);
  }, []);

  async function signOut() {
    try {
      await auth.logout();
    } finally {
      await refresh();
      setTab("Chat");
    }
  }

  if (error) return <div className="gate"><p className="error">{error}</p></div>;
  if (!status) return <div className="gate"><p className="muted">loading…</p></div>;
  if (!status.authenticated) return <Gate status={status} onAuthenticated={refresh} />;

  return (
    <div className="app">
      <nav className="sidebar">
        <div className="brand">yozhan</div>
        <div className="nav">
          {TABS.map((name) => (
            <button key={name} aria-current={tab === name} onClick={() => setTab(name)}>
              {name}
            </button>
          ))}
        </div>
        <button className="nav-signout" onClick={signOut}>
          Sign out
        </button>
      </nav>
      <main className="main">
        {!status.secure && (
          <p className="warn-banner">
            Served over plain HTTP — your session cookie is sent unencrypted on every request. Put
            yozhan behind HTTPS if it is reachable from the internet.
          </p>
        )}
        {tab === "Chat" && <Chat />}
        {tab === "Agents" && <Agents />}
        {tab === "Providers" && <Providers />}
        {tab === "Costs" && <Costs />}
        {tab === "Learning" && <Learning />}
        {tab === "Pairing" && <Pairing />}
        {tab === "Account" && <Account onSignedOut={refresh} />}
      </main>
    </div>
  );
}
