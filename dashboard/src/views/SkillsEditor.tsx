// Browse, edit and create skills.
//
// Only skills in the user directory are editable. The shipped ones live inside
// the container image, so an edit would look like it worked and then vanish on
// the next deploy — better to say so than to let that happen.

import { useState } from "react";
import { api, skillsApi, type Skill } from "../api";
import { useAsync } from "../useAsync";
import { Async, Panel } from "./Panel";

const TEMPLATE = `---
name: my-skill
version: 0.1.0
description: What this skill does, in one line.
capabilities: []
tags: []
depends_on: []
---

# my-skill

1. First step.
2. Second step.
`;

export function SkillsEditor() {
  const skills = useAsync(() => api.skills());
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [editable, setEditable] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  async function open(skill: Skill) {
    setMessage(null);
    setCreating(false);
    try {
      const data = await skillsApi.read(skill.name);
      setSelected(skill.name);
      setText(data.content);
      setEditable(data.editable);
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    }
  }

  function startNew() {
    setCreating(true);
    setSelected(null);
    setNewName("");
    setText(TEMPLATE);
    setEditable(true);
    setMessage(null);
  }

  async function save() {
    const name = creating ? newName.trim() : selected;
    if (!name) return;
    setBusy(true);
    setMessage(null);
    try {
      await skillsApi.save(name, creating ? text.replace(/^name:.*$/m, `name: ${name}`) : text);
      setMessage({ text: `Saved ${name}. It is callable immediately.`, ok: true });
      setCreating(false);
      setSelected(name);
      skills.reload();
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  async function remove(name: string) {
    if (!window.confirm(`Delete the skill "${name}"?`)) return;
    setBusy(true);
    try {
      await skillsApi.remove(name);
      setSelected(null);
      setText("");
      skills.reload();
    } catch (err) {
      setMessage({ text: (err as Error).message, ok: false });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Skills" subtitle="What the assistant knows how to do. Built-in skills are read-only.">
      {message && <p className={message.ok ? "ok" : "error"}>{message.text}</p>}

      <button className="action" onClick={startNew}>
        New skill
      </button>

      <Async state={skills}>
        {(rows) => (
          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Skill</th>
                <th>Tool</th>
                <th>Description</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((skill) => (
                <tr key={skill.name}>
                  <td>
                    {skill.name}
                    {skill.elevated && <span className="tag warn">elevated</span>}
                    {!skill.editable && <span className="tag">built-in</span>}
                  </td>
                  <td>{skill.tool ? <code>{skill.tool}</code> : <span className="muted">—</span>}</td>
                  <td className="muted">{skill.description}</td>
                  <td>
                    <button className="action" onClick={() => open(skill)}>
                      {skill.editable ? "Edit" : "View"}
                    </button>
                    {skill.editable && (
                      <button className="action" onClick={() => remove(skill.name)} disabled={busy}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>

      {(selected || creating) && (
        <div style={{ marginTop: 24 }}>
          <h2 className="card-title">{creating ? "New skill" : selected}</h2>
          {creating && (
            <>
              <label htmlFor="skill-name" className="chat-role">
                Skill name (lowercase-kebab-case)
              </label>
              <input
                id="skill-name"
                type="text"
                placeholder="my-skill"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </>
          )}
          {!editable && (
            <p className="muted">
              This skill ships inside the image, so it is read-only here — an edit would be reverted on the
              next deploy. Copy it into a new skill to change it.
            </p>
          )}
          <textarea
            className="yaml-editor"
            spellCheck={false}
            readOnly={!editable}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {editable && (
            <button className="action primary" onClick={save} disabled={busy || (creating && !newName)}>
              Save
            </button>
          )}
        </div>
      )}
    </Panel>
  );
}
