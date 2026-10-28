#!/usr/bin/env bash
# Build the web app with the hosted values and sync it into the iOS project.
#   npm run build:ios            build:hosted + npx cap sync ios
#   npm run build:ios -- --assets  also regenerate the icon and splash catalog from web/assets/
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
npm run build:hosted
if [ "${1:-}" = "--assets" ]; then
  npx capacitor-assets generate --ios --iconBackgroundColor '#181a1c' --iconBackgroundColorDark '#181a1c' \
    --splashBackgroundColor '#e6e8eb' --splashBackgroundColorDark '#0d0e10'
  # @capacitor/assets leaves the template's placeholder splashes behind; only the Default@*~universal files are referenced.
  rm -f ios/App/App/Assets.xcassets/Splash.imageset/splash-2732x2732*.png
fi
npx cap sync ios
echo "Next: npx cap open ios"
