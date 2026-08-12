import { useState } from "react";
import { auth } from "../auth";
import { useAsync } from "../useAsync";
import { Async, Panel } from "./Panel";

export function Account({ onSignedOut }: { onSignedOut: () => void }) {
  const me = useAsync(() => auth.me());
  const users = useAsync(() => auth.users());

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    if (next !== confirm) {
      setMessage({ text: "New passwords do not match.", ok: false });
      return;
    }
    setBusy(true);
    try {
      await auth.changePassword(current, next);
      setMessage({ text: "Password changed. All other sessions were signed out.", ok: true });
      setCurrent("");
      setNext("");
      setConfirm("");
      me.reload();
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  async function addUser(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    setBusy(true);
    try {
      await auth.addUser(newUsername, newPassword);
      setNewUsername("");
      setNewPassword("");
      users.reload();
      setMessage({ text: "User created.", ok: true });
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  async function removeUser(id: string, username: string) {
    if (!confirmRemoval(username)) return;
    setMessage(null);
    try {
      await auth.deleteUser(id);
      users.reload();
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    }
  }

  async function revokeAll() {
    await auth.revokeAllSessions();
    onSignedOut();
  }

  return (
    <Panel title="Account" subtitle="Your login, other users, and active sessions.">
      {message && <p className={message.ok ? "ok" : "error"}>{message.text}</p>}

      <Async state={me}>
        {(account) => (
          <div className="card">
            <div>
              Signed in as <strong>{account.username}</strong>
            </div>
            <p className="muted" style={{ margin: "4px 0 12px" }}>
              {account.sessions} active session{account.sessions === 1 ? "" : "s"}.
            </p>
            <button className="action" onClick={revokeAll}>
              Sign out everywhere
            </button>
          </div>
        )}
      </Async>

      <form className="card" onSubmit={changePassword}>
        <h2 className="card-title">Change password</h2>
        <label htmlFor="current">Current password</label>
        <input id="current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <label htmlFor="next">New password</label>
        <input id="next" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        <label htmlFor="confirm-new">Confirm new password</label>
        <input id="confirm-new" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <p className="muted">Changing your password signs out every other session.</p>
        <button className="action" type="submit" disabled={busy || !current || !next}>
          Change password
        </button>
      </form>

      <div className="card">
        <h2 className="card-title">Users</h2>
        <Async state={users}>
          {(rows) => (
            <table>
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((user) => (
                  <tr key={user.id}>
                    <td>{user.username}</td>
                    <td className="muted">{new Date(user.createdAt).toLocaleDateString()}</td>
                    <td>
                      <button className="action" onClick={() => removeUser(user.id, user.username)} disabled={rows.length <= 1}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Async>

        <form onSubmit={addUser} style={{ marginTop: 16 }}>
          <label htmlFor="new-username">Add a user</label>
          <div className="chat-form">
            <input id="new-username" type="text" placeholder="username" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} />
            <input type="password" placeholder="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            <button className="action" type="submit" disabled={busy || !newUsername || !newPassword}>
              Add
            </button>
          </div>
        </form>
      </div>
    </Panel>
  );
}

function confirmRemoval(username: string): boolean {
  return window.confirm(`Remove the user "${username}"? Their sessions will be signed out immediately.`);
}
