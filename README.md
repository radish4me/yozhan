# yozhan

A self-hosted, open-source AI assistant that unifies three previously-separate
capabilities into one deployable system: a **local-first multi-agent/skill
framework**, a **multi-channel gateway** with pairing and sandboxed tool
execution, and a **self-improving learning loop** with multi-provider model
routing. Deployable via `docker compose up` or a bare Linux VPS install
script. **Linux/Docker only** — no Windows installers, PowerShell, or
Windows-specific code paths anywhere in this project.

**New here? Start with the [User Guide](docs/USER_GUIDE.md).**
Deploying to a VPS? [Portainer setup](docs/PORTAINER.md).

| Doc | What's in it |
|---|---|
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Install, configure, and use yozhan |
| [docs/PORTAINER.md](docs/PORTAINER.md) | Step-by-step VPS deployment with Portainer |
| [docs/COMPARISON.md](docs/COMPARISON.md) | What OpenJarvis, OpenClaw and Hermes Agent have that yozhan doesn't |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Docker Compose + bare-metal install reference |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design and the config schemas |
| [ROADMAP.md](ROADMAP.md) | Phased build plan and license notes |

## Quickstart

```bash
git clone https://github.com/radish4me/yozhan.git
cd yozhan
cp .env.example .env
docker compose up
```

Then, in another terminal:

```bash
docker compose exec runtime yozhan chat
```

This talks to `llama-server` (llama.cpp) running the default local model,
[Qwen3.5-0.8B](https://huggingface.co/Qwen) — chosen as the out-of-the-box
default because it's the smallest of the three shipped models and fits
comfortably on a 2-4 vCPU / 4-8 GB RAM VPS alongside the Gateway and Agent
Runtime processes (see [ARCHITECTURE.md §4.3](ARCHITECTURE.md#43-why-qwen35-08b-as-the-out-of-the-box-default)).
Switch it, or add any other GGUF model from Hugging Face, by editing
[`config/providers.yaml`](config/providers.yaml) — no code change required.

For a bare VPS without Docker, see [DEPLOYMENT.md](DEPLOYMENT.md#2-bare-metal-linux-vps-install-no-docker).

## Status

Phases 1-12 of [ROADMAP.md](ROADMAP.md) are implemented. See
[Features](#features) for exactly what that means, and
[docs/COMPARISON.md](docs/COMPARISON.md) for what the projects that inspired
yozhan have that it does not.

## Features

### Local inference
- llama.cpp (`llama-server`) as a subprocess/service, never reimplemented
- GGUF models pulled straight from Hugging Face — no model-management daemon
- Three shipped, switchable models: Qwen3.5-0.8B (default), LFM2.5-1.2B, Agents-A1-4B
- Any other GGUF repo on Hugging Face works by editing one config line
- CPU build by default; CUDA build flag for GPU hosts
- Runs on a 2-4 vCPU / 4-8 GB VPS

### Model providers and routing
- Multiple providers: OpenAI, Anthropic, Gemini, Grok, OpenRouter, local llama.cpp, and any OpenAI-compatible endpoint
- **Multiple models per provider**, all usable at once
- **Fallback chains** — ordered, user-editable; on error/rate-limit/timeout the router walks to the next entry
- **Multiple API keys per provider**, rotating automatically on 401/403/429
- **Parallel fan-out** — a `mode: parallel` chain queries several models concurrently
- Per-model pricing for cost reporting; an unpriced model reports cost as *unknown*, never as free

### Agents
- `BaseAgent` with on-demand, **scheduled** (cron), and **continuous** (interval) modes
- Orchestrator dispatching across multiple agents, each independently model-assigned
- Per-agent and per-sub-agent model assignment; sub-agents override independently of their parent
- Agent-level sandbox overrides
- Built-in scheduler process for unattended agents

### Skills and tools
- One `SKILL.md` format everywhere (agentskills.io-compatible frontmatter)
- Optional `tool.py` per skill, exposed to the model as a callable tool
- Built-in skills: `read-file`, `web-search` (stub), `memory-note`, `a2a-peer`, `example-echo`
- User skills directory kept separate from shipped ones
- Create/edit/delete skills from the dashboard

### Memory and learning
- SQLite + FTS5 session store; history persists across restarts, per session id
- Curated cross-session memory (`MEMORY.md` / `USER.md`), size-capped, injected at session start
- Full trace log: every model and tool call with latency, tokens, cost, success/failure
- **Self-improving loop** — writes a reusable `SKILL.md` from a task's trace
- Proposals are **staged for approval**, never written silently
- Model-authored skill names validated before becoming a directory

### Channels
- **Telegram** (long-polling — no public URL needed)
- **Discord** (gateway websocket)
- **Slack** (Socket Mode — no public URL needed)
- Pairing: unknown senders get a short-lived code an admin approves once
- Per-identity persistent sessions (`telegram:<chat id>`)
- Bot-authored messages ignored, so two bots can't loop

### Dashboard (React/TypeScript)
- Chat, agent/skill/provider inspector, cost & latency report
- **Config editor** for `agents.yaml` / `providers.yaml` with validate-before-save and version history + rollback
- **Keys & tokens** manager (write-only — values are never displayed back)
- Skills editor, curated-memory editor
- Learning-proposal review, channel pairing approval

### Security
- Username/password login, created on first run; scrypt hashing
- Server-side sessions in an HttpOnly/SameSite cookie; `Secure` set automatically behind a TLS proxy
- Login throttling; no user enumeration; password change revokes other sessions
- **Sandboxed tool execution** — subprocess (default) or docker/podman, with a scrubbed environment so skill code cannot read your provider API keys
- Per-agent sandbox modes: `off` / `non-privileged-only` / `all`
- Config changes validated before writing, backed up, and attributed in an audit log

### Interop
- **A2A** (Agent2Agent) — agent card, JSON-RPC `message/send`, outbound named-peer client. Off by default
- Bearer-token API for scripts and CI

### Deployment
- `docker compose up`, or Portainer stacks (web-editor and repository methods)
- Bare-metal Linux install script with systemd units
- GHCR image publishing workflow
- nginx reverse-proxy config included
- Linux/Docker only — no Windows installers or PowerShell anywhere

## Not included

Called out explicitly so the list above can be trusted:

- **No MCP (Model Context Protocol)** client or server
- **No slash commands** (`/model`, `/newsession`, `/skillcreate`, …) in chat or channels
- **No TUI**; the CLI is a plain REPL
- **No voice, image, or file attachments** on any channel
- **No WhatsApp, Signal, iMessage, Matrix, Teams** or other channels beyond the three above
- **No skill marketplace/registry** — skills are local files
- **No vector/semantic memory** — full-text search only
- **No native desktop or mobile apps**

[docs/COMPARISON.md](docs/COMPARISON.md) has the full gap analysis against
OpenJarvis, OpenClaw and Hermes Agent.

## Project layout

```
runtime/     Python agent runtime — agent loop, skills, memory, model provider router
gateway/     Node/TypeScript channel gateway — pairing, channel adapters, sandboxing
dashboard/   React/TypeScript dashboard — chat, agents, providers, costs, pairing
config/      providers.yaml, agents.yaml — the two files you actually edit
skills/      built-in skills (SKILL.md, agentskills.io-compatible format)
docker/      Dockerfiles for llama-server, runtime, gateway
deploy/      Portainer stack files for VPS deployment
docs/        user guide and Portainer walkthrough
scripts/     bare-metal Linux install script
```

## License and attribution

yozhan is released under the [MIT License](LICENSE), Copyright (c) 2026
Radhakrishnan.

**Created by [Radhakrishnan](https://github.com/radish4me).**

yozhan's design draws architectural inspiration from three excellent
open-source projects — no code is copied or vendored from any of them; each
concept was reimplemented from their public documentation. See
[ROADMAP.md](ROADMAP.md#license-compatibility) for the full license-compatibility
notes.

- [OpenJarvis](https://github.com/open-jarvis/OpenJarvis) (Apache-2.0) — local-first agent framework, skill system, energy/cost-aware evals
- [OpenClaw](https://github.com/openclaw/openclaw) (MIT) — multi-channel gateway, pairing/security model, sandboxed tool execution
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) (MIT) — self-improving learning loop, persistent memory, multi-provider routing
