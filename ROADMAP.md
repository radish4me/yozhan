# yozhan — Roadmap

Each phase below is a working, demoable increment — runnable via `docker compose
up` (or the bare-VPS install script) at the end of every phase, not just at the
end of the roadmap. Phases build strictly on prior ones; nothing is a
big-bang merge.

## License compatibility

yozhan is released under the **MIT License**, copyright Radhakrishnan.

- Source inspirations: OpenJarvis (**Apache-2.0**) and OpenClaw + Hermes Agent
  (both **MIT**). All three are permissive and MIT-compatible as *inspiration
  sources* — but that compatibility only matters if code were actually copied.
- **No code is vendored from any of the three reference projects.** Every file
  in this repo is an original implementation written from the public
  architecture/README description, not a derivative of their source. Because
  nothing is copied, there is **no NOTICE-file obligation** (Apache-2.0's
  NOTICE-propagation clause is triggered by redistributing Apache-licensed
  *code*, not by reading it for design ideas) and no attribution requirement
  beyond what this repo chooses to give voluntarily.
- We voluntarily credit all three projects by name and link in
  [`README.md`](README.md) as design inspiration, as a matter of good open-source
  citizenship — this is a courtesy, not a license requirement.
- If any future contribution *does* incorporate third-party code (e.g. a
  vendored dependency, a pasted snippet), it must be flagged in the PR and
  recorded in a `THIRD_PARTY_NOTICES.md` at that time. None exists today
  because none is needed today.
- Any Python/Node dependencies pulled in via `pip`/`npm` (FastAPI, llama.cpp
  bindings, grammY, etc.) carry their own licenses as transitive dependencies,
  tracked normally via `pyproject.toml`/`package.json` — not a concern for
  *this* repo's license, same as any MIT project with a dependency tree.

## Phase 1 — Inference spine + CLI chat (MVP-0)

**Goal:** `docker compose up` gives you a terminal chat against a local model.

- Repo/Docker scaffold: `docker-compose.yml`, per-service Dockerfiles, `.env.example`.
- `llama-server` service (CPU build by default, `CUDA=1` build arg for GPU
  hosts), model pulled via `-hf <repo>:<quant>` at container start.
- `config/providers.yaml` with the `local` provider pre-populated with all
  three required models (Qwen3.5-0.8B, LFM2.5, Agents-A1-4B); default model
  swappable via `LOCAL_DEFAULT_MODEL` env or editing the file, no code change.
- Minimal Python CLI (`yozhan chat`) that talks directly to `llama-server`'s
  OpenAI-compatible endpoint — no agent loop yet, just a chat REPL.
- **Demo:** fresh clone → `docker compose up` → `yozhan chat` → conversation
  with the default local model on a 2-4 vCPU / 4-8 GB box.

## Phase 2 — Single-agent core

**Goal:** one real agent with tools, not just a raw chat completion loop.

- `BaseAgent` interface (on-demand execution only for now) + one concrete
  `ChatAgent` implementation.
- Unified skill format (`SKILL.md` + frontmatter, agentskills.io-compatible)
  and `SkillManager` discovery/loading; ship 2-3 trivial built-in skills
  (e.g. `read_file`, `web_search` stub) to prove the format end-to-end.
- Local session/memory store: SQLite + FTS5, one DB per user, conversation
  history persisted across CLI restarts.
- **Demo:** `yozhan chat` now invokes tools mid-conversation and remembers
  context from a previous session.

## Phase 3 — Multi-agent orchestration

**Goal:** more than one agent, each independently model-assigned.

- `Orchestrator` that resolves a task to an agent or set of sub-agents.
- `config/agents.yaml` implementing the per-agent/sub-agent model-assignment
  schema from `ARCHITECTURE.md` §4.2 (direct pin vs. named fallback chain,
  independent sub-agent overrides).
- At least two agents with different model assignments running side by side
  (e.g. a cheap local `researcher` + a pinned remote `coder`).
- **Demo:** a task that the orchestrator splits across two agents, each
  visibly using its own configured model (shown in CLI trace output).

## Phase 4 — Multi-provider/multi-model/multi-key router

**Goal:** the system never "runs out of models."

- `config/providers.yaml` fully wired: provider list (OpenRouter, Gemini,
  Grok, OpenAI, Anthropic, local llama.cpp, custom OpenAI-compatible), each
  with a list of models.
- Fallback-chain execution: on error/429/timeout, router walks the configured
  chain automatically; chain order is pure config.
- Multi-key rotation per provider (e.g. two Gemini keys), rotating on
  rate-limit/exhaustion.
- Parallel fan-out mode (`mode: parallel` chains) for tasks that want several
  models queried concurrently (e.g. the `reviewer` agent from Phase 3).
- **Demo:** kill/rate-limit-simulate a primary provider mid-task and show the
  router falling through to the next configured model without user-visible
  failure; show a parallel fan-out task querying 3 models at once.

## Phase 5 — TS gateway + first messaging channel

**Goal:** yozhan is reachable outside the terminal.

- Gateway service (Node/TypeScript) with the internal REST/WS contract to the
  Agent Runtime.
- Pairing/auth flow: unknown sender gets a short-lived pairing code, admin
  approves once, identity persisted.
- First channel adapter: Telegram (matches the "Telegram etc." requirement
  and has the simplest bot API for a first integration).
- **Demo:** message the Telegram bot from a fresh account, complete pairing,
  hold a conversation that round-trips through the same agent runtime as the
  CLI.

## Phase 6 — Self-improving learning loop

**Goal:** yozhan gets better at recurring tasks without a code change.

- Trace logging on every tool call/task (latency, cost, success/failure)
  feeding the SQLite+FTS5 store from Phase 2.
- Background reviewer that proposes new `SKILL.md` files or patches to
  existing ones after a task crosses a complexity threshold; staged for
  approval by default (`learning.write_approval: true`).
- Curated `MEMORY.md` / `USER.md` per user, injected at session start, edited
  via an explicit `memory` tool.
- **Demo:** perform the same multi-step task twice; show the second run using
  a skill the system authored from the first run's trace.

## Phase 7 — Additional channels, dashboard, scheduling, hardening

**Goal:** v1.

- Additional channel adapters (Discord, Slack, at minimum).
- React/TypeScript dashboard: chat, agent/skill/provider inspector, trace/cost
  view, pairing management.
- Scheduled (`cron`-style) and continuous agent modes fully wired through the
  orchestrator (`mode: scheduled` / `mode: continuous` from `agents.yaml`).
- Sandboxing hardening: containerized tool execution backend, per-agent
  sandbox mode enforcement (`off` / `non-privileged-only` / `all`).
- Cost/latency-aware eval reporting: surface per-agent $ and latency from
  trace data already collected since Phase 6, in the dashboard.
- **Demo:** full v1 — multi-channel, dashboard-visible, scheduled agent
  running unattended, sandboxed tool execution enforced by config.

## Out of scope for v1 (explicitly deferred)

- A2A protocol support (Hermes Agent's agent-to-agent interop) — real and
  useful, but not required for a self-hosted single-user/small-team
  assistant; revisit post-v1 if federated agent use cases emerge.
- Native desktop/mobile companion apps — dashboard (web) covers v1; native
  clients are a separate, larger effort.
- Any Windows installer or PowerShell tooling — out of scope by project
  mandate; Linux/Docker only, indefinitely.
