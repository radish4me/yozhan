// Curated cross-session memory: the two small files injected into every
// session. Both are size-capped, and the cap is enforced server-side — a save
// over it is refused rather than silently truncated.

import { useEffect, useState } from "react";
import { memoryApi } from "../api";
import { Panel } from "./Panel";

const KINDS = [
  { id: "memory", label: "MEMORY.md", hint: "Durable facts, preferences, project context." },
  { id: "user", label: "USER.md", hint: "Who the user is." },
] as const;

type Kind = (typeof KINDS)[number]["id"];

export function MemoryEditor() {
  const [kind, setKind] = useState<Kind>("memory");
  const [text, setText] = useState("");
  const [loaded, setLoaded] = useState("");
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setMessage(null);
    memoryApi
      .read(kind)
      .then((data) => {
        if (cancelled) return;
        setText(data.content);
        setLoaded(data.content);
      })
      .catch((err: Error) => !cancelled && setMessage({ text: err.message, ok: false }));
    return () => {
      cancelled = true;
    };
  }, [kind]);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await memoryApi.save(kind, text);
      setLoaded(text);
      setMessage({ text: "Saved.", ok: true });
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  const current = KINDS.find((k) => k.id === kind)!;

  return (
    <Panel
      title="Memory"
      subtitle="Injected at the start of every session, so keep it short — this is prompt overhead paid on every turn."
    >
      <div style={{ marginBottom: 12 }}>
        {KINDS.map((option) => (
          <button
            key={option.id}
            className="action"
            aria-current={kind === option.id}
            disabled={kind === option.id}
            onClick={() => setKind(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <p className="muted">{current.hint}</p>
      {message && <p className={message.ok ? "ok" : "error"}>{message.text}</p>}

      <textarea
        className="yaml-editor"
        spellCheck={false}
        placeholder="- one note per line"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <p className="muted">{text.length} characters</p>

      <button className="action primary" onClick={save} disabled={busy || text === loaded}>
        {text === loaded ? "No changes" : "Save"}
      </button>
    </Panel>
  );
}
