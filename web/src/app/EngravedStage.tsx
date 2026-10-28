/** The engraved page stage (features 005 and 010): a digital book's pages as MuseScore drew them on the box, one SVG per
 *  page, with the bar boxes it measured (`.mpos`, as fractions of the page). It stands where `ScoreStage` stands and
 *  speaks the same contract (focus, follow, underlay and overlay over a `Geo`, taps, holds, swipes), so highlights,
 *  notes, cuts, scribbles, presence and Follow work on these pages unchanged. Nothing is engraved on the device: a page
 *  is an image, and the geometry is arithmetic over the stage's size. One page per screen in portrait, two facing in
 *  landscape, as the PDF reader does. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'
import { supabase } from '../lib/supabase'
import type { Engraving } from '../mock'
import type { BarBox, Geo, Rect } from './geometry'
import { IChevronLeft, IChevronRight } from './icons'
import type { StageView } from './ScoreStage'
import { useStageGestures } from './stageGestures'

interface Props {
  engraving: Engraving
  /** Show the spread containing this bar whenever key changes. */
  focus: { bar: number; key: number }
  /** Keep this bar on screen: turns the page when it leaves the spread. */
  follow?: number
  onUserTurn?: () => void
  underlay?: (g: Geo) => ReactNode
  overlay?: (g: Geo) => ReactNode
  onBarTap?: (bar: number) => void
  onEmptyTap?: () => void
  onBarHold?: (bar: number) => void
  onView?: (v: StageView) => void
  /** Horizontal room kept free beside the pages, for margin notes. */
  margin?: number
  label: string
}

const SIGN_SEC = 3600

/** Signed URLs for the pages, one batch per page set, re-signed when the set changes. */
function useSignedPages(keys: string[]): Record<string, string> {
  const [urls, setUrls] = useState<Record<string, string>>({})
  const keyList = keys.join('\n')
  useEffect(() => {
    if (!keyList) return
    let live = true
    supabase.storage.from('scores').createSignedUrls(keyList.split('\n'), SIGN_SEC).then(({ data }) => {
      if (live && data) setUrls(Object.fromEntries(data.flatMap(u => (u.path && u.signedUrl ? [[u.path, u.signedUrl] as const] : []))))
    })
    return () => { live = false }
  }, [keyList])
  return urls
}

/** The piece's shape from the engraving alone: which page each bar is on, the bars of each page, the system of each bar. */
function modelOf(e: Engraving) {
  const barPage = new Map<number, number>()
  const pageBars: [number, number][] = Array.from({ length: e.pageCount }, () => [Infinity, -Infinity])
  // A system is one page and one y; its index runs through the piece in reading order.
  const sysOf = new Map<string, number>()
  const sorted = [...e.bars].sort((a, b) => a[1] - b[1] || a[3] - b[3] || a[2] - b[2])
  for (const b of sorted) {
    const k = `${b[1]}:${b[3].toFixed(3)}`
    if (!sysOf.has(k)) sysOf.set(k, sysOf.size)
  }
  for (const [bar, page] of e.bars) {
    const p = page - 1
    if (p < 0 || p >= e.pageCount) continue
    if (!barPage.has(bar)) barPage.set(bar, p)
    pageBars[p][0] = Math.min(pageBars[p][0], bar)
    pageBars[p][1] = Math.max(pageBars[p][1], bar)
  }
  return { pageCount: e.pageCount, barPage, pageBars, sysOf }
}

export function EngravedStage({ engraving, focus, follow, onUserTurn, underlay, overlay, onBarTap, onEmptyTap, onBarHold, onView, margin, label }: Props) {
  const stageRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [anchor, setAnchor] = useState(focus.bar)
  const urls = useSignedPages(engraving.paths)
  const model = useMemo(() => modelOf(engraving), [engraving])
  // Pages that have drawn, by key: a new engraving's keys are simply not in it yet.
  const [loaded, setLoaded] = useState<Set<string>>(() => new Set())

  useLayoutEffect(() => {
    const el = stageRef.current
    if (!el) return
    const apply = (width: number, height: number) => {
      if (width < 2 || height < 2) return
      const w = Math.round(width)
      const h = Math.round(height)
      setSize(s => (s && Math.abs(s.w - w) < 2 && Math.abs(s.h - h) < 2 ? s : { w, h }))
    }
    const r = el.getBoundingClientRect()
    apply(r.width, r.height)
    const ro = new ResizeObserver(([entry]) => apply(entry.contentRect.width, entry.contentRect.height))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => { setAnchor(focus.bar) }, [focus.key, focus.bar])

  // The page's shape: the engraver's page in millimetres (3:4 for the iPad layout, the scan's for the original).
  const aspect = engraving.pageMm ? engraving.pageMm[1] / engraving.pageMm[0] : 1.333
  const layout = useMemo(() => {
    if (!size) return null
    const { w, h } = size
    const perView = w / h > 1.12 && w >= 860 ? 2 : 1
    const padX = margin ?? (w < 760 ? 12 : 28)
    const padY = 14
    const gap = perView === 2 ? 28 : 0
    const footer = 30
    const availW = Math.max(200, w - padX * 2)
    const availH = Math.max(200, h - padY * 2 - footer)
    const boxW = perView === 2 ? (availW - gap) / 2 : availW
    const pw = Math.floor(Math.min(boxW, availH / aspect))
    const ph = Math.round(pw * aspect)
    return { perView, padX, padY, gap, availW, availH, pw, ph }
  }, [size, margin, aspect])

  const n = layout?.perView ?? 1
  const spreads = Math.max(1, Math.ceil(model.pageCount / n))
  const spread = Math.max(0, Math.min(spreads - 1, Math.floor((model.barPage.get(anchor) ?? 0) / n)))

  // Pages in stage coordinates: the spread's pages side by side, centred, each bar's box scaled onto its page.
  const geo = useMemo<Geo | null>(() => {
    if (!layout) return null
    const pages: (Rect | null)[] = Array.from({ length: model.pageCount }, () => null)
    const shown = Array.from({ length: n }, (_, i) => spread * n + i).filter(i => i < model.pageCount)
    const totalW = shown.length * layout.pw + (shown.length - 1) * layout.gap
    const x0 = layout.padX + (layout.availW - totalW) / 2
    const y0 = layout.padY + Math.max(0, (layout.availH - layout.ph) / 2)
    shown.forEach((p, i) => { pages[p] = { x: x0 + i * (layout.pw + layout.gap), y: y0, w: layout.pw, h: layout.ph } })
    const bars = new Map<number, BarBox>()
    for (const [bar, page, x, y, w, h] of engraving.bars) {
      const p = pages[page - 1]
      if (!p || bars.has(bar)) continue
      bars.set(bar, { bar, page: page - 1, sys: model.sysOf.get(`${page}:${y.toFixed(3)}`) ?? 0, x: p.x + x * p.w, y: p.y + y * p.h, w: w * p.w, h: h * p.h })
    }
    return { pageCount: model.pageCount, barPage: model.barPage, pageBars: model.pageBars, pages, bars }
  }, [layout, model, engraving, n, spread])

  useEffect(() => {
    if (follow == null) return
    const p = model.barPage.get(follow)
    if (p != null && Math.floor(p / n) !== spread) setAnchor(follow)
  }, [follow, model, n, spread])

  const view = useMemo<StageView | null>(() => {
    const pages = model.pageBars.slice(spread * n, spread * n + n).filter(([a]) => Number.isFinite(a))
    if (!pages.length) return null
    return { first: pages[0][0], last: pages[pages.length - 1][1], spread, spreads, perView: n }
  }, [model, spread, spreads, n])
  const onViewRef = useRef(onView)
  useLayoutEffect(() => { onViewRef.current = onView })
  useEffect(() => { if (view) onViewRef.current?.(view) }, [view])

  const turn = (d: number) => {
    const next = Math.max(0, Math.min(spreads - 1, spread + d))
    if (next === spread) return
    const first = model.pageBars[next * n]?.[0]
    if (Number.isFinite(first)) { setAnchor(first); onUserTurn?.() }
  }
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); turn(1) }
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); turn(-1) }
  }
  const { onPointerDown, onPointerMove, onPointerUp, onPointerCancel } = useStageGestures({ geo, stageRef, turn, onBarTap, onEmptyTap, onBarHold })

  const shownPages = geo ? geo.pages.map((p, i) => (p ? i : -1)).filter(i => i >= 0) : []
  const settled = shownPages.length > 0 && shownPages.every(i => loaded.has(engraving.paths[i]))

  return (
    <div
      className="stage is-engraved" ref={stageRef} tabIndex={0} role="region" aria-label={label} onKeyDown={onKeyDown}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerCancel}
      onContextMenu={e => e.preventDefault()}
    >
      <div className="stage-under" aria-hidden="true">
        {geo?.pages.map((p, i) => p && <div key={i} className="sheet" style={{ left: p.x, top: p.y, width: p.w, height: p.h }} />)}
        {settled && geo && underlay?.(geo)}
      </div>
      <div className="stage-host engraved-host" data-score-state={settled ? 'ready' : 'loading'}>
        {geo?.pages.map((p, i) => {
          if (!p) return null
          const key = engraving.paths[i]
          const url = urls[key]
          const style: CSSProperties = { left: p.x, top: p.y, width: p.w, height: p.h }
          return (
            <figure key={key} className={`engraved-page ${loaded.has(key) ? 'is-in' : ''}`} style={style}>
              {url ? <img src={url} alt={`Page ${i + 1}`} draggable={false} decoding="async" onLoad={() => setLoaded(s => (s.has(key) ? s : new Set(s).add(key)))} /> : null}
              {!loaded.has(key) && (
                <span className="skeleton-page" aria-hidden="true" style={{ width: p.w, height: p.h }}>
                  {Array.from({ length: 6 }, (_, j) => <span key={j} />)}
                </span>
              )}
            </figure>
          )
        })}
      </div>
      <div className="stage-over">{settled && geo && overlay?.(geo)}</div>
      {view && (
        <>
          <button type="button" className="turn turn-prev" onClick={() => turn(-1)} disabled={spread === 0} aria-label="Previous pages">
            <IChevronLeft size={22} />
          </button>
          <button type="button" className="turn turn-next" onClick={() => turn(1)} disabled={spread >= spreads - 1} aria-label="Next pages">
            <IChevronRight size={22} />
          </button>
          <p className="stage-foot">
            <span>{n === 2 ? 'Pages' : 'Page'} {spread * n + 1}{n === 2 && spread * n + 2 <= model.pageCount ? `–${spread * n + 2}` : ''} of {model.pageCount}</span>
            <span className="num">bars {view.first}–{view.last}</span>
          </p>
        </>
      )}
    </div>
  )
}
