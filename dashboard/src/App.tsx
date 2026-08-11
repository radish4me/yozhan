import { useState } from "react";
import { Agents } from "./views/Agents";
import { Chat } from "./views/Chat";
import { Costs } from "./views/Costs";
import { Learning } from "./views/Learning";
import { Pairing } from "./views/Pairing";
import { Panel } from "./views/Panel";
import { Providers } from "./views/Providers";

const TABS = ["Chat", "Agents", "Providers", "Costs", "Learning", "Pairing", "Settings"] as const;
type Tab = (typeof TABS)[number];

const TOKEN_KEY = "yozhan.adminToken";

export function App() {
  const [tab, setTab] = useState<Tab>("Chat");
  // Kept in sessionStorage, not localStorage: the admin token authorizes writes,
  // so it should not outlive the browser session on a shared machine.
  const [adminToken, setAdminToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? "");

  function updateToken(value: string) {
    setAdminToken(value);
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  }

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
      </nav>
      <main className="main">
        {tab === "Chat" && <Chat />}
        {tab === "Agents" && <Agents />}
        {tab === "Providers" && <Providers />}
        {tab === "Costs" && <Costs />}
        {tab === "Learning" && <Learning adminToken={adminToken} />}
        {tab === "Pairing" && <Pairing adminToken={adminToken} />}
        {tab === "Settings" && (
          <Panel
            title="Settings"
            subtitle="The admin token authorizes pairing approvals and skill-proposal writes (GATEWAY_ADMIN_TOKEN)."
          >
            <div className="card">
              <label htmlFor="admin-token" className="chat-role">
                Admin token
              </label>
              <input
                id="admin-token"
                type="password"
                value={adminToken}
                placeholder="GATEWAY_ADMIN_TOKEN"
                onChange={(e) => updateToken(e.target.value)}
              />
              <p className="muted" style={{ marginBottom: 0 }}>
                Held in this browser session only, and cleared when you close the tab.
              </p>
            </div>
          </Panel>
        )}
      </main>
    </div>
  );
}
