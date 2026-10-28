#!/usr/bin/env bash
# Build web/dist for the hosted app and the iPad shell, with the hosted values passed explicitly:
# VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY from web/.env (public values, hosted project) and
# VITE_API_URL=https://api.folio.jckjjcckk.com. web/.env.local (the local Docker stack for the dev server) is not read,
# because real environment variables rank above every .env file in Vite.
#   npm run build:hosted
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
API_URL="${VITE_API_URL_HOSTED:-https://api.folio.jckjjcckk.com}"
[ -f .env ] || { echo "web/.env missing (hosted VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY)"; exit 1; }
SUPA_URL="$(grep -E '^VITE_SUPABASE_URL=' .env | cut -d= -f2-)"
SUPA_KEY="$(grep -E '^VITE_SUPABASE_PUBLISHABLE_KEY=' .env | cut -d= -f2-)"
case "$SUPA_URL" in ""|http://127.0.0.1*|http://localhost*) echo "web/.env must hold the hosted Supabase project, not '$SUPA_URL'"; exit 1;; esac
[ -n "$SUPA_KEY" ] || { echo "web/.env is missing VITE_SUPABASE_PUBLISHABLE_KEY"; exit 1; }
echo "Building for $API_URL with Supabase at $SUPA_URL"
VITE_API_URL="$API_URL" VITE_SUPABASE_URL="$SUPA_URL" VITE_SUPABASE_PUBLISHABLE_KEY="$SUPA_KEY" npm run build
