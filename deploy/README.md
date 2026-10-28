# Hosting Folio

Two origins, both on CK's Cloudflare zone `jckjjcckk.com`:

| What | Where | How |
|---|---|---|
| Web app (`web/dist`) | `https://folio.jckjjcckk.com` | Cloudflare Pages project `folio` |
| API (`api/`) | `https://api.folio.jckjjcckk.com` | This Mac, behind the named tunnel `macbook_pro_m4` |

The API stays on the Mac on purpose: the Casio, the OMR tooling and the local fixtures live here.

## Web: Cloudflare Pages

`web/scripts/deploy-pages.sh` builds `web/` with the hosted values and uploads `dist` with wrangler
(direct upload; no GitHub integration, so nothing is deployed on push). The browser gets exactly three
values and nothing else: `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` (both read from `web/.env`,
which holds the hosted project) and `VITE_API_URL=https://api.folio.jckjjcckk.com`. `web/.env.local`
points the dev server at the local Docker stack and is ignored by the script because the values are passed
on the command line, which Vite ranks above every `.env` file.

One-time, by CK (needs the Cloudflare login):

1. `cd web && npx wrangler login` (opens the browser, approve once).
2. `npx wrangler pages project create folio --production-branch main`.
3. `./scripts/deploy-pages.sh` (every later deploy is just this).
4. Dashboard → Workers & Pages → `folio` → Custom domains → add `folio.jckjjcckk.com` (Cloudflare creates
   the CNAME in the zone itself; it is live within a minute).
5. Supabase dashboard → Authentication → URL Configuration: add `https://folio.jckjjcckk.com/**` to the
   redirect URLs (and set it as the site URL once the hosted site is the main one). Sign-in is by password,
   so this only matters for password resets and magic links, but the reviewer flow should not depend on it.

If CK prefers the dashboard's Git integration instead: root directory `web`, build command `npm run build`,
output `dist`, environment variables the three `VITE_*` above. Either way the SPA fallback is
`web/public/_redirects` (`/* /index.html 200`), copied into `dist` by Vite.

## API: the Mac behind the named tunnel

`./install.sh --serve` (run from `~/Documents/muse`, the main checkout) installs two launchd agents under
`~/Library/LaunchAgents` and starts them; they come back after a reboot or a crash:

- `com.jckjjcckk.folio.api`: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` in `api/`, no
  `--reload`, logs in `.logs/api.serve.log`.
- `com.jckjjcckk.folio.tunnel`: `cloudflared tunnel --config ~/.cloudflared/folio.yml run`, logs in
  `.logs/tunnel.serve.log`.

`./install.sh --unserve` stops and removes both. `./install.sh` (dev mode) keeps using port 8000 too, so
stop the service first when you want the reloading dev server (`--unserve`, or `launchctl bootout
gui/$(id -u)/com.jckjjcckk.folio.api`).

One-time, by CK (needs the Cloudflare login; `cloudflared` has no certificate on this Mac yet):

1. `cloudflared tunnel login` (browser; pick the `jckjjcckk.com` zone). Writes `~/.cloudflared/cert.pem`.
2. `cloudflared tunnel list` must show `macbook_pro_m4`. Its credentials JSON must be at
   `~/.cloudflared/<UUID>.json`; if it is not (the tunnel was created on another machine), recreate it:
   `cloudflared tunnel delete macbook_pro_m4 && cloudflared tunnel create macbook_pro_m4`.
3. `cloudflared tunnel route dns macbook_pro_m4 api.folio.jckjjcckk.com` (creates the CNAME).
4. `./install.sh --serve`. It writes `~/.cloudflared/folio.yml` from `deploy/cloudflared/config.yml` with the
   tunnel's UUID and credentials path, installs the agents and checks `https://api.folio.jckjjcckk.com/health`.

`api/.env` must list the web and app origins in `CORS_ORIGINS`:

```
CORS_ORIGINS=http://localhost:5173,https://folio.jckjjcckk.com,capacitor://localhost,ionic://localhost,http://localhost
```

(`capacitor://localhost` is the iOS app's origin; `http://localhost` is Android's; `ionic://localhost`
is the legacy scheme. Nothing but the API's CORS list changes for them.)

## Checks

```
curl -s https://api.folio.jckjjcckk.com/health      # {"status":"ok"}
curl -sI https://folio.jckjjcckk.com | head -1      # HTTP/2 200
```

Then sign in at `https://folio.jckjjcckk.com` on an iPad and open a book.
