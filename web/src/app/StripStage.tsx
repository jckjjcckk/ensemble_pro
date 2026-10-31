/** A PDF book's split on the Stand (008, 010): one strip per cut system, full width, stacked in reading order and scrolled
 *  like a part, with a "Tacet" row for each page where the part rests. It speaks the stage contract of `EngravedStage`
 *  (focus, follow, underlay and overlay over a `Geo`, taps, holds), so a tap on a bar of a strip opens the same quick
 *  menu as on a page and a mark lands on that bar of the strip. Each strip is a "page" of the `Geo`; its bars come from
 *  the split's `bars_at` (the book's placements, as fractions of the strip's width), so the numbers are the book's own:
 *  a highlight made on the full page shows on the strip, and the other way round. A strip cut before bar numbers were
 *  kept has no bar boxes: it reads, but its bars cannot be tapped. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { supabase } from '../lib/supabase'
import type { PartStrip } from './data'
import type { BarBox, Geo, Rect } from './geometry'
import type { StageView } from './ScoreStage'
import { useStageGestures } from './stageGestures'
import { useReducedMotion } from './layout'

interface Props {
  strip: PartStrip
  focus: { bar: number; key: number }
  follow?: number
  onUserTurn?: () => void
  underlay?: (g: Geo) => ReactNode
  overlay?: (g: Geo) => ReactNode
  onBarTap?: (bar: number) => void
  onEmptyTap?: () => void
  onBarHold?: (bar: number) => void
  onView?: (v: StageView) => void
  still?: boolean
  label: string
}

// Room above each strip for the notes that stand above their bar (a bubble is 34 px tall and sits 10 px over it).
const PAD_X = 46
const PAD_TOP = 60
const CAPTION = 34
const GAP = 50
const TACET = 52
/** A system strip is about six times wider than tall; the reserved shape until its image has loaded. */
const GUESS_ASPECT = 0.17

type Row =
  | { kind: 'strip'; key: string; index: number; page: number; system: number; from?: number; to?: number; bars: [number, number, number][] }
  | { kind: 'tacet'; page: number; from: number | null; to: number | null }

const range = (a?: number | null, b?: number | null) => (a == null ? '' : a === b || b == null ? `bar ${a}` : `bars ${a}–${b}`)

export function StripStage({ strip, focus, follow, onUserTurn, underlay, overlay, onBarTap, onEmptyTap, onBarHold, onView, still, label }: Props) {
  const reduced = useReducedMotion()
  const stageRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [height, setHeight] = useState(0)
  const [scrollY, setScrollY] = useState(0)
  const [aspects, setAspects] = useState<Record<string, number>>({})
  const [urls, setUrls] = useState<Record<string, string>>({})

  const pathKey = strip.paths.join('\n')
  useEffect(() => {
    if (!pathKey) return
    let live = true
    supabase.storage.from('scores').createSignedUrls(pathKey.split('\n'), 3600).then(({ data }) => {
      if (live && data) setUrls(Object.fromEntries(data.flatMap(u => (u.path && u.signedUrl ? [[u.path, u.signedUrl] as const] : []))))
    })
    return () => { live = false }
  }, [pathKey])

  useLayoutEffect(() => {
    const el = stageRef.current
    if (!el) return
    const apply = () => { setWidth(Math.round(el.clientWidth)); setHeight(Math.round(el.clientHeight)) }
    apply()
    const ro = new ResizeObserver(apply)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Strips and tacet rows in page order: a page's strips by system, its tacet row where nothing of the part was cut.
  const rows = useMemo<Row[]>(() => {
    const cut: Row[] = strip.paths.map((key, index) => {
      const s = strip.systems.find(x => x.key === key)
      return { kind: 'strip', key, index, page: s?.page ?? 0, system: s?.system ?? index + 1, from: s?.bar_from, to: s?.bar_to, bars: s?.bars_at ?? [] }
    })
    const rests: Row[] = strip.tacet.map(t => ({ kind: 'tacet', page: t.page, from: t.bar_from, to: t.bar_to }))
    return [...cut, ...rests].sort((a, b) => a.page - b.page || (a.kind === 'strip' ? a.system : 99) - (b.kind === 'strip' ? b.system : 99))
  }, [strip])

  // Where each row sits, in content coordinates, and the Geo the overlays draw on (one "page" per strip).
  const layout = useMemo(() => {
    const w = Math.max(200, width - PAD_X * 2)
    let y = PAD_TOP
    const placed: { row: Row; rect: Rect }[] = []
    for (const row of rows) {
      const h = row.kind === 'strip' ? Math.round(w * (aspects[row.key] ?? GUESS_ASPECT)) : TACET
      placed.push({ row, rect: { x: PAD_X, y, w, h } })
      y += h + (row.kind === 'strip' ? CAPTION : 0) + GAP
    }
    return { placed, contentH: y + PAD_TOP }
  }, [rows, width, aspects])

  const geo = useMemo<Geo | null>(() => {
    if (!width) return null
    const pages: (Rect | null)[] = Array.from({ length: strip.paths.length }, () => null)
    const bars = new Map<number, BarBox>()
    const barPage = new Map<number, number>()
    const pageBars: [number, number][] = Array.from({ length: strip.paths.length }, () => [Infinity, -Infinity])
    let sys = 0
    for (const { row, rect } of layout.placed) {
      if (row.kind !== 'strip') continue
      pages[row.index] = rect
      for (const [bar, x0, x1] of row.bars) {
        if (!bars.has(bar)) bars.set(bar, { bar, page: row.index, sys, x: rect.x + x0 * rect.w, y: rect.y, w: Math.max(4, (x1 - x0) * rect.w), h: rect.h })
        if (!barPage.has(bar)) barPage.set(bar, row.index)
        pageBars[row.index] = [Math.min(pageBars[row.index][0], bar), Math.max(pageBars[row.index][1], bar)]
      }
      sys += 1
    }
    return { pageCount: strip.paths.length, barPage, pageBars, pages, bars }
  }, [layout, strip.paths.length, width])

  // What is on screen: the strips whose middle is in view.
  const view = useMemo<StageView | null>(() => {
    if (!geo) return null
    const lo = scrollY, hi = scrollY + (height || 1)
    const seen = geo.pages.map((p, i) => ({ p, i })).filter(x => x.p && x.p.y + x.p.h / 2 >= lo && x.p.y + x.p.h / 2 <= hi)
    const nums = seen.flatMap(x => geo.pageBars[x.i]).filter(Number.isFinite)
    const all = [...geo.bars.keys()]
    if (!nums.length && !all.length) return null
    const first = nums.length ? Math.min(...nums) : Math.min(...all)
    const last = nums.length ? Math.max(...nums) : first
    return { first, last, spread: seen[0]?.i ?? 0, spreads: geo.pageCount, perView: 1 }
  }, [geo, scrollY, height])
  const onViewRef = useRef(onView)
  useLayoutEffect(() => { onViewRef.current = onView })
  useEffect(() => { if (view) onViewRef.current?.(view) }, [view])

  // A scroll the stage makes itself (a jump, Follow) is not the reader's own move.
  const auto = useRef(0)
  const scrollToBar = (bar: number) => {
    const el = stageRef.current
    const i = geo?.barPage.get(bar)
    const p = i != null ? geo?.pages[i] : null
    if (!el || !p) return
    auto.current = performance.now()
    el.scrollTo({ top: Math.max(0, p.y - PAD_TOP), behavior: reduced ? 'auto' : 'smooth' })
  }
  // A jump to a bar (a face, a note, "continues at") brings its strip to the top.
  const focusKey = useRef(-1)
  useEffect(() => {
    if (!geo || focus.key === focusKey.current) return
    focusKey.current = focus.key
    if (focus.bar > 1 || focus.key > 0) scrollToBar(focus.bar)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus.key, focus.bar, geo])
  // Follow (the admin's bar, the playhead): scroll only when its strip has left the screen.
  useEffect(() => {
    if (follow == null || !geo || !view) return
    const i = geo.barPage.get(follow)
    const p = i != null ? geo.pages[i] : null
    if (p && (p.y < scrollY || p.y + p.h > scrollY + height)) scrollToBar(follow)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [follow])

  const gestures = useStageGestures({ geo, stageRef: contentRef, onBarTap, onEmptyTap, onBarHold })
  const settled = !!geo

  return (
    <div className="stage-wrap">
      <div
        className="stage is-strips" ref={stageRef} tabIndex={0} role="region" aria-label={label}
        onScroll={e => { setScrollY(e.currentTarget.scrollTop); if (performance.now() - auto.current > 900) onUserTurn?.() }} onContextMenu={e => e.preventDefault()}
        style={still ? { overflowY: 'hidden', touchAction: 'none' } : undefined}
      >
        <div
          className="stage-content" ref={contentRef} style={{ width: '100%', height: layout.contentH }}
          onPointerDown={still ? undefined : gestures.onPointerDown} onPointerMove={gestures.onPointerMove} onPointerUp={gestures.onPointerUp} onPointerCancel={gestures.onPointerCancel}
        >
          <div className="stage-under" aria-hidden="true">
            {layout.placed.map(({ row, rect }) => row.kind === 'strip' && <div key={row.key} className="sheet page-paper" style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }} />)}
            {settled && geo && underlay?.(geo)}
          </div>
          <div className="stage-host engraved-host" role="list" aria-label={`${strip.label}, ${strip.paths.length} systems`}>
            {layout.placed.map(({ row, rect }) => row.kind === 'strip' ? (
              <figure key={row.key} role="listitem" className={`engraved-page strip-page ${aspects[row.key] ? 'is-in' : ''}`} style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}>
                {urls[row.key] && (
                  <img src={urls[row.key]} alt={`${strip.label}, page ${row.page}${row.from != null ? `, ${range(row.from, row.to)}` : ''}`} draggable={false} decoding="async"
                    loading={row.index < 3 ? 'eager' : 'lazy'}
                    onLoad={e => { const im = e.currentTarget; if (im.naturalWidth) setAspects(a => (a[row.key] ? a : { ...a, [row.key]: im.naturalHeight / im.naturalWidth })) }} />
                )}
                <figcaption className="strip-caption" style={{ top: rect.h }}>
                  <span>Page <span className="num">{row.page}</span></span>
                  {row.from != null && <span className="num">{range(row.from, row.to)}</span>}
                </figcaption>
              </figure>
            ) : (
              <div key={`tacet-${row.page}`} role="listitem" className="strip-tacet is-stage" style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}>
                <b>Tacet</b><span>page <span className="num">{row.page}</span></span>{row.from != null && <span className="num">{range(row.from, row.to)}</span>}
              </div>
            ))}
          </div>
          <div className="stage-over">{settled && geo && overlay?.(geo)}</div>
        </div>
      </div>
    </div>
  )
}
