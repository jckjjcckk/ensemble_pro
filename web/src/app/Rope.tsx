/** A book's state drawn on its own edge: a rope of fine fibres round the card, row or panel (the parent, which must be
 *  positioned; it takes its corners from the parent's border-radius). Blue with a light running round it: an agent is
 *  working on this book. Yellow or red, flowing and breathing with no light: the librarian is waiting for an answer, or
 *  the run failed. `WorkLoop` is the same idea for a line of text with no card to wrap. Mock and reasoning:
 *  DESIGN.md, Motion. Canvas 2D, 30 frames a second, off-screen ropes not drawn; reduced motion draws one still frame. */
import { useEffect, useRef } from 'react'
import { enrol, onDark } from './fibres'

export type RopeState = 'working' | 'asking' | 'failed'

const BLUE = ['#0175EE', '#0166E2', '#0155DE'] // CK's swatches
const HEAD = '#0166E2'
const YELLOW = ['#E6B53A', '#D8A62B', '#C2911D']
const RED = { light: ['#C94A3E', '#B5392E', '#9C2C22'], dark: ['#E0675A', '#D5574A', '#C94A3E'] } // the dark card takes a lighter red
const TAU = Math.PI * 2
const PAD = 12 // room outside the edge for the glow

function setUp(c: CanvasRenderingContext2D, dpr: number, w: number, h: number, dark: boolean) {
  c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h)
  c.lineCap = c.lineJoin = 'round'
  c.globalCompositeOperation = dark ? 'lighter' : 'source-over'
}

export function Rope({ state }: { state: RopeState }) {
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const host = ref.current!, card = host.parentElement!
    const [glow, core] = Array.from(host.children) as HTMLCanvasElement[]
    const gx = glow.getContext('2d')!, cx = core.getContext('2d')!
    const dpr = Math.min(2, devicePixelRatio || 1)
    let w = 0, h = 0, r = 0, P = 0
    const fit = () => {
      // offset sizes: unaffected by the press and lift transforms on a card.
      w = card.offsetWidth; h = card.offsetHeight
      r = Math.min(parseFloat(getComputedStyle(card).borderTopLeftRadius) || 0, w / 2, h / 2)
      P = 2 * (w - 2 * r) + 2 * (h - 2 * r) + TAU * r
      host.style.left = `${-PAD - card.clientLeft}px`; host.style.top = `${-PAD - card.clientTop}px`
      for (const c of [glow, core]) {
        c.width = (w + PAD * 2) * dpr; c.height = (h + PAD * 2) * dpr
        c.style.width = `${w + PAD * 2}px`; c.style.height = `${h + PAD * 2}px`
      }
    }
    // A point `d` along the rounded edge, with the outward direction there.
    const at = (d: number): [number, number, number, number] => {
      const sw = w - 2 * r, sh = h - 2 * r, q = (Math.PI * r) / 2
      d = ((d % P) + P) % P
      const arc = (x: number, y: number, a0: number): [number, number, number, number] => {
        const a = a0 + (q ? d / q : 0) * (Math.PI / 2)
        return [x + r * Math.cos(a), y + r * Math.sin(a), Math.cos(a), Math.sin(a)]
      }
      if (d < sw) return [r + d, 0, 0, -1]; d -= sw
      if (d < q) return arc(w - r, r, -Math.PI / 2); d -= q
      if (d < sh) return [w, r + d, 1, 0]; d -= sh
      if (d < q) return arc(w - r, h - r, 0); d -= q
      if (d < sw) return [w - r - d, h, 0, 1]; d -= sw
      if (d < q) return arc(r, h - r, Math.PI / 2); d -= q
      if (d < sh) return [0, h - r - d, -1, 0]; d -= sh
      return arc(r, r, Math.PI)
    }
    const paint = (now: number) => {
      if (!w) return
      const dark = onDark(card), waiting = state !== 'working'
      const t = waiting ? now * .5 : now
      const breath = waiting ? .74 + .26 * Math.sin(now * .85) : 1
      const colors = state === 'working' ? BLUE : state === 'asking' ? YELLOW : dark ? RED.dark : RED.light
      setUp(gx, dpr, w + PAD * 2, h + PAD * 2, dark); setUp(cx, dpr, w + PAD * 2, h + PAD * 2, dark)
      const path = (c: CanvasRenderingContext2D, i: number, k: number, from: number, span: number) => {
        c.beginPath()
        const n = Math.max(6, Math.round(span / 6))
        for (let s = 0; s <= n; s++) {
          const d = from + (span * s) / n, u = (d / P) * TAU
          const off = (1.6 * Math.sin(3 * u + t * .6 + i * 2.1) + .9 * Math.sin(7 * u - t * .8 + i) + k * .9 * Math.sin(5 * u + t + i)) * (waiting ? 1.5 : 1)
          const [x, y, nx, ny] = at(d)
          if (s) c.lineTo(PAD + x + nx * off, PAD + y + ny * off); else c.moveTo(PAD + x + nx * off, PAD + y + ny * off)
        }
      }
      colors.forEach((color, i) => {
        gx.strokeStyle = cx.strokeStyle = color
        gx.globalAlpha = (waiting ? .16 : .1) * breath; gx.lineWidth = 3
        path(gx, i, 0, 0, P); gx.stroke()
        for (const k of [-1, 0, 1]) {
          cx.globalAlpha = (waiting ? (k ? .5 : .85) : k ? .2 : .36) * breath
          cx.lineWidth = waiting ? (k ? .6 : .9) : k ? .5 : .75
          path(cx, i, k, 0, P); cx.stroke()
        }
      })
      if (waiting) return
      // The light: a bright head and a tail that fades to nothing behind it, so the eye goes to the head alone.
      const head = t * P * .07, tail = P * .26, SEGS = 16
      gx.strokeStyle = cx.strokeStyle = HEAD
      gx.lineCap = cx.lineCap = 'butt'
      for (let s = 0; s < SEGS; s++) {
        const p = (s + 1) / SEGS, from = head - tail + (tail * s) / SEGS, len = tail / SEGS + .4
        gx.globalAlpha = .5 * p * p; gx.lineWidth = 2 + 4 * p
        path(gx, 0, 0, from, len); gx.stroke()
        cx.lineWidth = .6 + 1.2 * p; cx.globalAlpha = p * p * p
        for (let i = 0; i < colors.length; i++) { path(cx, i, 0, from, len); cx.stroke() }
      }
    }
    fit()
    const ro = new ResizeObserver(fit); ro.observe(card)
    const leave = enrol(card, paint)
    return () => { ro.disconnect(); leave() }
  }, [state])
  return <span ref={ref} className="rope" aria-hidden="true"><canvas className="rope-glow" /><canvas /></span>
}

/** The rope's small form, for a line of text: two fine threads and the light with its fading tail. */
export function WorkLoop({ size = 14 }: { size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current!, x = c.getContext('2d')!, dpr = Math.min(2, devicePixelRatio || 1), box = size + 6
    c.width = c.height = box * dpr; c.style.width = c.style.height = `${box}px`
    const R = size / 2 - .6, o = box / 2
    const line = (i: number, from: number, span: number, t: number) => {
      x.beginPath()
      const n = Math.max(4, Math.round(64 * span))
      for (let s = 0; s <= n; s++) {
        const a = (from + (span * s) / n) * TAU, rr = R * (1 + (i ? 1 : -1) * .07 * Math.sin(3 * a + t * .9))
        if (s) x.lineTo(o + rr * Math.cos(a), o + rr * Math.sin(a)); else x.moveTo(o + rr * Math.cos(a), o + rr * Math.sin(a))
      }
    }
    return enrol(c, t => {
      setUp(x, dpr, box, box, onDark(c))
      x.strokeStyle = BLUE[0]; x.lineWidth = .8; x.globalAlpha = .55
      for (const i of [0, 1]) { line(i, 0, 1, t); x.stroke() }
      const head = (t * .28) % 1, tail = .34, SEGS = 8
      x.strokeStyle = HEAD; x.lineCap = 'butt'; x.lineWidth = 1.6
      for (let s = 0; s < SEGS; s++) {
        x.globalAlpha = ((s + 1) / SEGS) ** 2
        line(0, head - tail + (tail * s) / SEGS, tail / SEGS + .004, t); x.stroke()
      }
    })
  }, [size])
  return <canvas ref={ref} className="work-loop" aria-hidden="true" />
}
