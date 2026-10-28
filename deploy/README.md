# Hosting Folio

Three names on CK's Cloudflare zone `jckjjcckk.com`:

| What | Where | How |
|---|---|---|
| Marketing site | `https://folio.jckjjcckk.com` | A separate project |
| Web app (`web/dist`) | `https://folio-app.jckjjcckk.com` | Cloudflare Worker `folio-app` with static assets (`web/wrangler.jsonc`) |
| API (`api/`) | `https://folio-api.jckjjcckk.com` | This Mac, behind the named tunnel `macbook_pro_m4` |

The API stays on the Mac on purpose: the Casio, the OMR tooling and the local fixtures live here. CK does
every Cloudflare login and dashboard step; nothing here logs in or deploys on its own.

## The production build (reproducible)

```bash
cd web && npm run build:hosted
```

`scripts/build-hosted.sh` builds `web/dist` with the hosted values passed as real environment variables.
`VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` and `VITE_API_URL` are taken from the environment when
set (Workers Builds' build variables), otherwise from `web/.env` (the hosted project; public values), with
`VITE_API_URL` defaulting to `https://folio-api.jckjjcckk.com`. `web/.env.local` points the dev server at
the local Docker stack and is never read here, because Vite ranks environment variables above every `.env`
file. The script refuses a local Supabase or API URL. The same build goes into the iPad shell
(`npm run build:ios`).

## Web app: a Worker with static assets (dashboard only)

`web/wrangler.jsonc` names the Worker `folio-app`, serves `./dist` and answers unknown paths with
`index.html` (React Router). CK builds and deploys from the dashboard (Workers Builds); nothing on this Mac
logs in to Cloudflare.

1. Workers & Pages → Create → **Import a repository** → `jckjjcckk/ensemble_pro`, branch `main`: project name
   `folio-app`, root directory `web`, build command `npm run build:hosted`, deploy command
   `npx wrangler deploy`. Build variables, values taken from `web/.env` on the Mac: `VITE_SUPABASE_URL`,
   `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_URL=https://folio-api.jckjjcckk.com`. The build script
   prefers these over `web/.env` (which is gitignored and absent in the build), and never reads
   `web/.env.local`.
2. `folio-app` → Settings → Domains & Routes → Add → Custom domain → `folio-app.jckjjcckk.com`. Cloudflare
   writes the DNS record and the certificate itself. Every later push to `main` redeploys.

Optional, local path (not the plan): `cd web && npm run deploy:web` builds with the hosted values and runs
`npx wrangler deploy` from this Mac; it needs `npx wrangler login` once.

## API: the Mac behind the named tunnel

`deploy/cloudflared/config.yml` routes `folio-api.jckjjcckk.com` to `http://localhost:8000` and everything
else to 404. It is written, not run. Two ways to run the tunnel, CK's choice:

**A. Dashboard-managed (token).** Zero Trust → Networks → Tunnels → `macbook_pro_m4` → Configure:
- Public hostname: subdomain `api`, domain `folio.jckjjcckk.com`, service `HTTP` `localhost:8000`.
- Install connector → copy the token from the `cloudflared service install <token>` line, and save only
  the token to `~/.cloudflared/folio-tunnel.token` (`chmod 600`). Nothing else from that line is needed.
- `./install.sh --serve` then runs `cloudflared tunnel run --token ...` under launchd.

**B. Locally managed (config file).** `cloudflared tunnel login` (browser, pick the zone), then
`cloudflared tunnel list` must show `macbook_pro_m4` with its credentials at `~/.cloudflared/<UUID>.json`
(if the tunnel was created elsewhere: `cloudflared tunnel delete macbook_pro_m4 && cloudflared tunnel create
macbook_pro_m4`), then `cloudflared tunnel route dns macbook_pro_m4 folio-api.jckjjcckk.com`.
`./install.sh --serve` copies the config to `~/.cloudflared/folio.yml` with the UUID and credentials path.

Either way, `./install.sh --serve` (from `~/Documents/muse`, the main checkout) installs two launchd agents
under `~/Library/LaunchAgents` and starts them; they come back after a crash or a reboot:

- `com.jckjjcckk.folio.api`: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` in `api/`, no
  `--reload`, logs in `.logs/api.serve.log`.
- `com.jckjjcckk.folio.tunnel`: `cloudflared tunnel run` (token or config), logs in `.logs/tunnel.serve.log`.

`./install.sh --unserve` stops and removes both. The dev mode `./install.sh` uses port 8000 too, so
`--unserve` first when you want the reloading dev server.

`api/.env` lists the app and the iPad shell as origins (done; `api/.env.example` matches):

```
CORS_ORIGINS=http://localhost:5173,https://folio-app.jckjjcckk.com,capacitor://localhost,ionic://localhost,http://localhost
```

`capacitor://localhost` is the iOS app's origin; `http://localhost` is Android's; `ionic://localhost` the
legacy scheme. Supabase needs no redirect URL: sign-in is by password with sign-up off.

## Checks

```
curl -s https://folio-api.jckjjcckk.com/health       # {"status":"ok"}
curl -sI https://folio-app.jckjjcckk.com | head -1    # HTTP/2 200
```

Then sign in at `https://folio-app.jckjjcckk.com` on an iPad and open a book.
