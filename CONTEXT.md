# yozhan — session handoff

Everything a fresh Claude Code session needs to pick this project up. Written
2026-08-12, at commit `ae2b1c9`.

---

## 1. What this is

A self-hosted AI assistant, built from scratch in this repo. It unifies ideas
from three existing projects — **OpenJarvis** (local-first agent/skill
framework), **OpenClaw** (multi-channel gateway, pairing, sandboxing) and
**Hermes Agent** (self-improving loop, multi-provider routing).

**No code was copied from any of them.** Every concept was reimplemented from
their public documentation. That matters legally: MIT output with no vendored
code means no NOTICE-file obligation. Preserve this — if you ever add
third-party code, flag it and add `THIRD_PARTY_NOTICES.md`.

- **Repo**: <https://github.com/radish4me/yozhan> (public, MIT)
- **Owner**: Radhakrishnan, GitHub user `radish4me`
- **Live instance**: `http://rkshanu.cloud:3030` (their VPS, via Portainer)

---

## 2. Non-negotiable project rules

1. **Linux/Docker only.** No Windows installers, no PowerShell, no
   Windows-specific code paths in the shipped project. (The *development*
   machine is Windows; that's incidental.)
2. **MIT licence, "Copyright (c) 2026 Radhakrishnan".** README must credit
   Radhakrishnan as creator.
3. **Python** (runtime) + **TypeScript/Node** (gateway) + **React/TS**
   (dashboard) + **llama.cpp** (local inference, invoked, never
   reimplemented). Don't add a fourth core language.
4. **Three shipped local models** must stay selectable: Qwen3.5-0.8B
   (default), LFM2.5, Agents-A1-4B. Any other GGUF must also work.

---

## 3. Architecture in one screen

```
Dashboard (React/TS)  ──┐
Telegram/Discord/Slack ─┼──▶  Gateway (Node/TS, :3000)  ──▶  Runtime (Python, :8787)
CLI (yozhan chat) ──────┘        auth, pairing,                agents, skills, memory,
                                 channel adapters,             learning loop, MCP,
                                 proxies everything            provider router
                                                                      │
                                                    ┌─────────────────┴──────────────┐
                                              llama-server                    remote providers
                                              (llama.cpp)                (Anthropic/Gemini/…)
```

- Only the **gateway** publishes a port. Runtime and llama-server stay on the
  internal Docker network.
- **All three surfaces share one `ChatAgent`** against one session store, so
  behaviour cannot drift between CLI, chat and dashboard. Keep it that way.

### Key files

| Path | What |
|---|---|
| `runtime/yozhan_runtime/agents/chat_agent.py` | The agent loop everything runs through |
| `runtime/yozhan_runtime/agents/orchestrator.py` | Multi-agent dispatch, delegation |
| `runtime/yozhan_runtime/commands.py` | Slash commands (shared by all surfaces) |
| `runtime/yozhan_runtime/providers/router.py` | Provider dispatch, fallback, key rotation |
| `runtime/yozhan_runtime/config_store.py` | Validated config read/write + backups |
| `runtime/yozhan_runtime/credentials.py` | Domain-bound website credential vault |
| `runtime/yozhan_runtime/mcp/` | MCP client (stdio + HTTP/OAuth) |
| `runtime/yozhan_runtime/server.py` | FastAPI surface the gateway proxies |
| `gateway/src/index.ts` | Auth, channels, proxy, static dashboard |
| `gateway/src/auth/` | scrypt passwords, sessions, login throttle |
| `config/providers.yaml`, `config/agents.yaml` | The two files users edit |

---

## 4. What's built (Phases 1–12 + extras)

Local inference · multi-provider routing with fallback chains, multi-key
rotation and parallel fan-out · per-agent model assignment · unified
`SKILL.md` format · SQLite+FTS5 memory + curated `MEMORY.md`/`USER.md` ·
self-improving learning loop (approval-gated) · Telegram/Discord/Slack with
pairing · React dashboard · scheduled/continuous agents · sandboxed tools ·
cost/latency reporting · A2A · username/password auth · config editing UI ·
server-side secrets · slash commands · MCP (stdio + HTTP + OAuth) · headless
browser with domain-bound login · session switching · sub-agent delegation.

Full list in `README.md`. Honest gap list in `docs/COMPARISON.md`.

### Deliberately NOT built

MCP *server* (we're a client only) · TUI · plugin SDK · skill registry ·
vector/semantic memory · voice/images/attachments · OAuth *for providers* ·
learned/trace-driven routing · energy metrics · native apps · channels beyond
the three. Don't claim these exist.

---

## 5. Design decisions to preserve

These are load-bearing. Each exists because of a specific failure mode.

- **Config is validated by the real resolver before writing.** A schema check
  can't catch `fallback_chain: local_frist`. Rejected writes change nothing;
  every write is backed up and rollback-able.
- **Sandboxed tools get a scrubbed environment.** A skill — including one the
  learning loop wrote — must never be able to read `ANTHROPIC_API_KEY_1`.
- **The learning loop is approval-gated by default**, and model-authored skill
  names are validated before becoming directories.
- **Unpriced models report cost as `unknown`, not zero.** A cost report must
  not quietly under-report.
- **The model never sees a website password.** It names a site; the tool
  injects the credential. Credentials are domain-bound and refused on
  lookalikes.
- **Browser and A2A refuse private/link-local addresses.** Both take URLs
  influenced by model output; without this, a page saying "fetch
  169.254.169.254" is a credential-disclosure primitive.
- **A2A inbound auth fails closed**; outbound only reaches named peers.
- **Auth**: setup page closes permanently after first use; session tokens are
  stored hashed; a corrupt auth store refuses to start rather than reopening
  setup.
- **Delegation has a depth limit.** Without it an agent can delegate to itself
  forever, spending real money.

---

## 6. How to work on it

```bash
# Python runtime
python -m venv .venv && .venv/bin/pip install -e "./runtime[browser]" pytest
pytest runtime/tests -q          # 307 tests

# Gateway
npm install --prefix gateway && npm run build --prefix gateway
npm test --prefix gateway        # 56 tests

# Dashboard
npm install --prefix dashboard && npm run build --prefix dashboard
```

Env vars for local runs: `YOZHAN_CONFIG_DIR`, `YOZHAN_DATA_DIR`,
`YOZHAN_SKILLS_DIR`, `YOZHAN_USER_SKILLS_DIR`, `LLAMA_SERVER_URL`.

**Testing style used throughout**: test the *refusals*, not just the happy
path — a credential on the wrong domain, a config that would break, an
unauthenticated request. Several real bugs in this project were caught only by
driving the actual UI in a browser, not by unit tests. Do both.

---

## 7. Gotchas on this specific machine

- **`gh` CLI is at `C:\Program Files\GitHub CLI\gh.exe`** and is NOT on PATH.
  Call it by full path.
- **The active `gh` account drifts to `online4rk-star`.** The user requires
  pushes as **`radish4me`**. Check before every push:
  ```
  & "C:\Program Files\GitHub CLI\gh.exe" auth status
  & "C:\Program Files\GitHub CLI\gh.exe" auth switch --hostname github.com --user radish4me
  ```
- **The global git credential helper is broken** — it points at a nonexistent
  `gh.exe` under `Desktop\Trading\...`. Push with a one-off override:
  ```
  git -c credential.https://github.com.helper= \
      -c credential.https://github.com.helper="!'C:/Program Files/GitHub CLI/gh.exe' auth git-credential" \
      push origin master
  ```
  (The user was given the one-line permanent fix but hasn't applied it.)
- **PowerShell wraps git's stderr as a red error even on success.** Look for
  `abc123..def456  master -> master` — that means it worked.
- **Bash heredocs with complex quoting fail here.** Write Python patch scripts
  to the scratchpad and run them instead.
- **Docker CLI exists but the daemon is usually not running.** `docker compose
  config` (client-side) works; anything needing the daemon does not.
- Branch is **`master`**, not `main`.

---

## 8. Open items

1. **HTTPS is not set up.** The instance serves plain HTTP on port 3030, so
   login credentials and session cookies travel in the clear. The user has
   nginx already and `deploy/nginx-yozhan.conf` is ready; they need to install
   it, run certbot, and set `GATEWAY_BIND=127.0.0.1` so the plain port stops
   bypassing the proxy. **This is the most important outstanding task.**
2. **GHCR images may not exist yet.** Portainer Method A pulls
   `ghcr.io/radish4me/yozhan-*:latest`, published by the *Publish images*
   Action. If it hasn't run, Method A fails with `manifest unknown`; Method B
   (build from source) works regardless.
3. **Untested in reality**: real Telegram/Discord/Slack round-trips, the
   Playwright browser against a live page, A2A between two instances, and any
   deployment on the actual VPS. All are unit- and locally-integration-tested
   only.
4. **Secrets the user pasted into chat earlier** (a Telegram bot token and an
   admin token) were flagged as compromised and should have been rotated.
   Worth confirming.

---

## 9. Working style the user expects

- They ask for large batches of work and expect it delivered, tested and
  pushed in one go.
- **Be honest about what wasn't done.** They asked for "all features" once;
  the right response was to build the feasible subset and state plainly what
  was skipped. Don't overclaim.
- **Flag security issues even when not asked.** The single most valuable thing
  done in this project was noticing their instance was publicly serving
  `/chat` unauthenticated — found by actually probing it, not by assuming.
- Verify against reality (run it, curl it, open it in a browser) rather than
  reasoning about whether code should work. Multiple real bugs surfaced only
  that way.
