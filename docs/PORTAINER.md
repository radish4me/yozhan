# Deploying yozhan on a VPS with Portainer

Two ways to do this. Pick one.

| | Method A — Web editor | Method B — Repository |
|---|---|---|
| What it does | Pulls prebuilt images | Builds the images on your VPS |
| Setup | Paste one file | Point at the GitHub repo |
| First deploy | ~2 min + model download | ~5-10 min + model download |
| Needs | Published GHCR images | Nothing extra |

**Method A is the recommended path** — nothing compiles on your VPS.

> **Before Method A works**, the images must exist. They're published by the
> `Publish images` GitHub Action on every push to `master`. Check
> <https://github.com/radish4me/yozhan/pkgs/container/yozhan-runtime> — if it
> 404s, the workflow hasn't run yet (run it from the Actions tab) or the
> packages are private. Use Method B in the meantime; it needs no images.

Neither method compiles llama.cpp. Both use the upstream
`ghcr.io/ggml-org/llama.cpp:server` image, because building llama.cpp on a
2-4 vCPU VPS takes a long time and can run the box out of memory.

## Before you start

- A Linux VPS with **at least 4 GB RAM** (see [Sizing](#sizing) below)
- Portainer CE installed and reachable
- A long random string for `GATEWAY_ADMIN_TOKEN`. Generate one:

```bash
openssl rand -hex 32
```

Keep it somewhere safe — it's what authorizes pairing approvals and skill
approvals. Anyone with it can approve a stranger onto your assistant.

---

## Method A — Web editor (recommended)

### 1. Create the stack

Portainer → **Stacks** → **Add stack**

- **Name**: `yozhan`
- **Build method**: **Web editor**
- Paste the entire contents of
  [`deploy/portainer-stack.yml`](../deploy/portainer-stack.yml)

### 2. Set environment variables

Scroll to **Environment variables** → **Add an environment variable** for each.

**Required:**

| Name | Value |
|---|---|
| `GATEWAY_ADMIN_TOKEN` | your `openssl rand -hex 32` output |

**Optional but common:**

| Name | Example | What it does |
|---|---|---|
| `GATEWAY_PORT` | `3000` | Host port for the dashboard/API |
| `LLAMA_HF_MODEL` | `Qwen/Qwen3.5-0.8B-GGUF:Q4_K_M` | Which GGUF model to serve |
| `LLAMA_THREADS` | `2` | Match your vCPU count |
| `LLAMA_CONTEXT_SIZE` | `4096` | Lower it to save RAM |
| `TELEGRAM_BOT_TOKEN` | `123456:ABC…` | Turns on the Telegram channel |
| `ANTHROPIC_API_KEY_1` | `sk-ant-…` | Remote provider (optional) |
| `GEMINI_API_KEY_1` | `AIza…` | Remote provider (optional) |
| `OPENROUTER_API_KEY` | `sk-or-…` | Remote provider (optional) |
| `HF_TOKEN` | `hf_…` | Only for gated Hugging Face models |

You don't need any provider keys. With none set, yozhan runs entirely on the
local model.

### 3. Deploy

Click **Deploy the stack**.

The first start downloads the model (a few hundred MB for the default), so
`llama-server` sits in `starting` for several minutes. That's expected — the
healthcheck allows 5 minutes before it complains.

### 4. Check it came up

Portainer → **Containers**. You should see `llama-server`, `runtime`, and
`gateway` all `running`. Then open:

```
http://YOUR_VPS_IP:3000
```

You should get the yozhan dashboard. Try the **Chat** tab.

---

## Method B — Repository (builds on your VPS)

Portainer → **Stacks** → **Add stack**

- **Name**: `yozhan`
- **Build method**: **Repository**
- **Repository URL**: `https://github.com/radish4me/yozhan`
- **Repository reference**: `refs/heads/master`
- **Compose path**: `deploy/portainer-stack-build.yml`

Add the same environment variables as Method A, then **Deploy the stack**.

Portainer clones the repo (which is what gives `build:` a context — this is
exactly why the Web editor can't build) and builds the runtime and gateway
images. Allow 5-10 minutes on a small VPS.

To update later: Portainer → your stack → **Pull and redeploy**.

---

## Turning things on

### The dashboard

`http://YOUR_VPS_IP:3000`. Read-only tabs (Chat, Agents, Providers, Costs)
work immediately. To approve pairings or skill proposals, open **Settings**
and paste your `GATEWAY_ADMIN_TOKEN` — it's kept for that browser session
only.

### Telegram

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token
2. Add `TELEGRAM_BOT_TOKEN` to the stack's environment variables
3. Redeploy the stack
4. Message your bot. It replies with a pairing code, because unknown senders
   are not trusted by default.
5. Approve it: dashboard → **Pairing** → **Approve**. Or from a shell:

```bash
docker exec -it $(docker ps -qf name=gateway) sh -c 'GATEWAY_URL=http://localhost:3000 GATEWAY_ADMIN_TOKEN=YOUR_TOKEN node dist/pairing-cli.js list'
```

Discord (`DISCORD_BOT_TOKEN`) and Slack (`SLACK_APP_TOKEN` **and**
`SLACK_BOT_TOKEN`) work the same way.

### Scheduled agents

The `scheduler` service is opt-in. Once you've added a `mode: scheduled`
agent to `agents.yaml` (see below), add this environment variable and
redeploy:

| Name | Value |
|---|---|
| `COMPOSE_PROFILES` | `scheduler` |

---

## Editing configuration

`providers.yaml` and `agents.yaml` live in the `yozhan_config` volume, seeded
from the image the first time the stack starts. Your edits survive redeploys.

Portainer → **Containers** → `runtime` → **Console** → `/bin/sh`, then:

```bash
cat /app/config/agents.yaml
```

The image is slim and has no editor, so the easiest way to change a file is
to copy it out, edit it, and copy it back — from an SSH session on the VPS:

```bash
docker cp $(docker ps -qf name=runtime):/app/config/agents.yaml ./agents.yaml
nano ./agents.yaml
docker cp ./agents.yaml $(docker ps -qf name=runtime):/app/config/agents.yaml
docker restart $(docker ps -qf name=runtime)
```

Most day-to-day tuning (which model, which API keys) is doable through stack
environment variables alone and needs none of this.

---

## Sizing

The floor is **2-4 vCPU / 4-8 GB RAM**.

| Model | RAM for the model | Verdict at 4 GB |
|---|---|---|
| `Qwen/Qwen3.5-0.8B-GGUF:Q4_K_M` | ~1 GB | Comfortable — the default |
| `LiquidAI/LFM2.5-GGUF:Q4_K_M` | ~1.5 GB | Workable |
| `SomeOrg/Agents-A1-4B-Q4_K_M-GGUF` | ~3 GB | Tight. Wants 8 GB |

**Switch that agent to a remote provider instead of upsizing the VPS** when
you need a model above ~4B, when several agents run local inference at once
and latency degrades, or when a live chat channel has several simultaneous
users. It's a one-line change in `agents.yaml`, not a redeploy.

---

## Troubleshooting

**`invalid interpolation format ... You may need to escape any $ with another $`**

You edited a `${VAR:?...}` or `${VAR:-}` line to hard-code a value and wrote
`${VAR:value}`. Compose has no such form — it needs a dash:

| Syntax | Meaning |
|---|---|
| `${VAR:value}` | invalid — this error |
| `${VAR:-value}` | use `value` when `VAR` is unset or empty |
| `${VAR:?message}` | fail with `message` when `VAR` is unset |

Don't hard-code it at all: put the value in **Environment variables** below
the editor and leave the `${...}` reference alone. Stack definitions are
stored and shown in plain text, so a token pasted into the file is readable
by anyone with access to the stack. If you already pasted a real token
anywhere it shouldn't be, rotate it — Telegram tokens via @BotFather →
*Revoke current token*.

**`gateway` restarts / stack won't deploy**
`GATEWAY_ADMIN_TOKEN` isn't set. It's deliberately required — the stack
refuses to come up rather than exposing unauthenticated admin endpoints.

**`llama-server` unhealthy for a long time on first start**
It's downloading the model. Check: Containers → `llama-server` → **Logs**.
If it's still going after ~10 minutes, your VPS may be short on RAM or disk.

**Chat replies `local provider request failed`**
`llama-server` isn't up yet or has died. Check its logs. On a 2 GB VPS it
will be OOM-killed — that's a sizing problem, not a config one.

**`manifest unknown` when pulling images (Method A)**
The GHCR images don't exist or are private. See the note at the top; use
Method B in the meantime.

**Telegram bot doesn't answer**
Expected until you approve the pairing code it sent you. If it doesn't
respond at all, check `TELEGRAM_BOT_TOKEN` and the `gateway` logs.

**Discord messages arrive empty**
Enable the **Message Content** privileged intent in the Discord developer
portal.

---

## Updating and backups

**Update** — Method A: Portainer → stack → **Pull and redeploy** (ticking
*Re-pull image*). Method B: **Pull and redeploy** rebuilds from the latest
commit.

**Back up** these volumes — they hold everything you'd miss:

- `yozhan_data` — conversation history, traces, curated memory
- `yozhan_config` — your edited `providers.yaml` / `agents.yaml`
- `yozhan_user_skills` — skills the learning loop authored and you approved
- `gateway_data` — pairing state

```bash
docker run --rm -v yozhan_yozhan_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/yozhan-data-$(date +%F).tar.gz -C /data .
```

`llama_cache` is just downloaded models — skip it, it re-downloads.

---

## Security notes

- **Only the gateway's port is published.** The runtime and llama-server stay
  on an internal Docker network. Don't publish them.
- **Port 3000 has no TLS and no login.** The dashboard's read-only views are
  open to anyone who can reach that port. Put it behind a reverse proxy with
  HTTPS and auth (Caddy, nginx, Traefik), or firewall it to your own IP,
  before exposing it to the internet.
- **`GATEWAY_ADMIN_TOKEN` is the real key.** It authorizes pairing and skill
  approvals. Treat it like a password.
- **Sandboxing is on by default** (`non-privileged-only`): tool code runs in
  a separate process with a scrubbed environment and cannot read your
  provider API keys. If you install skills you didn't write, switch
  `defaults.sandbox_backend` to `docker` in `agents.yaml` for container
  isolation — and note that requires giving the runtime access to the Docker
  socket, which is itself a privilege worth thinking about.
