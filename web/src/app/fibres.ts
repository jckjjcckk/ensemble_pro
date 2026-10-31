/** What the drawn fibres share (the rope in Rope.tsx, the voice button in PillStrands.tsx): one clock, and the theme. */

const reduce = typeof matchMedia === 'undefined' ? null : matchMedia('(prefers-reduced-motion: reduce)')

// One clock for every fibre on screen, 30 frames a second. The browser stops it for a hidden page.
type Painter = { seen: boolean; paint: (t: number) => void }
const painters = new Set<Painter>()
let raf = 0, last = 0
function frame(now: number) {
  raf = painters.size ? requestAnimationFrame(frame) : 0
  if (now - last < (reduce?.matches ? 1000 : 32)) return
  last = now
  const t = reduce?.matches ? 12 : now / 1000
  painters.forEach(p => { if (p.seen) p.paint(t) })
}
export function enrol(el: Element, paint: (t: number) => void) {
  const p: Painter = { seen: true, paint }
  const io = new IntersectionObserver(es => { p.seen = es[es.length - 1].isIntersecting })
  io.observe(el)
  painters.add(p)
  if (!raf) raf = requestAnimationFrame(frame)
  return () => { io.disconnect(); painters.delete(p) }
}

/** Is the theme around this element dark? Its text colour is the cheapest thing to ask. */
export function onDark(el: Element) {
  const v = getComputedStyle(el).getPropertyValue('--text').trim()
  return /^#/.test(v) && parseInt(v.slice(1, 3), 16) > 128
}
