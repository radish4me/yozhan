import { useState } from "react";
import { api } from "../api";
import { useAsync } from "../useAsync";
import { Async, Panel } from "./Panel";

type GroupBy = "agent" | "name" | "provider";
const LABELS: Record<GroupBy, string> = { agent: "Agent", name: "Model", provider: "Provider" };

export function Costs() {
  const [by, setBy] = useState<GroupBy>("agent");
  const costs = useAsync(() => api.costs(by), [by]);

  return (
    <Panel title="Cost & latency" subtitle="Aggregated from the trace log written on every model and tool call.">
      <div style={{ marginBottom: 12 }}>
        {(Object.keys(LABELS) as GroupBy[]).map((option) => (
          <button
            key={option}
            className="action"
            aria-current={by === option}
            onClick={() => setBy(option)}
            disabled={by === option}
          >
            by {LABELS[option].toLowerCase()}
          </button>
        ))}
      </div>

      <Async state={costs}>
        {(rows) =>
          rows.length === 0 ? (
            <p className="muted">No traces recorded yet — run a task first.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{LABELS[by]}</th>
                  <th className="num">Calls</th>
                  <th className="num">Failures</th>
                  <th className="num">Avg latency</th>
                  <th className="num">Tokens</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <td>{row.key}</td>
                    <td className="num">{row.calls}</td>
                    <td className={`num${row.failures > 0 ? " error" : ""}`}>{row.failures}</td>
                    <td className="num">{Math.round(row.avg_latency_ms ?? 0)} ms</td>
                    <td className="num">{row.total_tokens.toLocaleString()}</td>
                    <td className="num">${row.total_cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </Async>
      <p className="muted" style={{ marginTop: 12 }}>
        Models without a <code>pricing:</code> block in providers.yaml contribute $0 here because their cost is
        unknown, not because they are free.
      </p>
    </Panel>
  );
}
