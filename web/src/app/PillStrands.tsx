/** Inside the voice button (VoiceNotes.tsx), one flow in one glass. Idle: six strands flow quietly. Listening: they
 *  gather into one string that swings wider with the voice. Working: the fibres let go and run together into moving
 *  shades of blue. Placed: the blue settles solid, then gathers back into strands. Everything breathes on one slow
 *  breath, about seven seconds. Reasoning: DESIGN.md, Motion. Canvas 2D on the fibres' shared clock. */
import { useEffect, useRef, type RefObject } from 'react'
import { enrol, onDark } from './fibres'

export type PillState = 'idle' | 'listening' | 'working' | 'placed'

const TAU = Math.PI * 2
const SOLID = '#0166E2'
const PALETTE = ['#017AF3', '#0175EE', '#0170EA', '#0166E2', '#015FDF', '#0155DE'] // CK's swatches
// The swatches are too close to read as shades once they fill the glass, so the cloud reaches darker and lighter.
const CLOUD = ['#0142B8', '#017AF3', '#0155DE', '#2E93FA', '#0170EA', '#0138A6', '#4BA3FB']

const seeded = (i: number, k: number) => { const s = Math.sin((i + 1) * 12.9898 + k * 78.233) * 43758.5453; return s - Math.floor(s) }
const STRANDS = PALETTE.map((color, i) => ({
  color, rest: (i - (PALETTE.length - 1) / 2) / PALETTE.length, f1: .7 + seeded(i, 1) * .6, f2: 1.6 + seeded(i, 2) * 1.2,
  w1: .55 + seeded(i, 4) * .5, w2: .9 + seeded(i, 5) * .7, p: seeded(i, 7) * TAU, twist: .8 + seeded(i, 8) * .8,
  v1: seeded(i, 9) * TAU, v2: seeded(i, 10) * TAU, v3: seeded(i, 11) * TAU,
}))
const BLOBS = CLOUD.map((color, i) => ({
  color, a: seeded(i + 2, 21) * TAU, b: seeded(i + 2, 22) * TAU, sa: .35 + seeded(i + 2, 23) * .5, sb: .45 + seeded(i + 2, 24) * .6, size: .55 + seeded(i + 2, 25) * .5,
}))

const smooth = (a: number, b: number, x: number) => { const u = Math.min(1, Math.max(0, (x - a) / (b - a))); return u * u * (3 - 2 * u) }
const ease = (x: number, target: number, k: number, dt: number) => x + (target - x) * (1 - Math.exp(-k * dt))

export function PillStrands({ state, level, reduced, paused, words }: {
  state: PillState
  /** The voice level, 0..1, written by the recorder about 20 times a second. */
  level: RefObject<number>
  reduced: boolean
  /** Out of sight (the tray is open over it): nothing to draw. */
  paused: boolean
  /** The button's words: they wait until the surface they belong on has arrived. */
  words: RefObject<HTMLElement | null>
}) {
  const host = useRef<HTMLSpanElement>(null)
  const live = useRef({ state, reduced, paused })
  useEffect(() => { live.current = { state, reduced, paused } })

  useEffect(() => {
    const el = host.current!
    const [fill, glow, core] = Array.from(el.children) as HTMLCanvasElement[]
    const fx = fill.getContext('2d')!, gx = glow.getContext('2d')!, cx = core.getContext('2d')!
    const dpr = Math.min(2, devicePixelRatio || 1)
    let w = 0, h = 0
    const fit = () => {
      w = el.offsetWidth; h = el.offsetHeight
      core.width = w * dpr; core.height = h * dpr; cx.setTransform(dpr, 0, 0, dpr, 0, 0)
      fill.width = w; fill.height = h
      glow.width = w / 2; glow.height = h / 2; gx.setTransform(.5, 0, 0, .5, 0, 0)
    }
    let hold = 0, lv = 0, diss = 0, solid = 0, T = 8, V = 0, B = 8
    let then = performance.now()

    const paint = () => {
      const now = performance.now(), dt = Math.min(.5, (now - then) / 1000)
      then = now
      const { state, reduced, paused } = live.current
      if (paused || !w) return
      const blue = state === 'working' || state === 'placed', holding = state === 'listening'
      const target = holding ? level.current : 0
      if (reduced) {
        // One still frame for each moment: no travel, no breath.
        hold = holding ? 1 : 0; diss = blue ? 1 : 0; solid = state === 'placed' ? 1 : 0; lv = target
      } else {
        hold = ease(hold, holding ? 1 : 0, holding ? 5 : 3, dt)
        diss = ease(diss, blue ? 1 : 0, blue ? 1 : 1.2, dt)                 // ink through water going out, gathering coming back
        solid = ease(solid, state === 'placed' ? 1 : 0, state === 'placed' ? 2.5 : 1.5, dt)
        lv = ease(lv, target, target > lv ? 4 : 1.5, dt)                    // a swell, not a meter: it must not bounce on every syllable
        T += dt * (.2 + .16 * hold - .08 * diss)
        V += dt * 4.5
        B += dt * .3
      }
      const breath = reduced ? .5 : .5 + .5 * Math.sin(B * 3)
      const box = words.current
      if (box) box.style.opacity = String(state === 'placed' ? 1 : blue ? smooth(.45, .65, diss) : 1 - smooth(.35, .55, diss))

      // The cloud: a blue that rises behind the strands as they let go.
      const cover = smooth(.3, .95, diss)
      fx.clearRect(0, 0, w, h)
      if (cover > .002) {
        fx.globalAlpha = cover * (.92 + .08 * solid); fx.fillStyle = SOLID; fx.fillRect(0, 0, w, h)
        if (solid < .995) for (const b of BLOBS) {
          const x = w * (.5 + .52 * Math.sin(B * b.sa + b.a)), y = h * (.5 + .62 * Math.cos(B * b.sb + b.b)), r = Math.max(h * 1.1, w * .34) * b.size
          const g = fx.createRadialGradient(x, y, 0, x, y, r)
          g.addColorStop(0, b.color); g.addColorStop(1, `${b.color}00`)
          fx.globalAlpha = cover * (1 - solid) * (.68 + .32 * breath); fx.fillStyle = g; fx.fillRect(0, 0, w, h)
        }
      }

      // The strands.
      const dark = onDark(el)
      const heard = hold * (.45 + .55 * lv), n = Math.round(w / 4)
      const amp = h * (.1 + .02 * hold) * (.82 + .36 * breath)
      const spread = h * (.66 - .46 * hold + .5 * diss)                     // apart at rest, one string while held, apart again letting go
      const swing = h * hold * (.02 + .44 * lv)
      const fade = Math.pow(1 - diss, 2.4), glowFade = 1 - smooth(.6, 1, diss)
      gx.clearRect(0, 0, w, h); cx.clearRect(0, 0, w, h)
      if (glowFade > .004) for (const s of STRANDS) {
        const line = (c: CanvasRenderingContext2D, k: number) => {
          c.beginPath()
          for (let i = 0; i <= n; i++) {
            const x = i / n
            const flow = Math.sin(TAU * s.f1 * x + s.w1 * T + s.p) * .6 + Math.sin(TAU * s.f2 * x - s.w2 * T + s.p * 1.7) * .3
            const twist = k * (h * .05 + h * .36 * diss) * Math.sin(TAU * s.twist * x + T * 1.3 + s.p)
            // A held string: its first three modes, the higher ones coming in as the voice gets louder.
            const modes = Math.sin(Math.PI * x) * Math.sin(V + s.v1) * .62 + Math.sin(TAU * x) * Math.sin(V * 1.73 + s.v2) * .3 + Math.sin(3 * Math.PI * x) * Math.sin(V * 2.41 + s.v3) * .2 * lv
            const y = h / 2 + Math.pow(Math.sin(Math.PI * x), .85) * (s.rest * spread + amp * flow + twist) + swing * modes
            if (i) c.lineTo(x * w, y); else c.moveTo(x * w, y)
          }
        }
        gx.strokeStyle = cx.strokeStyle = s.color; gx.lineCap = cx.lineCap = 'round'
        gx.globalAlpha = .2 * (1 + 2.6 * heard + 2.6 * diss) * glowFade * (.75 + .5 * breath)
        gx.lineWidth = h * (.05 + .1 * heard + .85 * diss * diss)           // the glow fattens until the strands run into each other
        line(gx, 0); gx.stroke()
        if (fade > .004) for (const k of [-1, 0, 1]) {
          cx.globalAlpha = Math.min(1, (k ? .3 : .6) * (1 + 1.1 * heard + .35 * hold) * (dark ? 1.25 : 1)) * fade
          cx.lineWidth = k ? .75 + .35 * heard : 1 + heard
          line(cx, k); cx.stroke()
        }
      }
    }
    fit()
    const ro = new ResizeObserver(fit); ro.observe(el)
    const leave = enrol(el, paint)
    return () => { ro.disconnect(); leave() }
  }, [level, words])

  return <span ref={host} className="v-strands" aria-hidden="true"><canvas /><canvas className="v-strands-glow" /><canvas /></span>
}
