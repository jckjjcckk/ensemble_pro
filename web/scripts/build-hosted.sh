#!/usr/bin/env bash
# Build web/dist for the hosted app and the iPad shell with the hosted values passed explicitly.
#   npm run build:hosted
# Where the values come from, in order:
#   1. VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY, VITE_API_URL already in the environment (Cloudflare Workers Builds
#      sets them as build variables; web/.env is gitignored and absent there).
#   2. Otherwise web/.env on this Mac (the hosted Supabase project; public values).
#   VITE_API_URL defaults to https://api.folio.jckjjcckk.com when neither sets it.
# web/.env.local (the local Docker stack for the dev server) is never read: the values go to Vite as real environment
# variables, which rank above every .env file. The build refuses a local Supabase URL.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

from_dotenv() { [ -f .env ] && grep -E "^$1=" .env | head -1 | cut -d= -f2- || true; }
SUPA_URL="${VITE_SUPABASE_URL:-$(from_dotenv VITE_SUPABASE_URL)}"
SUPA_KEY="${VITE_SUPABASE_PUBLISHABLE_KEY:-$(from_dotenv VITE_SUPABASE_PUBLISHABLE_KEY)}"
API_URL="${VITE_API_URL:-https://api.folio.jckjjcckk.com}"

[ -n "$SUPA_URL" ] && [ -n "$SUPA_KEY" ] || { echo "Need VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY: in the environment (build variables) or in web/.env"; exit 1; }
case "$SUPA_URL" in http://127.0.0.1*|http://localhost*) echo "VITE_SUPABASE_URL is the local stack ($SUPA_URL); the hosted build needs the hosted project"; exit 1;; esac
case "$API_URL" in http://localhost*|http://127.0.0.1*) echo "VITE_API_URL is local ($API_URL); the hosted build needs https://api.folio.jckjjcckk.com"; exit 1;; esac

echo "Building for $API_URL with Supabase at $SUPA_URL"
VITE_API_URL="$API_URL" VITE_SUPABASE_URL="$SUPA_URL" VITE_SUPABASE_PUBLISHABLE_KEY="$SUPA_KEY" npm run build
