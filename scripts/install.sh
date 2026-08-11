#!/usr/bin/env bash
# yozhan bare-metal Linux VPS installer. Debian/Ubuntu focused; see
# DEPLOYMENT.md section 2. Linux-only by project mandate — do not add a
# Windows/PowerShell path here.
set -euo pipefail

YOZHAN_HOME="${YOZHAN_HOME:-$HOME/.yozhan}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CUDA=0

for arg in "$@"; do
  case "$arg" in
    --cuda) CUDA=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

log() { echo "[yozhan-install] $*"; }

require_or_apt_install() {
  local bin="$1" pkg="$2"
  if ! command -v "$bin" >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
      log "installing $pkg (missing $bin)"
      sudo apt-get update -qq && sudo apt-get install -y "$pkg"
    else
      echo "missing dependency '$bin' and no apt-get available; install '$pkg' manually" >&2
      exit 1
    fi
  fi
}

log "checking dependencies"
require_or_apt_install git git
require_or_apt_install cmake cmake
require_or_apt_install make build-essential
require_or_apt_install python3 python3
require_or_apt_install node nodejs

mkdir -p "$YOZHAN_HOME"

# --- 1. build llama.cpp from source ---
if [ ! -x "$YOZHAN_HOME/llama.cpp/build/bin/llama-server" ]; then
  log "building llama.cpp (cuda=$CUDA)"
  if [ ! -d "$YOZHAN_HOME/llama.cpp" ]; then
    git clone --depth 1 https://github.com/ggml-org/llama.cpp "$YOZHAN_HOME/llama.cpp"
  fi
  cmake_flags=(-DLLAMA_CURL=ON -DCMAKE_BUILD_TYPE=Release)
  if [ "$CUDA" -eq 1 ]; then
    cmake_flags+=(-DGGML_CUDA=ON)
  fi
  cmake -S "$YOZHAN_HOME/llama.cpp" -B "$YOZHAN_HOME/llama.cpp/build" "${cmake_flags[@]}"
  cmake --build "$YOZHAN_HOME/llama.cpp/build" --target llama-server -j"$(nproc)"
else
  log "llama-server already built, skipping"
fi

# --- 2. python venv + runtime package ---
log "setting up python venv"
python3 -m venv "$YOZHAN_HOME/venv"
"$YOZHAN_HOME/venv/bin/pip" install --quiet --upgrade pip
"$YOZHAN_HOME/venv/bin/pip" install --quiet -e "$REPO_DIR/runtime"

# --- 3. gateway + dashboard ---
log "installing gateway node dependencies"
npm ci --prefix "$REPO_DIR/gateway"
npm run build --prefix "$REPO_DIR/gateway"

log "building dashboard"
npm ci --prefix "$REPO_DIR/dashboard"
npm run build --prefix "$REPO_DIR/dashboard"

# --- 4. config (never overwrite an existing install) ---
mkdir -p "$YOZHAN_HOME/config"
for f in providers.yaml agents.yaml; do
  if [ ! -f "$YOZHAN_HOME/config/$f" ]; then
    cp "$REPO_DIR/config/$f" "$YOZHAN_HOME/config/$f"
  fi
done
if [ ! -f "$YOZHAN_HOME/.env" ]; then
  cp "$REPO_DIR/.env.example" "$YOZHAN_HOME/.env"
  log "wrote default config to $YOZHAN_HOME/.env — edit it to add provider keys"
fi

# --- 5. systemd --user units (best-effort) ---
if command -v systemctl >/dev/null 2>&1 && systemctl --user status >/dev/null 2>&1; then
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/yozhan-runtime.service" <<EOF
[Unit]
Description=yozhan agent runtime
[Service]
Environment=YOZHAN_CONFIG_DIR=$YOZHAN_HOME/config
Environment=YOZHAN_SKILLS_DIR=$REPO_DIR/skills
Environment=YOZHAN_USER_SKILLS_DIR=$YOZHAN_HOME/skills
Environment=YOZHAN_DATA_DIR=$YOZHAN_HOME/data
Environment=YOZHAN_WORKSPACE_DIR=$YOZHAN_HOME/workspace
Environment=LLAMA_SERVER_URL=http://127.0.0.1:8080/v1
EnvironmentFile=$YOZHAN_HOME/.env
ExecStart=$YOZHAN_HOME/venv/bin/yozhan serve
Restart=on-failure
[Install]
WantedBy=default.target
EOF
  cat > "$HOME/.config/systemd/user/yozhan-gateway.service" <<EOF
[Unit]
Description=yozhan gateway
After=yozhan-runtime.service
[Service]
WorkingDirectory=$REPO_DIR/gateway
Environment=RUNTIME_URL=http://127.0.0.1:8787
Environment=DASHBOARD_DIR=$REPO_DIR/dashboard/dist
EnvironmentFile=$YOZHAN_HOME/.env
ExecStart=/usr/bin/env node dist/index.js
Restart=on-failure
[Install]
WantedBy=default.target
EOF
  cat > "$HOME/.config/systemd/user/yozhan-scheduler.service" <<EOF
[Unit]
Description=yozhan scheduled/continuous agents
After=yozhan-runtime.service
[Service]
Environment=YOZHAN_CONFIG_DIR=$YOZHAN_HOME/config
Environment=YOZHAN_SKILLS_DIR=$REPO_DIR/skills
Environment=YOZHAN_USER_SKILLS_DIR=$YOZHAN_HOME/skills
Environment=YOZHAN_DATA_DIR=$YOZHAN_HOME/data
Environment=YOZHAN_WORKSPACE_DIR=$YOZHAN_HOME/workspace
Environment=LLAMA_SERVER_URL=http://127.0.0.1:8080/v1
EnvironmentFile=$YOZHAN_HOME/.env
ExecStart=$YOZHAN_HOME/venv/bin/yozhan scheduler
Restart=on-failure
[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now yozhan-runtime.service yozhan-gateway.service
  log "enabled systemd --user services: yozhan-runtime, yozhan-gateway"
  # The scheduler unit is written but left disabled: it exits immediately when
  # no scheduled/continuous agent is configured, which with Restart=on-failure
  # would just spin. Enable it once you've added one to config/agents.yaml.
  log "scheduler unit written (disabled) — enable with:"
  log "  systemctl --user enable --now yozhan-scheduler.service"
else
  log "systemd --user unavailable; start manually:"
  log "  YOZHAN_CONFIG_DIR=$YOZHAN_HOME/config YOZHAN_SKILLS_DIR=$REPO_DIR/skills \\"
  log "  YOZHAN_DATA_DIR=$YOZHAN_HOME/data YOZHAN_WORKSPACE_DIR=$YOZHAN_HOME/workspace \\"
  log "  $YOZHAN_HOME/venv/bin/yozhan serve"
  log "  (cd $REPO_DIR/gateway && npm run build && node dist/index.js)"
fi

log "done. CLI chat: $YOZHAN_HOME/venv/bin/yozhan chat"
