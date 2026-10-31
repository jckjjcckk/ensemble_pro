// E2E night: the shelf's Realtime channels (web/src/app/data.tsx useWorld), subscribed as a signed-in account, logging
// every row change that arrives. Run from web/ so supabase-js resolves:
//   cd web && node ../api/experiments/e2e_night/realtime_listen.mjs <token-file> <out.jsonl> <seconds>
// The token file holds {"access_token": ...} for the account; the URL and key come from web/.env. Nothing is printed
// but counts.
import { readFileSync, appendFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
const require = createRequire(process.cwd() + '/package.json')
const { createClient } = require('@supabase/supabase-js')

const [tokFile, out, secs] = process.argv.slice(2)
const env = Object.fromEntries(readFileSync('.env', 'utf8').split('\n').filter(l => l.includes('=') && !l.trim().startsWith('#'))
  .map(l => { const i = l.indexOf('='); return [l.slice(0, i).trim(), l.slice(i + 1).trim().replace(/^['"]|['"]$/g, '')] }))
const tok = JSON.parse(readFileSync(tokFile, 'utf8')).access_token
const sb = createClient(env.VITE_SUPABASE_URL, env.VITE_SUPABASE_PUBLISHABLE_KEY, {
  global: { headers: { Authorization: `Bearer ${tok}` } }, auth: { persistSession: false, autoRefreshToken: false },
})
sb.realtime.setAuth(tok)
writeFileSync(out, '')
const log = (o) => appendFileSync(out, JSON.stringify({ t: Date.now(), ...o }) + '\n')
const tag = Math.random().toString(36).slice(2, 10)
let n = 0
const listen = (name, tables) => tables
  .reduce((ch, table) => ch.on('postgres_changes', { event: '*', schema: 'public', table }, p => {
    n++
    const r = p.new && Object.keys(p.new).length ? p.new : p.old
    log({ table: p.table, type: p.eventType, id: r?.id, kind: r?.kind, status: r?.status, progress: r?.progress, score_id: r?.score_id ?? r?.payload?.score_id })
  }), sb.channel(`world-${name}:${tag}`))
  .subscribe((status, err) => log({ channel: name, status, err: err ? String(err) : undefined }))
listen('core', ['scores', 'jobs', 'interpretations', 'members', 'score_shares'])
listen('more', ['parts', 'sources', 'ensembles'])
setTimeout(() => { console.log(`events ${n}`); process.exit(0) }, Number(secs) * 1000)
