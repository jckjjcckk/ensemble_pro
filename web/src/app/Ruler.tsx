import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { TroubleSpot } from '../mock'
import type { Span } from './store'

export interface RulerMark { id: string; bar: number; kind: 'voice' | 'mark'; label: string }
export interface RulerPresence { bar: number; label: string }

interface Props {
  total: number
  /** The bracket. loop and range: both ends draggable and the body moves; view: the body moves; none: drawn only. */
  span?: Span | null
  mode?: 'loop' | 'range' | 'view' | 'none'
  /** loop/range: called live while dragging. view: called on release. */
  onSpan?: (s: Span) => void
  heat?: TroubleSpot[]
  onHeat?: (t: TroubleSpot) => void
  cuts?: Span[]
  marks?: RulerMark[]
  onMark?: (id: string) => void
  presence?: RulerPresence[]
  /** Fractional bar position of the playhead. */
  playhead?: number | null
  /** Listening state colours the playhead: green following, amber lost. */
  playTone?: 'following' | 'lost' | 'off'
  onSeek?: (bar: number) => void
  compact?: boolean
  readOnly?: boolean
  label: string
  spanLabel?: string
  /** What bar k (1-based along the ruler) is called, when the book's numbers are not 1..total (a pickup bar 0). */
  labelOf?: (k: number) => string | number
}

type Drag =
  | { kind: 'from' | 'to'; startX: number; moved: boolean }
  | { kind: 'move'; startX: number; start: Span; moved: boolean }
  | { kind: 'seek'; startX: number; moved: boolean }
  | { kind: 'heat'; startX: number; moved: boolean; spot: TroubleSpot }
  | { kind: 'mark'; startX: number; moved: boolean; id: string }

const PAD = 18
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v))

export function Ruler({
  total, span = null, mode = 'none', onSpan, heat = [], onHeat, cuts = [], marks = [], onMark,
  presence = [], playhead = null, playTone = 'off', onSeek, compact = false, readOnly = false, label, spanLabel = 'Loop',
  labelOf = k => k,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(0)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [preview, setPreview] = useState<Span | null>(null)
  const hatchId = useId().replace(/:/g, '')

  useLayoutEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const H = compact ? 60 : 72
  const yTop = 18
  const yBase = compact ? 40 : 46
  const yHeat = yBase + 4
  const heatH = compact ? 7 : 9
  const yScale = H - 5
  const x0 = PAD
  const x1 = Math.max(PAD + 1, w - PAD)
  const bx = (k: number) => x0 + (k / total) * (x1 - x0)
  const kAt = (x: number) => Math.round(((x - x0) / (x1 - x0)) * total)
  const barAt = (x: number) => clamp(Math.floor(((x - x0) / (x1 - x0)) * total) + 1, 1, total)

  const shown = preview ?? span
  const editable = !readOnly && (mode === 'loop' || mode === 'range')

  const local = (e: PointerEvent) => {
    const r = wrapRef.current!.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (readOnly || e.button > 0) return
    const { x, y } = local(e)
    let d: Drag | null = null
    if (span && mode !== 'none') {
      const xl = bx(span.from - 1)
      const xr = bx(span.to)
      const inner = Math.min(14, (xr - xl) / 2)
      if (editable && x >= xl - 30 && x <= xl + inner) d = { kind: 'from', startX: x, moved: false }
      else if (editable && x >= xr - inner && x <= xr + 30) d = { kind: 'to', startX: x, moved: false }
      else if (x > xl && x < xr && (mode === 'view' || y <= yBase + 2)) d = { kind: 'move', startX: x, start: span, moved: false }
    }
    if (!d && y > yBase + 1 && heat.length) {
      const spot = heat.find(t => x >= bx(t.barFrom - 1) - 4 && x <= bx(t.barTo) + 4)
      if (spot) d = { kind: 'heat', startX: x, moved: false, spot }
    }
    if (!d && y > yBase + 1 && marks.length) {
      let best: RulerMark | null = null
      let dist = 12
      for (const m of marks) {
        const dx = Math.abs(bx(m.bar - 0.5) - x)
        if (dx < dist) { best = m; dist = dx }
      }
      if (best) d = { kind: 'mark', startX: x, moved: false, id: best.id }
    }
    if (!d) d = { kind: 'seek', startX: x, moved: false }
    e.currentTarget.setPointerCapture(e.pointerId)
    setDrag(d)
  }

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag || !span && drag.kind !== 'seek') return
    const { x } = local(e)
    const moved = drag.moved || Math.abs(x - drag.startX) > 4
    if (moved !== drag.moved) setDrag({ ...drag, moved })
    if (!moved) return
    if (drag.kind === 'from' && span) onSpan?.({ from: clamp(kAt(x) + 1, 1, span.to), to: span.to })
    if (drag.kind === 'to' && span) onSpan?.({ from: span.from, to: clamp(kAt(x), span.from, total) })
    if (drag.kind === 'move') {
      const len = drag.start.to - drag.start.from
      const delta = Math.round(((x - drag.startX) / (x1 - x0)) * total)
      const from = clamp(drag.start.from + delta, 1, total - len)
      const next = { from, to: from + len }
      if (mode === 'view') setPreview(next)
      else onSpan?.(next)
    }
  }

  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag) return
    const { x } = local(e)
    if (drag.kind === 'move' && mode === 'view' && preview) onSpan?.(preview)
    if (drag.kind === 'seek') onSeek?.(barAt(x))
    if (drag.kind === 'heat' && !drag.moved) onHeat?.(drag.spot)
    if (drag.kind === 'mark' && !drag.moved) onMark?.(drag.id)
    setDrag(null)
    setPreview(null)
  }

  const keyStep = (e: KeyboardEvent, edge: 'from' | 'to' | 'move') => {
    if (!span) return
    const step = e.shiftKey || e.key === 'PageUp' || e.key === 'PageDown' ? 10 : 1
    let d = 0
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown' || e.key === 'PageDown') d = -step
    else if (e.key === 'ArrowRight' || e.key === 'ArrowUp' || e.key === 'PageUp') d = step
    else if (e.key !== 'Home' && e.key !== 'End') return
    e.preventDefault()
    const len = span.to - span.from
    if (edge === 'from') {
      const v = e.key === 'Home' ? 1 : e.key === 'End' ? span.to : clamp(span.from + d, 1, span.to)
      onSpan?.({ from: v, to: span.to })
    } else if (edge === 'to') {
      const v = e.key === 'Home' ? span.from : e.key === 'End' ? total : clamp(span.to + d, span.from, total)
      onSpan?.({ from: span.from, to: v })
    } else {
      // The view bracket steps a whole screen at a time, like a page turn.
      const from = e.key === 'Home' ? 1 : e.key === 'End' ? total - len : clamp(span.from + Math.sign(d) * (len + 1), 1, total - len)
      onSpan?.({ from, to: from + len })
    }
  }

  const scaleMarks = [1, ...Array.from({ length: Math.floor(total / 50) }, (_, i) => (i + 1) * 50)]
  const lastLabel = scaleMarks[scaleMarks.length - 1]
  if (total - lastLabel > 14) scaleMarks.push(total)

  const presenceBars = [...new Set(presence.map(p => p.bar))]
  const active = drag && (drag.kind === 'from' || drag.kind === 'to' || drag.kind === 'move') && drag.moved

  return (
    <div
      ref={wrapRef}
      className={`ruler ${compact ? 'is-compact' : ''} ${readOnly ? 'is-static' : ''} ${active ? 'is-dragging' : ''}`}
      style={{ height: H }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => { setDrag(null); setPreview(null) }}
      role="group"
      aria-label={label}
    >
      {w > 0 && (
        <svg width={w} height={H} aria-hidden="true">
          <defs>
            <pattern id={hatchId} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="5" className="r-hatch" />
            </pattern>
          </defs>

          {heat.map(t => (
            <rect
              key={`${t.barFrom}`} className="r-heat"
              x={bx(t.barFrom - 1)} y={yHeat} width={Math.max(3, bx(t.barTo) - bx(t.barFrom - 1))} height={heatH} rx={1.5}
              style={{ opacity: 0.22 + t.severity * 0.6 }}
            />
          ))}

          {cuts.map(c => (
            <g key={`${c.from}-${c.to}`}>
              <rect x={bx(c.from - 1)} y={yTop + 6} width={bx(c.to) - bx(c.from - 1)} height={yBase - yTop - 6} fill={`url(#${hatchId})`} />
              <line x1={bx(c.from - 1)} x2={bx(c.from - 1)} y1={yTop + 6} y2={yBase} className="r-cut-edge" />
              <line x1={bx(c.to)} x2={bx(c.to)} y1={yTop + 6} y2={yBase} className="r-cut-edge" />
            </g>
          ))}

          <line x1={x0} x2={x1} y1={yBase} y2={yBase} className="r-base" />
          {Array.from({ length: Math.floor(total / 10) }, (_, i) => (i + 1) * 10).map(k => (
            <line key={k} x1={bx(k)} x2={bx(k)} y1={yBase - (k % 50 === 0 ? 9 : 4)} y2={yBase} className="r-tick" />
          ))}
          {scaleMarks.map(b => (
            <text key={b} x={bx(b - 1)} y={yScale} className="r-scale" textAnchor={b === 1 ? 'start' : b === total ? 'end' : 'middle'}>{labelOf(b)}</text>
          ))}

          {presenceBars.map(b => (
            <line key={`p${b}`} x1={bx(b - 0.5)} x2={bx(b - 0.5)} y1={yTop + 8} y2={yBase - 1} className="r-presence">
              <title>{presence.filter(p => p.bar === b).map(p => p.label).join(', ')}, bar {b}</title>
            </line>
          ))}

          {marks.map(m => m.kind === 'voice'
            ? <circle key={m.id} cx={bx(m.bar - 0.5)} cy={yHeat + heatH / 2} r={3.2} className="r-mark-voice" />
            : <rect key={m.id} x={bx(m.bar - 0.5) - 1} y={yHeat} width={2} height={heatH} className="r-mark" />)}

          {shown && mode !== 'none' && (() => {
            const xl = bx(shown.from - 1)
            const xr = bx(shown.to)
            const mid = clamp((xl + xr) / 2, x0 + 26, x1 - 26)
            return (
              <g className={`r-span ${mode === 'view' ? 'is-view' : ''}`}>
                <rect x={xl} y={yTop} width={Math.max(2, xr - xl)} height={yBase - yTop} className="r-span-fill" />
                <path d={`M${xl} ${yBase} V${yTop} H${xr} V${yBase}`} className="r-span-line" />
                {editable && <>
                  <rect x={xl - 3} y={yTop + 6} width={6} height={yBase - yTop - 12} rx={2} className="r-knob" />
                  <rect x={xr - 3} y={yTop + 6} width={6} height={yBase - yTop - 12} rx={2} className="r-knob" />
                </>}
                <text x={mid} y={yTop - 6} textAnchor="middle" className="r-span-label">
                  {shown.from === shown.to ? labelOf(shown.from) : `${labelOf(shown.from)}–${labelOf(shown.to)}`}
                  {active && <tspan className="r-span-count"> · {shown.to - shown.from + 1} bars</tspan>}
                </text>
              </g>
            )
          })()}

          {playhead != null && (
            <g className={`r-play is-${playTone}`} transform={`translate(${bx(playhead - 1)} 0)`}>
              <line x1={0} x2={0} y1={yTop - 2} y2={yHeat + heatH + 2} />
              <path d={`M-4 ${yTop - 6} H4 L0 ${yTop - 1} Z`} />
            </g>
          )}
        </svg>
      )}

      {span && editable && w > 0 && (
        <>
          <div
            className="r-handle" role="slider" tabIndex={0}
            aria-label={`${spanLabel} start bar`} aria-valuemin={1} aria-valuemax={span.to} aria-valuenow={span.from}
            style={{ left: bx(span.from - 1) - 22, top: 0, height: yBase + 2 }}
            onKeyDown={e => keyStep(e, 'from')}
          />
          <div
            className="r-handle" role="slider" tabIndex={0}
            aria-label={`${spanLabel} end bar`} aria-valuemin={span.from} aria-valuemax={total} aria-valuenow={span.to}
            style={{ left: bx(span.to) - 22, top: 0, height: yBase + 2 }}
            onKeyDown={e => keyStep(e, 'to')}
          />
        </>
      )}
      {span && mode === 'view' && !readOnly && w > 0 && (
        <div
          className="r-handle is-wide" role="slider" tabIndex={0}
          aria-label="Bars on screen" aria-valuemin={1} aria-valuemax={total} aria-valuenow={span.from}
          aria-valuetext={`Bars ${span.from} to ${span.to}`}
          style={{ left: bx(span.from - 1), width: Math.max(44, bx(span.to) - bx(span.from - 1)), top: 0, height: yBase + 2 }}
          onKeyDown={e => keyStep(e, 'move')}
        />
      )}
    </div>
  )
}
