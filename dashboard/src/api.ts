// Thin API client for the Gateway. Everything the dashboard shows comes from
// the Gateway, never straight from the runtime — the runtime stays on the
// internal Docker network.

export interface Agent {
  name: string;
  mode: string;
  subagent_of: string | null;
  provider: string;
  model: string;
  error?: string;
}

export interface Skill {
  name: string;
  version: string;
  description: string;
  tags: string[];
  tool: string | null;
  elevated: boolean;
}

export interface Provider {
  name: string;
  type: string;
  models: string[];
  keys_configured: number;
  keys_declared: number;
}

export interface CostRow {
  key: string;
  calls: number;
  failures: number;
  avg_latency_ms: number | null;
  total_cost_usd: number;
  total_tokens: number;
}

export interface Proposal {
  id: number;
  action: string;
  skill_name: string;
  rationale: string;
  content: string;
  status: string;
}

export interface PendingPairing {
  code: string;
  channel: string;
  externalId: string;
  expiresAt: string;
}

/** A 401 means the session expired; tell App to show the login screen again. */
function checkAuthorized(resp: Response): void {
  if (resp.status === 401) {
    window.dispatchEvent(new CustomEvent("yozhan:unauthorized"));
    throw new Error("Your session expired. Please sign in again.");
  }
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(path, { credentials: "same-origin" });
  checkAuthorized(resp);
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status} ${resp.statusText}`);
  return (await resp.json()) as T;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  checkAuthorized(resp);
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status} ${resp.statusText}`);
  return (await resp.json()) as T;
}

export const api = {
  agents: () => get<Agent[]>("/agents"),
  skills: () => get<Skill[]>("/skills"),
  providers: () => get<Provider[]>("/providers"),
  costs: (by = "agent") => get<CostRow[]>(`/costs?by=${by}`),
  proposals: () => get<Proposal[]>("/proposals"),
  approveProposal: (id: number) => post(`/proposals/${id}/approve`),
  rejectProposal: (id: number) => post(`/proposals/${id}/reject`),
  pendingPairings: () => get<PendingPairing[]>("/pairing/pending"),
  approvePairing: (code: string) => post("/pairing/approve", { code }),
  chat: (message: string, sessionId: string) =>
    post<{ content?: string; error?: string }>("/chat", { message, session_id: sessionId }),
};
