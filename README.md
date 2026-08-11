# yozhan

A self-hosted, open-source AI assistant that unifies three previously-separate
capabilities into one deployable system: a **local-first multi-agent/skill
framework**, a **multi-channel gateway** with pairing and sandboxed tool
execution, and a **self-improving learning loop** with multi-provider model
routing. Deployable via `docker compose up` or a bare Linux VPS install
script. **Linux/Docker only** — no Windows installers, PowerShell, or
Windows-specific code paths anywhere in this project.

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design (including
the concrete per-agent model-assignment and provider/fallback config
schemas), [ROADMAP.md](ROADMAP.md) for the phased build plan, and
[DEPLOYMENT.md](DEPLOYMENT.md) for setup instructions.

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

v1 feature-complete against [ROADMAP.md](ROADMAP.md) Phases 1-7: local
inference + CLI chat, a single-agent core with a unified skill format,
multi-agent orchestration with per-agent model assignment, a
multi-provider/multi-key router with fallback chains and parallel fan-out,
a channel gateway (Telegram, Discord, Slack) with pairing, a self-improving
learning loop with approval-gated skill authoring, scheduled/continuous
agents, sandboxed tool execution, a React dashboard, and cost/latency
reporting.

## Project layout

```
runtime/     Python agent runtime — agent loop, skills, memory, model provider router
gateway/     Node/TypeScript channel gateway — pairing, channel adapters, sandboxing
dashboard/   React/TypeScript dashboard — chat, agents, providers, costs, pairing
config/      providers.yaml, agents.yaml — the two files you actually edit
skills/      built-in skills (SKILL.md, agentskills.io-compatible format)
docker/      Dockerfiles for llama-server, runtime, gateway
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
