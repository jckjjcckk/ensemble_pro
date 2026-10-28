import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import { measureGeo, readModel, type Geo } from './geometry'
import { IChevronLeft, IChevronRight } from './icons'
import { Fade } from './Sheet'

/** Page shapes the stage may ask OSMD for. Few buckets, so a small resize re-engraves at the same shape. */
const ASPECTS = [0.72, 0.82, 0.94, 1.06, 1.2, 1.414]

/** A resize burst (window drag, rotation) settles this long before the score re-engraves. */
const RESIZE_SETTLE_MS = 160

export interface StageView { first: number; last: number; spread: number; spreads: number; perView: number }

interface Props {
  src: string
  /** Instrument indices to show; null shows the full score. */
  instruments: number[] | null
  /** Effective staff scale on screen (1 = OSMD at 100%). */
  scale: number
  /** Show the spread containing this bar whenever key changes. */
  focus: { bar: number; key: number }
  /** Keep this bar on screen: turns the page when it leaves the spread. */
  follow?: number
  underlay?: (g: Geo) => ReactNode
  overlay?: (g: Geo) => ReactNode
  onBarTap?: (bar: number) => void
  /** Long press on a bar (500 ms without moving), for annotating from the music itself. */
  onBarHold?: (bar: number) => void
  onView?: (v: StageView) => void
  /** Horizontal room kept free beside the pages, for margin notes. Defaults to the stage's own padding. */
  margin?: number
  label: string
}

const HOLD_MS = 500
const SWIPE_PX = 56

function nearest(xs: number[], v: number) {
  return xs.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a))
}

/**
 * The stage engraves for exactly three reasons: the score loaded, the stage's own size changed (a rotation or a
 * window resize, settled), or the part changed. Chrome never resizes it: panels and the composer float over it.
 * The reader's place survives every engrave as a bar number (the anchor), never as a page number.
 */
export function ScoreStage({ src, instruments, scale, focus, follow, underlay, overlay, onBarTap, onBarHold, onView, margin, label }: Props) {
  const stageRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const osmdRef = useRef<OpenSheetMusicDisplay | null>(null)
  /** The instance has drawn at least once; before that there is nothing to measure. */
  const drawnRef = useRef(false)
  /** An engrave is scheduled; measurements of the old drawing are skipped until it lands. */
  const pendingRef = useRef(false)
  /** What the current drawing was engraved for. A change that settles back here is not re-engraved. */
  const engravedRef = useRef<string | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [loaded, setLoaded] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [geo, setGeo] = useState<Geo | null>(null)
  const [settled, setSettled] = useState(false)
  const [anchor, setAnchor] = useState(focus.bar)
  const anchorRef = useRef(anchor)
  const instrumentsKey = JSON.stringify(instruments)
  const instrumentsRef = useRef(instruments)

  // The stage's real size. A zero size (hidden, or not laid out yet) is not a size: the engrave waits for a real one.
  useLayoutEffect(() => {
    const el = stageRef.current
    if (!el) return
    const apply = (width: number, height: number) => {
      if (width < 2 || height < 2) return
      const w = Math.round(width)
      const h = Math.round(height)
      setSize(s => (s && Math.abs(s.w - w) < 2 && Math.abs(s.h - h) < 2 ? s : { w, h }))
    }
    // The size at mount is read directly: a page that gets no frames yet (background tab) still engraves.
    const r = el.getBoundingClientRect()
    apply(r.width, r.height)
    const ro = new ResizeObserver(([entry]) => apply(entry.contentRect.width, entry.contentRect.height))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

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
    const aspect = nearest(ASPECTS, availH / boxW)
    const pw = Math.floor(Math.min(boxW, availH / aspect))
    const ph = Math.round(pw * aspect)
    const ratio = pw / availW
    const zoom = Math.max(0.3, Math.round((scale / ratio) * 20) / 20)
    return { perView, padX, padY, gap, availW, pw, ph, zoom, format: `1000x${Math.round(1000 * aspect)}` }
  }, [size, scale, margin])

  const perViewRef = useRef(1)
  useLayoutEffect(() => {
    anchorRef.current = anchor
    perViewRef.current = layout?.perView ?? 1
    instrumentsRef.current = instruments
  })

  /** Show the spread holding the anchor bar and read every bar's box on it. Cheap: no OSMD work. */
  const measure = useCallback(() => {
    const stage = stageRef.current
    const container = hostRef.current
    const osmd = osmdRef.current
    if (!stage || !container || !osmd || !drawnRef.current || pendingRef.current) return
    const pageEls = Array.from(container.children) as HTMLElement[]
    const n = perViewRef.current
    const model = readModel(osmd)
    let spread = Math.floor((model.barPage.get(anchorRef.current) ?? 0) / n)
    spread = Math.max(0, Math.min(spread, Math.ceil(model.pageCount / n) - 1))
    pageEls.forEach((el, i) => { el.style.display = i >= spread * n && i < spread * n + n ? '' : 'none' })
    setGeo(measureGeo(osmd, stage, pageEls))
    setSettled(true)
  }, [])

  // One instance per score, loaded once. Page format, zoom and visible parts are set per engrave, not per load.
  useEffect(() => {
    const container = hostRef.current
    if (!container) return
    const osmd = new OpenSheetMusicDisplay(container, {
      autoResize: false,
      backend: 'svg',
      drawTitle: false,
      drawComposer: false,
      drawSubtitle: false,
      drawLyricist: false,
      drawPartNames: true,
      drawMeasureNumbers: true,
      pageFormat: 'A4_P',
    })
    osmdRef.current = osmd
    drawnRef.current = false
    let cancelled = false
    setLoaded(null)
    setError(null)
    setSettled(false)
    setGeo(null)
    osmd.load(src)
      .then(() => { if (!cancelled) setLoaded(src) })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
    return () => {
      cancelled = true
      osmd.clear()
      if (osmdRef.current === osmd) osmdRef.current = null
      drawnRef.current = false
    }
  }, [src])

  // The engrave. Scheduled in the layout phase so measure() below knows to wait. The first one for a score runs
  // right after the next paint, so the skeleton is on screen while OSMD works (hundreds of ms here, seconds on an
  // iPad); later ones wait for the burst to settle, since a rotation changes the viewport, the scale and the
  // stage's size in separate frames. Whatever the inputs settle back to, an unchanged drawing is kept.
  useLayoutEffect(() => {
    const osmd = osmdRef.current
    if (!osmd || loaded !== src || !layout) return
    const signature = `${src} ${layout.format} ${layout.zoom} ${instrumentsKey}`
    if (drawnRef.current && engravedRef.current === signature) { measure(); return }
    pendingRef.current = true
    setSettled(false)
    let done = false
    const engrave = () => {
      if (done || osmdRef.current !== osmd) return
      done = true
      osmd.setPageFormat(layout.format)
      osmd.zoom = layout.zoom
      const want = instrumentsRef.current
      osmd.Sheet.Instruments.forEach((ins, i) => { ins.Visible = want === null || want.includes(i) })
      performance.mark('score-engrave', { detail: { format: layout.format, zoom: layout.zoom, parts: instrumentsKey, w: size?.w, h: size?.h } })
      osmd.render()
      drawnRef.current = true
      engravedRef.current = signature
      pendingRef.current = false
      measure()
    }
    let frame: number | undefined
    let timer: number | undefined
    // A part switch at the same shape re-engraves at once; a size change is a burst and waits for it to settle.
    const partSwitch = drawnRef.current && engravedRef.current?.startsWith(`${src} ${layout.format} ${layout.zoom} `)
    if (drawnRef.current && !partSwitch) {
      timer = window.setTimeout(engrave, RESIZE_SETTLE_MS)
    } else {
      // After the next paint when frames come (so the skeleton is on screen first); on a timer when they do not
      // (a background tab gets no frames).
      frame = window.requestAnimationFrame(() => { timer = window.setTimeout(engrave, 0) })
      timer = window.setTimeout(engrave, 120)
    }
    return () => {
      done = true
      if (frame !== undefined) window.cancelAnimationFrame(frame)
      window.clearTimeout(timer)
      pendingRef.current = false
    }
  }, [loaded, src, layout?.format, layout?.zoom, instrumentsKey, measure]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setAnchor(focus.bar) }, [focus.key, focus.bar])

  useLayoutEffect(() => { measure() }, [anchor, layout?.perView, layout?.pw, measure])

  const n = layout?.perView ?? 1
  const spreads = geo ? Math.max(1, Math.ceil(geo.pageCount / n)) : 1
  const spread = geo ? Math.max(0, Math.min(spreads - 1, Math.floor((geo.barPage.get(anchor) ?? 0) / n))) : 0

  // Follow a moving bar (practice playhead): turn when it leaves the spread.
  useEffect(() => {
    if (!geo || follow == null) return
    const p = geo.barPage.get(follow)
    if (p == null) return
    if (Math.floor(p / n) !== spread) setAnchor(follow)
  }, [follow, geo, n, spread])

  const view = useMemo<StageView | null>(() => {
    if (!geo) return null
    const pages = geo.pageBars.slice(spread * n, spread * n + n).filter(([a]) => Number.isFinite(a))
    if (!pages.length) return null
    return { first: pages[0][0], last: pages[pages.length - 1][1], spread, spreads, perView: n }
  }, [geo, spread, spreads, n])

  const onViewRef = useRef(onView)
  useLayoutEffect(() => { onViewRef.current = onView })
  useEffect(() => { if (view) onViewRef.current?.(view) }, [view])

  const turn = (d: number) => {
    if (!geo) return
    const next = Math.max(0, Math.min(spreads - 1, spread + d))
    if (next === spread) return
    const first = geo.pageBars[next * n]?.[0]
    if (Number.isFinite(first)) setAnchor(first)
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); turn(1) }
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); turn(-1) }
  }

  const barAt = (clientX: number, clientY: number): number | null => {
    if (!geo || !stageRef.current) return null
    const r = stageRef.current.getBoundingClientRect()
    const x = clientX - r.left
    const y = clientY - r.top
    for (const b of geo.bars.values()) {
      const pad = Math.max(10, b.h * 0.35)
      if (x >= b.x && x <= b.x + b.w && y >= b.y - pad && y <= b.y + b.h + pad) return b.bar
    }
    return null
  }

  // One pointer gesture, three outcomes: a tap selects a bar, a hold annotates it, a horizontal swipe turns the page.
  const gesture = useRef<{ x: number; y: number; t: number; hold?: number; done: boolean } | null>(null)
  const onPointerDown = (e: PointerEvent) => {
    if (e.button > 0 || (e.target as HTMLElement).closest('button, a, [role="dialog"]')) return
    const g = { x: e.clientX, y: e.clientY, t: performance.now(), done: false, hold: 0 }
    if (onBarHold) {
      g.hold = window.setTimeout(() => {
        const bar = barAt(e.clientX, e.clientY)
        if (bar != null && gesture.current === g && !g.done) { g.done = true; onBarHold(bar) }
      }, HOLD_MS)
    }
    gesture.current = g
  }
  const onPointerMove = (e: PointerEvent) => {
    const g = gesture.current
    if (!g || g.done) return
    if (Math.hypot(e.clientX - g.x, e.clientY - g.y) > 8) window.clearTimeout(g.hold)
  }
  const onPointerUp = (e: PointerEvent) => {
    const g = gesture.current
    gesture.current = null
    if (!g) return
    window.clearTimeout(g.hold)
    if (g.done) return
    const dx = e.clientX - g.x
    const dy = e.clientY - g.y
    const dt = performance.now() - g.t
    if (Math.abs(dx) >= SWIPE_PX && Math.abs(dy) < Math.abs(dx) * 0.6 && dt < 700) { turn(dx < 0 ? 1 : -1); return }
    if (Math.hypot(dx, dy) < 10 && onBarTap) {
      const bar = barAt(e.clientX, e.clientY)
      if (bar != null) onBarTap(bar)
    }
  }
  const onPointerCancel = () => { window.clearTimeout(gesture.current?.hold); gesture.current = null }

  // The host exists before the size is known so the score can start loading at once. It fades in once settled; while
  // a re-engrave is pending the old drawing dims under the skeleton rather than cutting to nothing.
  const hostStyle: CSSProperties = layout ? {
    left: layout.padX, top: layout.padY, width: layout.availW,
    '--pw': `${layout.pw}px`, '--gap': `${layout.gap}px`,
    opacity: settled ? 1 : geo ? 0.4 : 0, transition: 'opacity 200ms var(--ease)',
  } as CSSProperties : { left: 0, top: 0, width: '100%', opacity: 0 }
  const state = error ? 'error' : settled ? 'ready' : 'loading'

  return (
    <div
      className="stage" ref={stageRef} tabIndex={0} role="region" aria-label={label} onKeyDown={onKeyDown}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerCancel}
      onContextMenu={e => e.preventDefault()}
    >
      <div className="stage-under" aria-hidden="true">
        {settled && geo?.pages.map((p, i) => p && <div key={i} className="sheet" style={{ left: p.x, top: p.y, width: p.w, height: p.h }} />)}
        {settled && geo && underlay?.(geo)}
      </div>
      <div className="stage-host" style={hostStyle}>
        <div className="osmd" data-score-state={state}>
          <div key={src} ref={hostRef} />
          {error && <p role="alert">Could not render score: {error}</p>}
        </div>
      </div>
      <div className="stage-over">{settled && geo && overlay?.(geo)}</div>
      <Fade
        show={!!layout && !settled && !error} className="stage-skeleton" aria-label="Engraving score" role="status"
        style={layout ? { left: layout.padX, top: layout.padY, width: layout.availW, gap: layout.gap } : undefined}
      >
        {layout && Array.from({ length: layout.perView }, (_, i) => (
          <div key={i} className="skeleton-page" style={{ width: layout.pw, height: layout.ph }}>
            {Array.from({ length: 6 }, (_, j) => <span key={j} />)}
          </div>
        ))}
      </Fade>
      {view && (
        <>
          <button type="button" className="turn turn-prev" onClick={() => turn(-1)} disabled={spread === 0} aria-label="Previous pages">
            <IChevronLeft size={22} />
          </button>
          <button type="button" className="turn turn-next" onClick={() => turn(1)} disabled={spread >= spreads - 1} aria-label="Next pages">
            <IChevronRight size={22} />
          </button>
          <p className="stage-foot">
            <span>{n === 2 ? 'Pages' : 'Page'} {spread * n + 1}{n === 2 && spread * n + 2 <= (geo?.pageCount ?? 0) ? `–${spread * n + 2}` : ''} of {geo?.pageCount}</span>
            <span className="num">bars {view.first}–{view.last}</span>
          </p>
        </>
      )}
    </div>
  )
}
