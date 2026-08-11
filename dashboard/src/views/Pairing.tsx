import { useState } from "react";
import { api } from "../api";
import { useAsync } from "../useAsync";
import { Async, Panel } from "./Panel";

export function Pairing({ adminToken }: { adminToken: string }) {
  const pending = useAsync(() => (adminToken ? api.pendingPairings(adminToken) : Promise.resolve([])), [adminToken]);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function approve(code: string) {
    setBusy(code);
    setActionError(null);
    try {
      await api.approvePairing(code, adminToken);
      pending.reload();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!adminToken) {
    return (
      <Panel title="Pairing" subtitle="Approve people who have messaged yozhan on a channel.">
        <p className="muted">Set an admin token in Settings to view pairing requests.</p>
      </Panel>
    );
  }

  return (
    <Panel title="Pairing" subtitle="Approve people who have messaged yozhan on a channel.">
      {actionError && <p className="error">{actionError}</p>}
      <Async state={pending}>
        {(rows) =>
          rows.length === 0 ? (
            <p className="muted">No pending pairing requests.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Identity</th>
                  <th>Expires</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((request) => (
                  <tr key={request.code}>
                    <td>
                      <code>{request.code}</code>
                    </td>
                    <td>
                      {request.channel}:{request.externalId}
                    </td>
                    <td className="muted">{new Date(request.expiresAt).toLocaleString()}</td>
                    <td>
                      <button
                        className="action"
                        onClick={() => approve(request.code)}
                        disabled={busy === request.code}
                      >
                        Approve
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
