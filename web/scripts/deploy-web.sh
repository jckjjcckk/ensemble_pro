#!/usr/bin/env bash
# Build web/ with the hosted values and deploy dist/ as the Cloudflare Worker `folio-app` (static assets, wrangler.jsonc).
#   npm run deploy:web      (this script)
# Needs `npx wrangler login` once (CK's Cloudflare account). The custom domain is added in the dashboard: deploy/README.md.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
npm run build:hosted
npx wrangler deploy
