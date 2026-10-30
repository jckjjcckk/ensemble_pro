/** Quick marks and scribbles (012): what a tap on a bar writes, and the ink drawn over the page.
 *
 *  Marks are `annotations` rows on stable `measures.id` (the same record the collaboration item pushes live);
 *  scribbles are `scribbles` rows, one per (score, page as drawn, part, author). A score that is not in Supabase
 *  (the mock world, the practice screen) keeps both in memory for the session, behind the same functions. */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { supabase } from '../lib/supabase'
import { isMissingLayer, layerColumn, newId, useArrivals, useLiveRows, type Change } from './presence'
import type { Annotation, AnnotationKind } from '../mock'
import type { Geo, Rect } from './geometry'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
/** Scores from Supabase have uuids; the mock world's do not. */
export const isSyncedScore = (id: string) => UUID.test(id)

/** Who is marking, in the ensemble that owns the score. */
export interface Me {
  /** The signed-in account; null when nothing syncs (marks live in memory). */
  userId: string | null
  /** The member row in the owning ensemble, or the personal library's self id. */
  memberId: string
  /** The score belongs to an ensemble (not a personal library). */
  ensemble: boolean
  /** Admin of the ensemble or owner of the library: may address everyone and remove anyone's mark. */
  admin: boolean
}

export type BarMark = Annotation & {
  mine: boolean
  removable: boolean
  /** Who it is for: everyone, one part, or the author alone (a personal note). */
  audience: 'ensemble' | 'part' | 'member'
  /** Just arrived from another reader: drawn with a quiet entrance. */
  arriving?: boolean
}

/** Who a new mark is for. `self` is a private note (the owner alone in a personal library). */
export type Audience = 'ensemble' | 'self' | { part: string }

export interface NewMark {
  kind: AnnotationKind
  barFrom: number
  barTo?: number
  text?: string
  audience: Audience
  /** The part on screen when the mark was made (parts.name), kept in the payload. */
  part?: string | null
}

// ---------------------------------------------------------------- an in-memory store for scores that do not sync

type Listener = () => void
function memory<T>() {
  const data = new Map<string, T[]>()
  const listeners = new Set<Listener>()
  return {
    get: (key: string) => data.get(key) ?? EMPTY as T[],
    set: (key: string, next: T[]) => { data.set(key, next); listeners.forEach(l => l()) },
    subscribe: (l: Listener) => { listeners.add(l); return () => { listeners.delete(l) } },
  }
}
const EMPTY: never[] = []
const localMarks = memory<BarMark>()
const LOCAL_AUTHOR = 'me'

let seq = 0
const tempId = (p: string) => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`

// ---------------------------------------------------------------- marks
// ---------------------------------------------------------------- marks

/**
 * The mark layer a reader is in (`ensemble_id`, migration 20261028200000_score_shares, `useStore().markGroupFor`):
 * `null` on a group's own book (null means the book's group) and for the owner's private marks in their own library;
 * a group id for that group's layer on a shared personal book; `undefined` where nothing is layered (practice).
 * Marks and scribbles are read, written and applied from Realtime in that layer only: an owner of a shared book can
 * read every layer, so an unfiltered read would mix them.
 */
export type Layer = string | null | undefined

/** An annotation as the reader holds it: the stored record, its bars resolved to numbers. `proposed` rows are voice
 *  proposals (013) waiting for the admin: never drawn as marks, only as ghosts and tray cards. */
export interface MarkRec {
  id: string; scoreId: string; kind: AnnotationKind; body: string | null
  audience: 'ensemble' | 'part' | 'member'; audiencePart: string | null; audienceMember: string | null
  authorId: string; createdAt: string; barFrom: number; barTo: number
  status: 'live' | 'proposed'
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: Record<string, any> | null
}
type Rec = MarkRec

/** Who one stored row is for. */
export type Who = { audience: 'ensemble' } | { audience: 'part'; part: string } | { audience: 'member'; member: string }
export const whoOf = (r: Pick<Rec, 'audience' | 'audiencePart' | 'audienceMember'>): Who =>
  r.audience === 'part' && r.audiencePart ? { audience: 'part', part: r.audiencePart }
    : r.audience === 'member' && r.audienceMember ? { audience: 'member', member: r.audienceMember }
      : { audience: 'ensemble' }
export const sameWho = (a: Who, b: Who) =>
  a.audience === b.audience && (a.audience !== 'part' || a.part === (b as typeof a).part) && (a.audience !== 'member' || a.member === (b as typeof a).member)

/** A row to write in one `commit`: a change to a held row (only the fields given), or a new one. */
export interface MarkPatch { id: string; body?: string | null; barFrom?: number; barTo?: number; who?: Who; status?: 'live' | 'proposed' }
export interface MarkInsert {
  kind: AnnotationKind; body: string | null; barFrom: number; barTo: number; who: Who; status: 'live' | 'proposed'
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: Record<string, any>
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>

const COLS = 'id,score_id,kind,body,payload,audience,audience_part,audience_member_id,author_id,status,created_at,measure_from,measure_to'
const BARS = 'mf:measures!annotations_measure_from_fkey(number),mt:measures!annotations_measure_to_fkey(number)'
const markSelect = () => `${COLS}${layerColumn.missing ? '' : ',ensemble_id'},${BARS}`

const posInt = (v: unknown) => (typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : null)

/** A row from a query (bars embedded) or from Realtime (bars from the measure cache or the payload); null when its
 *  bars cannot be told yet. Learns measure numbers into `bars` as it goes. */
function toRec(r: Row, bars: Map<string, number>): Rec | null {
  if (r.mf?.number) bars.set(r.measure_from, r.mf.number)
  if (r.mt?.number) bars.set(r.measure_to, r.mt.number)
  const from = posInt(r.mf?.number) ?? bars.get(r.measure_from) ?? posInt(r.payload?.bar)
  if (from == null) return null
  const to = posInt(r.mt?.number) ?? bars.get(r.measure_to) ?? posInt(r.payload?.bar_to) ?? from
  return {
    id: r.id, scoreId: r.score_id, kind: r.kind, body: r.body ?? null, audience: r.audience,
    audiencePart: r.audience_part ?? null, audienceMember: r.audience_member_id ?? null, authorId: r.author_id,
    createdAt: r.created_at ?? new Date().toISOString(), barFrom: from, barTo: to,
    status: r.status === 'proposed' ? 'proposed' : 'live', payload: r.payload ?? null,
  }
}

const inLayer = (r: Row, layer: Layer) => layer === undefined || layerColumn.missing || (r.ensemble_id ?? null) === layer

/**
 * The marks on one score: loaded with the score, then kept live from Realtime row changes (an insert, update or
 * delete by anyone is applied to this list as it arrives, without a refetch), written optimistically with ids made
 * here, so a mark and its own Realtime echo are one row. On every (re)join of the channel the score's rows are
 * fetched once and reconciled: nothing lost during a wifi drop, nothing doubled. `partIdByName` maps a part audience
 * back to the app's part ids; `ensembleId` lets authors be named by their member rows.
 */
export function useBarMarks(scoreId: string, me: Me | null, opts: { partIdByName?: Record<string, string>; ensembleId?: string; layer?: Layer } = {}) {
  const synced = !!me?.userId && isSyncedScore(scoreId)
  const local = useSyncExternalStore(localMarks.subscribe, () => localMarks.get(scoreId))
  const [recs, setRecs] = useState<Rec[]>([])
  const [authors, setAuthors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const arrivals = useArrivals()
  const markArrival = arrivals.mark
  const layer = opts.layer
  const partIds = opts.partIdByName
  const meRef = useRef(me)
  const layerRef = useRef(layer)
  useLayoutEffect(() => { meRef.current = me; layerRef.current = layer })
  const recsRef = useRef(recs)
  useLayoutEffect(() => { recsRef.current = recs })
  /** measures.id → bar number, learnt from every row fetched. */
  const bars = useRef(new Map<string, number>())
  /** Written here and not yet confirmed; removed here and not yet confirmed. A refetch keeps the first, drops the second. */
  const pending = useRef(new Set<string>())
  const removing = useRef(new Set<string>())
  /** Changes that arrive while a refetch is in flight wait for it, then apply on top of its snapshot. */
  const syncing = useRef(0)
  const held = useRef<Change[]>([])

  const upsert = useCallback((rec: Rec) => {
    if (removing.current.has(rec.id)) return
    setRecs(xs => {
      const i = xs.findIndex(x => x.id === rec.id)
      return i < 0 ? [...xs, rec] : xs.map((x, j) => (j === i ? rec : x))
    })
  }, [])

  const fetchOne = useCallback(async (id: string) => {
    const { data } = await supabase.from('annotations').select(markSelect()).eq('id', id).maybeSingle()
    const rec = data ? toRec(data as Row, bars.current) : null
    if (rec) upsert(rec)
    else setRecs(xs => xs.filter(x => x.id !== id)) // no longer visible to this reader
  }, [upsert])

  const apply = useCallback((c: Change) => {
    if (syncing.current) { held.current.push(c); return }
    if (c.eventType === 'DELETE') {
      const id = String(c.old.id)
      setRecs(xs => (xs.some(x => x.id === id) ? xs.filter(x => x.id !== id) : xs))
      return
    }
    const r = c.new
    if (r.score_id !== scoreId || !inLayer(r, layerRef.current)) return
    const rec = c.errors ? null : toRec(r, bars.current)
    if (!rec) { void fetchOne(String(r.id)); return }
    if (pending.current.has(rec.id)) return // our own write's echo: the insert's answer replaces the optimistic row
    if (c.eventType === 'INSERT' && rec.authorId !== meRef.current?.userId) markArrival([rec.id])
    upsert(rec)
  }, [scoreId, fetchOne, upsert, markArrival])

  const refetch = useCallback(async () => {
    syncing.current++
    const run = () => {
      let q = supabase.from('annotations').select(markSelect()).eq('score_id', scoreId)
      if (layer !== undefined && !layerColumn.missing) q = layer === null ? q.is('ensemble_id', null) : q.eq('ensemble_id', layer)
      return q.order('created_at')
    }
    let res = await run()
    if (res.error && isMissingLayer(res.error)) { layerColumn.missing = true; res = await run() }
    syncing.current--
    if (res.error) setError(res.error.message)
    else {
      setError(null)
      const fresh = ((res.data ?? []) as unknown as Row[]).map(r => toRec(r, bars.current)).filter((x): x is Rec => !!x)
      const ids = new Set(fresh.map(x => x.id))
      setRecs(prev => [
        ...fresh.filter(x => !removing.current.has(x.id)),
        ...prev.filter(x => pending.current.has(x.id) && !ids.has(x.id)),
      ])
    }
    if (!syncing.current) { const h = held.current; held.current = []; h.forEach(apply) }
  }, [scoreId, layer, apply])

  // Who wrote what: account ids to the member ids the screens name.
  const ensembleId = opts.ensembleId
  useEffect(() => {
    if (!synced || !ensembleId || !isSyncedScore(ensembleId)) return
    let live = true
    supabase.from('members').select('id,user_id').eq('ensemble_id', ensembleId).then(({ data }) => {
      if (!live || !data) return
      setAuthors(Object.fromEntries(data.filter(m => m.user_id).map(m => [m.user_id as string, m.id as string])))
    })
    return () => { live = false }
  }, [synced, ensembleId])

  useEffect(() => {
    setRecs([])
    if (synced) void refetch()
  }, [synced, refetch])
  const status = useLiveRows(synced ? scoreId : null, ['annotations'], apply, () => void refetch())

  // Proposed rows (013) are the admin's to confirm: they never draw as marks (pins, margin, cuts, the ruler).
  const rows = useMemo<BarMark[]>(() => recs.filter(r => r.status !== 'proposed').map(r => {
    const mine = r.authorId === me?.userId
    return {
      id: r.id, scoreId: r.scoreId, kind: r.kind,
      partId: r.audience === 'part' && r.audiencePart ? partIds?.[r.audiencePart] ?? r.audiencePart : null,
      authorId: mine ? me!.memberId : authors[r.authorId] ?? r.authorId,
      barFrom: r.barFrom, barTo: r.barTo, text: r.body ?? undefined, createdAt: r.createdAt,
      mine, removable: mine || !!me?.admin, audience: r.audience,
      ...(arrivals.ids.has(r.id) ? { arriving: true } : {}),
    }
  }), [recs, me, authors, partIds, arrivals.ids])

  const marks = synced ? rows : local
  /** The reader's own voice proposals on this layer, waiting in the tray. */
  const proposed = useMemo(() => recs.filter(r => r.status === 'proposed' && r.authorId === me?.userId), [recs, me?.userId])

  const add = useCallback(async (n: NewMark): Promise<void> => {
    const m = meRef.current
    const barTo = n.barTo ?? n.barFrom
    const aud = n.audience
    const id = newId()
    const audience = aud === 'self' ? (m?.ensemble === false ? 'ensemble' : 'member') : aud === 'ensemble' ? 'ensemble' : 'part'
    if (!synced) {
      const temp: BarMark = {
        id, scoreId, kind: n.kind, partId: typeof aud === 'object' ? partIds?.[aud.part] ?? null : null,
        authorId: m?.memberId ?? LOCAL_AUTHOR, barFrom: n.barFrom, barTo, text: n.text, createdAt: new Date().toISOString(),
        mine: true, removable: true, audience,
      }
      localMarks.set(scoreId, [...localMarks.get(scoreId), temp])
      return
    }
    pending.current.add(id)
    upsert({
      id, scoreId, kind: n.kind, body: n.text ?? null, audience, audiencePart: typeof aud === 'object' ? aud.part : null,
      audienceMember: null, authorId: m!.userId!, createdAt: new Date().toISOString(), barFrom: n.barFrom, barTo,
      status: 'live', payload: null,
    })
    try {
      const nums = [...new Set([n.barFrom, barTo])]
      const { data: ids, error: e1 } = await supabase.rpc('measure_ids', { p_score: scoreId, p_numbers: nums })
      if (e1) throw e1
      const idOf = new Map((ids as { number: number; id: string }[]).map(r => [r.number, r.id]))
      for (const [num, mid] of idOf) bars.current.set(mid, num)
      const who = aud === 'self'
        ? (m!.ensemble ? { audience: 'member', audience_member_id: m!.memberId } : { audience: 'ensemble' })
        : aud === 'ensemble' ? { audience: 'ensemble' } : { audience: 'part', audience_part: aud.part }
      const lay = layerRef.current
      const row: Row = {
        id, score_id: scoreId, kind: n.kind, measure_from: idOf.get(n.barFrom), measure_to: idOf.get(barTo),
        author_id: m!.userId, body: n.text ?? null, payload: { bar: n.barFrom, bar_to: barTo, part: n.part ?? null, via: 'quick' },
        ...who,
        // Every mark names its layer; a stack without the column takes the write without it (retried below).
        ...(lay !== undefined && !layerColumn.missing ? { ensemble_id: lay } : {}),
      }
      let res = await supabase.from('annotations').insert(row).select(markSelect()).single()
      if (res.error && isMissingLayer(res.error)) {
        layerColumn.missing = true
        delete row.ensemble_id
        res = await supabase.from('annotations').insert(row).select(markSelect()).single()
      }
      if (res.error) throw res.error
      pending.current.delete(id)
      const rec = toRec(res.data as unknown as Row, bars.current)
      if (rec) upsert(rec)
      setError(null)
    } catch (e) {
      pending.current.delete(id)
      setRecs(xs => xs.filter(x => x.id !== id))
      setError(e instanceof Error ? e.message : String((e as { message?: string })?.message ?? e))
    }
  }, [scoreId, synced, partIds, upsert])

  const remove = useCallback(async (id: string): Promise<void> => {
    if (!synced) { localMarks.set(scoreId, localMarks.get(scoreId).filter(x => x.id !== id)); return }
    const was = recsRef.current.find(x => x.id === id)
    removing.current.add(id)
    setRecs(xs => xs.filter(x => x.id !== id))
    const { error: e } = await supabase.from('annotations').delete().eq('id', id)
    removing.current.delete(id)
    if (e) { setError(e.message); if (was) upsert(was) }
  }, [scoreId, synced, upsert])

  /** Highlight is a toggle of the reader's own highlight on that bar; other people's stay. */
  const toggleHighlight = useCallback((bar: number, part: string | null) => {
    const own = marks.find(x => x.kind === 'highlight' && x.mine && x.barFrom === bar)
    if (own) return remove(own.id)
    return add({ kind: 'highlight', barFrom: bar, audience: 'ensemble', part })
  }, [marks, add, remove])

  /**
   * Several row writes as one step (013, accepting or dismissing a voice proposal): removes, changes to held rows and
   * new rows, applied here at once and then written. Bars are given as numbers and resolved to `measures.id`. On a
   * refusal the score's rows are fetched again, so the screen shows what the database holds. Resolves to whether
   * every write went through.
   */
  const commit = useCallback(async (w: { remove?: string[]; update?: MarkPatch[]; insert?: MarkInsert[] }): Promise<boolean> => {
    if (!synced) return false
    const m = meRef.current
    const del = w.remove ?? [], upd = w.update ?? []
    const ins = (w.insert ?? []).map(x => ({ ...x, id: newId() }))
    const now = new Date().toISOString()
    const patched = (r: Rec, p: MarkPatch): Rec => {
      const who = p.who ?? whoOf(r)
      return {
        ...r, body: p.body !== undefined ? p.body : r.body, barFrom: p.barFrom ?? r.barFrom, barTo: p.barTo ?? r.barTo, status: p.status ?? r.status,
        audience: who.audience, audiencePart: who.audience === 'part' ? who.part : null, audienceMember: who.audience === 'member' ? who.member : null,
      }
    }
    del.forEach(id => removing.current.add(id))
    upd.forEach(p => pending.current.add(p.id))
    ins.forEach(x => pending.current.add(x.id))
    setRecs(xs => [
      ...xs.filter(x => !del.includes(x.id)).map(x => { const p = upd.find(u => u.id === x.id); return p ? patched(x, p) : x }),
      ...ins.map(x => patched({
        id: x.id, scoreId, kind: x.kind, body: x.body, audience: 'ensemble', audiencePart: null, audienceMember: null,
        authorId: m!.userId!, createdAt: now, barFrom: x.barFrom, barTo: x.barTo, status: x.status, payload: x.payload,
      }, { id: x.id, who: x.who })),
    ])
    const whoCols = (who: Who) => ({
      audience: who.audience, audience_part: who.audience === 'part' ? who.part : null, audience_member_id: who.audience === 'member' ? who.member : null,
    })
    try {
      const nums = [...new Set([...upd.flatMap(p => [p.barFrom, p.barTo]), ...ins.flatMap(x => [x.barFrom, x.barTo])].filter((n): n is number => n != null))]
      const idOf = new Map<number, string>()
      if (nums.length) {
        const { data, error: e1 } = await supabase.rpc('measure_ids', { p_score: scoreId, p_numbers: nums })
        if (e1) throw e1
        for (const r of data as { number: number; id: string }[]) { idOf.set(r.number, r.id); bars.current.set(r.id, r.number) }
        const missing = nums.find(n => !idOf.has(n))
        if (missing != null) throw new Error(`This score has no bar ${missing}.`)
      }
      if (del.length) {
        const { error: e } = await supabase.from('annotations').delete().in('id', del)
        if (e) throw e
      }
      for (const p of upd) {
        const row: Row = {
          ...(p.status ? { status: p.status } : {}), ...(p.body !== undefined ? { body: p.body } : {}),
          ...(p.barFrom != null ? { measure_from: idOf.get(p.barFrom) } : {}), ...(p.barTo != null ? { measure_to: idOf.get(p.barTo) } : {}),
          ...(p.who ? whoCols(p.who) : {}),
        }
        const { data, error: e } = await supabase.from('annotations').update(row).eq('id', p.id).select(markSelect()).single()
        if (e) throw e
        const rec = toRec(data as unknown as Row, bars.current)
        if (rec) upsert(rec)
      }
      if (ins.length) {
        const lay = layerRef.current
        const rows: Row[] = ins.map(x => ({
          id: x.id, score_id: scoreId, kind: x.kind, measure_from: idOf.get(x.barFrom), measure_to: idOf.get(x.barTo),
          author_id: m!.userId, body: x.body, status: x.status, payload: { ...x.payload, bar: x.barFrom, bar_to: x.barTo }, ...whoCols(x.who),
          ...(lay !== undefined && !layerColumn.missing ? { ensemble_id: lay } : {}),
        }))
        const { data, error: e } = await supabase.from('annotations').insert(rows).select(markSelect())
        if (e) throw e
        for (const r of (data ?? []) as unknown as Row[]) { const rec = toRec(r, bars.current); if (rec) upsert(rec) }
      }
      setError(null)
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String((e as { message?: string })?.message ?? e))
      // After a refusal the optimistic rows are wrong: read the truth again, once the guards above are let go.
      window.setTimeout(() => void refetch(), 0)
      return false
    } finally {
      del.forEach(id => removing.current.delete(id))
      upd.forEach(p => pending.current.delete(p.id))
      ins.forEach(x => pending.current.delete(x.id))
    }
  }, [scoreId, synced, upsert, refetch])

  return { marks, proposed, add, remove, commit, toggleHighlight, synced, error, live: status }
}

// ---------------------------------------------------------------- scribbles

export type PenColor = 'ink' | 'red' | 'blue'
export const PEN_COLORS: PenColor[] = ['ink', 'red', 'blue']

/**
 * One stroke, as stored. Coordinates are fractions of the page it was drawn on (x of its width, y of its height),
 * rounded to 4 places; `aspect` is that page's height over its width. `bar` and `box` (the bar's box, same
 * fractions) anchor the stroke to the music: a digital score re-engraves on rotation and resize, so a stroke is
 * placed by its bar, and its shape is scaled with the staff, never stretched.
 */
export interface Stroke {
  id: string
  color: PenColor
  /** Nominal width as a fraction of the page width. */
  width: number
  aspect: number
  bar: number | null
  box: [number, number, number, number] | null
  /** [x, y, pressure 0..1] */
  points: [number, number, number][]
}

export interface ScribbleRow {
  /** The stored row's id, once it has one (a Realtime delete names only this). */
  id?: string
  page: number
  /** parts.name on screen, null for the full score. */
  part: string | null
  userId: string
  strokes: Stroke[]
}

const LOCAL_USER = 'local'
const localInk = memory<ScribbleRow>()
const SAVE_EVERY_MS = 3000
const INK_KEY = 'score_id,page,part,user_id'

const toInk = (r: Row): ScribbleRow => ({
  id: r.id, page: r.page as number, part: (r.part as string | null) ?? null, userId: r.user_id as string,
  strokes: (r.strokes as Stroke[]) ?? [],
})

/**
 * Everyone's strokes on one score and part, plus the reader's own edits. Loaded with the score (rows are small;
 * strokes are placed by bar, so every page on screen draws from the same set), then kept live: another reader's
 * saved page arrives as a row change and replaces that page, its new strokes fading in. A page the reader is still
 * editing keeps its local strokes until saved. On every (re)join the rows are fetched once and reconciled. The
 * reader's pages save every few seconds while they draw, and at once on `flush` (Done) and on leaving.
 */
export function useScribbles(scoreId: string, part: string | null, me: Me | null, layer?: Layer) {
  const synced = !!me?.userId && isSyncedScore(scoreId)
  const uid = synced ? me!.userId! : LOCAL_USER
  const localKey = `${scoreId}|${part ?? ''}`
  const local = useSyncExternalStore(localInk.subscribe, () => localInk.get(localKey))
  const [remote, setRemote] = useState<ScribbleRow[]>([])
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const arrivals = useArrivals()
  const markArrival = arrivals.mark
  /** Pages of the reader's own ink edited since the last save. */
  const dirty = useRef(new Set<number>())
  const timer = useRef<number | undefined>(undefined)
  const remoteRef = useRef(remote)
  useLayoutEffect(() => { remoteRef.current = remote })
  const layerRef = useRef(layer)
  useLayoutEffect(() => { layerRef.current = layer })

  const refetch = useCallback(async () => {
    const run = () => {
      let q = supabase.from('scribbles').select(`id,page,part,user_id,strokes${layerColumn.missing ? '' : ',ensemble_id'}`).eq('score_id', scoreId)
      q = part === null ? q.is('part', null) : q.eq('part', part)
      if (layer !== undefined && !layerColumn.missing) q = layer === null ? q.is('ensemble_id', null) : q.eq('ensemble_id', layer)
      return q
    }
    let res = await run()
    if (res.error && isMissingLayer(res.error)) { layerColumn.missing = true; res = await run() }
    if (res.error) { console.warn('scribbles', res.error.message); return }
    const fresh = ((res.data ?? []) as Row[]).map(toInk)
    // Pages the reader is still editing keep their local strokes until saved.
    setRemote(prev => {
      const keep = prev.filter(r => r.userId === uid && dirty.current.has(r.page))
      return [...fresh.filter(r => !(r.userId === uid && dirty.current.has(r.page))), ...keep]
    })
  }, [scoreId, part, uid, layer])

  const refetchSoon = useRef<number | undefined>(undefined)
  const apply = useCallback((c: Change) => {
    if (c.eventType === 'DELETE') {
      const id = String(c.old.id)
      setRemote(xs => (xs.some(x => x.id === id) ? xs.filter(x => x.id !== id) : xs))
      return
    }
    const r = c.new
    if (r.score_id !== scoreId || (r.part ?? null) !== part || !inLayer(r, layerRef.current)) return
    if (c.errors || !Array.isArray(r.strokes)) {
      // Too large to travel: read it from the database instead.
      window.clearTimeout(refetchSoon.current)
      refetchSoon.current = window.setTimeout(() => void refetch(), 150)
      return
    }
    const row = toInk(r)
    if (row.userId === uid && dirty.current.has(row.page)) return
    if (row.userId !== uid) {
      const had = new Set(remoteRef.current.find(x => x.userId === row.userId && x.page === row.page)?.strokes.map(s => s.id))
      markArrival(row.strokes.filter(s => !had.has(s.id)).map(s => s.id))
    }
    setRemote(xs => {
      const i = xs.findIndex(x => x.userId === row.userId && x.page === row.page)
      return i < 0 ? [...xs, row] : xs.map((x, j) => (j === i ? row : x))
    })
  }, [scoreId, part, uid, refetch, markArrival])

  useEffect(() => {
    setRemote([])
    if (!synced) return
    dirty.current.clear()
    void refetch()
    return () => window.clearTimeout(refetchSoon.current)
  }, [synced, refetch])
  useLiveRows(synced ? scoreId : null, ['scribbles'], apply, () => void refetch())

  const rows = synced ? remote : local

  const save = useCallback(async () => {
    window.clearTimeout(timer.current)
    timer.current = undefined
    if (!synced || !dirty.current.size) return
    const pages = [...dirty.current]
    dirty.current.clear()
    setState('saving')
    const own = remoteRef.current.filter(r => r.userId === uid)
    const lay = layerRef.current
    const payload = (withLayer: boolean) => pages.map(page => ({
      score_id: scoreId, page, part, user_id: uid,
      strokes: own.find(r => r.page === page)?.strokes ?? [],
      ...(withLayer && lay !== undefined ? { ensemble_id: lay } : {}),
    }))
    // With the share migration the unique key carries the layer (`ensemble_id`); without it, it does not.
    const put = () => supabase.from('scribbles').upsert(payload(!layerColumn.missing), { onConflict: layerColumn.missing ? INK_KEY : `${INK_KEY},ensemble_id` })
    let { error } = await put()
    if (error && isMissingLayer(error)) { layerColumn.missing = true; ({ error } = await put()) }
    if (error) {
      pages.forEach(p => dirty.current.add(p))
      setState('error')
      console.warn('scribbles save', error.message)
      return
    }
    setState(dirty.current.size ? 'saving' : 'saved')
  }, [synced, scoreId, part, uid])

  const saveRef = useRef(save)
  useEffect(() => { saveRef.current = save })
  // Leaving the score (or switching part) saves what is pending.
  useEffect(() => () => { void saveRef.current() }, [scoreId, part])

  const edit = useCallback((page: number, fn: (strokes: Stroke[]) => Stroke[]) => {
    const apply = (xs: ScribbleRow[]) => {
      const i = xs.findIndex(r => r.userId === uid && r.page === page)
      const cur = i >= 0 ? xs[i].strokes : []
      const next = { ...(i >= 0 ? xs[i] : {}), page, part, userId: uid, strokes: fn(cur) }
      return i >= 0 ? xs.map((r, j) => (j === i ? next : r)) : [...xs, next]
    }
    if (!synced) { localInk.set(localKey, apply(localInk.get(localKey))); return }
    setRemote(apply)
    dirty.current.add(page)
    setState('saving')
    if (timer.current === undefined) timer.current = window.setTimeout(() => void saveRef.current(), SAVE_EVERY_MS)
  }, [synced, uid, part, localKey])

  const addStroke = useCallback((page: number, s: Stroke) => edit(page, xs => [...xs, s]), [edit])
  const erase = useCallback((ids: Set<string>) => {
    const pages = new Set(rows.filter(r => r.userId === uid && r.strokes.some(s => ids.has(s.id))).map(r => r.page))
    pages.forEach(p => edit(p, xs => xs.filter(s => !ids.has(s.id))))
  }, [rows, uid, edit])

  return { rows, uid, addStroke, erase, flush: save, synced, state, arriving: arrivals.ids }
}

// ---------------------------------------------------------------- stroke geometry

/** A point on screen: x, y and the drawn width, in stage pixels. */
export type Pt = [number, number, number]

const r4 = (v: number) => Math.round(v * 10000) / 10000
/** A Pencil's pressure (0..1; a finger reads 0.5) as a multiple of the pen's nominal width. */
export const pressureWidth = (p: number) => 0.55 + 0.9 * p

/** Ramer-Douglas-Peucker on stage pixels: drop points within `eps` of the line through their neighbours. */
export function simplify<T extends [number, number, ...number[]]>(pts: T[], eps: number): T[] {
  if (pts.length < 3) return pts
  const keep = new Uint8Array(pts.length)
  keep[0] = keep[pts.length - 1] = 1
  const stack: [number, number][] = [[0, pts.length - 1]]
  while (stack.length) {
    const [a, b] = stack.pop()!
    const [ax, ay] = pts[a]
    const [bx, by] = pts[b]
    const dx = bx - ax, dy = by - ay
    const len = Math.hypot(dx, dy) || 1
    let far = -1, dmax = eps
    for (let i = a + 1; i < b; i++) {
      const d = Math.abs((pts[i][0] - ax) * dy - (pts[i][1] - ay) * dx) / len
      if (d > dmax) { dmax = d; far = i }
    }
    if (far > 0) { keep[far] = 1; stack.push([a, far], [far, b]) }
  }
  return pts.filter((_, i) => keep[i])
}

/** Bars on one page, nearest first to a point: the bar a stroke is drawn over. */
function nearestBar(geo: Geo, page: number, x: number, y: number) {
  let best: { bar: number; d: number } | null = null
  for (const b of geo.bars.values()) {
    if (b.page !== page) continue
    const dx = Math.max(b.x - x, 0, x - (b.x + b.w))
    const dy = Math.max(b.y - y, 0, y - (b.y + b.h))
    const d = Math.hypot(dx, dy * 1.5)
    if (!best || d < best.d) best = { bar: b.bar, d }
  }
  return best?.bar ?? null
}

/** The page under a stage point (0-based), or the nearest displayed page. */
export function pageAt(geo: Geo, x: number, y: number): number | null {
  let best = -1
  let bestD = Infinity
  for (let i = 0; i < geo.pages.length; i++) {
    const p = geo.pages[i]
    if (!p) continue
    const d = Math.hypot(Math.max(p.x - x, 0, x - (p.x + p.w)), Math.max(p.y - y, 0, y - (p.y + p.h)))
    if (d < bestD) { bestD = d; best = i }
  }
  return best < 0 ? null : best
}

/** A finished stroke in stage pixels ([x, y, pressure]) becomes the stored shape, anchored to its bar. */
export function makeStroke(raw: [number, number, number][], pageIndex: number, geo: Geo, color: PenColor, widthPx: number, sameAs?: number | null): Stroke | null {
  const pg = geo.pages[pageIndex]
  if (!pg || !raw.length) return null
  const pts = simplify(raw, 0.6)
  // The bar under the pen as it touched down, or the bar of the stroke just drawn beside it (`sameAs`): the strokes
  // of one sign (a hairpin's two lines, the letters of a word) share a bar and move as one.
  const bar = sameAs != null && geo.bars.get(sameAs)?.page === pageIndex ? sameAs : nearestBar(geo, pageIndex, pts[0][0], pts[0][1])
  const b = bar != null ? geo.bars.get(bar) : undefined
  const fx = (x: number) => r4((x - pg.x) / pg.w)
  const fy = (y: number) => r4((y - pg.y) / pg.h)
  return {
    id: tempId('s'), color, width: r4(widthPx / pg.w) || 0.0001, aspect: r4(pg.h / pg.w),
    bar: b ? bar : null,
    box: b ? [fx(b.x), fy(b.y), r4(b.w / pg.w), r4(b.h / pg.h)] : null,
    points: pts.map(([x, y, p]) => [fx(x), fy(y), Math.round(p * 100) / 100]),
  }
}

/**
 * Where a stored stroke sits on the current engraving, in stage pixels. Its bar's box now decides: the point where
 * the pen touched down keeps its relative place in the bar, and the shape scales with the bar's height (the staff
 * size), never stretched. Unanchored strokes sit on their page by fractions. Null when neither is on screen.
 */
export function placeStroke(s: Stroke, page: number, geo: Geo): Pt[] | null {
  if (!s.points.length) return null
  const a = s.aspect || 1.414
  const cx = s.points[0][0], cy = s.points[0][1] * a
  const b = s.bar != null ? geo.bars.get(s.bar) : undefined
  if (b && s.box) {
    const [bx, byf, bw, bhf] = s.box
    const by = byf * a, bh = bhf * a
    const k = b.h / (bh || 1e-6)
    const ax = b.x + ((cx - bx) / (bw || 1e-6)) * b.w
    const ay = b.y + ((cy - by) / (bh || 1e-6)) * b.h
    return s.points.map(([x, y, p]) => [ax + (x - cx) * k, ay + (y * a - cy) * k, s.width * k * pressureWidth(p)])
  }
  if (s.bar != null) return null // its bar is on another spread
  const pg: Rect | null | undefined = geo.pages[page - 1]
  if (!pg) return null
  return s.points.map(([x, y, p]) => [pg.x + x * pg.w, pg.y + y * pg.h, s.width * pg.w * pressureWidth(p)])
}

/** A variable-width stroke as one filled outline: offset each side by half the width, round caps, smoothed. */
export function outlinePath(input: Pt[]): string {
  const pts: Pt[] = []
  for (const p of input) {
    const q = pts[pts.length - 1]
    if (!q || Math.hypot(p[0] - q[0], p[1] - q[1]) > 0.35) pts.push(p)
  }
  const f = (v: number) => Math.round(v * 100) / 100
  if (pts.length === 1) {
    const [x, y, w] = pts[0]
    const r = Math.max(0.6, w / 2)
    return `M${f(x - r)} ${f(y)}a${f(r)} ${f(r)} 0 1 0 ${f(2 * r)} 0a${f(r)} ${f(r)} 0 1 0 ${f(-2 * r)} 0Z`
  }
  const L: [number, number][] = []
  const R: [number, number][] = []
  for (let i = 0; i < pts.length; i++) {
    const a = pts[Math.max(0, i - 1)]
    const b = pts[Math.min(pts.length - 1, i + 1)]
    let dx = b[0] - a[0], dy = b[1] - a[1]
    const len = Math.hypot(dx, dy) || 1
    dx /= len; dy /= len
    const r = Math.max(0.35, pts[i][2] / 2)
    L.push([pts[i][0] - dy * r, pts[i][1] + dx * r])
    R.push([pts[i][0] + dy * r, pts[i][1] - dx * r])
  }
  const side = (s: [number, number][]) => {
    let d = ''
    for (let i = 1; i < s.length - 1; i++) {
      const mx = (s[i][0] + s[i + 1][0]) / 2, my = (s[i][1] + s[i + 1][1]) / 2
      d += `Q${f(s[i][0])} ${f(s[i][1])} ${f(mx)} ${f(my)}`
    }
    const e = s[s.length - 1]
    return d + `L${f(e[0])} ${f(e[1])}`
  }
  const rEnd = Math.max(0.35, pts[pts.length - 1][2] / 2)
  const rStart = Math.max(0.35, pts[0][2] / 2)
  const Rr = [...R].reverse()
  return `M${f(L[0][0])} ${f(L[0][1])}${side(L)}A${f(rEnd)} ${f(rEnd)} 0 0 1 ${f(Rr[0][0])} ${f(Rr[0][1])}${side(Rr)}A${f(rStart)} ${f(rStart)} 0 0 1 ${f(L[0][0])} ${f(L[0][1])}Z`
}

/** Whether a point is within `radius` of a placed stroke (the eraser takes whole strokes). */
export function hitsStroke(pts: Pt[], x: number, y: number, radius: number): boolean {
  for (let i = 0; i < pts.length; i++) {
    const [ax, ay, w] = pts[i]
    const [bx, by] = pts[Math.min(pts.length - 1, i + 1)]
    const dx = bx - ax, dy = by - ay
    const l2 = dx * dx + dy * dy
    const t = l2 ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) : 0
    if (Math.hypot(x - (ax + t * dx), y - (ay + t * dy)) <= radius + w / 2) return true
  }
  return false
}

/** Every placed stroke of the rows, split into the reader's own and everyone else's. */
export function usePlaced(rows: ScribbleRow[], uid: string, geo: Geo | null) {
  return useMemo(() => {
    const out: { id: string; color: PenColor; mine: boolean; pts: Pt[]; d: string }[] = []
    if (!geo) return out
    for (const r of rows) for (const s of r.strokes) {
      const pts = placeStroke(s, r.page, geo)
      if (pts) out.push({ id: s.id, color: s.color, mine: r.userId === uid, pts, d: outlinePath(pts) })
    }
    return out
  }, [rows, uid, geo])
}
