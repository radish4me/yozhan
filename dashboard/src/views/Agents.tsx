import { api } from "../api";
import { useAsync } from "../useAsync";
import { Async, Panel } from "./Panel";

export function Agents() {
  const agents = useAsync(() => api.agents());
  const skills = useAsync(() => api.skills());

  return (
    <Panel title="Agents & skills" subtitle="Resolved model assignment per agent, from config/agents.yaml.">
      <Async state={agents}>
        {(rows) => (
          <table>
            <thead>
              <tr>
                <th>Agent</th>
                <th>Mode</th>
                <th>Sub-agent of</th>
                <th>Resolves to</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((agent) => (
                <tr key={agent.name}>
                  <td>{agent.name}</td>
                  <td>{agent.mode ?? "—"}</td>
                  <td className="muted">{agent.subagent_of ?? "—"}</td>
                  <td>
                    {agent.error ? (
                      <span className="error">{agent.error}</span>
                    ) : (
                      <code>
                        {agent.provider}/{agent.model}
                      </code>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>

      <h1 style={{ marginTop: 28 }}>Skills</h1>
      <p className="subtitle">Loaded from the built-in and user skill directories.</p>
      <Async state={skills}>
        {(rows) => (
          <table>
            <thead>
              <tr>
                <th>Skill</th>
                <th>Tool</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((skill) => (
                <tr key={skill.name}>
                  <td>
                    {skill.name} <span className="muted">v{skill.version}</span>
                    {skill.elevated && <span className="tag warn" title="Runs outside the sandbox">elevated</span>}
                  </td>
                  <td>{skill.tool ? <code>{skill.tool}</code> : <span className="muted">instructions only</span>}</td>
                  <td className="muted">{skill.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </Panel>
  );
}
