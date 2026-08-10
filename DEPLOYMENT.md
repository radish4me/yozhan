# yozhan — Deployment

Linux/Docker only. There are no Windows installers, no PowerShell, and no
Windows-specific code paths anywhere in this project.

Two supported paths:

1. **Docker Compose** (recommended) — everything below in one command.
2. **Bare-metal Linux VPS install script** — for hosts without Docker.

## 1. Docker Compose

### Requirements

- Linux host (or Docker Desktop on macOS for local dev; production target is Linux)
- Docker Engine 25+ and the Compose plugin (`docker compose`, not `docker-compose`)
- 4-8 GB RAM floor for the default local model; see §3 for when to switch to a
  remote provider instead of sizing the VPS up

### Quickstart

```bash
git clone https://github.com/radish4me/yozhan.git
cd yozhan
cp .env.example .env
# edit .env: set at least LOCAL_DEFAULT_MODEL, and any remote provider keys you have
docker compose up
```

This starts three services:

| Service | Image/build | Port (host) | Purpose |
|---|---|---|---|
| `llama-server` | built from `ghcr.io/ggml-org/llama.cpp:server` base | 8080 (internal only) | local GGUF inference |
| `runtime` | `docker/runtime.Dockerfile` (Python) | 8787 (internal only) | agent runtime + skill/memory/router |
| `gateway` | `docker/gateway.Dockerfile` (Node) | 3000 | CLI/channel entrypoint, pairing, dashboard API |

Only `gateway`'s port is published to the host by default; `llama-server` and
`runtime` are reachable only on the internal Compose network
(`yozhan_internal`). Once Phase 7 ships the dashboard, it's served from the
`gateway` container on the same published port.

### `docker-compose.yml` structure (see repo root for the live file)

```yaml
services:
  llama-server:
    build: ./docker/llama.Dockerfile
    environment:
      - LLAMA_CACHE=/models
      - HF_TOKEN=${HF_TOKEN:-}
      - MODEL_ENDPOINT=${MODEL_ENDPOINT:-}
      - LOCAL_DEFAULT_MODEL=${LOCAL_DEFAULT_MODEL:-qwen3.5-0.8b}
    volumes:
      - llama_cache:/models
    networks: [yozhan_internal]

  runtime:
    build:
      context: .
      dockerfile: docker/runtime.Dockerfile
    env_file: .env
    volumes:
      - ./config:/app/config
      - runtime_data:/app/data
    depends_on: [llama-server]
    networks: [yozhan_internal]

  gateway:
    build:
      context: .
      dockerfile: docker/gateway.Dockerfile
    env_file: .env
    ports: ["3000:3000"]
    depends_on: [runtime]
    networks: [yozhan_internal]

volumes:
  llama_cache:
  runtime_data:

networks:
  yozhan_internal:
```

### Switching the default local model

Set `LOCAL_DEFAULT_MODEL` in `.env` to one of the three pre-configured
options (`qwen3.5-0.8b`, `lfm2.5`, `agents-a1-4b`) — or add an entirely new
entry under `providers.local.models` in `config/providers.yaml` for any other
GGUF model on Hugging Face. No rebuild is required; `llama-server` re-pulls
via `-hf <repo>:<quant>` on next container start (and caches it under the
`llama_cache` volume for subsequent starts).

### Enabling remote providers

Add API keys to `.env` (see `.env.example` for the full list —
`ANTHROPIC_API_KEY_1`, `ANTHROPIC_API_KEY_2`, `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`,
`OPENROUTER_API_KEY`, `GROK_API_KEY`, `OPENAI_API_KEY`, etc.). Multiple
numbered keys per provider enable automatic rotation — see
`config/providers.yaml` and `ARCHITECTURE.md` §4.1. No restart is required
for key/model/fallback-chain edits; the router re-reads config on next
dispatch.

### Enabling the Telegram channel and pairing new users

Set `TELEGRAM_BOT_TOKEN` in `.env` (create a bot via
[@BotFather](https://t.me/BotFather) to get one) and `GATEWAY_ADMIN_TOKEN`
(any long random string — it protects the admin-only pairing endpoints).
Restart the gateway service to pick them up.

The Gateway never trusts an unknown sender by default. The first time
someone messages the bot, they get a short-lived pairing code back instead
of a reply; approve it as the admin from a shell with `GATEWAY_ADMIN_TOKEN`
set:

```bash
GATEWAY_URL=http://localhost:3000 GATEWAY_ADMIN_TOKEN=<your token> \
  npm run pairing --prefix gateway -- list
GATEWAY_URL=http://localhost:3000 GATEWAY_ADMIN_TOKEN=<your token> \
  npm run pairing --prefix gateway -- approve <CODE>
```

Once approved, that Telegram user's messages round-trip through the same
Agent Runtime `/chat` endpoint the CLI uses, in their own persisted session
(`telegram:<chatId>`) — conversation history and tool use behave identically
to `yozhan chat`. Additional channels (Discord, Slack, ...) plug into the
same `ChannelAdapter` interface (`gateway/src/channels/types.ts`) and reuse
this same pairing flow — see ROADMAP.md Phase 7.

### GPU hosts

```bash
LLAMA_BUILD=cuda docker compose -f docker-compose.yml -f docker-compose.cuda.yml up --build
```

`docker-compose.cuda.yml` overrides the `llama-server` build to use a CUDA
base image and requests a GPU device via Compose's `deploy.resources.reservations.devices`.
CPU build remains the default with plain `docker compose up`.

## 2. Bare-metal Linux VPS install (no Docker)

For a minimal VPS where you'd rather not run Docker. `scripts/install.sh` is
plain bash, tested against Ubuntu 22.04/24.04 and Debian 12.

```bash
curl -fsSL https://raw.githubusercontent.com/radish4me/yozhan/main/scripts/install.sh | bash
```

or, reviewing before running (recommended over any curl-pipe-bash):

```bash
git clone https://github.com/radish4me/yozhan.git
cd yozhan
./scripts/install.sh
```

What it does:

1. Checks for `git`, `python3` (3.11+), `node` (22+), `cmake`, `make`, a C++
   compiler; installs missing ones via `apt` (Debian/Ubuntu) where possible,
   otherwise exits with an actionable error naming what to install manually.
2. Builds `llama.cpp` from source (CPU-only by default; pass `--cuda` to
   build with CUDA support if `nvidia-smi` is detected) into
   `~/.yozhan/llama.cpp/`.
3. Creates a Python virtualenv under `~/.yozhan/venv`, installs the
   `runtime` package (`pip install -e ./runtime`).
4. Installs Node dependencies for the `gateway` package (`npm ci --prefix
   ./gateway`).
5. Copies `config/providers.yaml`, `config/agents.yaml`, and `.env.example`
   (→ `.env`) into `~/.yozhan/` if not already present — re-running the
   script never overwrites an existing config.
6. Writes and enables two `systemd --user` units, `yozhan-runtime.service`
   and `yozhan-gateway.service` (or prints the equivalent manual commands if
   systemd/user services aren't available), so both processes survive reboot.
7. Prints the CLI entrypoint (`yozhan chat`) and the Gateway's listening port.

No PowerShell, no `.exe`, no Windows code path exists anywhere in this
script or the repo — this is the only supported non-Docker path, and it is
Linux-only by design.

## 3. VPS sizing and the local-vs-remote cutover point

The documented floor is **2-4 vCPU / 4-8 GB RAM**. At that floor:

- Qwen3.5-0.8B (Q4_K_M, the shipped default — see `ARCHITECTURE.md` §4.3)
  runs comfortably alongside the Gateway and Agent Runtime processes.
- LFM2.5 is also edge-sized and workable at this floor; verify headroom if
  running multiple concurrent agent sessions.
- Agents-A1-4B (4B params) is the upper edge of what this floor can host —
  expect noticeably higher latency and reduced headroom for concurrent
  sessions; treat it as "usable, not comfortable" at the floor spec, and
  comfortable once RAM is closer to 8 GB dedicated to the model alone.

**Switch that agent's `agents.yaml` model assignment to a remote provider**
(rather than upsizing the VPS) once any of the following is true:

- The task needs a model larger than ~4B parameters for quality reasons.
- Multiple agents/sub-agents need to run local inference concurrently and
  latency degrades under that contention.
- The workload is latency-sensitive (e.g. a live chat channel with several
  simultaneous users) and local CPU inference can't keep up.

Because model assignment is per-agent config (`ARCHITECTURE.md` §4.2), this
is a one-line edit — e.g. changing `coder`'s `fallback_chain` from
`local_first` to `default` — not a redeploy.
