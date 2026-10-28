# 015 iOS wrapper around the React PWA

Status: built, not yet on TestFlight (2026-10-28) | Meta model: none.

## Purpose

An App Store presence for the same React app: a reviewer and a TestFlight tester get Folio on an iPad the
way musicians will. The web app at `https://folio-app.jckjjcckk.com` stays the primary surface.

## Decisions

- Capacitor shell under `web/ios/`, app id `com.jckjjcckk.folio`, name Folio, iPad only, iOS 16+, all four
  orientations, bundled assets (`webDir: dist`, never `server.url`) so App Store guideline 4.2 and offline hold.
  Swift Package Manager, not CocoaPods. `npm run build:ios` (the hosted build, then `cap sync`). How to build,
  sync, sign and submit: `docs/ios.md`.
- One bridge file, `web/src/lib/native.ts`: camera into the scan screen, the share sheet for Export, the
  status bar's text following the theme, a light haptic on a new page. Every function is a no-op or the web
  path in Safari, and the plugins load with `import()` only inside the shell.
- The shell talks to the hosted API (`https://folio-api.jckjjcckk.com`, `deploy/README.md`) and the hosted
  Supabase project; its origin `capacitor://localhost` is in the API's `CORS_ORIGINS`.
- Still only possible in a wrapper, still not built: a true in-app IMSLP browser with download interception
  (002), share-to-Folio from Files, background audio for practice mode, MIDI over USB without the Mac.

## Next steps

- CK: Xcode signing team, a run on the iPad, Archive → TestFlight (`docs/ios.md`).
- The bar-numbered PDF export through the share sheet (today it opens in the webview).
- A privacy page and a support page (the marketing site at folio.jckjjcckk.com) before the store listing.
