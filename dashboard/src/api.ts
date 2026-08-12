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
  /** False for skills that ship inside the image, which cannot be edited. */
  editable: boolean;
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

// --- config, secrets, skills, memory (Phases 10-12) ---

export interface ConfigFile {
  name: string;
  content: string;
  parsed: Record<string, unknown>;
}

export interface BackupInfo {
  id: string;
  file: string;
  created_at: string;
  size: number;
}

export interface SecretInfo {
  name: string;
  stored: boolean;
  from_environment: boolean;
  set: boolean;
  updated_at: string | null;
}

export interface AuditEntry {
  at: string;
  file: string;
  actor: string;
  backup: string | null;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "PUT",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  checkAuthorized(resp);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error((data as { detail?: string }).detail ?? `${resp.status} ${resp.statusText}`);
  return data as T;
}

async function del<T>(path: string): Promise<T> {
  const resp = await fetch(path, { method: "DELETE", credentials: "same-origin" });
  checkAuthorized(resp);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error((data as { detail?: string }).detail ?? `${resp.status} ${resp.statusText}`);
  return data as T;
}

export const configApi = {
  index: () => get<{ files: string[]; backups: BackupInfo[] }>("/config"),
  read: (name: string) => get<ConfigFile>(`/config/${name}`),
  validate: (name: string, content: string) =>
    post<{ valid: boolean; error?: string }>(`/config/${name}/validate`, { content }),
  save: (name: string, content: string) => put<{ saved: string }>(`/config/${name}`, { content }),
  restore: (backupId: string) => post<{ restored: string }>(`/config/restore/${backupId}`),
  readBackup: (backupId: string) => get<{ id: string; content: string }>(`/config/backup/${backupId}`),
  audit: () => get<AuditEntry[]>("/config/audit"),
};

export const secretsApi = {
  list: () => get<SecretInfo[]>("/secrets"),
  set: (name: string, value: string) => put<{ saved: string }>("/secrets", { name, value }),
  remove: (name: string) => del<{ deleted: string }>(`/secrets/${name}`),
};

export const skillsApi = {
  read: (name: string) => get<{ name: string; content: string; editable: boolean }>(`/skills/${name}`),
  save: (name: string, content: string) => put<{ saved: string }>(`/skills/${name}`, { content }),
  remove: (name: string) => del<{ deleted: string }>(`/skills/${name}`),
};

export const memoryApi = {
  read: (kind: "memory" | "user") => get<{ kind: string; content: string }>(`/memory/${kind}`),
  save: (kind: "memory" | "user", content: string) => put<{ saved: string }>(`/memory/${kind}`, { content }),
};
