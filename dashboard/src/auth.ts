// Auth API client. The session lives in an HttpOnly cookie, which JavaScript
// deliberately cannot read — so "am I logged in?" is a server question, asked
// via /auth/status rather than inspected locally.

export interface AuthStatus {
  needsSetup: boolean;
  authenticated: boolean;
  secure: boolean;
  minPasswordLength: number;
}

export interface Account {
  id: string;
  username: string;
  createdAt: string;
  sessions: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error((data as { error?: string }).error ?? `${resp.status} ${resp.statusText}`);
  return data as T;
}

export const auth = {
  status: () => request<AuthStatus>("/auth/status"),
  setup: (username: string, password: string) =>
    request<Account>("/auth/setup", { method: "POST", body: JSON.stringify({ username, password }) }),
  login: (username: string, password: string) =>
    request<Account>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => request<{ ok: true }>("/auth/logout", { method: "POST" }),
  me: () => request<Account>("/auth/me"),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ ok: true }>("/auth/password", {
      method: "POST",
      body: JSON.stringify({ currentPassword, newPassword }),
    }),
  users: () => request<Array<{ id: string; username: string; createdAt: string }>>("/auth/users"),
  addUser: (username: string, password: string) =>
    request<Account>("/auth/users", { method: "POST", body: JSON.stringify({ username, password }) }),
  deleteUser: (id: string) => request<{ ok: true }>(`/auth/users/${id}`, { method: "DELETE" }),
  revokeAllSessions: () => request<{ ok: true }>("/auth/sessions/revoke-all", { method: "POST" }),
};
