/** The page stage (features 005, 010; R3's Stand): a book's pages as images with a box per bar. A digital book's pages
 *  are the SVGs MuseScore drew on the box with the bar boxes it measured (`.mpos`); a PDF book's are the page images the
 *  librarian rendered, with the bar boxes it placed (`measure_placements`). Both arrive as one `Engraving` (page keys,
 *  bars as page fractions), so the PDF and the Digital stand are the same stage. It speaks the `ScoreStage` contract
 *  (focus, follow, underlay and overlay over a `Geo`, taps, holds, swipes), so highlights, notes, cuts, scribbles,
 *  presence and Follow work unchanged. One page in portrait, two facing in landscape; a pinch (or a trackpad pinch,
 *  ctrl + wheel) zooms into one page, which then pans under the finger, and pinching back to the whole page returns to
 *  the spread. Nothing is engraved on the device: a page is an image and the geometry is arithmetic. */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { supabase } from '../lib/supabase'
import type { Engraving } from '../mock'
import type { BarBox, Geo, Rect } from './geometry'
import type { StageView } from './ScoreStage'
import { useStageGestures } from './stageGestures'
import { useReducedMotion } from './layout'

export interface ZoomView { k: number; page: number; /** visible part of the page, as fractions of its height */ top: number; bottom: number }

interface Props {
  engraving: Engraving
  /** Height over width of a page when the engraving does not say (a PDF page image). */
  aspect?: number
  /** Show the spread containing this bar whenever key changes. */
  focus: { bar: number; key: number }
  /** Keep this bar on screen: turns the page when it leaves the spread. */
  follow?: number
  onUserTurn?: () => void
  underlay?: (g: Geo) => ReactNode
  overlay?: (g: Geo, zoom: ZoomView | null) => ReactNode
  onBarTap?: (bar: number) => void
  onEmptyTap?: () => void
  onBarHold?: (bar: number) => void
  onView?: (v: StageView, zoom: ZoomView | null) => void
  /** Pause gestures that turn or zoom (a scribble in progress owns the pointer). */
  still?: boolean
  label: string
}

const SIGN_SEC = 3600
const MAX_K = 4

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

/** "bars 49–64", or nothing for a page without bars (a title page). */
export const barsWords = (r: [number, number] | undefined) => (r && Number.isFinite(r[0]) ? (r[0] === r[1] ? `bar ${r[0]}` : `bars ${r[0]}–${r[1]}`) : '')

export function EngravedStage({ engraving, aspect: aspectIn, focus, follow, onUserTurn, underlay, overlay, onBarTap, onEmptyTap, onBarHold, onView, still, label }: Props) {
  const reduced = useReducedMotion()
  const stageRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [anchor, setAnchor] = useState(focus.bar)
  const urls = useSignedPages(engraving.paths)
  const model = useMemo(() => modelOf(engraving), [engraving])
  // Pages that have drawn, by key: a new engraving's keys are simply not in it yet.
  const [loaded, setLoaded] = useState<Set<string>>(() => new Set())
  // Zoomed into one page: the factor over the whole-page size, and which page.
  const [zoom, setZoom] = useState<{ k: number; page: number } | null>(null)
  const [scroll, setScroll] = useState({ x: 0, y: 0 })
  // Where the fingers are on the page while zooming, so that point stays under them.
  const focal = useRef<{ fx: number; fy: number; sx: number; sy: number } | null>(null)

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
  // A jump to a bar (a face, a note, the shelf's "continues at") shows its whole spread.
  const focusKey = useRef(focus.key)
  useEffect(() => { if (focus.key !== focusKey.current) { focusKey.current = focus.key; setZoom(null) } }, [focus.key])

  // The page's shape: the engraver's page in millimetres (3:4 for the iPad layout, the scan's for the original), or the
  // page image's own.
  const aspect = engraving.pageMm ? engraving.pageMm[1] / engraving.pageMm[0] : aspectIn ?? 1.333
  const layout = useMemo(() => {
    if (!size) return null
    const { w, h } = size
    const facing = w / h > 1.12 && w >= 860
    const perView = facing && !zoom ? 2 : 1
    // A gutter each side for the faces at the page edge (R3: 47 px in portrait, wider in a spread).
    const padX = w < 760 ? 40 : 46
    const padY = 20
    const gap = perView === 2 ? 24 : 0
    const availW = Math.max(200, w - padX * 2)
    const availH = Math.max(200, h - padY * 2)
    const boxW = facing ? (availW - 24) / 2 : availW
    // The whole page: the largest that fits. In a spread both pages share the width.
    const fitW = Math.floor(Math.min(perView === 2 ? boxW : facing ? boxW : availW, availH / aspect))
    const pw = Math.round(fitW * (zoom?.k ?? 1))
    const ph = Math.round(pw * aspect)
    return { perView, padX, padY, gap, availW, availH, pw, ph, fitW, w, h }
  }, [size, aspect, zoom])

  const n = layout?.perView ?? 1
  const spreads = Math.max(1, Math.ceil(model.pageCount / n))
  const spread = zoom ? zoom.page : Math.max(0, Math.min(spreads - 1, Math.floor((model.barPage.get(anchor) ?? 0) / n)))

  // The content's own size: the stage, or the zoomed page and its margins (it then scrolls).
  const contentW = layout ? Math.max(layout.w, zoom ? layout.pw + layout.padX * 2 : 0) : 0
  const contentH = layout ? Math.max(layout.h, zoom ? layout.ph + layout.padY * 2 : 0) : 0

  // Pages in content coordinates: the spread's pages side by side, centred, each bar's box scaled onto its page.
  const geo = useMemo<Geo | null>(() => {
    if (!layout) return null
    const pages: (Rect | null)[] = Array.from({ length: model.pageCount }, () => null)
    const shown = zoom ? [zoom.page] : Array.from({ length: n }, (_, i) => spread * n + i).filter(i => i < model.pageCount)
    const totalW = shown.length * layout.pw + (shown.length - 1) * layout.gap
    const x0 = Math.max(layout.padX, (contentW - totalW) / 2)
    const y0 = zoom ? layout.padY : layout.padY + Math.max(0, (layout.availH - layout.ph) / 2)
    shown.forEach((p, i) => { pages[p] = { x: x0 + i * (layout.pw + layout.gap), y: y0, w: layout.pw, h: layout.ph } })
    const bars = new Map<number, BarBox>()
    for (const [bar, page, x, y, w, h] of engraving.bars) {
      const p = pages[page - 1]
      if (!p || bars.has(bar)) continue
      bars.set(bar, { bar, page: page - 1, sys: model.sysOf.get(`${page}:${y.toFixed(3)}`) ?? 0, x: p.x + x * p.w, y: p.y + y * p.h, w: w * p.w, h: h * p.h })
    }
    return { pageCount: model.pageCount, barPage: model.barPage, pageBars: model.pageBars, pages, bars }
  }, [layout, model, engraving, n, spread, zoom, contentW])

  // After a zoom step, scroll so the point under the fingers stays there.
  useLayoutEffect(() => {
    const el = stageRef.current
    const f = focal.current
    if (!el || !f || !geo || !zoom) return
    const p = geo.pages[zoom.page]
    if (!p) return
    el.scrollLeft = p.x + f.fx * p.w - f.sx
    el.scrollTop = p.y + f.fy * p.h - f.sy
    setScroll({ x: el.scrollLeft, y: el.scrollTop })
  }, [geo, zoom])

  useEffect(() => {
    if (follow == null || zoom) return
    const p = model.barPage.get(follow)
    if (p != null && Math.floor(p / n) !== spread) setAnchor(follow)
  }, [follow, model, n, spread, zoom])

  // What is on screen. Zoomed: the bars whose middle is in the visible band of the page, and that band.
  const zoomView = useMemo<ZoomView | null>(() => {
    if (!zoom || !geo || !layout) return null
    const p = geo.pages[zoom.page]
    if (!p) return null
    const top = Math.max(0, Math.min(1, (scroll.y - p.y) / p.h))
    const bottom = Math.max(0, Math.min(1, (scroll.y + layout.h - p.y) / p.h))
    return { k: zoom.k, page: zoom.page, top, bottom }
  }, [zoom, geo, layout, scroll.y])
  const view = useMemo<StageView | null>(() => {
    if (zoomView && geo) {
      const p = geo.pages[zoomView.page]!
      const lo = p.y + zoomView.top * p.h, hi = p.y + zoomView.bottom * p.h
      const seen = [...geo.bars.values()].filter(b => b.y + b.h / 2 >= lo && b.y + b.h / 2 <= hi).map(b => b.bar)
      const range = model.pageBars[zoomView.page]
      const first = seen.length ? Math.min(...seen) : range[0]
      const last = seen.length ? Math.max(...seen) : range[1]
      if (!Number.isFinite(first)) return null
      return { first, last, spread: zoomView.page, spreads: model.pageCount, perView: 1 }
    }
    const pages = model.pageBars.slice(spread * n, spread * n + n).filter(([a]) => Number.isFinite(a))
    if (!pages.length) return null
    return { first: pages[0][0], last: pages[pages.length - 1][1], spread, spreads, perView: n }
  }, [model, spread, spreads, n, zoomView, geo])
  const onViewRef = useRef(onView)
  useLayoutEffect(() => { onViewRef.current = onView })
  useEffect(() => { if (view) onViewRef.current?.(view, zoomView) }, [view, zoomView])

  const turn = (d: number) => {
    if (zoom) return
    const next = Math.max(0, Math.min(spreads - 1, spread + d))
    if (next === spread) return
    const first = model.pageBars[next * n]?.[0]
    if (Number.isFinite(first)) { setAnchor(first); onUserTurn?.() }
  }
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); turn(1) }
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); turn(-1) }
    if ((e.key === '+' || e.key === '=') && geo) { e.preventDefault(); zoomBy(1.25, layout ? layout.w / 2 : 0, layout ? layout.h / 2 : 0) }
    if (e.key === '-' && zoom) { e.preventDefault(); zoomBy(0.8, layout ? layout.w / 2 : 0, layout ? layout.h / 2 : 0) }
    if (e.key === '0' && zoom) { e.preventDefault(); unzoom() }
  }
  const gestures = useStageGestures({ geo, stageRef: contentRef, turn, onBarTap, onEmptyTap, onBarHold })

  // ---------------------------------------------------------------- zoom

  const unzoom = useCallback(() => {
    focal.current = null
    setZoom(null)
    if (stageRef.current) { stageRef.current.scrollLeft = 0; stageRef.current.scrollTop = 0 }
    setScroll({ x: 0, y: 0 })
  }, [])

  /** Scale by `ratio` about a point given in stage (viewport) coordinates. */
  const zoomBy = useCallback((ratio: number, sx: number, sy: number) => {
    const el = stageRef.current
    if (!geo || !layout || !el) return
    const cx = sx + el.scrollLeft
    const cy = sy + el.scrollTop
    // The page under the point (or the nearest shown page), in content coordinates.
    const shown = geo.pages.map((p, i) => ({ p, i })).filter((x): x is { p: Rect; i: number } => !!x.p)
    if (!shown.length) return
    const hit = shown.find(({ p }) => cx >= p.x && cx <= p.x + p.w) ?? shown.reduce((a, b) => (Math.abs(b.p.x + b.p.w / 2 - cx) < Math.abs(a.p.x + a.p.w / 2 - cx) ? b : a))
    const k0 = zoom?.k ?? 1
    // A spread's page is a little narrower than a single page's whole size; zoom is relative to the whole-page size.
    const k = Math.max(1, Math.min(MAX_K, k0 * ratio))
    if (k <= 1.02) { unzoom(); return }
    focal.current = { fx: (cx - hit.p.x) / hit.p.w, fy: (cy - hit.p.y) / hit.p.h, sx, sy }
    setZoom({ k: Math.round(k * 100) / 100, page: hit.i })
  }, [geo, layout, zoom, unzoom])

  // Two fingers pinch (touch events, so the pan the zoomed page allows never swallows the second finger).
  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    let start: { d: number; k: number } | null = null
    const mid = (t: TouchList) => {
      const r = el.getBoundingClientRect()
      return { x: (t[0].clientX + t[1].clientX) / 2 - r.left, y: (t[0].clientY + t[1].clientY) / 2 - r.top, d: Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY) }
    }
    const onStart = (e: TouchEvent) => {
      if (still || e.touches.length !== 2) return
      cancelRef.current()
      start = { d: mid(e.touches).d, k: 1 }
    }
    const onMove = (e: TouchEvent) => {
      if (!start || e.touches.length !== 2) return
      e.preventDefault()
      const m = mid(e.touches)
      const ratio = m.d / start.d / start.k
      if (Math.abs(ratio - 1) < 0.015) return
      start.k *= ratio
      zoomByRef.current(ratio, m.x, m.y)
    }
    const onEnd = (e: TouchEvent) => { if (e.touches.length < 2) start = null }
    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchmove', onMove, { passive: false })
    el.addEventListener('touchend', onEnd)
    el.addEventListener('touchcancel', onEnd)
    // A trackpad pinch arrives as ctrl + wheel.
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey || still) return
      e.preventDefault()
      const r = el.getBoundingClientRect()
      zoomByRef.current(Math.exp(-e.deltaY * 0.01), e.clientX - r.left, e.clientY - r.top)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchmove', onMove)
      el.removeEventListener('touchend', onEnd)
      el.removeEventListener('touchcancel', onEnd)
      el.removeEventListener('wheel', onWheel)
    }
  }, [still])
  const zoomByRef = useRef(zoomBy)
  const cancelRef = useRef(gestures.onPointerCancel)
  useLayoutEffect(() => { zoomByRef.current = zoomBy; cancelRef.current = gestures.onPointerCancel })

  // A new book or layout starts whole.
  useEffect(() => { unzoom() }, [engraving.id, unzoom])

  const shownPages = geo ? geo.pages.map((p, i) => (p ? i : -1)).filter(i => i >= 0) : []
  const settled = shownPages.length > 0 && shownPages.every(i => loaded.has(engraving.paths[i]))
  const pageKey = zoom ? `z${zoom.page}` : `s${spread}`
  // Which way the last turn went, so the new spread slides in from that side.
  const [turned, setTurned] = useState({ spread, dir: 0 })
  if (turned.spread !== spread) setTurned({ spread, dir: spread > turned.spread ? 1 : -1 })
  const dir = turned.dir
  const slide = reduced || zoom ? 0 : 36
  const contentStyle: CSSProperties = { width: contentW || '100%', height: contentH || '100%' }

  return (
    <div className="stage-wrap">
    <div
      className={`stage is-engraved ${zoom ? 'is-zoomed' : ''}`} ref={stageRef} tabIndex={0} role="region" aria-label={label} onKeyDown={onKeyDown}
      onScroll={e => { const t = e.currentTarget; setScroll({ x: t.scrollLeft, y: t.scrollTop }) }}
      onContextMenu={e => e.preventDefault()}
    >
      <div
        className="stage-content" ref={contentRef} style={contentStyle}
        onPointerDown={still ? undefined : gestures.onPointerDown} onPointerMove={gestures.onPointerMove} onPointerUp={gestures.onPointerUp} onPointerCancel={gestures.onPointerCancel}
      >
        <AnimatePresence initial={false} mode="popLayout" custom={dir}>
          <motion.div
            key={pageKey} className="stage-turn" custom={dir}
            variants={{
              enter: (d: number) => ({ opacity: 0, x: d * slide }),
              center: { opacity: 1, x: 0 },
              leave: (d: number) => ({ opacity: 0, x: -d * slide, transition: { duration: 0.16, ease: [0.22, 1, 0.36, 1] } }),
            }}
            initial="enter" animate="center" exit="leave"
            transition={reduced ? { duration: 0.12 } : { type: 'spring', stiffness: 360, damping: 36, mass: 0.8 }}
          >
            <div className="stage-under" aria-hidden="true">
              {geo?.pages.map((p, i) => p && <div key={i} className="sheet page-paper" style={{ left: p.x, top: p.y, width: p.w, height: p.h }} />)}
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
                    {!zoom && <figcaption className="page-label">{[barsWords(model.pageBars[i]), n === 1 ? `p. ${i + 1}` : ''].filter(Boolean).join(' · ')}</figcaption>}
                  </figure>
                )
              })}
            </div>
          </motion.div>
        </AnimatePresence>
        <div className="stage-over">{settled && geo && overlay?.(geo, zoomView)}</div>
      </div>
    </div>
      {view && !zoom && (
        <>
          <button type="button" className="turn turn-prev" onClick={() => turn(-1)} disabled={spread === 0} aria-label="Previous pages">‹</button>
          <button type="button" className="turn turn-next" onClick={() => turn(1)} disabled={spread >= spreads - 1} aria-label="Next pages">›</button>
        </>
      )}
      {zoom && zoomView && layout && (
        <div className="zoom-hud">
          <button type="button" className="zoom-pill" onClick={unzoom} aria-label={`${Math.round(zoom.k * 100)} percent. Show the whole page`}>
            {Math.round(zoom.k * 100)} % · pinch to see the whole page
          </button>
          <span className="zoom-map" aria-label="Page overview, showing the visible part" role="img">
            {[8, 30, 52, 74].map(t => <span key={t} className="zoom-map-line" style={{ top: t }} />)}
            <span className="zoom-map-view" style={{ top: `${zoomView.top * 100}%`, height: `${(zoomView.bottom - zoomView.top) * 100}%` }} />
          </span>
        </div>
      )}
    </div>
  )
}
