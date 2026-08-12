import { useCallback, useEffect, useState } from "react";
import { auth, type AuthStatus } from "./auth";
import { Account } from "./views/Account";
import { Agents } from "./views/Agents";
import { Chat } from "./views/Chat";
import { ConfigEditor } from "./views/ConfigEditor";
import { Costs } from "./views/Costs";
import { Gate } from "./views/Gate";
import { Learning } from "./views/Learning";
import { MemoryEditor } from "./views/MemoryEditor";
import { Pairing } from "./views/Pairing";
import { Providers } from "./views/Providers";
import { Secrets } from "./views/Secrets";
import { SkillsEditor } from "./views/SkillsEditor";

const GROUPS = [
  { label: "Use", tabs: ["Chat", "Costs"] },
  { label: "Configure", tabs: ["Configuration", "Keys & tokens", "Agents", "Providers"] },
  { label: "Content", tabs: ["Skills", "Memory", "Learning"] },
  { label: "Access", tabs: ["Pairing", "Account"] },
] as const;

const TABS = GROUPS.flatMap((g) => g.tabs);
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
          {GROUPS.map((group) => (
            <div key={group.label} className="nav-group">
              <div className="nav-heading">{group.label}</div>
              {group.tabs.map((name) => (
                <button key={name} aria-current={tab === name} onClick={() => setTab(name as Tab)}>
                  {name}
                </button>
              ))}
            </div>
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
        {tab === "Costs" && <Costs />}
        {tab === "Configuration" && <ConfigEditor />}
        {tab === "Keys & tokens" && <Secrets />}
        {tab === "Agents" && <Agents />}
        {tab === "Providers" && <Providers />}
        {tab === "Skills" && <SkillsEditor />}
        {tab === "Memory" && <MemoryEditor />}
        {tab === "Learning" && <Learning />}
        {tab === "Pairing" && <Pairing />}
        {tab === "Account" && <Account onSignedOut={refresh} />}
      </main>
    </div>
  );
}
