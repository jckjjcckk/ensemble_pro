#!/usr/bin/env bash
# Local dev bootstrap for this Mac.
#   ./install.sh          check requirements, install deps, restart web + api
#   ./install.sh --stop   just stop anything running on the dev ports
#   ./install.sh --check  only run the requirement checks
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
