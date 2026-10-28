#!/usr/bin/env bash
# Local dev bootstrap for this Mac.
#   ./install.sh          check requirements, install deps, restart web + api
#   ./install.sh --stop   just stop anything running on the dev ports
#   ./install.sh --check  only run the requirement checks
#   ./install.sh --serve  install launchd agents: the API on :8000 and the named Cloudflare tunnel
#                         (api.folio.jckjjcckk.com); both restart after a crash or reboot. See deploy/README.md
#   ./install.sh --unserve  stop and remove those agents
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_PORT=5173
API_PORT=8000
LOG_DIR="$ROOT/.logs"
MODE="${1:-start}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }

fail=0
need() { # need <cmd> <hint>
  if command -v "$1" >/dev/null 2>&1; then green "  ok   $1 ($($1 --version 2>&1 | head -1))"
  else red "  MISSING $1  -> $2"; fail=1; fi
}
env_filled() { # env_filled <file> <KEY>...
  local f="$1"; shift
  if [ ! -f "$f" ]; then red "  MISSING $f  -> cp ${f}.example $f and fill it in"; fail=1; return; fi
  for k in "$@"; do
    if grep -qE "^${k}=.+" "$f"; then green "  ok   $k"
    else red "  EMPTY $k in $f"; fail=1; fi
  done
}

kill_port() {
  local pids
  pids="$(lsof -ti tcp:"$1" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    dim "  stopping port $1 (pids: $(echo "$pids" | tr '\n' ' '))"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    pids="$(lsof -ti tcp:"$1" 2>/dev/null || true)"
    # shellcheck disable=SC2086
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
  fi
}

lan_ip() { ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1"; }

# ---------------------------------------------------------------- stop
if [ "$MODE" = "--stop" ]; then
  echo "Stopping dev servers"; kill_port $WEB_PORT; kill_port $API_PORT; green "done"; exit 0
fi

# ---------------------------------------------------------------- serve (launchd: API + named tunnel)
API_LABEL="com.jckjjcckk.folio.api"
TUNNEL_LABEL="com.jckjjcckk.folio.tunnel"
TUNNEL_NAME="macbook_pro_m4"
API_HOST="api.folio.jckjjcckk.com"
AGENTS="$HOME/Library/LaunchAgents"
unload_agent() { launchctl bootout "gui/$(id -u)/$1" >/dev/null 2>&1 || true; }

if [ "$MODE" = "--unserve" ]; then
  echo "Removing launchd agents"
  unload_agent "$API_LABEL"; unload_agent "$TUNNEL_LABEL"
  rm -f "$AGENTS/$API_LABEL.plist" "$AGENTS/$TUNNEL_LABEL.plist"
  green "done"; exit 0
fi

if [ "$MODE" = "--serve" ]; then
  echo "Serving the API behind the named tunnel"
  need uv "brew install uv"; need cloudflared "brew install cloudflared"
  env_filled "$ROOT/api/.env" SUPABASE_URL SUPABASE_SECRET_KEY CORS_ORIGINS
  grep -qE '^CORS_ORIGINS=.*https://folio\.jckjjcckk\.com' "$ROOT/api/.env" || { red "  CORS_ORIGINS in api/.env must include https://folio.jckjjcckk.com (and capacitor://localhost for the iPad app)"; fail=1; }
  if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
    red "  cloudflared is not logged in on this Mac."
    echo "    1. cloudflared tunnel login            (browser: choose the jckjjcckk.com zone)"
    echo "    2. cloudflared tunnel list             (must show $TUNNEL_NAME; if its ~/.cloudflared/<UUID>.json is missing, recreate it:"
    echo "       cloudflared tunnel delete $TUNNEL_NAME && cloudflared tunnel create $TUNNEL_NAME)"
    echo "    3. cloudflared tunnel route dns $TUNNEL_NAME $API_HOST"
    echo "    4. ./install.sh --serve"
    exit 1
  fi
  uuid="$(cloudflared tunnel list --name "$TUNNEL_NAME" --output json 2>/dev/null | python3 -c 'import json,sys; t=json.load(sys.stdin); print(t[0]["id"] if t else "")' 2>/dev/null || true)"
  [ -n "$uuid" ] || { red "  tunnel $TUNNEL_NAME not found: cloudflared tunnel create $TUNNEL_NAME"; exit 1; }
  cred="$HOME/.cloudflared/$uuid.json"
  [ -f "$cred" ] || { red "  $cred missing (the tunnel was created on another machine): cloudflared tunnel delete $TUNNEL_NAME && cloudflared tunnel create $TUNNEL_NAME, then rerun"; exit 1; }
  [ "$fail" -ne 0 ] && { red "Fix the items above, then rerun."; exit 1; }
  # The checked-in config is a template; the copy with this Mac's tunnel id and credentials path lives in ~/.cloudflared.
  CF_CONFIG="$HOME/.cloudflared/folio.yml"
  sed -e "s|^tunnel: .*|tunnel: $uuid|" -e "s|^credentials-file: .*|credentials-file: $cred|" "$ROOT/deploy/cloudflared/config.yml" >"$CF_CONFIG"
  cloudflared tunnel route dns "$TUNNEL_NAME" "$API_HOST" >/dev/null 2>&1 || true
  ( cd "$ROOT/api" && uv sync --quiet )
  mkdir -p "$LOG_DIR" "$AGENTS"
  UV="$(command -v uv)"; CF="$(command -v cloudflared)"
  write_agent() { # write_agent <label> <workdir> <log> <program args...>
    local label="$1" wd="$2" log="$3"; shift 3
    local args=""; for a in "$@"; do args="$args
    <string>$a</string>"; done
    cat >"$AGENTS/$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>$args
  </array>
  <key>WorkingDirectory</key><string>$wd</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict></plist>
PLIST
  }
  unload_agent "$API_LABEL"; unload_agent "$TUNNEL_LABEL"; kill_port $API_PORT
  write_agent "$API_LABEL" "$ROOT/api" "$LOG_DIR/api.serve.log" "$UV" run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT"
  write_agent "$TUNNEL_LABEL" "$ROOT" "$LOG_DIR/tunnel.serve.log" "$CF" tunnel --config "$CF_CONFIG" run
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$API_LABEL.plist"
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$TUNNEL_LABEL.plist"
  for i in $(seq 1 40); do curl -sf "http://localhost:$API_PORT/health" >/dev/null 2>&1 && break; sleep 0.5; done
  curl -sf "http://localhost:$API_PORT/health" >/dev/null && green "api  http://localhost:$API_PORT (launchd $API_LABEL)" || red "api did not start, see $LOG_DIR/api.serve.log"
  for i in $(seq 1 30); do curl -sf "https://$API_HOST/health" >/dev/null 2>&1 && break; sleep 1; done
  curl -sf "https://$API_HOST/health" >/dev/null && green "api  https://$API_HOST/health" || red "https://$API_HOST not answering yet (DNS can take a minute), see $LOG_DIR/tunnel.serve.log"
  dim "Stop and remove: ./install.sh --unserve"
  exit 0
fi

# ---------------------------------------------------------------- checks
echo "Tools"
need node "brew install node"
need npm  "comes with node"
need uv   "brew install uv"
need git  "xcode-select --install"
if command -v node >/dev/null 2>&1; then
  major="$(node -p 'process.versions.node.split(".")[0]')"
  [ "$major" -ge 20 ] || { red "  node >= 20 required, have $major"; fail=1; }
fi
echo "Optional"
command -v docker  >/dev/null 2>&1 && green "  ok   docker (Audiveris fallback)"  || dim "  --   docker not found (only needed for Audiveris)"
command -v supabase >/dev/null 2>&1 && green "  ok   supabase cli" || dim "  --   supabase cli not found (brew install supabase/tap/supabase)"

echo "web/.env"
env_filled "$ROOT/web/.env" VITE_SUPABASE_URL VITE_SUPABASE_PUBLISHABLE_KEY VITE_API_URL
echo "api/.env"
env_filled "$ROOT/api/.env" SUPABASE_URL SUPABASE_SECRET_KEY LLM_PROVIDER META_API_KEY
provider="$(grep -E '^LLM_PROVIDER=' "$ROOT/api/.env" 2>/dev/null | cut -d= -f2 || true)"
if [ "$provider" = "anthropic" ]; then env_filled "$ROOT/api/.env" ANTHROPIC_API_KEY; fi

if [ "$fail" -ne 0 ]; then red "Fix the items above, then rerun."; exit 1; fi
[ "$MODE" = "--check" ] && { green "All checks passed."; exit 0; }

# ---------------------------------------------------------------- install
echo "Installing dependencies"
( cd "$ROOT/web" && npm install --no-fund --no-audit --silent )
( cd "$ROOT/api" && uv sync --quiet )
green "  deps ok"

# ---------------------------------------------------------------- restart
echo "Restarting servers"
kill_port $WEB_PORT; kill_port $API_PORT
mkdir -p "$LOG_DIR"
( cd "$ROOT/api" && nohup uv run uvicorn app.main:app --reload --host 0.0.0.0 --port $API_PORT >"$LOG_DIR/api.log" 2>&1 & )
( cd "$ROOT/web" && nohup npm run dev -- --port $WEB_PORT >"$LOG_DIR/web.log" 2>&1 & )

for i in $(seq 1 20); do curl -sf "http://localhost:$API_PORT/health" >/dev/null 2>&1 && break; sleep 0.5; done
for i in $(seq 1 20); do curl -sf "http://localhost:$WEB_PORT" >/dev/null 2>&1 && break; sleep 0.5; done

ip="$(lan_ip)"
echo
if curl -sf "http://localhost:$API_PORT/health" >/dev/null; then green "api  http://localhost:$API_PORT  (docs at /docs)"; else red "api failed, see $LOG_DIR/api.log"; fi
if curl -sf "http://localhost:$WEB_PORT" >/dev/null;        then green "web  http://localhost:$WEB_PORT"; else red "web failed, see $LOG_DIR/web.log"; fi
echo
echo "On an iPad on this wifi:  http://$ip:$WEB_PORT"
dim "Logs: $LOG_DIR/web.log  $LOG_DIR/api.log     Stop: ./install.sh --stop"
