#!/usr/bin/env bash
# OPTIONAL local path, not the plan: the Worker `folio-app` is built and deployed by Workers Builds from GitHub (deploy/README.md).
# This builds web/ with the hosted values and deploys dist/ from this Mac; needs `npx wrangler login` once.
#   npm run deploy:web
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
npm run build:hosted
npx wrangler deploy
