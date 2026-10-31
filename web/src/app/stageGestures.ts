/** One pointer gesture on a stage, two outcomes: a tap on a bar opens its quick menu, a hold (500 ms without moving)
 *  opens the composer on it. Shared by the OSMD stage (`ScoreStage`) and the engraved page stage (`EngravedStage`), so
 *  both readers feel the same under the finger. While scribbling the ink surface takes the pointer and none fire.
 *
 *  Turning the page is not here: the stage's spread is a `motion` drag on x (CK, 2026-10-28: standard components, no
 *  invented touch logic). Motion tracks the finger and its velocity; `turnFromDrag` only reads its result on release. */
import { useRef, type PointerEvent, type RefObject } from 'react'
import type { PanInfo } from 'motion/react'
import { barAtPoint, type Geo } from './geometry'

const HOLD_MS = 500
/** A flick: released faster than this (px/s) turns whatever the distance. */
const FLICK_V = 400

/** On release of a horizontal drag of the spread: a flick turns towards it; a slow drag turns once past half the
 *  stage, else the spread settles back. −1 previous, +1 next, 0 stay. */
export function turnFromDrag(info: PanInfo, width: number): -1 | 0 | 1 {
  const { velocity: { x: v }, offset: { x: o } } = info
  if (v < -FLICK_V || (Math.abs(v) <= FLICK_V && o < -width / 2)) return 1
  if (v > FLICK_V || (Math.abs(v) <= FLICK_V && o > width / 2)) return -1
  return 0
}

interface Args {
  geo: Geo | null
  stageRef: RefObject<HTMLElement | null>
  onBarTap?: (bar: number) => void
  onEmptyTap?: () => void
  onBarHold?: (bar: number) => void
}

export function useStageGestures({ geo, stageRef, onBarTap, onEmptyTap, onBarHold }: Args) {
  const barAt = (clientX: number, clientY: number): number | null => {
    if (!geo || !stageRef.current) return null
    const r = stageRef.current.getBoundingClientRect()
    return barAtPoint(geo.bars.values(), clientX - r.left, clientY - r.top)
  }

  const gesture = useRef<{ x: number; y: number; hold?: number; done: boolean } | null>(null)
  const onPointerDown = (e: PointerEvent) => {
    if (e.button > 0 || (e.target as HTMLElement).closest('button, a, [role="dialog"]')) return
    const g = { x: e.clientX, y: e.clientY, done: false, hold: 0 }
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
    if (Math.hypot(e.clientX - g.x, e.clientY - g.y) < 10) {
      const bar = barAt(e.clientX, e.clientY)
      if (bar != null) onBarTap?.(bar)
      else onEmptyTap?.()
    }
  }
  const onPointerCancel = () => { window.clearTimeout(gesture.current?.hold); gesture.current = null }
  return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel, barAt }
}
