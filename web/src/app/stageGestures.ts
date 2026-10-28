/** One pointer gesture on a stage, three outcomes: a tap on a bar opens its quick menu, a hold (500 ms without moving)
 *  opens the composer on it, a horizontal swipe turns the page. Shared by the OSMD stage (`ScoreStage`) and the engraved
 *  page stage (`EngravedStage`), so both readers feel the same under the finger. While scribbling the ink surface takes
 *  the pointer and none of these fire. */
import { useRef, type PointerEvent, type RefObject } from 'react'
import type { Geo } from './geometry'

const HOLD_MS = 500
const SWIPE_PX = 56

interface Args {
  geo: Geo | null
  stageRef: RefObject<HTMLElement | null>
  /** Turn the spread by d (−1 or +1). */
  turn: (d: number) => void
  onBarTap?: (bar: number) => void
  onEmptyTap?: () => void
  onBarHold?: (bar: number) => void
}

export function useStageGestures({ geo, stageRef, turn, onBarTap, onEmptyTap, onBarHold }: Args) {
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
    if (Math.hypot(dx, dy) < 10) {
      const bar = barAt(e.clientX, e.clientY)
      if (bar != null) onBarTap?.(bar)
      else onEmptyTap?.()
    }
  }
  const onPointerCancel = () => { window.clearTimeout(gesture.current?.hold); gesture.current = null }
  return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel, barAt }
}
