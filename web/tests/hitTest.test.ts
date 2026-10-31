// The bar under a finger (`barAtPoint`, used by every stage's tap and hold). Run: npm test (node --test, types stripped).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { barAtPoint } from '../src/app/geometry.ts'

// Rach 2, p. 2 of the 4-page full-score test book, as the librarian placed it (page fractions, x0 y0 x1 y1): two
// orchestral systems of four bars, 10-13 above and 14-17 below.
const PAGE = { x: 40, y: 20, w: 754, h: 1068 }
const placed: [number, number, number, number, number][] = [
  [10, 0.08548, 0.06268, 0.31371, 0.4604], [11, 0.30726, 0.06268, 0.50645, 0.4604],
  [12, 0.5, 0.06268, 0.70484, 0.4604], [13, 0.69758, 0.06268, 0.90403, 0.4604],
  [14, 0.0871, 0.50427, 0.34355, 0.9641], [15, 0.33629, 0.50427, 0.52984, 0.9641],
  [16, 0.52258, 0.50427, 0.70806, 0.9641], [17, 0.70081, 0.50427, 0.90484, 0.9641],
]
const boxes = placed.map(([bar, x0, y0, x1, y1]) => ({ bar, x: PAGE.x + x0 * PAGE.w, y: PAGE.y + y0 * PAGE.h, w: (x1 - x0) * PAGE.w, h: (y1 - y0) * PAGE.h }))
const at = (fx: number, fy: number) => [PAGE.x + fx * PAGE.w, PAGE.y + fy * PAGE.h] as const

test('a tap on the cellos in the first bar of the upper system is bar 10, whatever order the rows came in', () => {
  const [x, y] = at(0.21, 0.43)
  assert.equal(barAtPoint(boxes, x, y), 10)
  assert.equal(barAtPoint([...boxes].reverse(), x, y), 10)
  // The order the hosted rows arrived in: the lower system first.
  assert.equal(barAtPoint([...boxes.slice(4), ...boxes.slice(0, 4)], x, y), 10)
})

test('the lower system still answers for itself', () => {
  assert.equal(barAtPoint(boxes, ...at(0.2, 0.55)), 14)
  assert.equal(barAtPoint(boxes, ...at(0.8, 0.9)), 17)
})

test('just below a system takes that system, the gap between two takes the nearer', () => {
  assert.equal(barAtPoint([...boxes].reverse(), ...at(0.2, 0.47)), 10)
  assert.equal(barAtPoint(boxes, ...at(0.2, 0.50)), 14)
})

test('on a shared barline the bar the point is deeper inside wins', () => {
  const left = boxes[0], right = boxes[1]
  const x = right.x + 1 // inside both: the boxes overlap by the barline's width
  assert.ok(x < left.x + left.w)
  assert.equal(barAtPoint([right, left], x, left.y + 10), 10)
  assert.equal(barAtPoint([left, right], left.x + left.w - 1, left.y + 10), 11)
})

test('far from every box, or beside the staves, is no bar', () => {
  assert.equal(barAtPoint(boxes, ...at(0.5, 1.02)), null)
  assert.equal(barAtPoint(boxes, ...at(0.02, 0.3)), null)
  // A small system's reach stays small: 10 px at least, a third of its height at most 48 px.
  const small = [{ bar: 1, x: 0, y: 100, w: 100, h: 60 }]
  assert.equal(barAtPoint(small, 50, 85), 1)
  assert.equal(barAtPoint(small, 50, 75), null)
})
