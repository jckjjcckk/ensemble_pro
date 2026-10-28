/** Live rows and presence (012, build-queue item 5).
 *
 *  `useLiveRows` is the one Realtime subscription the reader's layers share: row changes for one score, applied by the
 *  caller as they arrive, and a resync (one refetch) every time the channel joins again after a drop. Realtime is the
 *  notification, the database is the truth.
 *
 *  `usePresence` is who is reading the score and on which bar: one `presence` row per (score, member), written on
 *  every page turn (at most once every 2 s) and once a minute while the score is open, deleted on leaving; rows older
 *  than 10 minutes are ignored. */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { supabase } from '../lib/supabase'

// ---------------------------------------------------------------- ids

/** A v4 uuid. `crypto.randomUUID` needs a secure context (an iPad on the LAN over http is not one). */
export function newId(): string {
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = Array.from(b, x => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

// ---------------------------------------------------------------- one channel per layer, resync on rejoin

type Row = Record<string, unknown>
export interface Change {
  eventType: 'INSERT' | 'UPDATE' | 'DELETE'
  table: string
  /** The row after the change (INSERT, UPDATE); `{}` for a DELETE. */
  new: Row
  /** For a DELETE, the primary key only (RLS hides the rest). */
  old: Row
  commit_timestamp?: string
  /** Set when Realtime could not send the row (too large): refetch instead. */
  errors?: unknown
}

export type LiveStatus = 'off' | 'joining' | 'live' | 'lost'

/**
 * Row changes of `table` where `score_id` is `scoreId`, for as long as `scoreId` is set. A filtered subscription
 * receives no DELETE (Realtime cannot filter them), so deletes come from an unfiltered binding carrying only the
 * primary key; the caller drops what it does not hold. `onResync` runs on every join: the first one closes the gap
 * between the initial fetch and the subscription, later ones (after `CHANNEL_ERROR`, `TIMED_OUT` or `CLOSED`: a wifi
 * drop, a sleeping iPad) refetch once and reconcile.
 */
export function useLiveRows(scoreId: string | null, tables: string[], onChange: (c: Change) => void, onResync: () => void): LiveStatus {
  const changeRef = useRef(onChange)
  const resyncRef = useRef(onResync)
  useLayoutEffect(() => { changeRef.current = onChange; resyncRef.current = onResync })
  const [status, setStatus] = useState<LiveStatus>('off')
  const key = tables.join(',')

  useEffect(() => {
    if (!scoreId) { setStatus('off'); return }
    setStatus('joining')
    let ch = supabase.channel(`live:${key}:${scoreId}:${newId().slice(0, 8)}`)
    for (const table of key.split(',')) {
      ch = ch
        .on('postgres_changes', { event: '*', schema: 'public', table, filter: `score_id=eq.${scoreId}` }, p => changeRef.current({ ...(p as unknown as Change), table }))
        .on('postgres_changes', { event: 'DELETE', schema: 'public', table }, p => changeRef.current({ ...(p as unknown as Change), table }))
    }
    let alive = true
    ch.subscribe(s => {
      if (!alive) return
      if (s === 'SUBSCRIBED') { setStatus('live'); resyncRef.current() }
      else setStatus('lost') // CHANNEL_ERROR, TIMED_OUT, CLOSED: the client rejoins on its own; the resync follows the join
    })
    return () => { alive = false; void supabase.removeChannel(ch) }
  }, [scoreId, key])

  return status
}

/** Ids that arrived from someone else in the last moment: their layers draw a quiet entrance (200 ms fade). */
export function useArrivals(ms = 900) {
  const [ids, setIds] = useState<ReadonlySet<string>>(() => new Set())
  const timers = useRef(new Map<string, number>())
  useEffect(() => () => { timers.current.forEach(t => window.clearTimeout(t)) }, [])
  const mark = useCallback((xs: string[]) => {
    if (!xs.length) return
    setIds(s => new Set([...s, ...xs]))
    for (const id of xs) {
      window.clearTimeout(timers.current.get(id))
      timers.current.set(id, window.setTimeout(() => {
        timers.current.delete(id)
        setIds(s => { const n = new Set(s); n.delete(id); return n })
      }, ms))
    }
  }, [ms])
  return { ids, mark }
}

// ---------------------------------------------------------------- mark layers

/** Whether `annotations.ensemble_id` / `scribbles.ensemble_id` are missing (a stack without the share migration, such
 *  as the hosted project until it is pushed); learnt from the first refusal, after which reads and writes go without. */
export const layerColumn = { missing: false }
/** PostgREST's "no such column" (schema cache) or Postgres's undefined column, about `ensemble_id`. */
export const isMissingLayer = (e: { code?: string; message?: string } | null | undefined) =>
  !!e && (e.code === 'PGRST204' || e.code === '42703' || e.code === '42P10') && /ensemble_id|ON CONFLICT/i.test(e.message ?? '')

// ---------------------------------------------------------------- presence

export interface Presence {
  memberId: string
  userId: string
  bar: number
  part: string | null
  updatedAt: number
}

/** A place is written at most this often; a page turn inside the window is written when it closes. */
const WRITE_EVERY_MS = 2000
/** The row is refreshed this often while the score stays open, so it never looks stale to the others. */
const KEEPALIVE_MS = 60_000
/** Older rows are someone who left without saying so (a closed lid, a dead battery): ignored. */
export const STALE_MS = 10 * 60_000

const toPresence = (r: Row): Presence => ({
  memberId: String(r.member_id), userId: String(r.user_id), bar: Number(r.bar) || 1,
  part: (r.part as string | null) ?? null, updatedAt: Date.parse(String(r.updated_at)) || Date.now(),
})

/**
 * Everyone's place on one score, and the reader's own written as they turn pages. `me` is null when nothing syncs
 * (a personal book, the mock world): then there is no presence at all.
 */
export function usePresence(scoreId: string, me: { memberId: string; userId: string } | null, place: { bar: number; part: string | null } | null) {
  const on = !!me
  const [rows, setRows] = useState<Map<string, Presence>>(() => new Map())
  const [now, setNow] = useState(() => Date.now())

  const refetch = useCallback(async () => {
    const since = new Date(Date.now() - STALE_MS).toISOString()
    const { data, error } = await supabase.from('presence').select('member_id,user_id,bar,part,updated_at').eq('score_id', scoreId).gt('updated_at', since)
    if (error) { console.warn('presence', error.message); return }
    setRows(new Map((data ?? []).map(r => { const p = toPresence(r); return [p.memberId, p] })))
  }, [scoreId])

  useEffect(() => { setRows(new Map()); if (on) void refetch() }, [on, refetch])

  const onChange = useCallback((c: Change) => {
    if (c.eventType === 'DELETE') {
      if (c.old.score_id !== scoreId) return
      setRows(m => { if (!m.has(String(c.old.member_id))) return m; const n = new Map(m); n.delete(String(c.old.member_id)); return n })
      return
    }
    const p = toPresence(c.new)
    setRows(m => new Map(m).set(p.memberId, p))
  }, [scoreId])
  const status = useLiveRows(on ? scoreId : null, ['presence'], onChange, () => void refetch())

  // Rows go stale while the score is open: look again every half minute.
  useEffect(() => {
    if (!on) return
    const t = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(t)
  }, [on])

  // ---------------------------------------------------------------- the reader's own place

  const meRef = useRef(me)
  const placeRef = useRef(place)
  useLayoutEffect(() => { meRef.current = me; placeRef.current = place })
  const lastWrite = useRef(0)
  const trailing = useRef<number | undefined>(undefined)
  const written = useRef<string | null>(null)

  const write = useCallback(async (force = false) => {
    window.clearTimeout(trailing.current)
    trailing.current = undefined
    const m = meRef.current, p = placeRef.current
    if (!m || !p) return
    const sig = `${p.bar}|${p.part ?? ''}`
    if (!force && sig === written.current) return
    lastWrite.current = Date.now()
    written.current = sig
    // Optimistic: the reader's own face moves at once.
    setRows(r => new Map(r).set(m.memberId, { memberId: m.memberId, userId: m.userId, bar: p.bar, part: p.part, updatedAt: Date.now() }))
    const { error } = await supabase.from('presence').upsert(
      { score_id: scoreId, member_id: m.memberId, user_id: m.userId, bar: p.bar, part: p.part },
      { onConflict: 'score_id,member_id' },
    )
    if (error) { written.current = null; console.warn('presence write', error.message) }
  }, [scoreId])

  // A page turn (the first bar on screen changes) or a part switch writes, at most once every 2 s.
  const bar = place?.bar, part = place?.part
  useEffect(() => {
    if (!on || bar == null) return
    const wait = lastWrite.current + WRITE_EVERY_MS - Date.now()
    if (wait <= 0) void write()
    else if (trailing.current === undefined) trailing.current = window.setTimeout(() => void write(), wait)
  }, [on, bar, part, write])

  // Keep the row fresh; after a drop, say where we are again.
  useEffect(() => {
    if (!on) return
    const t = window.setInterval(() => void write(true), KEEPALIVE_MS)
    return () => window.clearInterval(t)
  }, [on, write])
  useEffect(() => { if (status === 'live' && written.current !== null) void write(true) }, [status, write])

  // Leaving the score takes the reader's face away for everyone.
  useEffect(() => {
    if (!on) return
    const leave = () => {
      const m = meRef.current
      window.clearTimeout(trailing.current)
      written.current = null
      if (m) void supabase.from('presence').delete().eq('score_id', scoreId).eq('member_id', m.memberId)
    }
    window.addEventListener('pagehide', leave)
    return () => { window.removeEventListener('pagehide', leave); leave() }
  }, [on, scoreId])

  const fresh = useMemo(() => [...rows.values()].filter(p => now - p.updatedAt < STALE_MS || p.memberId === me?.memberId), [rows, now, me?.memberId])
  return { rows: fresh, status }
}
