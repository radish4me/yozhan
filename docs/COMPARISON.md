# What yozhan doesn't have

yozhan borrows ideas from OpenJarvis, OpenClaw and Hermes Agent. It is much
smaller than any of them. This is the honest gap list.

**On accuracy:** this is based on those projects' public documentation as read
in August 2026, when yozhan's architecture was designed. All three move fast,
so treat it as a snapshot — check upstream before relying on any single line.
yozhan's side of the comparison is checked against its own source.

**The short version:** all three are mature platforms with plugin ecosystems,
many channels, and years of accumulated surface. yozhan implements one
coherent path through the same problem space — local-first inference, a
config-driven multi-provider router, one skill format, an approval-gated
learning loop, and a small number of well-tested channels — and deliberately
stops there.

---

## Missing from yozhan regardless of source

These come up in more than one of the three, and are the largest gaps.

| Capability | Who has it | Notes |
|---|---|---|
| **MCP server** | OpenClaw | yozhan is an MCP *client* (any stdio server's tools are usable), but does not expose its own tools over MCP to other applications. |
| **TUI** | Hermes | yozhan's CLI is a plain prompt/response REPL — no panes, mouse selection, or modal overlays. |
| **Plugin system** (third-party code extending the runtime) | OpenClaw, Hermes | yozhan has skills, not plugins. You cannot register a new provider type, channel, or memory backend without editing the source. |
| **Skill registry / marketplace** | All three | No ClawHub/Skills-Hub/`skill install <url>` equivalent. Skills are files you write or the learning loop proposes. |
| **Vector / semantic memory** | OpenJarvis, Hermes | SQLite FTS5 keyword search only. No embeddings, FAISS, ColBERT, or hybrid retrieval. |
| **Voice, images, attachments** | OpenClaw, Hermes | Text only, end to end. |
| **Native desktop / mobile apps** | OpenJarvis, OpenClaw, Hermes | Web dashboard only. |
| **Windows support** | OpenClaw, Hermes | Excluded by project mandate, not by omission. |

---

## OpenJarvis (Apache-2.0)

Local-first agent framework from Stanford's Hazy Research / Scaling
Intelligence Lab.

**Not in yozhan:**

- **Eight-plus built-in agent types** — `native_react`, CodeAct/OpenHands,
  `operative`, `monitor_operative`, `RLMAgent`, `ClaudeCodeAgent` and others.
  yozhan has one concrete agent (`ChatAgent`) that every configured agent runs
  as; the variation is in model assignment and mode, not in agent architecture.
- **Auto-discovering inference backends** — Ollama, vLLM and SGLang behind one
  `InferenceEngine` interface with health probing. yozhan reaches all three
  through its OpenAI-compatible provider type, but you configure them by hand
  rather than having them discovered.
- **Retrieval backends** — FAISS, ColBERTv2, BM25 and RRF hybrid fusion.
- **Learned routing** — `TraceDrivenPolicy` and a GRPO-based router policy that
  learn which model to use from past traces. yozhan's routing is static
  config: you write the chain, it walks it.
- **Energy-aware evaluation** — FLOPs and watt-hours as first-class metrics,
  plus a community "savings leaderboard". yozhan tracks latency, tokens and
  dollars, but not energy.
- **A Rust extension** for performance-critical paths.
- **Desktop installers** — `.exe`, `.dmg`, `.deb`, `.rpm`, `.AppImage`.
- **`jarvis skill install`** from arbitrary GitHub repos.

---

## OpenClaw (MIT)

Personal-assistant gateway; by far the largest surface of the three.

**Not in yozhan:**

- **~45 more channels** — WhatsApp, Signal, iMessage, Matrix, Microsoft Teams,
  Google Chat, IRC, Line, WeChat, Zalo and more. yozhan has three: Telegram,
  Discord, Slack.
- **An MCP *server*** — OpenClaw both consumes and exposes MCP; yozhan only consumes.
- **A real plugin SDK** — `openclaw.plugin.json` manifests validated without
  executing code, typed `api.register*()` hooks for model providers, speech,
  embeddings and channels, plus auto-detection of Agent Plugins / Codex /
  Claude / Cursor bundle formats.
- **ClawHub** community distribution.
- **Node pairing plus capability approval** — yozhan pairs *identities* on a
  channel; OpenClaw also pairs *devices* and approves per-capability what a
  connected node may expose.
- **Sandbox scopes** — `agent` / `session` / `shared`, and SSH and "openshell"
  backends. yozhan has modes but a single scope, and subprocess/docker/podman
  backends only.
- **Access groups, channel routing, bot-loop protection** as configurable
  policy. yozhan ignores bot messages but has no group/routing policy layer.
- **Native companion apps** for Android, iOS, macOS and Linux.
- **Managed deployment targets** — Kubernetes, Fly.io, Render, Railway,
  Northflank, Ansible, Nix, Raspberry Pi. yozhan documents Docker Compose,
  Portainer and a bare-metal script.
- **Cross-platform installers**, including Windows.

---

## Hermes Agent (MIT)

Self-improving agent from Nous Research.

**Not in yozhan:**

- **70+ tools across 28 toolsets**, self-registering. yozhan ships seven
  skills, one of which is a stub — though MCP now closes much of this gap, since
  any MCP server's tools become usable.
- **A richer CLI surface** — `hermes doctor`, `hermes setup`,
  `--continue`/`--resume`, interrupt-and-redirect mid-turn, and `-w` to run an
  agent in an isolated git worktree. (yozhan now has slash commands, but not
  these.)
- **A full TUI.**
- **Seven execution backends** — local, Docker, SSH, Singularity, Modal,
  Daytona, Vercel Sandbox, including hibernate-on-idle serverless.
- **Pluggable memory providers** (Honcho and others) for cross-session user
  modelling.
- **OAuth for provider auth** and ~18 providers. yozhan is API-key only, with
  six provider types plus a generic OpenAI-compatible one.
- **`provider_routing`** — sort by price/throughput/latency, `only`/`ignore`
  lists, explicit ordering (via OpenRouter). yozhan's chains are hand-written.
- **Profile-based routing** — one gateway serving many isolated profiles, keyed
  per Discord server/channel/thread.
- **ACP adapter** for IDE integration.
- **Electron desktop app.**

**Where yozhan is closest to Hermes:** the learning loop, curated
`MEMORY.md`/`USER.md`, and A2A are all present — A2A with inbound auth that
fails closed and outbound calls restricted to named peers.

---

## Things yozhan does that none of the three do in the same way

Not a claim of superiority — mostly consequences of being small and late.

- **One agent runtime, three surfaces.** CLI, channels and dashboard all run
  the same `ChatAgent` against the same session store, so behaviour cannot
  drift between them.
- **Config edits validated by the real resolver.** Saving `agents.yaml` from
  the dashboard resolves every agent against it first; a config that would
  break every task is refused rather than written, with automatic backups and
  rollback.
- **Sandboxed tools get a scrubbed environment.** A skill — including one the
  learning loop wrote — cannot read `ANTHROPIC_API_KEY_1` or any other
  credential.
- **Learning writes are approval-gated by default**, and model-authored skill
  names are validated before they become directories.
- **Unpriced models report cost as unknown, not zero**, so a cost report can't
  quietly under-report.
