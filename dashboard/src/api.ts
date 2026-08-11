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

async function get<T>(path: string, adminToken?: string): Promise<T> {
  const resp = await fetch(path, {
    headers: adminToken ? { authorization: `Bearer ${adminToken}` } : undefined,
  });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status} ${resp.statusText}`);
  return (await resp.json()) as T;
}

async function post<T>(path: string, body?: unknown, adminToken?: string): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(adminToken ? { authorization: `Bearer ${adminToken}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status} ${resp.statusText}`);
  return (await resp.json()) as T;
}

export const api = {
  agents: () => get<Agent[]>("/agents"),
  skills: () => get<Skill[]>("/skills"),
  providers: () => get<Provider[]>("/providers"),
  costs: (by = "agent") => get<CostRow[]>(`/costs?by=${by}`),
  proposals: () => get<Proposal[]>("/proposals"),
  approveProposal: (id: number, token: string) => post(`/proposals/${id}/approve`, undefined, token),
  rejectProposal: (id: number, token: string) => post(`/proposals/${id}/reject`, undefined, token),
  pendingPairings: (token: string) => get<PendingPairing[]>("/pairing/pending", token),
  approvePairing: (code: string, token: string) => post("/pairing/approve", { code }, token),
  chat: (message: string, sessionId: string) =>
    post<{ content?: string; error?: string }>("/chat", { message, session_id: sessionId }),
};
