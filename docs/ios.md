# Folio on the iPad: the Capacitor shell

The App Store app is the same React build that runs at `https://folio-app.jckjjcckk.com`, bundled inside a
Capacitor shell (`web/ios/`). No `server.url`: the assets ship in the binary, the API is reached at
`https://folio-api-stable.jckjjcckk.com`, Supabase at the hosted project. Feature file: `docs/features/015-ios-wrapper.md`.

| Thing | Value |
|---|---|
| Bundle id | `com.jckjjcckk.folio` |
| Name | Folio |
| Devices | iPad only (`TARGETED_DEVICE_FAMILY = 2`), iOS 16+, all four orientations, multitasking on |
| Web assets | `web/dist` → `web/ios/App/App/public` (gitignored; `npx cap sync ios` fills it) |
| Config | `web/capacitor.config.ts` (`ios/App/App/capacitor.config.json` is generated from it) |
| Plugins | camera, filesystem, haptics, keyboard, share, splash-screen, status-bar (Swift Package Manager) |
| Icon and splash sources | `web/assets/` (1024 icon, 2732 splash light and dark), rendered by `@capacitor/assets` |

## Build

```bash
cd web
npm run build:ios             # build:hosted (hosted VITE_* values) + npx cap sync ios
npx cap open ios              # Xcode; pick an iPad simulator or the connected iPad, press Run
```

`npm run build:hosted` (`scripts/build-hosted.sh`) passes the hosted values as environment variables, so
`web/.env.local` (the local Docker stack for the dev server) never leaks into the binary. It needs `web/.env`
with the hosted `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`; `VITE_API_URL` is fixed to
`https://folio-api-stable.jckjjcckk.com`. The same command makes the build that is deployed to
`folio-app.jckjjcckk.com` (`deploy/README.md`).

Without Xcode's UI, a simulator build proves the project compiles:

```bash
cd web/ios/App && xcodebuild -project App.xcodeproj -scheme App -configuration Debug -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPad Pro 13-inch (M4)' CODE_SIGNING_ALLOWED=NO \
  -scmProvider system build
```

`-scmProvider system` makes Swift package resolution use the system git, so the one remote package
(`capacitor-swift-pm`, public) is fetched anonymously and Xcode does not ask the keychain for a saved
github.com credential. If a keychain prompt appears anyway, Deny it: the build does not need it. If
resolution then fails, run `xcodebuild -resolvePackageDependencies -scmProvider system` once in
`web/ios/App`, or clear a stale `credential.helper` from git config. Never type a keychain password for a
build.

## Sync after a web change

```bash
cd web && npm run build:ios      # or: npm run build:hosted && npx cap sync ios
```

`cap sync` copies `dist/` into the project and resolves the plugin packages. It never touches the Swift
sources, `Info.plist` or the asset catalog, so edits there are safe. Rerun the asset catalog (`npm run build:ios -- --assets`) only when the icon or splash changes.

## How the web app behaves inside the shell

- `web/src/lib/native.ts` is the whole bridge. In Safari every function is a no-op or the web path, so the
  hosted site is unchanged; the plugins are loaded with `import()` only when `Capacitor.isNativePlatform()`.
- Scan (`Scan.tsx`): "Photograph a page" opens the camera; in Safari the same button is "Add pages" and opens
  the image chooser (the iPad offers the camera there too). A page waiting for a retake takes the next photo.
- Export (`data.tsx` → `deliverFile`): the share sheet (Save to Files, AirDrop, Mail) in the app; a download in
  Safari.
- Status bar: translucent over the header, and its text follows the theme (`App.tsx` → `syncStatusBar`).
- Keyboard: the webview shrinks (`resize: native`); the web app's `--kb` lift measures 0 and does nothing.
- Safe areas: `viewport-fit=cover` is kept and `contentInset: never` stops the webview adding its own inset.
- Origin: `capacitor://localhost`. The API's `CORS_ORIGINS` lists it (`deploy/README.md`).

## The hosted app: a Worker with static assets (dashboard only)

The reviewer and the testers use the same hosted stack as the web app. CK deploys from the Cloudflare
dashboard; nothing on this Mac logs in to Cloudflare. `deploy/README.md` is the runbook.

1. Dashboard → Workers & Pages → Create → **Import a repository** → `jckjjcckk/folio-pad`, branch
   `main`. Build settings:
   - Project name `folio-app-web`
   - Root directory `web`
   - Build command `npm run build:hosted`
   - Deploy command `npx wrangler deploy`
   - Build variables (values from `web/.env` on the Mac; never written into a doc or the repo):
     `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, and `VITE_API_URL` set to
     `https://folio-api-stable.jckjjcckk.com`.
   `build:hosted` reads those variables first and falls back to `web/.env` only when they are absent, so
   the dashboard's values win and `web/.env.local` is never involved. `web/wrangler.jsonc` tells wrangler
   to serve `dist` as static assets with unknown paths → `index.html`.
2. `folio-app-web` → Settings → Domains & Routes → Add → Custom domain → `folio-app.jckjjcckk.com`. Cloudflare
   writes the DNS record and the certificate; live within a minute. Later pushes to `main` redeploy.
3. The API: Zero Trust → Networks → Tunnels → `macbook_pro_m4` → public hostname `folio-api-dev.jckjjcckk.com` →
   `http://localhost:8000`; save the connector token to `~/.cloudflared/folio-tunnel.token`; then
   `./install.sh --serve` from the main checkout.

Optional, local only: `cd web && npm run deploy:web` builds and runs `npx wrangler deploy` from this Mac
(needs `npx wrangler login` once). Not part of the plan; the dashboard build is the model.

## What CK does in Xcode (once)

1. `cd web && npx cap open ios`.
2. Target **App** → **Signing & Capabilities**: tick *Automatically manage signing*, choose the team (the
   Apple developer account). Bundle identifier stays `com.jckjjcckk.folio`; Xcode registers it.
3. **General**: check *Supported Destinations* shows iPad only, *Deployment* iOS 16.0, orientations all four.
   Version 1.0, build 1 (bump the build for every TestFlight upload: `CURRENT_PROJECT_VERSION`).
4. Plug in the iPad, choose it as the run destination, press Run once (trusts the developer certificate on
   the device: Settings → General → VPN & Device Management).
5. TestFlight: **Product → Archive** (destination *Any iOS Device (arm64)*), then in the Organizer
   **Distribute App → App Store Connect → Upload**. In App Store Connect → TestFlight add CK as an internal
   tester; the build appears in the TestFlight app on the iPad within an hour.

## App Store checklist

App Store Connect → My Apps → New App: platform iOS, name Folio, primary language English, bundle id
`com.jckjjcckk.folio`, SKU `folio-ipad`.

- **Demo account in the review notes.** Reviewers cannot sign up (signups are off). CK makes a test
  account for App Review and types its email and password into the review notes in App Store Connect only
  (never into the repo or these docs); say which ensemble it belongs to, that a book is already in the
  library, and name the three things to try: open a book, make a mark, export MusicXML.
- **Privacy policy URL** (required): a page on `folio.jckjjcckk.com/privacy` saying what is stored (account
  email, scores and markings in Supabase, usage events for the model budget), that pages sent to the
  librarian go to Meta's model API, and that nothing is sold. **Support URL**: the GitHub repo or
  `folio.jckjjcckk.com/support`.
- **App privacy** (the questionnaire): data collected: email (account), user content (scores, photos of
  pages, markings), usage data (model spend). Not used for tracking.
- **Screenshots**: iPad 13-inch (2064×2752 or 2752×2064) and iPad 12.9-inch (2048×2732 or 2732×2048); up to
  ten each, both orientations allowed. Take them in the simulator (`xcrun simctl io booted screenshot`) with
  the Beethoven quartet open: library, the score with marks, the part view, scan order, practice mode.
- **Age rating**: none of the questionnaire's categories apply → 4+.
- **Category**: Music; secondary Productivity. **Price**: free.
- **Export compliance**: `ITSAppUsesNonExemptEncryption` is already `false` in `Info.plist` (HTTPS only).
- **Camera and photos**: the usage strings in `Info.plist` say why (page photographs); keep them honest.
- **Guideline 4.2 (minimum functionality), the defence**, written into the review notes: the app is not a
  website in a frame. Its assets are bundled and it opens offline to the library and the last-opened
  books; it uses the camera to photograph pages (the native camera plugin, not a file picker); it writes
  files through the share sheet and reads them from Files; it draws with the Pencil over the score with
  pressure; it has haptics; iPad-only layout for the music stand (landscape and portrait, multitasking). Say
  the backend does the heavy work (model calls, OMR) because that is where the ensemble's shared truth lives.
- **Guideline 5.1.1**: sign-in is required because every score belongs to an ensemble; say so in the notes
  and that accounts are created by the ensemble's admin (the reviewer's demo account covers this).
- **Guideline 2.1**: the reviewer's account must work on the first try: before submitting, run
  `curl https://folio-api-stable.jckjjcckk.com/health` and sign in on the hosted site with that account.

## Known limits of the shell today

- Export of the bar-numbered PDF is a link that opens in the webview (`Pages.tsx`); a share-sheet path like
  MusicXML export is a small follow-up.
- No deep links, no share-to-Folio from Files, no background audio; feature 015 lists them.
- The service worker does not run under `capacitor://` (WKWebView), which is fine: the assets are local.
