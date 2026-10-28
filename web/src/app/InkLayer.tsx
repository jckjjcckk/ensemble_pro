import { useEffect, useRef, type PointerEvent as ReactPointerEvent } from 'react'
import { Pop } from './Sheet'
import type { Geo } from './geometry'
import { PEN_COLORS, hitsStroke, makeStroke, outlinePath, pageAt, pressureWidth, usePlaced, type PenColor, type Pt, type ScribbleRow, type Stroke } from './ink'
import { IEraser, IPen } from './MarkIcons'
import './Ink.css'

export type InkTool = 'pen' | 'eraser'

/** Pen width as a fraction of the page width (about 2 px on an iPad page), scaled by pressure. */
const PEN_W = 0.0034
const ERASER_R = 14
/** A stroke begun within this distance of the last one, this soon after it, is part of the same sign. */
const SIGN_PX = 40
const SIGN_MS = 6000

/**
 * Ink over the score. Always draws: everyone's strokes faintly, the reader's own at full ink. While `active` it
 * also takes the pointer over the whole stage (Pencil or finger, `touch-action: none` only then): the pen draws a
 * stroke, the eraser removes whole strokes it touches. Once a Pencil has drawn, a resting palm or finger does not.
 */
export function InkLayer({ geo, rows, uid, active, tool, color, onStroke, onErase, arriving }: {
  geo: Geo
  rows: ScribbleRow[]
  uid: string
  /** Strokes that just arrived from another stand: they fade in. */
  arriving?: ReadonlySet<string>
  active: boolean
  tool: InkTool
  color: PenColor
  onStroke: (page: number, s: Stroke) => void
  onErase: (ids: Set<string>) => void
}) {
  const placed = usePlaced(rows, uid, geo)
  const surface = useRef<HTMLDivElement>(null)
  const live = useRef<SVGPathElement>(null)
  const ring = useRef<SVGCircleElement>(null)
  const pen = useRef(false)
  /** The last stroke drawn: one begun right beside it, soon after, belongs to the same sign and the same bar. */
  const last = useRef<{ page: number; bar: number | null; box: [number, number, number, number]; t: number } | null>(null)
  const cur = useRef<{ id: number; type: string; page: number; widthPx: number; pts: [number, number, number][]; erase: boolean } | null>(null)

  useEffect(() => { if (!active) { cur.current = null; if (live.current) live.current.setAttribute('d', '') } }, [active])

  const local = (e: { clientX: number; clientY: number }) => {
    const r = surface.current!.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }
  const pressure = (e: PointerEvent) => (e.pointerType === 'pen' && e.pressure > 0 ? e.pressure : 0.5)

  const eraseAt = (x: number, y: number) => {
    const ids = new Set(placed.filter(s => s.mine && hitsStroke(s.pts, x, y, ERASER_R)).map(s => s.id))
    if (ids.size) onErase(ids)
    ring.current?.setAttribute('cx', String(x))
    ring.current?.setAttribute('cy', String(y))
  }

  const drawLive = () => {
    const c = cur.current
    if (!c || !live.current) return
    live.current.setAttribute('d', outlinePath(c.pts.map(([x, y, p]): Pt => [x, y, c.widthPx * pressureWidth(p)])))
  }

  const down = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation()
    if (e.button > 0) return
    if (e.pointerType === 'pen') pen.current = true
    else if (e.pointerType === 'touch' && pen.current) return // the palm under a Pencil
    if (cur.current) {
      // A second finger means a pinch or a page gesture, not a line: drop the stroke in progress.
      if (cur.current.type === 'touch' && e.pointerType === 'touch') { cur.current = null; live.current?.setAttribute('d', '') }
      return
    }
    const { x, y } = local(e)
    try { surface.current?.setPointerCapture(e.pointerId) } catch { /* a pointer the browser no longer tracks */ }
    if (tool === 'eraser') {
      cur.current = { id: e.pointerId, type: e.pointerType, page: -1, widthPx: 0, pts: [], erase: true }
      ring.current?.setAttribute('r', String(ERASER_R))
      eraseAt(x, y)
      return
    }
    const page = pageAt(geo, x, y)
    const pg = page != null ? geo.pages[page] : null
    if (page == null || !pg) return
    cur.current = { id: e.pointerId, type: e.pointerType, page, widthPx: PEN_W * pg.w, pts: [[x, y, pressure(e.nativeEvent)]], erase: false }
    drawLive()
  }

  const move = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation()
    const c = cur.current
    if (!c || e.pointerId !== c.id) return
    const evs = e.nativeEvent.getCoalescedEvents?.() ?? []
    for (const ev of evs.length ? evs : [e.nativeEvent]) {
      const { x, y } = local(ev)
      if (c.erase) eraseAt(x, y)
      else c.pts.push([x, y, pressure(ev)])
    }
    if (!c.erase) drawLive()
  }

  const up = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation()
    const c = cur.current
    if (!c || e.pointerId !== c.id) return
    cur.current = null
    ring.current?.setAttribute('r', '0')
    if (c.erase) return
    const [sx, sy] = c.pts[0]
    const l = last.current
    const near = l && l.page === c.page && performance.now() - l.t < SIGN_MS &&
      sx >= l.box[0] - SIGN_PX && sx <= l.box[2] + SIGN_PX && sy >= l.box[1] - SIGN_PX && sy <= l.box[3] + SIGN_PX
    const s = makeStroke(c.pts, c.page, geo, color, c.widthPx, near ? l.bar : null)
    live.current?.setAttribute('d', '')
    if (!s) return
    const xs = c.pts.map(q => q[0]), ys = c.pts.map(q => q[1])
    last.current = { page: c.page, bar: s.bar, box: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)], t: performance.now() }
    onStroke(c.page + 1, s)
  }

  const cancel = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation()
    if (cur.current?.id !== e.pointerId) return
    cur.current = null
    live.current?.setAttribute('d', '')
    ring.current?.setAttribute('r', '0')
  }

  return (
    <>
      <svg className={`ink-svg ${active ? 'is-active' : ''}`} aria-hidden="true">
        {placed.filter(s => !s.mine).map(s => <path key={s.id} className={`ink-path is-${s.color} is-faint${arriving?.has(s.id) ? ' is-arriving' : ''}`} d={s.d} />)}
        {placed.filter(s => s.mine).map(s => <path key={s.id} className={`ink-path is-${s.color}`} d={s.d} />)}
        <path ref={live} className={`ink-path is-${color}`} />
        <circle ref={ring} className="ink-ring" r={0} />
      </svg>
      {active && (
        <div
          ref={surface} className={`ink-surface is-${tool}`} aria-hidden="true"
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={cancel} onLostPointerCapture={cancel}
          onContextMenu={e => e.preventDefault()}
        />
      )}
    </>
  )
}

const colorName: Record<PenColor, string> = { ink: 'Ink', red: 'Red', blue: 'Blue' }

/** The scribble tools, floating at the foot of the stage: pen, eraser, three colours, Done. */
export function InkBar({ open, tool, color, status, onTool, onColor, onDone }: {
  open: boolean
  tool: InkTool
  color: PenColor
  /** Saving state of the reader's ink; `local` when this score does not sync. */
  status: 'idle' | 'saving' | 'saved' | 'error' | 'local'
  onTool: (t: InkTool) => void
  onColor: (c: PenColor) => void
  onDone: () => void
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onDone() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onDone])
  const said = status === 'saving' ? 'Saving' : status === 'saved' ? 'Saved' : status === 'error' ? 'Not saved, retrying' : status === 'local' ? 'This device only' : ''
  return (
    <Pop open={open} className="inkbar" role="toolbar" aria-label="Scribble" origin="50% 100%">
      <div className="inkbar-seg" role="radiogroup" aria-label="Tool">
        <button type="button" role="radio" aria-checked={tool === 'pen'} className="inkbar-btn" onClick={() => onTool('pen')} aria-label="Pen"><IPen size={22} /></button>
        <button type="button" role="radio" aria-checked={tool === 'eraser'} className="inkbar-btn" onClick={() => onTool('eraser')} aria-label="Eraser"><IEraser size={22} /></button>
      </div>
      <div className="inkbar-seg" role="radiogroup" aria-label="Colour">
        {PEN_COLORS.map(c => (
          <button key={c} type="button" role="radio" aria-checked={color === c && tool === 'pen'} className="inkbar-btn" aria-label={colorName[c]}
            onClick={() => { onColor(c); onTool('pen') }}>
            <span className={`inkbar-swatch is-${c}`} />
          </button>
        ))}
      </div>
      <span className={`inkbar-status ${status === 'error' ? 'is-error' : ''}`} aria-live="polite">{said}</span>
      <button type="button" className="dbtn is-primary inkbar-done" onClick={onDone}>Done</button>
    </Pop>
  )
}
