import { useState } from "react";
import { api } from "../api";
import { Panel } from "./Panel";

interface Turn {
  role: "you" | "yozhan";
  text: string;
  failed?: boolean;
}

export function Chat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || busy) return;

    setTurns((prev) => [...prev, { role: "you", text: message }]);
    setInput("");
    setBusy(true);
    try {
      const result = await api.chat(message, "dashboard");
      setTurns((prev) => [
        ...prev,
        result.error
          ? { role: "yozhan", text: result.error, failed: true }
          : { role: "yozhan", text: result.content ?? "(no reply)" },
      ]);
    } catch (err) {
      setTurns((prev) => [...prev, { role: "yozhan", text: (err as Error).message, failed: true }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Chat" subtitle="Same agent runtime and session store as the CLI and messaging channels.">
      <div className="card chat-log">
        {turns.length === 0 && <p className="muted">No messages yet.</p>}
        {turns.map((turn, i) => (
          <div className="chat-row" key={i}>
            <div className="chat-role">{turn.role}</div>
            <div className={`chat-body${turn.failed ? " error" : ""}`}>{turn.text}</div>
          </div>
        ))}
        {busy && <p className="muted">thinking…</p>}
      </div>
      <form className="chat-form" onSubmit={send}>
        <input
          type="text"
          value={input}
          placeholder="Ask yozhan something"
          onChange={(e) => setInput(e.target.value)}
        />
        <button className="action" type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </Panel>
  );
}
