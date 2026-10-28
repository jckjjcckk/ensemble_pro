#!/usr/bin/env bash
# Build the web app with the hosted values and sync it into the iOS project.
#   ./scripts/build-ios.sh            build + npx cap sync ios
#   ./scripts/build-ios.sh --assets   also regenerate the icon and splash catalog from web/assets/
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

API_URL="${VITE_API_URL_HOSTED:-https://api.folio.jckjjcckk.com}"
[ -f .env ] || { echo "web/.env missing (hosted VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY)"; exit 1; }
SUPA_URL="$(grep -E '^VITE_SUPABASE_URL=' .env | cut -d= -f2-)"
SUPA_KEY="$(grep -E '^VITE_SUPABASE_PUBLISHABLE_KEY=' .env | cut -d= -f2-)"
case "$SUPA_URL" in ""|http://127.0.0.1*|http://localhost*) echo "web/.env must hold the hosted Supabase project, not '$SUPA_URL'"; exit 1;; esac

echo "Building for $API_URL with Supabase at $SUPA_URL"
VITE_API_URL="$API_URL" VITE_SUPABASE_URL="$SUPA_URL" VITE_SUPABASE_PUBLISHABLE_KEY="$SUPA_KEY" npm run build

if [ "${1:-}" = "--assets" ]; then
  npx capacitor-assets generate --ios --iconBackgroundColor '#181a1c' --iconBackgroundColorDark '#181a1c' \
    --splashBackgroundColor '#e6e8eb' --splashBackgroundColorDark '#0d0e10'
  # @capacitor/assets leaves the template's placeholder splashes behind; only the Default@*~universal files are referenced.
  rm -f ios/App/App/Assets.xcassets/Splash.imageset/splash-2732x2732*.png
fi

npx cap sync ios
echo "Next: npx cap open ios"
