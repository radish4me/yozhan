// API key and channel token management.
//
// Values are write-only: the API reports whether a key is set, never what it
// is. Reading one back would make any dashboard session a key-exfiltration
// tool, which is exactly what storing them server-side is meant to contain.

import { useState } from "react";
import { secretsApi, type SecretInfo } from "../api";
import { useAsync } from "../useAsync";
import { Async, Panel } from "./Panel";

export function Secrets() {
  const secrets = useAsync(() => secretsApi.list());
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [newName, setNewName] = useState("");
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(name: string) {
    setBusy(true);
    setMessage(null);
    try {
      await secretsApi.set(name, value);
      setEditing(null);
      setValue("");
      setNewName("");
      secrets.reload();
      setMessage({ text: `${name} saved. It takes effect on the next request.`, ok: true });
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  async function remove(secret: SecretInfo) {
    if (!window.confirm(`Delete the stored value for ${secret.name}?`)) return;
    setBusy(true);
    setMessage(null);
    try {
      await secretsApi.remove(secret.name);
      secrets.reload();
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  function status(secret: SecretInfo) {
    if (secret.from_environment) return <span className="ok">set in stack</span>;
    if (secret.stored) return <span className="ok">stored here</span>;
    return <span className="muted">not set</span>;
  }

  return (
    <Panel
      title="Keys & tokens"
      subtitle="Provider API keys and channel tokens. Values are never displayed back — only whether each one is set."
    >
      <p className="warn-banner">
        Stored keys are written to <code>secrets.json</code> on the server in plain text (readable only by
        the container user). Anyone with root on the host, or a copy of the volume, can read them. A key set
        in your Portainer stack takes precedence over one stored here.
      </p>

      {message && <p className={message.ok ? "ok" : "error"}>{message.text}</p>}

      <Async state={secrets}>
        {(rows) => (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((secret) => (
                <tr key={secret.name}>
                  <td>
                    <code>{secret.name}</code>
                  </td>
                  <td>{status(secret)}</td>
                  <td className="muted">
                    {secret.updated_at ? new Date(secret.updated_at).toLocaleDateString() : "—"}
                  </td>
                  <td>
                    {editing === secret.name ? (
                      <span className="chat-form">
                        <input
                          type="password"
                          autoFocus
                          placeholder="paste value"
                          value={value}
                          onChange={(e) => setValue(e.target.value)}
                        />
                        <button className="action" onClick={() => save(secret.name)} disabled={busy || !value}>
                          Save
                        </button>
                        <button className="action" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <>
                        <button
                          className="action"
                          onClick={() => {
                            setEditing(secret.name);
                            setValue("");
                          }}
                          disabled={secret.from_environment}
                          title={secret.from_environment ? "Set in the stack; edit it there" : undefined}
                        >
                          {secret.stored ? "Replace" : "Set"}
                        </button>
                        {secret.stored && (
                          <button className="action" onClick={() => remove(secret)} disabled={busy}>
                            Delete
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>

      <div className="card" style={{ marginTop: 20 }}>
        <h2 className="card-title">Add another key</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          For a provider you added to <code>providers.yaml</code> yourself. The name must match the{" "}
          <code>env:</code> value there.
        </p>
        <div className="chat-form">
          <input
            type="text"
            placeholder="MY_PROVIDER_API_KEY"
            value={newName}
            onChange={(e) => setNewName(e.target.value.toUpperCase())}
          />
          <input
            type="password"
            placeholder="value"
            value={editing === "__new__" ? value : ""}
            onFocus={() => setEditing("__new__")}
            onChange={(e) => setValue(e.target.value)}
          />
          <button className="action" onClick={() => save(newName)} disabled={busy || !newName || !value}>
            Add
          </button>
        </div>
      </div>
    </Panel>
  );
}
