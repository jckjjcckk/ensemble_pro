/** Quick marks and scribbles (012): what a tap on a bar writes, and the ink drawn over the page.
 *
 *  Marks are `annotations` rows on stable `measures.id` (the same record the collaboration item pushes live);
 *  scribbles are `scribbles` rows, one per (score, page as drawn, part, author). A score that is not in Supabase
 *  (the mock world, the practice screen) keeps both in memory for the session, behind the same functions. */
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { supabase } from '../lib/supabase'
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

interface Row {
  id: string; score_id: string; kind: AnnotationKind; body: string | null; payload: Record<string, unknown> | null
  audience: 'ensemble' | 'part' | 'member'; audience_part: string | null; author_id: string; status: string; created_at: string
  mf: { number: number } | null; mt: { number: number } | null
}

const SELECT = 'id,score_id,kind,body,payload,audience,audience_part,author_id,status,created_at,mf:measures!annotations_measure_from_fkey(number),mt:measures!annotations_measure_to_fkey(number)'

/**
 * The marks on one score: loaded with the score, refetched when any row of it changes (Realtime as a
 * notification; the database is truth), written optimistically. `partIdByName` maps a part audience back to the
 * app's part ids; `ensembleId` lets authors be named by their member rows.
 */
export function useBarMarks(scoreId: string, me: Me | null, opts: { partIdByName?: Record<string, string>; ensembleId?: string } = {}) {
  const synced = !!me?.userId && isSyncedScore(scoreId)
  const local = useSyncExternalStore(localMarks.subscribe, () => localMarks.get(scoreId))
  const [rows, setRows] = useState<BarMark[]>([])
  const [authors, setAuthors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const meRef = useRef(me)
  useEffect(() => { meRef.current = me })
  const partIds = opts.partIdByName
  const partIdsRef = useRef(partIds)
  useEffect(() => { partIdsRef.current = partIds })

  const toMark = useCallback((r: Row, who: Record<string, string>): BarMark => {
    const m = meRef.current
    const bar = r.mf?.number ?? Number(r.payload?.bar ?? 0)
    const mine = r.author_id === m?.userId
    return {
      id: r.id, scoreId: r.score_id, kind: r.kind,
      partId: r.audience === 'part' && r.audience_part ? partIdsRef.current?.[r.audience_part] ?? r.audience_part : null,
      authorId: mine ? m!.memberId : who[r.author_id] ?? r.author_id,
      barFrom: bar, barTo: r.mt?.number ?? bar,
      text: r.body ?? undefined, createdAt: r.created_at,
      mine, removable: mine || !!m?.admin, audience: r.audience,
    }
  }, [])

  const authorsRef = useRef(authors)
  useEffect(() => { authorsRef.current = authors })

  const refetch = useCallback(async () => {
    const { data, error: e } = await supabase.from('annotations').select(SELECT).eq('score_id', scoreId).order('created_at')
    if (e) { setError(e.message); return }
    setError(null)
    setRows((data as unknown as Row[]).map(r => toMark(r, authorsRef.current)))
  }, [scoreId, toMark])

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
    if (!synced) { setRows([]); return }
    void refetch()
    let timer: number | undefined
    const ch = supabase.channel(`marks:${scoreId}:${tempId('c')}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'annotations', filter: `score_id=eq.${scoreId}` }, () => {
        window.clearTimeout(timer)
        timer = window.setTimeout(() => void refetch(), 150)
      })
      .subscribe()
    return () => { window.clearTimeout(timer); void supabase.removeChannel(ch) }
  }, [synced, scoreId, refetch])

  // A late author map re-labels what is already loaded.
  useEffect(() => { if (synced && Object.keys(authors).length) void refetch() }, [authors, synced, refetch])

  const marks = synced ? rows : local

  const add = useCallback(async (n: NewMark): Promise<void> => {
    const m = meRef.current
    const barTo = n.barTo ?? n.barFrom
    const aud = n.audience
    const temp: BarMark = {
      id: tempId('m'), scoreId, kind: n.kind, partId: typeof n.audience === 'object' ? partIdsRef.current?.[n.audience.part] ?? null : null,
      authorId: m?.memberId ?? LOCAL_AUTHOR, barFrom: n.barFrom, barTo, text: n.text, createdAt: new Date().toISOString(),
      mine: true, removable: true,
      audience: aud === 'self' ? (m?.ensemble === false ? 'ensemble' : 'member') : aud === 'ensemble' ? 'ensemble' : 'part',
    }
    if (!synced) { localMarks.set(scoreId, [...localMarks.get(scoreId), temp]); return }
    setRows(xs => [...xs, temp])
    try {
      const nums = [...new Set([n.barFrom, barTo])]
      const { data: ids, error: e1 } = await supabase.rpc('measure_ids', { p_score: scoreId, p_numbers: nums })
      if (e1) throw e1
      const idOf = new Map((ids as { number: number; id: string }[]).map(r => [r.number, r.id]))
      const audience = aud === 'self'
        ? (m!.ensemble ? { audience: 'member', audience_member_id: m!.memberId } : { audience: 'ensemble' })
        : aud === 'ensemble' ? { audience: 'ensemble' } : { audience: 'part', audience_part: aud.part }
      const { data, error: e2 } = await supabase.from('annotations').insert({
        score_id: scoreId, kind: n.kind, measure_from: idOf.get(n.barFrom), measure_to: idOf.get(barTo),
        author_id: m!.userId, body: n.text ?? null, payload: { bar: n.barFrom, bar_to: barTo, part: n.part ?? null, via: 'quick' },
        ...audience,
      }).select(SELECT).single()
      if (e2) throw e2
      setRows(xs => xs.map(x => (x.id === temp.id ? toMark(data as unknown as Row, authorsRef.current) : x)))
      setError(null)
    } catch (e) {
      setRows(xs => xs.filter(x => x.id !== temp.id))
      setError(e instanceof Error ? e.message : String((e as { message?: string })?.message ?? e))
    }
  }, [scoreId, synced, toMark])

  const remove = useCallback(async (id: string): Promise<void> => {
    if (!synced) { localMarks.set(scoreId, localMarks.get(scoreId).filter(x => x.id !== id)); return }
    let removed: BarMark | undefined
    setRows(xs => { removed = xs.find(x => x.id === id); return xs.filter(x => x.id !== id) })
    const { error: e } = await supabase.from('annotations').delete().eq('id', id)
    if (e) { setError(e.message); if (removed) setRows(xs => [...xs, removed!]) }
  }, [scoreId, synced])

  /** Highlight is a toggle of the reader's own highlight on that bar; other people's stay. */
  const toggleHighlight = useCallback((bar: number, part: string | null) => {
    const own = marks.find(x => x.kind === 'highlight' && x.mine && x.barFrom === bar)
    if (own) return remove(own.id)
    return add({ kind: 'highlight', barFrom: bar, audience: 'ensemble', part })
  }, [marks, add, remove])

  return { marks, add, remove, toggleHighlight, synced, error }
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
  page: number
  /** parts.name on screen, null for the full score. */
  part: string | null
  userId: string
  strokes: Stroke[]
}

const LOCAL_USER = 'local'
const localInk = memory<ScribbleRow>()
const SAVE_EVERY_MS = 3000

/**
 * Everyone's strokes on one score and part, plus the reader's own edits. Loaded with the score (rows are small;
 * strokes are placed by bar, so every page on screen draws from the same set), refetched on any change. The
 * reader's pages save every few seconds while they draw, and at once on `flush` (Done) and on leaving.
 */
export function useScribbles(scoreId: string, part: string | null, me: Me | null) {
  const synced = !!me?.userId && isSyncedScore(scoreId)
  const uid = synced ? me!.userId! : LOCAL_USER
  const localKey = `${scoreId}|${part ?? ''}`
  const local = useSyncExternalStore(localInk.subscribe, () => localInk.get(localKey))
  const [remote, setRemote] = useState<ScribbleRow[]>([])
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  /** Pages of the reader's own ink edited since the last save. */
  const dirty = useRef(new Set<number>())
  const timer = useRef<number | undefined>(undefined)
  const remoteRef = useRef(remote)
  useEffect(() => { remoteRef.current = remote })

  const refetch = useCallback(async () => {
    let q = supabase.from('scribbles').select('page,part,user_id,strokes').eq('score_id', scoreId)
    q = part === null ? q.is('part', null) : q.eq('part', part)
    const { data, error } = await q
    if (error) { console.warn('scribbles', error.message); return }
    const fresh = (data ?? []).map(r => ({ page: r.page as number, part: (r.part as string | null) ?? null, userId: r.user_id as string, strokes: (r.strokes as Stroke[]) ?? [] }))
    // Pages the reader is still editing keep their local strokes until saved.
    setRemote(prev => {
      const keep = prev.filter(r => r.userId === uid && dirty.current.has(r.page))
      return [...fresh.filter(r => !(r.userId === uid && dirty.current.has(r.page))), ...keep]
    })
  }, [scoreId, part, uid])

  useEffect(() => {
    setRemote([])
    if (!synced) return
    dirty.current.clear()
    void refetch()
    let t: number | undefined
    const ch = supabase.channel(`ink:${scoreId}:${tempId('c')}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'scribbles', filter: `score_id=eq.${scoreId}` }, () => {
        window.clearTimeout(t)
        t = window.setTimeout(() => void refetch(), 200)
      })
      .subscribe()
    return () => { window.clearTimeout(t); void supabase.removeChannel(ch) }
  }, [synced, scoreId, refetch])

  const rows = synced ? remote : local

  const save = useCallback(async () => {
    window.clearTimeout(timer.current)
    timer.current = undefined
    if (!synced || !dirty.current.size) return
    const pages = [...dirty.current]
    dirty.current.clear()
    setState('saving')
    const own = remoteRef.current.filter(r => r.userId === uid)
    const payload = pages.map(page => ({
      score_id: scoreId, page, part, user_id: uid,
      strokes: own.find(r => r.page === page)?.strokes ?? [],
    }))
    const { error } = await supabase.from('scribbles').upsert(payload, { onConflict: 'score_id,page,part,user_id' })
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
      const next = { page, part, userId: uid, strokes: fn(cur) }
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

  return { rows, uid, addStroke, erase, flush: save, synced, state }
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
