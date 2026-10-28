#!/usr/bin/env bash
# Build web/ with the hosted values and upload dist/ to the Cloudflare Pages project `folio`.
#   ./scripts/deploy-pages.sh            production deploy (branch main)
#   ./scripts/deploy-pages.sh --preview  preview deploy on the current git branch
# Needs `npx wrangler login` once (CK's Cloudflare account) and the project created once:
#   npx wrangler pages project create folio --production-branch main
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PROJECT="${PAGES_PROJECT:-folio}"
API_URL="${VITE_API_URL_HOSTED:-https://api.folio.jckjjcckk.com}"

# web/.env holds the hosted Supabase project (public values only). .env.local (the local Docker stack) is
# not read here: the values are passed as real environment variables, which Vite ranks above every .env file.
[ -f .env ] || { echo "web/.env missing (hosted VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY)"; exit 1; }
SUPA_URL="$(grep -E '^VITE_SUPABASE_URL=' .env | cut -d= -f2-)"
SUPA_KEY="$(grep -E '^VITE_SUPABASE_PUBLISHABLE_KEY=' .env | cut -d= -f2-)"
[ -n "$SUPA_URL" ] && [ -n "$SUPA_KEY" ] || { echo "web/.env is missing VITE_SUPABASE_URL or VITE_SUPABASE_PUBLISHABLE_KEY"; exit 1; }
case "$SUPA_URL" in http://127.0.0.1*|http://localhost*) echo "web/.env points at the local stack ($SUPA_URL); the hosted build needs the hosted project"; exit 1;; esac

echo "Building for $API_URL with Supabase at $SUPA_URL"
VITE_API_URL="$API_URL" VITE_SUPABASE_URL="$SUPA_URL" VITE_SUPABASE_PUBLISHABLE_KEY="$SUPA_KEY" npm run build

if [ "${1:-}" = "--preview" ]; then
  branch="$(git rev-parse --abbrev-ref HEAD)"
  npx wrangler pages deploy dist --project-name "$PROJECT" --branch "$branch"
else
  npx wrangler pages deploy dist --project-name "$PROJECT" --branch main
fi
