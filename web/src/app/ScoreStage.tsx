import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import type { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'
import { ScoreView } from '../mock'
import { measureGeo, readModel, type Geo } from './geometry'
import { IChevronLeft, IChevronRight } from './icons'

/** Page shapes the stage may ask OSMD for. Few buckets, so a small resize re-renders instead of reloading. */
const ASPECTS = [0.72, 0.82, 0.94, 1.06, 1.2, 1.414]

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

export function ScoreStage({ src, instruments, scale, focus, follow, underlay, overlay, onBarTap, onBarHold, onView, margin, label }: Props) {
  const stageRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const osmdRef = useRef<OpenSheetMusicDisplay | null>(null)
  const awaitingRef = useRef(false)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const [geo, setGeo] = useState<Geo | null>(null)
  const [settled, setSettled] = useState(false)
  const [anchor, setAnchor] = useState(focus.bar)
  const anchorRef = useRef(anchor)
  const instrumentsKey = JSON.stringify(instruments)
  const instrumentsRef = useRef(instruments)

  useLayoutEffect(() => {
    const el = stageRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize(s => (s && Math.abs(s.w - width) < 2 && Math.abs(s.h - height) < 2 ? s : { w: Math.round(width), h: Math.round(height) }))
    })
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

  const measure = useCallback(() => {
    const host = hostRef.current
    const stage = stageRef.current
    const osmd = osmdRef.current
    const container = host?.querySelector<HTMLElement>('.osmd > div')
    if (!stage || !container) return
    const pageEls = Array.from(container.children) as HTMLElement[]
    const n = perViewRef.current
    let spread = 0
    if (osmd && !awaitingRef.current) {
      const model = readModel(osmd)
      spread = Math.floor((model.barPage.get(anchorRef.current) ?? 0) / n)
      spread = Math.max(0, Math.min(spread, Math.ceil(model.pageCount / n) - 1))
    }
    pageEls.forEach((el, i) => { el.style.display = i >= spread * n && i < spread * n + n ? '' : 'none' })
    if (!osmd || awaitingRef.current) return
    setGeo(measureGeo(osmd, stage, pageEls))
    setSettled(true)
  }, [])

  const applyInstruments = useCallback((osmd: OpenSheetMusicDisplay): boolean => {
    const want = instrumentsRef.current
    let changed = false
    osmd.Sheet.Instruments.forEach((ins, i) => {
      const v = want === null || want.includes(i)
      if (ins.Visible !== v) { ins.Visible = v; changed = true }
    })
    return changed
  }, [])

  const onReady = useCallback((osmd: OpenSheetMusicDisplay) => {
    osmdRef.current = osmd
    // Every render, including OSMD's own resize renders, re-measures synchronously before paint.
    const render = osmd.render.bind(osmd)
    osmd.render = () => {
      if (osmdRef.current !== osmd) return
      render()
      awaitingRef.current = false
      measure()
    }
    if (applyInstruments(osmd)) {
      // ScoreView re-renders once more after load (its zoom effect); measure then. Fallback if it does not.
      awaitingRef.current = true
      setSettled(false)
      window.setTimeout(() => { if (awaitingRef.current && osmdRef.current === osmd) osmd.render() }, 700)
    } else {
      measure()
    }
  }, [applyInstruments, measure])

  // Part switch on a live instance.
  useEffect(() => {
    const osmd = osmdRef.current
    if (!osmd || !osmd.GraphicSheet) return
    if (applyInstruments(osmd)) osmd.render()
  }, [instrumentsKey, applyInstruments])

  // A new page format reloads the score: hide until it settles again.
  useEffect(() => { osmdRef.current = null; setSettled(false); setGeo(null) }, [layout?.format, src])

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

  const hostStyle = layout ? ({
    left: layout.padX, top: layout.padY, width: layout.availW,
    '--pw': `${layout.pw}px`, '--gap': `${layout.gap}px`,
    visibility: settled ? 'visible' : 'hidden',
  } as CSSProperties) : undefined

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
      {layout && (
        <div className="stage-host" ref={hostRef} style={hostStyle}>
          <ScoreView src={src} zoom={layout.zoom} pageFormat={layout.format} onReady={onReady} className="osmd" />
        </div>
      )}
      <div className="stage-over">{settled && geo && overlay?.(geo)}</div>
      {layout && !settled && (
        <div className="stage-skeleton" style={{ left: layout.padX, top: layout.padY, width: layout.availW, gap: layout.gap }} aria-label="Engraving score" role="status">
          {Array.from({ length: layout.perView }, (_, i) => (
            <div key={i} className="skeleton-page" style={{ width: layout.pw, height: layout.ph }}>
              {Array.from({ length: 6 }, (_, j) => <span key={j} />)}
            </div>
          ))}
        </div>
      )}
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
