// YAML editor for providers.yaml / agents.yaml, with validate-before-save and
// one-click rollback.
//
// Saving runs the same validation the runtime does, so a config that would
// break every task is refused with the specific reason rather than written and
// discovered later. Every save also snapshots the previous version.

import { useEffect, useState } from "react";
import { configApi, type BackupInfo } from "../api";
import { useAsync } from "../useAsync";
import { Async, Panel } from "./Panel";

const FILES = ["agents.yaml", "providers.yaml"] as const;
type FileName = (typeof FILES)[number];

export function ConfigEditor() {
  const [file, setFile] = useState<FileName>("agents.yaml");
  const [text, setText] = useState("");
  const [loaded, setLoaded] = useState("");
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const index = useAsync(() => configApi.index());

  useEffect(() => {
    let cancelled = false;
    setMessage(null);
    configApi
      .read(file)
      .then((data) => {
        if (cancelled) return;
        setText(data.content);
        setLoaded(data.content);
      })
      .catch((err: Error) => !cancelled && setMessage({ text: err.message, ok: false }));
    return () => {
      cancelled = true;
    };
  }, [file]);

  const dirty = text !== loaded;

  async function validate() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await configApi.validate(file, text);
      setMessage(
        result.valid
          ? { text: "Valid — safe to save.", ok: true }
          : { text: result.error ?? "Invalid.", ok: false }
      );
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await configApi.save(file, text);
      setLoaded(text);
      setMessage({ text: "Saved. Changes take effect on the next task.", ok: true });
      index.reload();
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  async function rollback(backup: BackupInfo) {
    if (!window.confirm(`Restore ${backup.file} from ${new Date(backup.created_at).toLocaleString()}?`)) return;
    setBusy(true);
    setMessage(null);
    try {
      await configApi.restore(backup.id);
      const data = await configApi.read(backup.file);
      if (backup.file === file) {
        setText(data.content);
        setLoaded(data.content);
      }
      setMessage({ text: `Restored ${backup.file}.`, ok: true });
      index.reload();
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Configuration"
      subtitle="Edit the files directly. Saving validates first — a config that wouldn't resolve is refused, not written."
    >
      <div style={{ marginBottom: 12 }}>
        {FILES.map((name) => (
          <button
            key={name}
            className="action"
            aria-current={file === name}
            disabled={file === name}
            onClick={() => setFile(name)}
          >
            {name}
          </button>
        ))}
      </div>

      {message && <p className={message.ok ? "ok" : "error"}>{message.text}</p>}

      <textarea
        className="yaml-editor"
        spellCheck={false}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      <div style={{ marginTop: 10 }}>
        <button className="action" onClick={validate} disabled={busy}>
          Validate
        </button>
        <button className="action primary" onClick={save} disabled={busy || !dirty}>
          {dirty ? "Save changes" : "No changes"}
        </button>
        {dirty && (
          <button className="action" onClick={() => setText(loaded)} disabled={busy}>
            Discard
          </button>
        )}
      </div>

      <h2 className="card-title" style={{ marginTop: 28 }}>
        Version history
      </h2>
      <p className="subtitle">Every save snapshots the previous version. Restoring re-validates first.</p>
      <Async state={index}>
        {(data) =>
          data.backups.length === 0 ? (
            <p className="muted">No saved versions yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Saved</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.backups.map((backup) => (
                  <tr key={backup.id}>
                    <td>{backup.file}</td>
                    <td className="muted">{new Date(backup.created_at).toLocaleString()}</td>
                    <td>
                      <button className="action" onClick={() => rollback(backup)} disabled={busy}>
                        Restore
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </Async>
    </Panel>
  );
}
