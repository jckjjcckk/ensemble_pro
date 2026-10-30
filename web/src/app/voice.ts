/** Voice notes (013): what the admin says becomes proposed marks they confirm. A take is one hold of the voice button:
 *  the WAV goes to the API (`sendVoice`), the `transcribe_voice` job is watched on Realtime with a 2 s poll beside it,
 *  and its proposals arrive as `annotations` rows with `status = 'proposed'` through the marks hook (`useBarMarks`).
 *  What it heard but could not place on a bar comes back in the job's result (`unplaced`) and waits here, in memory,
 *  for the admin to tap a bar. Nothing goes live without the admin's Accept.
 *  What was said stays the sender's: the transcript and each mark's quote live only on the sender's own job row
 *  (`result.transcript`, `result.quotes[mark_id]`), never on an annotation, so a player who later sees an accepted
 *  mark reads only its stand text. */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { AnnotationKind } from '../mock'
import { supabase } from '../lib/supabase'
import { ApiError, apiFailure, sendVoice } from '../lib/api'
import type { Recording } from '../lib/recorder'
import { newId } from './presence'
import { sameWho, whoOf, type Layer, type MarkInsert, type MarkPatch, type MarkRec, type Who } from './ink'
import { barRange } from './store'

/** Heard, but not on a bar the score has (a rehearsal letter it lacks, "the last page"). */
export interface Unplaced { text: string; kind: string; position: string; audience: string[]; quote: string }
/** A finished job's `result`. */
export interface VoiceResult {
  utterance_id: string; transcript: string; proposed: number; unplaced: Unplaced[]; refused: string[]
  /** Each proposed mark's quote, by `mark_id`. */
  quotes: Record<string, string>
  seconds?: number; cost_usd?: number
}

type Phase = 'sending' | 'queued' | 'running' | 'done' | 'failed'
/** The parts and players a note can be for. */
export interface Roster { parts: string[]; members: { id: string; name: string }[] }
export interface TakeProblem { kind: 'offline' | 'server' | 'job'; message: string }

export interface Take {
  key: string
  /** `score|layer` it was spoken on. */
  scope: string
  /** When the take was sent (ms). */
  at: number
  phase: Phase
  jobId?: string
  utteranceId?: string
  result?: VoiceResult
  problem?: TakeProblem
  /** An attempt failed and the worker will try the job again. */
  retrying?: boolean
  /** The recording, kept for a retry until the job is done. */
  wav: Blob | null
  /** Unplaced items still waiting, each with the bar the admin tapped for it. */
  unplaced: { id: string; item: Unplaced; bar: number | null }[]
  /** The admin put the group away (nothing to mark, a failure they gave up on). */
  closed: boolean
  /** Cards of this take the admin accepted or dismissed. */
  settled: number
}

/** One proposed mark: one or several rows sharing `payload.mark_id` (a mark for two parts is two rows), or one
 *  unplaced item. */
export interface Card {
  key: string
  kind: AnnotationKind
  body: string
  barFrom: number | null
  barTo: number | null
  who: Who[]
  quote: string | null
  rows: MarkRec[]
  unplaced?: { takeKey: string; id: string; item: Unplaced }
}

export interface Group {
  key: string
  at: number
  transcript: string | null
  take?: Take
  cards: Card[]
  refused: string[]
}

/** Edits the admin made to a card before accepting it. */
export interface Draft { body: string; barFrom: number; barTo: number; who: Who[] }

const KINDS: AnnotationKind[] = ['cut', 'dynamic', 'marking', 'text', 'breath', 'bowing']
const asKind = (k: unknown): AnnotationKind => (KINDS.includes(k as AnnotationKind) ? (k as AnnotationKind) : 'text')
const JOB_POLL_MS = 2000
/** A job is watched until it is done or failed. The worker retries a failed attempt twice (10 s, then 20 s later), so
 *  an answer comes within two minutes when a worker is up; past this, the take stops waiting, and Send again first
 *  asks the job once more, so a job that does finish is never doubled by a second one. */
const JOB_WAIT_MS = 5 * 60_000

/** The job's own words when the handler gave a reason the admin can act on (`ScoreFailure`); technical text stays in
 *  `jobs.error`. */
function jobWords(err: unknown): { message: string; final: boolean } {
  const e = typeof err === 'string' ? err : ''
  if (e.startsWith('ScoreFailure: ')) { const m = e.slice(14).trim(); return { message: /[.!?]$/.test(m) ? m : `${m}.`, final: true } }
  return { message: 'Muse couldn’t place that note.', final: false }
}

/** A cut's stand text that only restates its bars ("Cut 42–48") follows the bars when they are edited. */
const BARE_CUT = /^cut(?:\s+(?:bars?\s+)?\d+(?:\s*[–-]\s*\d+)?)?$/i
export const cutText = (kind: AnnotationKind, body: string, from: number, to: number) =>
  kind === 'cut' && BARE_CUT.test(body.trim()) ? `Cut ${barRange(from, to)}` : body

function parseResult(r: unknown): VoiceResult {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const x = (r ?? {}) as Record<string, any>
  return {
    utterance_id: String(x.utterance_id ?? ''), transcript: typeof x.transcript === 'string' ? x.transcript : '',
    proposed: Number(x.proposed) || 0,
    unplaced: Array.isArray(x.unplaced) ? x.unplaced.filter(Boolean).map((u: Record<string, unknown>) => ({
      text: String(u.text ?? ''), kind: String(u.kind ?? 'text'), position: String(u.position ?? ''),
      audience: Array.isArray(u.audience) ? u.audience.map(String) : [], quote: String(u.quote ?? ''),
    })) : [],
    refused: Array.isArray(x.refused) ? x.refused.map(String) : [],
    quotes: x.quotes && typeof x.quotes === 'object' ? Object.fromEntries(Object.entries(x.quotes).map(([k, v]) => [k, String(v)])) : {},
    seconds: typeof x.seconds === 'number' ? x.seconds : undefined, cost_usd: typeof x.cost_usd === 'number' ? x.cost_usd : undefined,
  }
}

/**
 * An unplaced item's audience words as rows' audiences. Taken as the eval wrote them (`ensemble`, `part:<name>`,
 * `member:<id or name>`) or bare: a part's name, a member's name. Unknown words are dropped; none left is everyone.
 */
export function parseAudience(words: string[], parts: string[], members: { id: string; name: string }[]): Who[] {
  const out: Who[] = []
  const low = (s: string) => s.trim().toLowerCase()
  for (const raw of words) {
    const [head, ...rest] = raw.split(':')
    const tail = rest.join(':').trim()
    const word = low(rest.length ? tail : raw)
    let who: Who | null = null
    if (['ensemble', 'everyone', 'all', 'tutti'].includes(low(raw))) who = { audience: 'ensemble' }
    else if ((rest.length && low(head) === 'part') || (!rest.length && parts.some(p => low(p) === word))) {
      const p = parts.find(x => low(x) === word)
      if (p) who = { audience: 'part', part: p }
    } else {
      const m = members.find(x => x.id === (rest.length ? tail : raw) || low(x.name) === word || low(x.name.split(/\s+/)[0]) === word)
      if (m) who = { audience: 'member', member: m.id }
    }
    if (who && !out.some(w => sameWho(w, who!))) out.push(who)
  }
  return out.some(w => w.audience === 'ensemble') || !out.length ? [{ audience: 'ensemble' }] : out
}

/** The rows of a mark as one card; its quote from the sender's job result. */
function cardOf(rows: MarkRec[], quotes: Map<string, string>): Card {
  const r = rows[0]
  const who: Who[] = []
  for (const x of rows) { const w = whoOf(x); if (!who.some(y => sameWho(y, w))) who.push(w) }
  return {
    key: String(r.payload?.mark_id ?? r.id), kind: r.kind, body: r.body ?? '', barFrom: r.barFrom, barTo: r.barTo, who,
    quote: quotes.get(String(r.payload?.mark_id ?? '')) ?? null, rows,
  }
}

/** The writes that accept a card with the admin's edits: every row of the mark goes live; an audience added becomes a
 *  new row (or reuses a row whose audience was taken away), one taken away and not reused is deleted. */
export function acceptWrites(card: Card, d: Draft, utteranceId: string | null): { update: MarkPatch[]; insert: MarkInsert[]; remove: string[] } {
  const want = d.who.length ? d.who : [{ audience: 'ensemble' } as Who]
  const body = cutText(card.kind, d.body.trim() || card.body, d.barFrom, d.barTo)
  if (card.unplaced) {
    const markId = newId()
    return {
      update: [], remove: [],
      insert: want.map(who => ({
        kind: card.kind, body, barFrom: d.barFrom, barTo: d.barTo, who, status: 'live',
        payload: { source: 'voice', utterance_id: utteranceId, mark_id: markId, position: card.unplaced!.item.position },
      })),
    }
  }
  const used = new Set<string>()
  const update: MarkPatch[] = []
  const later: Who[] = []
  const fields = (r: MarkRec): Omit<MarkPatch, 'id'> => ({
    status: 'live',
    ...(body !== (r.body ?? '') ? { body } : {}),
    ...(d.barFrom !== r.barFrom ? { barFrom: d.barFrom } : {}),
    ...(d.barTo !== r.barTo ? { barTo: d.barTo } : {}),
  })
  for (const w of want) {
    const r = card.rows.find(x => !used.has(x.id) && sameWho(whoOf(x), w))
    if (r) { used.add(r.id); update.push({ id: r.id, ...fields(r) }) } else later.push(w)
  }
  const spare = card.rows.filter(x => !used.has(x.id))
  const insert: MarkInsert[] = []
  for (const w of later) {
    const r = spare.shift()
    if (r) update.push({ id: r.id, ...fields(r), who: w })
    else insert.push({ kind: card.kind, body, barFrom: d.barFrom, barTo: d.barTo, who: w, status: 'live', payload: { ...(card.rows[0]?.payload ?? {}) } })
  }
  return { update, insert, remove: spare.map(x => x.id) }
}

/**
 * The voice takes of this visit and the proposals waiting on this score's layer, as tray groups (newest first).
 * `proposed` comes from the marks hook; proposals left from an earlier visit form groups of their own.
 */
export function useVoice({ scoreId, layer, token, proposed, roster, reload, onArrive }: {
  scoreId: string; layer: Layer; token: string | null; proposed: MarkRec[]; roster: Roster
  /** Read the score's marks again: a finished job's proposals are fetched even if their Realtime inserts were missed. */
  reload?: () => void
  onArrive?: (t: Take) => void
}) {
  const [all, setTakes] = useState<Take[]>([])
  // A take belongs to the score and layer it was spoken on; another one starts an empty tray.
  const scope = `${scoreId}|${layer ?? ''}`
  const takes = useMemo(() => all.filter(t => t.scope === scope), [all, scope])
  const tokenRef = useRef(token)
  const arriveRef = useRef(onArrive)
  const reloadRef = useRef(reload)
  useLayoutEffect(() => { tokenRef.current = token; arriveRef.current = onArrive; reloadRef.current = reload })
  const patch = useCallback((key: string, fn: (t: Take) => Take) => setTakes(ts => ts.map(t => (t.key === key ? fn(t) : t))), [])

  const post = useCallback(async (key: string, wav: Blob) => {
    const tk = tokenRef.current
    if (!tk) { patch(key, t => ({ ...t, phase: 'failed', problem: { kind: 'server', message: 'Sign in again to send voice notes.' } })); return }
    try {
      const r = await sendVoice(scoreId, wav, { ensembleId: layer ?? null }, tk)
      patch(key, t => ({ ...t, phase: t.phase === 'sending' ? 'queued' : t.phase, jobId: r.job_id, utteranceId: r.utterance_id }))
    } catch (e) {
      const offline = (e instanceof ApiError && e.status === 0) || !navigator.onLine
      patch(key, t => ({
        ...t, phase: 'failed',
        problem: offline ? { kind: 'offline', message: 'You are offline. The note is kept; send it again when you are back.' } : { kind: 'server', message: apiFailure(e, 'Voice notes') },
      }))
    }
  }, [scoreId, layer, patch])

  const send = useCallback((rec: Recording) => {
    const key = newId()
    setTakes(ts => [...ts, { key, scope, at: Date.now(), phase: 'sending', wav: rec.wav, unplaced: [], closed: false, settled: 0 }])
    void post(key, rec.wav)
  }, [post, scope])

  const retry = useCallback(async (key: string) => {
    const t = takes.find(x => x.key === key)
    if (!t) return
    // A job that stopped being watched may still be working or done: watch it again rather than send a second one.
    if (t.jobId) {
      const { data } = await supabase.from('jobs').select('status').eq('id', t.jobId).maybeSingle()
      if (data && data.status !== 'failed') { patch(key, x => ({ ...x, phase: 'queued', problem: undefined, closed: false })); return }
    }
    if (!t.wav) return
    patch(key, x => ({ ...x, at: Date.now(), phase: 'sending', problem: undefined, retrying: false, jobId: undefined, utteranceId: undefined, result: undefined, closed: false }))
    void post(key, t.wav)
  }, [takes, patch, post])

  // ---------------------------------------------------------------- watching the jobs

  const watchers = useRef(new Map<string, () => void>())
  const watch = useCallback((key: string, jobId: string) => {
    let over = false
    const t0 = Date.now()
    const onRow = (row: { status?: string; result?: unknown; error?: string | null } | null) => {
      if (over || !row?.status) return
      if (row.status === 'done') {
        stop()
        const result = parseResult(row.result)
        patch(key, t => (t.phase === 'done' ? t : { ...t, phase: 'done', retrying: false, result, wav: null, unplaced: result.unplaced.map(item => ({ id: newId(), item, bar: null })) }))
        if (result.proposed > 0) reloadRef.current?.()
      } else if (row.status === 'failed') {
        stop()
        const w = jobWords(row.error)
        // A reason about the recording itself will not change on a second send: no Send again.
        patch(key, t => ({ ...t, phase: 'failed', retrying: false, problem: { kind: 'job', message: w.message }, ...(w.final ? { wav: null } : {}) }))
      } else if (row.status === 'running' || row.status === 'queued') {
        const phase = row.status
        const retrying = !!row.error
        patch(key, t => (t.phase === 'done' || t.phase === 'failed' || (t.phase === phase && !!t.retrying === retrying) ? t : { ...t, phase, retrying }))
      }
    }
    const ch = supabase.channel(`job:${jobId}:${newId().slice(0, 8)}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'jobs', filter: `id=eq.${jobId}` }, p => onRow(p.new as never))
      .subscribe()
    const poll = window.setInterval(() => {
      if (Date.now() - t0 > JOB_WAIT_MS) {
        stop()
        patch(key, t => ({ ...t, phase: 'failed', problem: { kind: 'job', message: 'Muse hasn’t answered yet.' } }))
        return
      }
      void supabase.from('jobs').select('id,status,result,error').eq('id', jobId).maybeSingle().then(({ data }) => onRow(data))
    }, JOB_POLL_MS)
    function stop() {
      if (over) return
      over = true
      window.clearInterval(poll)
      void supabase.removeChannel(ch)
      watchers.current.delete(jobId)
    }
    return stop
  }, [patch])

  useEffect(() => {
    for (const t of takes) {
      if (t.jobId && (t.phase === 'queued' || t.phase === 'running') && !watchers.current.has(t.jobId)) watchers.current.set(t.jobId, watch(t.key, t.jobId))
    }
  }, [takes, watch])
  useEffect(() => {
    const w = watchers.current
    return () => { [...w.values()].forEach(stop => stop()); w.clear() }
  }, [scoreId, layer])

  // A finished take with something to check opens the tray once.
  const announced = useRef(new Set<string>())
  useEffect(() => {
    for (const t of takes) {
      if (t.phase !== 'done' || announced.current.has(t.key)) continue
      announced.current.add(t.key)
      if ((t.result?.proposed ?? 0) > 0 || t.unplaced.length) arriveRef.current?.(t)
    }
  }, [takes])

  // ---------------------------------------------------------------- the tray

  // Proposals spoken on an earlier visit: their transcript and quotes are on the sender's own job rows (RLS: only
  // the job's creator reads it), fetched once per utterance.
  const [earlier, setEarlier] = useState<Map<string, VoiceResult>>(() => new Map())
  const asked = useRef(new Set<string>())
  useEffect(() => {
    const live = new Set(takes.map(t => t.utteranceId).filter(Boolean))
    const ids = [...new Set(proposed.map(r => r.payload?.utterance_id as string | undefined))]
      .filter((u): u is string => !!u && !live.has(u) && !asked.current.has(u))
    if (!ids.length) return
    ids.forEach(u => asked.current.add(u))
    void supabase.from('jobs').select('result').eq('kind', 'transcribe_voice').in('payload->>utterance_id', ids).then(({ data }) => {
      if (!data?.length) return
      setEarlier(m => { const n = new Map(m); for (const j of data) { const r = parseResult(j.result); if (r.utterance_id) n.set(r.utterance_id, r) } return n })
    })
  }, [proposed, takes])

  const groups = useMemo<Group[]>(() => {
    const quotes = new Map<string, string>()
    for (const r of [...earlier.values(), ...takes.map(t => t.result).filter((x): x is VoiceResult => !!x)]) for (const [k, v] of Object.entries(r.quotes)) quotes.set(k, v)
    const byMark = new Map<string, MarkRec[]>()
    for (const r of proposed) {
      const k = String(r.payload?.mark_id ?? r.id)
      byMark.set(k, [...(byMark.get(k) ?? []), r])
    }
    const cards = [...byMark.values()].map(rows => cardOf(rows, quotes)).sort((a, b) => (a.barFrom ?? 0) - (b.barFrom ?? 0))
    const utt = (c: Card) => (c.rows[0]?.payload?.utterance_id as string | undefined) ?? null
    const out: Group[] = []
    const claimed = new Set<string>()
    for (const t of takes) {
      const mine = t.utteranceId ? cards.filter(c => utt(c) === t.utteranceId) : []
      mine.forEach(c => claimed.add(c.key))
      const loose: Card[] = t.unplaced.map(u => ({
        key: `${t.key}:${u.id}`, kind: asKind(u.item.kind), body: u.item.text, barFrom: u.bar, barTo: u.bar,
        who: parseAudience(u.item.audience, roster.parts, roster.members), quote: u.item.quote, rows: [],
        unplaced: { takeKey: t.key, id: u.id, item: u.item },
      }))
      const all = [...mine, ...loose]
      if (t.closed && !all.length) continue
      // A finished take whose cards were all accepted or dismissed leaves the tray. One whose proposals have not
      // arrived yet stays, still placing.
      if (t.phase === 'done' && !all.length && t.settled > 0) continue
      out.push({ key: t.key, at: t.at, transcript: t.result?.transcript ?? null, take: t, cards: all, refused: t.result?.refused ?? [] })
    }
    // Proposals from an earlier visit (or another device), grouped by what was said.
    const rest = new Map<string, Card[]>()
    for (const c of cards) if (!claimed.has(c.key)) { const k = utt(c) ?? c.key; rest.set(k, [...(rest.get(k) ?? []), c]) }
    for (const [k, cs] of rest) {
      const at = Math.min(...cs.flatMap(c => c.rows.map(r => Date.parse(r.createdAt) || Date.now())))
      out.push({ key: `u:${k}`, at, transcript: earlier.get(k)?.transcript ?? null, cards: cs, refused: [] })
    }
    return out.sort((a, b) => b.at - a.at)
  }, [takes, proposed, earlier, roster])

  const close = useCallback((key: string) => patch(key, t => ({ ...t, closed: true, wav: null })), [patch])
  const settle = useCallback((key: string) => patch(key, t => ({ ...t, settled: t.settled + 1 })), [patch])
  const placeUnplaced = useCallback((takeKey: string, id: string, bar: number) =>
    patch(takeKey, t => ({ ...t, unplaced: t.unplaced.map(u => (u.id === id ? { ...u, bar } : u)) })), [patch])
  const dropUnplaced = useCallback((takeKey: string, id: string) =>
    patch(takeKey, t => ({ ...t, unplaced: t.unplaced.filter(u => u.id !== id) })), [patch])

  const latest = takes.length ? takes[takes.length - 1] : null
  const waiting = groups.reduce((n, g) => n + g.cards.length, 0)
  return { takes, latest, groups, waiting, send, retry, close, settle, placeUnplaced, dropUnplaced }
}
