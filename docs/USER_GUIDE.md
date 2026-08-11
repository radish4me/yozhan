# yozhan — User Guide

A practical guide to installing, configuring, and actually using yozhan.

- Deploying on a VPS with Portainer? → [PORTAINER.md](PORTAINER.md)
- Want the design rationale? → [ARCHITECTURE.md](../ARCHITECTURE.md)

**Contents**

1. [What yozhan is](#1-what-yozhan-is)
2. [Install](#2-install)
3. [First run](#3-first-run)
4. [Configuration](#4-configuration)
5. [Using it](#5-using-it)
6. [Skills](#6-skills)
7. [Memory and the learning loop](#7-memory-and-the-learning-loop)
8. [Multiple agents](#8-multiple-agents)
9. [Scheduled agents](#9-scheduled-agents)
10. [Sandboxing](#10-sandboxing)
11. [Costs](#11-costs)
12. [Talking to other agents (A2A)](#12-talking-to-other-agents-a2a)
13. [Troubleshooting](#13-troubleshooting)
14. [Command reference](#14-command-reference)

---

## 1. What yozhan is

A self-hosted AI assistant you run on your own machine or VPS. It:

- runs a **local model** by default (llama.cpp), so it works with no API keys
- can **fall back to remote providers** (Anthropic, Gemini, OpenRouter, …) per
  agent, with automatic key rotation and fallback chains
- reaches you over **Telegram, Discord, Slack**, a **CLI**, or a **web dashboard**
- **learns skills** from what it does, and asks before saving them
- runs tool code in a **sandbox** that can't see your API keys

Linux and Docker only. There are no Windows installers.

---

## 2. Install

### Option A — Docker Compose (easiest)

Requires Docker Engine 25+ with the Compose plugin.

```bash
git clone https://github.com/radish4me/yozhan.git
cd yozhan
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
GATEWAY_ADMIN_TOKEN=paste-a-long-random-string-here
```

Generate one with `openssl rand -hex 32`. Then:

```bash
docker compose up -d
```

This builds llama.cpp from source, which takes a while. **On a small VPS use
the [Portainer stacks](PORTAINER.md) instead** — they use a prebuilt llama.cpp
image and skip the compile entirely.

### Option B — VPS with Portainer

See [PORTAINER.md](PORTAINER.md). This is the recommended VPS path.

### Option C — Bare Linux, no Docker

```bash
git clone https://github.com/radish4me/yozhan.git
cd yozhan
./scripts/install.sh
```

It installs dependencies, builds llama.cpp, creates a Python virtualenv,
builds the gateway and dashboard, and writes `systemd --user` services. Pass
`--cuda` on a GPU host.

---

## 3. First run

The first start downloads the model (a few hundred MB), so give it a few
minutes. Check progress:

```bash
docker compose logs -f llama-server
```

Then talk to it:

```bash
docker compose exec runtime yozhan chat
```

```
yozhan chat — model: qwen3.5-0.8b | session: default | tools: read_file, web_search, memory_note, a2a_peer
you> hello
yozhan> Hi! How can I help?
```

Or open the dashboard at `http://localhost:3000` (`http://YOUR_VPS_IP:3000`).

Conversations persist. Re-running `yozhan chat` continues where you left off.
Use `--session work` to keep separate threads.

---

## 4. Configuration

Two files do almost everything. Both are hot-reloaded — a change takes effect
on the next task, no restart needed.

### `config/providers.yaml` — models, keys, fallback

Which models exist and what to do when one fails.

```yaml
providers:
  local:
    type: llama_cpp
    base_url: http://llama-server:8080/v1
    models:
      - id: qwen3.5-0.8b
        hf: unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M
      - id: lfm2.5
        hf: LiquidAI/LFM2.5-1.2B-Instruct-GGUF:Q4_K_M
    default_model: ${LOCAL_DEFAULT_MODEL:-qwen3.5-0.8b}

  gemini:
    type: gemini
    api_keys:
      - env: GEMINI_API_KEY_1
      - env: GEMINI_API_KEY_2   # rotates here automatically on a 429
    models: [gemini-2.5-flash, gemini-2.5-pro]
```

**Fallback chains** are tried top to bottom until one works:

```yaml
fallback_chains:
  default:
    - {provider: anthropic, model: claude-sonnet-5}
    - {provider: gemini, model: gemini-2.5-flash}
    - {provider: local, model: qwen3.5-0.8b}    # always ends somewhere free
```

A `mode: parallel` chain queries every member at once instead:

```yaml
  cheap_parallel_fanout:
    mode: parallel
    members:
      - {provider: openrouter, model: qwen/qwen-2.5-coder}
      - {provider: gemini, model: gemini-2.5-flash}
```

**Adding any other model**: add an entry under a provider's `models:`. Any
GGUF repo on Hugging Face works for `local`.

### `config/agents.yaml` — who uses which model

```yaml
defaults:
  fallback_chain: default
  sandbox: non-privileged-only

agents:
  researcher:
    fallback_chain: local_first     # cheap, stays on the VPS
    mode: on-demand

  coder:
    provider: anthropic             # pinned to one model
    model: claude-sonnet-5
    mode: on-demand
```

Resolution order per agent: an explicit `provider` + `model` pin →
its named `fallback_chain` → `defaults.fallback_chain`. **Sub-agents resolve
independently** — a `coder` sub-agent can be pinned to Claude while its parent
uses the default chain.

Check what resolved:

```bash
yozhan agents
```

```
orchestrator     mode=on-demand  subagent_of=-              -> anthropic/claude-sonnet-5
researcher       mode=on-demand  subagent_of=orchestrator   -> local/qwen3.5-0.8b
```

### Environment variables

Set in `.env` (Compose) or the stack's environment variables (Portainer).

| Variable | Purpose |
|---|---|
| `GATEWAY_ADMIN_TOKEN` | **Required.** Authorizes pairing + skill approvals |
| `LOCAL_DEFAULT_MODEL` | Which shipped local model to use |
| `ANTHROPIC_API_KEY_1`, `_2` | Two keys ⇒ automatic rotation |
| `GEMINI_API_KEY_1`, `_2` | Same |
| `OPENROUTER_API_KEY`, `GROK_API_KEY`, `OPENAI_API_KEY` | Other providers |
| `TELEGRAM_BOT_TOKEN` | Enables Telegram |
| `DISCORD_BOT_TOKEN` | Enables Discord |
| `SLACK_APP_TOKEN` + `SLACK_BOT_TOKEN` | Enables Slack (needs both) |
| `HF_TOKEN` | Only for gated Hugging Face models |

---

## 5. Using it

### CLI

```bash
yozhan chat                      # interactive
yozhan chat --session work       # a separate thread
yozhan chat --model lfm2.5       # override the model for this session
```

### Dashboard

`http://localhost:3000` — chat, resolved model assignments, skills, provider
key health, cost/latency, staged skill proposals, pairing.

Read-only tabs need nothing. To approve anything, paste your
`GATEWAY_ADMIN_TOKEN` under **Settings** (held for that browser session only).

### Messaging channels

Set the token, restart, then message the bot. **It will not answer yet** —
unknown senders get a pairing code instead, because an open bot is an open
door to your assistant and your provider spend.

Approve it in the dashboard's **Pairing** tab, or:

```bash
GATEWAY_URL=http://localhost:3000 GATEWAY_ADMIN_TOKEN=... \
  npm run pairing --prefix gateway -- list
GATEWAY_URL=http://localhost:3000 GATEWAY_ADMIN_TOKEN=... \
  npm run pairing --prefix gateway -- approve ABCD1234
```

Each paired identity gets its own persistent session, so your Telegram history
and your CLI history are separate.

---

## 6. Skills

A skill is a folder with a `SKILL.md`. Some also have a `tool.py` the model
can call.

```
skills/read-file/
  SKILL.md      manifest + instructions
  tool.py       optional implementation
```

```markdown
---
name: read-file
version: 0.1.0
description: Read a UTF-8 text file from the workspace.
capabilities: [filesystem]
tags: [example]
depends_on: []
tool: true          # has a callable tool.py
elevated: false     # true = runs outside the sandbox (see §10)
---

# read-file

1. Take the path.
2. Return the file contents.
```

The format follows the [agentskills.io](https://agentskills.io/specification)
spec, so community skills drop in without translation.

**Where skills load from**

- `skills/` — shipped with yozhan
- the user skills dir (`~/.yozhan/skills`, or the `yozhan_user_skills` volume)
  — yours, plus anything the learning loop wrote. Kept separate so an approved
  proposal can never overwrite a built-in.

`tool.py` needs `NAME`, `DESCRIPTION`, `PARAMETERS` (JSON Schema), and `run()`:

```python
NAME = "word_count"
DESCRIPTION = "Count words in some text."
PARAMETERS = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}

def run(text: str) -> str:
    return f"{len(text.split())} words"
```

Drop the folder in the user skills dir and restart the runtime.

---

## 7. Memory and the learning loop

### Curated memory

Two small Markdown files injected at the start of every session:

- `MEMORY.md` — durable facts, preferences, project context
- `USER.md` — who you are

```bash
yozhan memory show
yozhan memory add "prefers concise answers"
yozhan memory add "works in UTC+1" --kind user
yozhan memory remove "concise"
```

The assistant can write to these itself through the `memory_note` tool. Both
are **size-capped** on purpose — they're prompt overhead paid on every single
turn, and an unbounded memory file quietly turns into noise. A write over the
cap is refused rather than truncated, so you condense instead of sprawling.

### The learning loop

After a task that took several tool calls or recovered from an error, yozhan
asks a model to write the procedure up as a reusable skill.

**Nothing is written to disk automatically.** Proposals are staged:

```bash
yozhan learn pending          # what's waiting
yozhan learn show 1           # read the full SKILL.md
yozhan learn approve 1        # write it to the user skills dir
yozhan learn reject 1
```

Or use the dashboard's **Learning** tab.

Approval is the default because an agent that silently rewrites its own
instruction set is very hard to debug and easy to poison. Turn it off in
`agents.yaml` (`learning.write_approval: false`) only if you understand that.

```yaml
learning:
  enabled: true
  write_approval: true
  min_tool_calls: 3            # below this, a task teaches nothing reusable
  fallback_chain: local_first  # the reviewer is a cheap background job
```

Review older tasks manually:

```bash
yozhan learn review --limit 10
```

---

## 8. Multiple agents

Run several agents on one task, each with its own model:

```bash
yozhan orchestrate \
  --agent researcher "find the three most recent releases" \
  --agent coder "write a migration script"
```

```
[researcher] local/qwen3.5-0.8b
  -> ...
[coder] anthropic/claude-sonnet-5
  -> ...
```

One agent failing doesn't stop the others. An agent on a `mode: parallel`
chain queries several models at once and returns all their answers labelled.

---

## 9. Scheduled agents

Agents that run without you. Add to `agents.yaml`:

```yaml
agents:
  digest:
    fallback_chain: local_first
    mode: scheduled
    schedule: "0 8 * * *"      # min hour day month weekday
    task: "Summarize anything noteworthy from yesterday's sessions."

  watcher:
    fallback_chain: local_first
    mode: continuous
    interval_seconds: 900
    task: "Check the workspace for new files."
```

Both need a `task:` — there's no human turn to supply one.

```bash
yozhan scheduler
```

Under Docker Compose the `scheduler` service already does this. In Portainer
it's opt-in — set `COMPOSE_PROFILES=scheduler` and redeploy.

Cron supports `*`, `5`, `1-5`, `1,3,5`, and `*/15`. Not `@daily` — and not
seconds; something that frequent wants a continuous agent.

---

## 10. Sandboxing

Tool code runs in a sandbox by default. The point is that a skill — one you
installed from elsewhere, or one the learning loop wrote — **cannot read your
provider API keys**. Sandboxed tools get a small environment allowlist, never
`ANTHROPIC_API_KEY_1`, `HF_TOKEN`, or `GATEWAY_ADMIN_TOKEN`.

```yaml
defaults:
  sandbox: non-privileged-only   # off | non-privileged-only | all
  sandbox_backend: subprocess    # subprocess | docker | podman
  sandbox_timeout_seconds: 30
```

| Mode | Behaviour |
|---|---|
| `off` | everything runs in the runtime process |
| `non-privileged-only` | everything sandboxed except skills marked `elevated: true` |
| `all` | everything sandboxed |

Any agent can override the default with its own `sandbox:`.

A skill sets `elevated: true` when it genuinely needs the runtime process —
`memory-note` writes outside the workspace, `a2a-peer` needs network and peer
tokens. Marking a skill elevated is a deliberate trust decision, which is why
it lives in the manifest rather than in the code.

**Know the limits.** `subprocess` is process isolation: it stops credential
leakage and runaway tools. It is *not* kernel isolation and won't contain
someone who already has code execution. For skills you didn't write, use the
`docker` backend — a throwaway container with `--network none` and read-only
mounts. That backend needs a Docker socket and CLI available to the runtime,
which the shipped runtime image doesn't have; if it's missing you'll get a
clear "backend is not installed" error rather than a silent fallback to no
sandboxing.

---

## 11. Costs

Every model and tool call is traced.

```bash
yozhan costs                 # by agent
yozhan costs --by model
yozhan costs --by provider
```

```
agent             calls  fails    avg ms    tokens        USD
coder                 2      0       416      1,540     0.0087
researcher            1      1       140          0     0.0000
```

Or the dashboard's **Costs** tab.

Cost needs prices. Add them per model in `providers.yaml`:

```yaml
  anthropic:
    models:
      - id: claude-sonnet-5
        pricing: {input_per_mtok: 3.0, output_per_mtok: 15.0}
```

**A model with no `pricing:` block reports `$0.0000` because its cost is
unknown, not because it's free.** Local llama.cpp inference is genuinely $0
and is priced as such explicitly.

---

## 12. Talking to other agents (A2A)

Off by default — turning it on both exposes this agent and lets it call out.

```yaml
a2a:
  enabled: true
  require_token: true
  token_env: A2A_INBOUND_TOKEN
  public_url: https://yozhan.example.com/a2a
  peers:
    - name: research-bot
      url: https://peer.example.com/a2a
      token_env: A2A_PEER_RESEARCH_TOKEN
```

**Inbound**: other agents fetch `GET /.well-known/agent-card.json` and post
JSON-RPC `message/send` to `/a2a` with a bearer token. Only skills marked
`a2a: true` are advertised — nothing is published by default. If a token is
required but unset, requests are refused rather than allowed through.

**Outbound**: the `a2a_peer` skill can `list`, `discover`, and `ask`. Peers
must be **named in config**. There's deliberately no URL parameter: a tool
that fetches whatever URL a prompt names is a request-forgery primitive aimed
at your own network, including cloud metadata endpoints.

Text from a peer is labelled untrusted in both directions. That reduces
prompt-injection risk without eliminating it — extend a peer roughly the trust
you'd extend an anonymous user.

---

## 13. Troubleshooting

**`local provider request failed`**
`llama-server` isn't up. `docker compose logs llama-server`. On first run it's
downloading; on a 2 GB box it's being OOM-killed.

**`no API key configured for provider 'anthropic'`**
The key env var isn't set, or you set it in `.env` without restarting.

**`every provider in the fallback chain failed`**
Every entry failed — the message lists each reason. Usually no local model
running *and* no remote keys.

**The bot ignores me**
Expected until you approve its pairing code. Dashboard → **Pairing**.

**Dashboard loads but tabs are empty**
The gateway can't reach the runtime. Check the `runtime` container.

**The assistant forgot something I told it**
Conversation history is per session. Cross-session facts belong in curated
memory — `yozhan memory add "..."`.

**A skill I added isn't showing up**
It needs `SKILL.md` with valid frontmatter including `name` and
`description`, in a folder under a skills dir. Restart the runtime and check
`yozhan agents` / the dashboard's Skills list.

**A tool errors with "not installed on this host"**
You set `sandbox_backend: docker` but the runtime has no Docker CLI/socket.
Use `subprocess`, or give the runtime Docker access.

---

## 14. Command reference

```bash
# Chat
yozhan chat [--session NAME] [--model ID]

# Inspect
yozhan agents                          # agents + resolved models
yozhan costs [--by agent|model|provider]

# Multi-agent
yozhan orchestrate --agent NAME "task" [--agent NAME "task" ...]

# Memory
yozhan memory show [--kind memory|user]
yozhan memory add "note" [--kind memory|user]
yozhan memory remove "substring"

# Learning
yozhan learn review [--limit N] [--session NAME]
yozhan learn pending
yozhan learn show ID
yozhan learn approve ID
yozhan learn reject ID

# Services
yozhan serve [--host H] [--port P]     # runtime HTTP API
yozhan scheduler                       # scheduled/continuous agents
```

Under Docker, prefix with `docker compose exec runtime`.

**Gateway HTTP API** (default `:3000`)

| Method | Path | Auth |
|---|---|---|
| `GET` | `/health` | — |
| `POST` | `/chat` | — |
| `GET` | `/agents`, `/skills`, `/providers`, `/costs`, `/proposals` | — |
| `POST` | `/proposals/:id/approve`, `/proposals/:id/reject` | admin token |
| `GET` | `/pairing/pending`, `/pairing/paired` | admin token |
| `POST` | `/pairing/approve` | admin token |

The read-only endpoints have no auth — put the gateway behind a reverse proxy
with TLS and access control before exposing it publicly.
