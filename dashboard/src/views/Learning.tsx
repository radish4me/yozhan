import { useState } from "react";
import { api } from "../api";
import { useAsync } from "../useAsync";
import { Async, Panel } from "./Panel";

export function Learning() {
  const proposals = useAsync(() => api.proposals());
  const [expanded, setExpanded] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function act(id: number, action: "approve" | "reject") {
    setBusy(id);
    setActionError(null);
    try {
      if (action === "approve") await api.approveProposal(id);
      else await api.rejectProposal(id);
      proposals.reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel
      title="Learning"
      subtitle="Skills the learning loop proposed from task traces. Nothing is written to disk until you approve it."
    >
      {actionError && <p className="error">{actionError}</p>}
      <Async state={proposals}>
        {(rows) =>
          rows.length === 0 ? (
            <p className="muted">No pending proposals.</p>
          ) : (
            rows.map((proposal) => (
              <div className="card" key={proposal.id}>
                <div>
                  <strong>{proposal.skill_name}</strong> <span className="tag">{proposal.action}</span>
                </div>
                <p className="muted" style={{ margin: "6px 0 12px" }}>
                  {proposal.rationale}
                </p>
                <button className="action" onClick={() => act(proposal.id, "approve")} disabled={busy === proposal.id}>
                  Approve
                </button>
                <button className="action" onClick={() => act(proposal.id, "reject")} disabled={busy === proposal.id}>
                  Reject
                </button>
                <button
                  className="action"
                  onClick={() => setExpanded(expanded === proposal.id ? null : proposal.id)}
                >
                  {expanded === proposal.id ? "Hide" : "View"} SKILL.md
                </button>
                {expanded === proposal.id && <pre>{proposal.content}</pre>}
              </div>
            ))
          )
        }
      </Async>
    </Panel>
  );
}
