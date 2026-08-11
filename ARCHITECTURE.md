# yozhan — Architecture

yozhan is a self-hosted AI assistant that unifies three ideas that today live in
separate projects:

- **local-first multi-agent/skill framework** (inspired by OpenJarvis)
- **multi-channel gateway with pairing + sandboxed execution** (inspired by OpenClaw)
- **self-improving learning loop + multi-provider model routing** (inspired by Hermes Agent)

Nothing in this repo is copied from those projects. This document describes an
original design that borrows *concepts*, not code, and maps each concept to a
concrete component below.

## 1. Design goals

1. Runs end-to-end on a modest Linux VPS (2-4 vCPU / 4-8 GB RAM) with a local
   quantized model, with no external API keys required to get a working assistant.
2. Scales up cleanly to remote/cloud model providers, multiple channels, and
   multiple concurrent agents without a rewrite.
3. One unified skill format used by every agent, every channel tool call, and the
   learning loop — no per-component skill dialect.
4. Model selection is configuration, not code: which model backs which agent
   (and which sub-agent), and which providers/keys are available, are both
   plain YAML files a self-hoster edits directly.
5. Docker Compose is the default deploy path; a bash install script is the
   fallback for a bare VPS. Linux only — no Windows installers or PowerShell
   anywhere in the shipped tooling.

## 2. Component map

```
                         ┌─────────────────────────────────────────┐
                         │              Dashboard (React/TS)         │
                         │  chat UI · agent/skill inspector · logs   │
                         └───────────────────┬───────────────────────┘
                                              │ REST/WS
┌───────────────────────────────────────────┴───────────────────────────────────┐
│                          Gateway  (Node/TypeScript)                            │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────────────────┐    │
│  │  Channel      │  │  Pairing &        │  │  Sandboxed tool execution     │    │
│  │  Adapters     │  │  Auth             │  │  (docker/subprocess isolation)│    │
│  │  (Telegram,   │  │  (device/DM       │  │                                │    │
│  │  Discord,     │  │  pairing codes,   │  │                                │    │
│  │  Slack, CLI…) │  │  capability grants)│  │                                │    │
│  └──────┬────────┘  └─────────┬─────────┘  └───────────────┬───────────────┘    │
│         └────────────────────┬┴────────────────────────────┘                    │
│                    normalized Message/Event bus (WS to agent runtime)           │
└───────────────────────────────┬──────────────────────────────────────────────────┘
                                 │ REST/WS (internal, localhost by default)
┌────────────────────────────────┴──────────────────────────────────────────────┐
│                        Agent Runtime  (Python)                                 │
│  ┌───────────────┐   ┌────────────────────┐   ┌──────────────────────────┐    │
│  │ Orchestrator  │   │  Agent loop(s)      │   │  Skill / Tool layer       │    │
│  │ (routes tasks │──▶│  on-demand /        │──▶│  SKILL.md + frontmatter   │    │
│  │  to agents,   │   │  scheduled /        │   │  (agentskills.io format), │    │
│  │  fan-out for  │   │  continuous         │   │  registered tools, MCP    │    │
│  │  parallel     │   │  BaseAgent.run()    │   │  passthrough              │    │
│  │  sub-agents)  │   └─────────┬───────────┘   └────────────┬──────────────┘    │
│  └───────┬───────┘             │                            │                   │
│          │                     ▼                            ▼                   │
│          │        ┌────────────────────────┐   ┌────────────────────────────┐  │
│          │        │ Memory & Learning Store │   │  Model Provider Router     │  │
│          │        │ SQLite+FTS5 session/    │   │  providers.yaml: provider  │  │
│          │        │ trace log · MEMORY.md/  │   │  lists, per-provider model │  │
│          │        │ USER.md curated memory ·│   │  lists, multi-key rotation,│  │
│          │        │ skill-authoring loop    │   │  fallback chains, parallel │  │
│          │        │ (writes/patches SKILL.md│   │  fan-out                   │  │
│          │        │ from usage traces)      │   └───────────┬────────────────┘  │
│          │        └────────────────────────┘                │                   │
│          └───────────────────────────────────────────────────┘                  │
└────────────────────────────────┬──────────────────────────────────────────────┘
                                  │ OpenAI-compatible HTTP
                    ┌─────────────┴─────────────┐        ┌───────────────────────┐
                    │   llama-server (llama.cpp) │        │  Remote providers:     │
                    │   local GGUF inference,    │        │  OpenRouter, Gemini,   │
                    │   HF_TOKEN/LLAMA_CACHE,    │        │  Grok, OpenAI,         │
                    │   CPU default / CUDA flag  │        │  Anthropic, custom      │
                    └────────────────────────────┘        └───────────────────────┘
```

## 3. Components in detail

### 3.1 Gateway (TypeScript / Node)

Owns everything that talks to the outside world, mirroring OpenClaw's
gateway-as-daemon concept:

- **Channel adapters** — one package per channel (`gateway/channels/telegram`,
  `.../discord`, `.../slack`, `.../cli`), each translating a platform's native
  message format into a normalized internal `Event`. Adding a channel means
  adding an adapter package, not touching the agent runtime.
- **Pairing & auth** — unknown senders on a channel get a short-lived pairing
  code that an admin approves once; approved identities are persisted and
  scoped to specific agents/capabilities. Separate from provider API-key auth.
- **Sandboxed tool execution** — when a skill's tool step needs to run
  arbitrary code (shell, file I/O, browser), the Gateway executes it in an
  isolated subprocess/container rather than the agent runtime's process,
  configurable per-agent as `off` / `non-privileged-only` / `all`.
- Talks to the Agent Runtime over an internal REST/WebSocket API, defaulting to
  localhost-only binding.

### 3.2 Agent Runtime (Python)

The core "brain," structured around a small `BaseAgent` interface (on-demand,
scheduled, continuous execution modes) and an `Orchestrator` that resolves a
task to one or more agents/sub-agents and, when the task allows it, fans it out
to run **in parallel** against different models (see §4).

### 3.3 Skill / Tool layer (Python, shared)

A single skill format is used everywhere — CLI, channels, scheduled agents,
and the learning loop — so a skill authored by the learning loop is
immediately usable by any agent:

- Each skill is a directory: `SKILL.md` (YAML frontmatter: `name`, `version`,
  `description`, `capabilities`, `tags`, `depends_on`) + markdown body
  (procedure/instructions) + optional `tool.py`/`tool.ts` implementation.
- Format is compatible with the open **agentskills.io** specification, so
  existing community skills can be dropped into `skills/` without translation.
- A `SkillManager` discovers skills at startup (`skills/` built-ins +
  `~/.yozhan/skills/` user overrides) and exposes them to the orchestrator as
  callable tools.

### 3.4 Memory & Learning Store (Python)

- **Session/trace store**: SQLite + FTS5 (default, zero external deps) —
  conversation history, tool-call traces, latency/cost/energy metadata per
  call. Pluggable vector backend (e.g. FAISS via sentence-transformers) behind
  the same `MemoryBackend` interface for semantic recall.
- **Curated memory**: two size-capped, human-readable files per user —
  `MEMORY.md` (durable facts/preferences) and `USER.md` (profile) — injected
  into agent context at session start. Edited via an explicit `memory` tool,
  not silently rewritten.
- **Learning loop**: after a task crosses a complexity threshold (multiple
  tool calls, an error-recovery, or an explicit user correction), a background
  reviewer proposes a new skill or a *patch* to an existing `SKILL.md`. Writes
  are staged for approval by default (`learning.write_approval: true`);
  auto-commit is opt-in per deployment.

### 3.5 Model Provider Router (Python)

Central place that turns a logical `(provider, model)` reference into an
actual HTTP call, with fallback and rotation baked into config rather than
code. Full schema in §4.

### 3.6 Local inference (llama.cpp)

- `llama-server` (OpenAI-compatible `/v1/chat/completions`) run as a
  subprocess/service — never reimplemented.
- Models are pulled straight from Hugging Face: `llama-server -hf
  <repo>[:quant]`. No separate model-management daemon; `LLAMA_CACHE` controls
  the on-disk GGUF cache, `HF_TOKEN` / `MODEL_ENDPOINT` are respected for
  gated models / mirrors.
- CPU build is the default target (matches the VPS floor); a `CUDA=1` build
  flag switches to a GPU build for hosts that have one.

### 3.7 Dashboard (React/TypeScript)

Thin client against the Gateway's REST/WS API: chat, agent/skill/config
inspector, provider health, trace/cost view. Ships after the CLI/channel path
is solid (Phase 7) — not required for the core assistant to function.

## 4. Configuration schemas

These are the two files a self-hoster actually edits. Both live under
`config/` and are hot-reloadable (a change takes effect on next task
dispatch, no restart required for model/routing changes).

### 4.1 `config/providers.yaml` — providers, models, keys, fallback chains

```yaml
# One entry per provider. Each provider may list MULTIPLE models and
# MULTIPLE API keys; keys rotate automatically on rate-limit/error.
providers:
  local:
    type: llama_cpp
    base_url: http://llama-server:8080/v1   # OpenAI-compatible
    models:
      - id: qwen3.5-0.8b
        hf: Qwen/Qwen3.5-0.8B-GGUF:Q4_K_M
      - id: lfm2.5
        hf: LiquidAI/LFM2.5-GGUF:Q4_K_M
      - id: agents-a1-4b
        hf: SomeOrg/Agents-A1-4B-Q4_K_M-GGUF
    default_model: qwen3.5-0.8b   # global default (see rationale below)

  anthropic:
    type: anthropic
    api_keys:
      - env: ANTHROPIC_API_KEY_1
      - env: ANTHROPIC_API_KEY_2       # 2nd key: auto-rotate on 429
    models: [claude-sonnet-5, claude-haiku-4-5]

  gemini:
    type: gemini
    api_keys:
      - env: GEMINI_API_KEY_1
      - env: GEMINI_API_KEY_2
    models: [gemini-2.5-flash, gemini-2.5-pro]

  openrouter:
    type: openrouter
    api_keys:
      - env: OPENROUTER_API_KEY
    models: [qwen/qwen-2.5-coder, google/gemini-flash-1.5, x-ai/grok-4]

  grok:
    type: grok
    api_keys: [{env: GROK_API_KEY}]
    models: [grok-4]

  openai:
    type: openai
    api_keys: [{env: OPENAI_API_KEY}]
    models: [gpt-5.1, gpt-5.1-mini]

  custom_vps:                          # any self-hosted OpenAI-compatible endpoint
    type: openai_compatible
    base_url: https://models.example.internal/v1
    api_keys: [{env: CUSTOM_VPS_KEY}]
    models: [my-finetune-7b]

# Fallback chains: ordered list tried top-to-bottom on error/rate-limit/timeout.
# Referenced by name from agents.yaml (see §4.2). Purely config, no code change
# needed to reorder, add, or remove a step.
fallback_chains:
  default:
    - {provider: anthropic, model: claude-sonnet-5}
    - {provider: gemini, model: gemini-2.5-flash}
    - {provider: openrouter, model: qwen/qwen-2.5-coder}
    - {provider: local, model: qwen3.5-0.8b}

  local_first:
    - {provider: local, model: qwen3.5-0.8b}
    - {provider: openrouter, model: google/gemini-flash-1.5}

  cheap_parallel_fanout:               # used by orchestrator for multi-model fan-out
    mode: parallel                     # run all entries concurrently, not sequentially
    members:
      - {provider: openrouter, model: qwen/qwen-2.5-coder}
      - {provider: gemini, model: gemini-2.5-flash}
      - {provider: local, model: qwen3.5-0.8b}
```

### 4.2 `config/agents.yaml` — per-agent and per-sub-agent model assignment

```yaml
# Every agent/sub-agent resolves to a model via EITHER a direct
# {provider, model} pin OR a named fallback_chain from providers.yaml.
# Omitting both inherits `defaults.fallback_chain`.

defaults:
  fallback_chain: default
  sandbox: non-privileged-only

agents:
  orchestrator:
    fallback_chain: default            # top-level router/planner agent

  researcher:
    subagent_of: orchestrator
    fallback_chain: local_first        # cheap, runs on the VPS's local model
    mode: on-demand

  coder:
    subagent_of: orchestrator
    provider: anthropic                # direct pin, no fallback list
    model: claude-sonnet-5
    mode: on-demand

  reviewer:
    subagent_of: orchestrator
    fallback_chain: cheap_parallel_fanout   # fans out to 3 models at once,
    mode: on-demand                         # orchestrator merges/votes on results

  scheduler_digest:
    fallback_chain: default
    mode: scheduled
    schedule: "0 8 * * *"               # cron; daily digest agent

  monitor:
    fallback_chain: local_first
    mode: continuous                    # long-running watch agent
```

**Resolution order** for any agent/sub-agent: explicit `provider`+`model` pin
→ named `fallback_chain` → `defaults.fallback_chain`. Sub-agents may override
independently of their parent (a `coder` sub-agent can pin Claude while its
parent `orchestrator` uses the default chain) — nothing cascades unless the
child omits its own setting.

### 4.3 Why Qwen3.5-0.8B as the out-of-the-box default

Of the three required shipped models, Qwen3.5-0.8B has the smallest parameter
count and memory footprint. On the documented VPS floor (2-4 vCPU / 4-8 GB
RAM), a Q4_K_M quant of an ~0.8B model leaves enough headroom for the
Gateway (Node) and Agent Runtime (Python) processes to run alongside it
without swapping. LFM2.5 and Agents-A1-4B (4B params) remain fully supported
— switch `providers.local.default_model` (and `agents.yaml` overrides) with
no code change — but are better suited to hosts with more RAM or a GPU.
**Local-inference cutover point:** once a workload needs a model above
roughly 4B parameters, or needs consistent low-latency response under
concurrent multi-agent fan-out, switch that agent's config to a remote
provider (see `fallback_chains.default` above) rather than sizing the VPS up
for local inference — documented further in `DEPLOYMENT.md`.

## 5. Source-project → yozhan concept map

| Concept | Source project | yozhan component |
|---|---|---|
| `BaseAgent`, on-demand/scheduled/continuous execution | OpenJarvis | Agent Runtime `agents/base.py` |
| Skill manifest + `agentskills.io` compliance | OpenJarvis, Hermes Agent, OpenClaw (all three converge here) | Skill/Tool layer, `SKILL.md` format |
| Energy/cost-aware trace metadata | OpenJarvis | Memory/Learning Store trace log columns |
| Channel adapters, pairing codes, sandboxed tool execution | OpenClaw | Gateway |
| Skill self-authoring/patching from usage traces | Hermes Agent | Learning loop in Memory & Learning Store |
| Curated `MEMORY.md`/`USER.md`, cross-session recall | Hermes Agent | Memory & Learning Store |
| Multi-provider routing, per-(provider,model) credential resolution | Hermes Agent | Model Provider Router |
| A2A protocol support | Hermes Agent | `runtime/yozhan_runtime/a2a/` — inbound agent card + JSON-RPC, outbound named-peer client (Phase 8) |

## 6. Internal transport

Gateway (Node) ↔ Agent Runtime (Python) communicate over REST for
request/response calls and WebSocket for streaming tokens/events, both
bound to `127.0.0.1` by default in Docker Compose (inter-container network),
never exposed to the host network directly — only the Gateway's
channel-facing ports and the Dashboard are published.
